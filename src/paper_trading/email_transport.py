"""
Transporte SMTP para el canal de notificaciones de Email (Etapa 6.14),
tercer canal externo real, construido con el mismo patrón ya aprobado
para Telegram/Slack (Etapa 6.12/6.12.1/6.13/6.13.1, ver
telegram_transport.py/slack_transport.py):

- `SmtpEmailConfig` (value object inmutable): concentra host, puerto,
  credenciales (opcionales pero consistentes), remitente, destinatario
  y política de seguridad TLS en un único lugar. Valida todo de forma
  estructural (nunca por red ni DNS).
- `EmailTransport` (`Protocol`) / `SmtpEmailTransport`: reciben la
  configuración y el timeout **una sola vez**, en el constructor.
  `send_message()` ya no recibe ninguna credencial ni dirección -- solo
  `subject`/`body`. `EmailNotificationChannel` (notification_channels.py)
  nunca conoce SMTP, ni siquiera indirectamente.

Solo usa la biblioteca estándar de Python (`smtplib`, `ssl`, `math`,
`dataclasses`, `email.message`, `email.utils`, `typing`): sin
`sendgrid`/`mailgun`/`boto3`/`requests`/`httpx`/`aiosmtplib`/`yagmail`.

Política de seguridad: solo se acepta `security="starttls"` o
`security="ssl"` -- nunca SMTP sin cifrar, nunca un fallback silencioso
de TLS a texto plano. `SmtpEmailTransport` convierte cualquier fallo
(conexión, DNS, timeout, TLS/STARTTLS, autenticación, respuesta SMTP,
envío, o cualquier excepción inesperada de una capa inferior) en
`EmailTransportError` con un mensaje sanitizado por categoría -- nunca
incluye host, username, password, sender, recipient, la respuesta SMTP
completa ni el payload completo en ningún mensaje de error.

Política de cierre de sesión (§29.x): si `send_message()` (la entrega
real) ya tuvo éxito, un fallo posterior al cerrar la sesión SMTP
(`quit()`) nunca se reporta como fallo ni provoca un reintento/segundo
envío -- se descarta silenciosamente, documentado explícitamente aquí,
no por accidente.

Nota de seguridad honesta (igual que Telegram/Slack): esto reduce la
superficie de exposición **accidental** de las credenciales (no viven
en el Channel, no aparecen en `repr`/`str`, no se filtran en
errores/logs). Python no garantiza el borrado físico de un `str` de la
memoria del proceso -- esta capa no afirma ni implica que el secreto
"desaparece" de memoria, solo que se concentra en el único lugar que
realmente lo necesita.

Fuera de alcance (responsabilidad de otras capas): el formato del
mensaje (`notification_channels.py`), reintentos (`AlertDeliveryService`/
`CompositeNotificationChannel`, ver §25.2), persistencia, idempotencia,
y la lectura de variables de entorno (Composition Root/`src/utils/config.py`).
"""

import math
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Optional, Protocol

_ALLOWED_SECURITY_MODES = frozenset({"starttls", "ssl"})
_FORBIDDEN_HOST_CHARACTERS = (" ", "\t", "\r", "\n", "/", "?", "#", ":", "@")


def _is_blank(value: Optional[str]) -> bool:
    return not isinstance(value, str) or not value.strip()


def _validate_email_address(value: Optional[str], field_name: str) -> None:
    if _is_blank(value):
        raise ValueError(f"SMTP {field_name} is required when Email notifications are enabled.")
    if "\r" in value or "\n" in value:
        raise ValueError(f"SMTP {field_name} must not contain line breaks.")
    if "," in value:
        raise ValueError(f"SMTP {field_name} must contain exactly one address.")

    _, address = parseaddr(value)
    if not address or "@" not in address:
        raise ValueError(f"SMTP {field_name} must be a valid email address.")
    local_part, _, domain = address.partition("@")
    if not local_part or not domain:
        raise ValueError(f"SMTP {field_name} must be a valid email address.")


@dataclass(frozen=True)
class SmtpEmailConfig:
    """Value object inmutable con la configuración de un servidor SMTP.

    `username`/`password` se excluyen explícitamente de `repr()`/`str()`
    (`field(repr=False)`) para reducir su exposición accidental en
    logs, tracebacks o depuración interactiva -- mismo criterio que
    `TelegramCredentials`/`SlackWebhookConfig`.

    Validación estructural (nunca por red ni DNS), en orden
    determinista: host -> puerto -> seguridad -> credenciales
    (consistentes: ambas presentes o ambas ausentes) -> remitente ->
    destinatario (ambos validados con `email.utils.parseaddr`, exigiendo
    exactamente una dirección con parte local y dominio, sin saltos de
    línea).

    Limitación real, no una promesa de seguridad: Python no garantiza
    el borrado seguro de un `str` de la memoria del proceso. Esta clase
    reduce la exposición accidental (dónde aparecen las credenciales en
    el código/logs/errores), no elimina el secreto de memoria."""

    host: str
    port: int
    sender: str
    recipient: str
    security: str = "starttls"
    username: Optional[str] = field(default=None, repr=False)
    password: Optional[str] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if _is_blank(self.host):
            raise ValueError("SMTP host is required when Email notifications are enabled.")
        if any(c in self.host for c in _FORBIDDEN_HOST_CHARACTERS):
            raise ValueError("SMTP host must be a bare hostname without scheme, port, path, or credentials.")

        if isinstance(self.port, bool) or not isinstance(self.port, int) or not (1 <= self.port <= 65535):
            raise ValueError("SMTP port must be an integer between 1 and 65535.")

        if self.security not in _ALLOWED_SECURITY_MODES:
            raise ValueError("SMTP security must be 'starttls' or 'ssl'.")

        username_given = self.username is not None
        password_given = self.password is not None
        if username_given != password_given:
            raise ValueError("SMTP username and password must both be provided or both be omitted.")
        if username_given and _is_blank(self.username):
            raise ValueError("SMTP username must not be empty.")
        if password_given and _is_blank(self.password):
            raise ValueError("SMTP password must not be empty.")

        _validate_email_address(self.sender, "sender address")
        _validate_email_address(self.recipient, "recipient address")


class EmailTransportError(Exception):
    """Fallo del transporte de Email. El mensaje nunca incluye host,
    username, password, sender, recipient, la respuesta SMTP completa
    ni el payload completo."""


class EmailTransport(Protocol):
    def send_message(self, *, subject: str, body: str) -> None:
        """Envía un email de texto plano con `subject`/`body` al
        destinatario configurado.

        La configuración SMTP (host/puerto/credenciales/remitente/
        destinatario/seguridad) y el timeout ya están fijados en el
        constructor de la implementación concreta -- este método recibe
        únicamente el asunto y el cuerpo. Realiza como máximo una
        sesión SMTP por llamada -- no reintenta internamente (eso es
        responsabilidad exclusiva de `AlertDeliveryService`/
        `CompositeNotificationChannel`, ver §25.2). Lanza
        `EmailTransportError` (nunca otro tipo de excepción) ante
        cualquier fallo de conexión, TLS, autenticación o envío."""
        ...


class SmtpEmailTransport:
    """Única implementación real de `EmailTransport`: usa exclusivamente
    `smtplib`/`ssl` de la biblioteca estándar.

    Recibe `config`/`timeout_seconds` una sola vez, en el constructor.
    Conserva un único `SmtpEmailConfig` (`self._config`), nunca copias
    sueltas como `self._host`/`self._username`/`self._password`, para
    no multiplicar los lugares donde las credenciales viven en
    memoria."""

    def __init__(self, *, config: SmtpEmailConfig, timeout_seconds: float = 10.0):
        if isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("SMTP timeout must be a finite number greater than zero.")
        self._config = config
        self._timeout_seconds = timeout_seconds

    def __repr__(self) -> str:
        return f"SmtpEmailTransport(timeout_seconds={self._timeout_seconds!r})"

    def send_message(self, *, subject: str, body: str) -> None:
        email_message = EmailMessage()
        email_message["From"] = self._config.sender
        email_message["To"] = self._config.recipient
        email_message["Subject"] = subject
        email_message.set_content(body, subtype="plain", charset="utf-8")

        try:
            if self._config.security == "starttls":
                self._send_via_starttls(email_message)
            else:
                self._send_via_ssl(email_message)
        except EmailTransportError:
            raise
        except Exception:
            # Sanitización defensiva (igual que Telegram/Slack): cualquier
            # excepción no anticipada de una capa inferior podría incluir
            # accidentalmente host/credenciales/direcciones en su propio
            # str() -- nunca se persiste directamente, se reemplaza
            # siempre por un mensaje genérico sin detalles.
            raise EmailTransportError("SMTP request failed unexpectedly.") from None

    def _send_via_starttls(self, email_message: EmailMessage) -> None:
        try:
            client = smtplib.SMTP(self._config.host, self._config.port, timeout=self._timeout_seconds)
        except TimeoutError:
            raise EmailTransportError("SMTP operation timed out.") from None
        except OSError:
            raise EmailTransportError("SMTP connection failed.") from None

        try:
            client.ehlo()
            try:
                client.starttls(context=ssl.create_default_context())
            except (smtplib.SMTPException, ssl.SSLError, OSError):
                raise EmailTransportError("SMTP TLS negotiation failed.") from None
            client.ehlo()
            self._login_if_configured(client)
            self._send_and_handle(client, email_message)
        except EmailTransportError:
            raise
        except TimeoutError:
            raise EmailTransportError("SMTP operation timed out.") from None
        except smtplib.SMTPException:
            raise EmailTransportError("SMTP server returned an unsuccessful response.") from None
        finally:
            self._close_quietly(client)

    def _send_via_ssl(self, email_message: EmailMessage) -> None:
        try:
            context = ssl.create_default_context()
            client = smtplib.SMTP_SSL(
                self._config.host, self._config.port, timeout=self._timeout_seconds, context=context,
            )
        except TimeoutError:
            raise EmailTransportError("SMTP operation timed out.") from None
        except (OSError, ssl.SSLError):
            raise EmailTransportError("SMTP connection failed.") from None

        try:
            self._login_if_configured(client)
            self._send_and_handle(client, email_message)
        except EmailTransportError:
            raise
        except TimeoutError:
            raise EmailTransportError("SMTP operation timed out.") from None
        except smtplib.SMTPException:
            raise EmailTransportError("SMTP server returned an unsuccessful response.") from None
        finally:
            self._close_quietly(client)

    def _login_if_configured(self, client) -> None:
        if self._config.username is not None and self._config.password is not None:
            try:
                client.login(self._config.username, self._config.password)
            except smtplib.SMTPException:
                raise EmailTransportError("SMTP authentication failed.") from None

    @staticmethod
    def _send_and_handle(client, email_message: EmailMessage) -> None:
        try:
            client.send_message(email_message)
        except smtplib.SMTPException:
            raise EmailTransportError("SMTP message delivery failed.") from None

    @staticmethod
    def _close_quietly(client) -> None:
        """Política de cierre (§29.x): la entrega ya se decidió (éxito o
        fallo) antes de este punto. Un fallo de `quit()` nunca se
        reporta ni provoca un segundo envío -- se descarta en
        silencio, deliberadamente."""
        try:
            client.quit()
        except Exception:
            pass

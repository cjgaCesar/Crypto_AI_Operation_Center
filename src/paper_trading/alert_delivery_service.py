"""
AlertDeliveryService -- entrega de alertas PENDING con reintentos acotados (Etapa 6.9,
ampliado en 6.10 para depender de InspectionNotificationChannel en vez de un sink concreto,
y en 6.10.1 para persistir toda excepción directa del canal -- ver §25.1).

Ver docs/ARQUITECTURA_PAPER_TRADING.md §23.9/§24/§25. No modifica órdenes,
balances ni posiciones; no llama ReconciliationService/repair(); no
ejecuta trading. Un fallo de entrega o de actualización de estado de
una alerta nunca detiene el procesamiento de las demás.

Depende únicamente de `InspectionNotificationChannel` (patrón Strategy,
§24.2): nunca conoce `LoggingInspectionAlertSink`/`CompositeNotificationChannel`/
ningún canal concreto por nombre, y nunca contiene un `if`/`isinstance`
por tipo de canal -- quien decide qué canales existen es la Composition
Root, no este servicio.

Etapa 6.10.1 (§25.1): ya no depende exclusivamente de que el canal
capture sus propios errores. `deliver_pending_alerts()` envuelve la
llamada a `channel.deliver()` en su propio `try/except`: cualquier
excepción se convierte en un `AlertDeliveryResult(success=False, ...)`
sintético y se procesa exactamente igual que un fallo normal --
`delivery_attempts` se incrementa, `last_error` se guarda, y el estado
pasa a `FAILED` al agotar `max_attempts`. Nunca queda una alerta en
reintento infinito sin rastro.

Etapa 6.11 (§26): antes de llamar a `channel.deliver()`, este servicio
usa un `InspectionNotificationTemplate` inyectado para convertir la
`InspectionAlert` en un `NotificationMessage` (`template.render(alert)`).
El servicio nunca construye el contenido del mensaje él mismo -- solo
orquesta la secuencia `template.render() -> channel.deliver()`. El
canal recibido nunca vuelve a ver una `InspectionAlert`.

Etapa 6.11.1 (§26.x): `template.render(alert)` -- y su validación --
quedan dentro del mismo `try/except` que ya protegía `channel.deliver()`.
Cualquier excepción del template, cualquier resultado que no sea una
instancia de `NotificationMessage`, y cualquier `NotificationMessage`
cuyo `alert_id` no coincida exactamente con `alert.id`, se tratan
exactamente igual que un fallo de canal: nunca se propagan, nunca se
invoca ningún canal con ese mensaje, `delivery_attempts` se incrementa
y `last_error` queda con un mensaje que identifica la causa.

Etapa 6.16 (§31/§32, auditoría transversal): el `error_message`
sintético que se construye cuando `template.render()`/`channel.deliver()`
lanzan directamente ahora pasa por `_truncate_delivery_error()`
(`notification_channels.py`, `MAX_DELIVERY_ERROR_LENGTH = 500`) antes
de convertirse en `AlertDeliveryResult` -- mismo límite que ya se
aplica dentro de cada canal y de `CompositeNotificationChannel`, para
que ningún `last_error` persistido pueda crecer sin límite.

Etapa 6.16.1 (§31.x): corrige el hallazgo bloqueante de la 6.16 --
truncar `str(exc)` acotaba la longitud, pero no sanitizaba el
contenido. `_render_and_deliver()` (nuevo método privado, extraído de
`deliver_pending_alerts()` para poder distinguir sus dos fuentes de
fallo) separa explícitamente:

- las dos validaciones de contrato que este propio servicio ya
  controlaba (la plantilla no devuelve `NotificationMessage`, o
  devuelve un `alert_id` que no corresponde a la alerta real): siguen
  siendo mensajes estáticos y propios, nunca derivados de una
  excepción externa -- se conservan tal cual (información operativa
  útil, ya sanitizada por construcción);
- cualquier excepción realmente inesperada de `template.render()` o de
  `channel.deliver()` (que, por contrato, nunca deberían lanzar --
  defensa en profundidad): se clasifica y sanitiza con
  `_classify_and_sanitize()` (`notification_channels.py`) -- nunca
  `str(exc)`/`repr(exc)`/`exc.args` directo. Solo un
  `TelegramTransportError`/`SlackTransportError`/`EmailTransportError`/
  `WebhookTransportError` (ya sanitizado en su propio transporte) se
  conserva; cualquier otra excepción se reemplaza por el mensaje
  genérico `"Unexpected alert delivery failure."`.
"""

from typing import NamedTuple, Optional

from src.paper_trading.alert_models import AlertDeliveryResult, AlertStatus, InspectionAlert
from src.paper_trading.base import PaperTradingRepository
from src.paper_trading.notification_channels import (
    InspectionNotificationChannel, _classify_and_sanitize, _truncate_delivery_error,
)
from src.paper_trading.notification_templates import (
    DefaultInspectionNotificationTemplate, InspectionNotificationTemplate, NotificationMessage,
)
from src.paper_trading.runtime import Clock, SystemClock

_UNEXPECTED_DELIVERY_FAILURE_MESSAGE = "Unexpected alert delivery failure."


class AlertDeliveryBatchResult(NamedTuple):
    """Resumen de una corrida de deliver_pending_alerts()."""

    delivered_count: int
    failed_count: int


class AlertDeliveryService:
    """Lee alertas PENDING, las entrega vía un InspectionNotificationChannel
    (típicamente un CompositeNotificationChannel), y actualiza su estado
    (DELIVERED/FAILED, respetando max_attempts)."""

    def __init__(
        self,
        repository: PaperTradingRepository,
        channel: InspectionNotificationChannel,
        max_attempts: int,
        clock: Clock = SystemClock(),
        template: InspectionNotificationTemplate = DefaultInspectionNotificationTemplate(),
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts debe ser >= 1.")
        self._repository = repository
        self._channel = channel
        self._max_attempts = max_attempts
        self._clock = clock
        self._template = template

    def deliver_pending_alerts(self, limit: Optional[int] = None) -> AlertDeliveryBatchResult:
        alerts = self._repository.fetch_pending_inspection_alerts(limit=limit)
        delivered_count = 0
        failed_count = 0

        for alert in alerts:
            result = self._render_and_deliver(alert)

            attempts = alert.delivery_attempts + 1
            try:
                if result.success:
                    self._repository.update_inspection_alert_delivery(
                        alert_id=alert.id, status=AlertStatus.DELIVERED, delivery_attempts=attempts,
                        last_error=None, delivered_at=result.delivered_at,
                    )
                    delivered_count += 1
                else:
                    new_status = (
                        AlertStatus.FAILED if (attempts >= self._max_attempts or result.terminal)
                        else AlertStatus.PENDING
                    )
                    self._repository.update_inspection_alert_delivery(
                        alert_id=alert.id, status=new_status, delivery_attempts=attempts,
                        last_error=result.error_message, delivered_at=None,
                    )
                    failed_count += 1
            except Exception:
                # La propia actualización de estado falló (ej. problema de
                # BD) -- nunca detiene el procesamiento de las demás alertas.
                failed_count += 1
                continue

        return AlertDeliveryBatchResult(delivered_count=delivered_count, failed_count=failed_count)

    def _render_and_deliver(self, alert: InspectionAlert) -> AlertDeliveryResult:
        """Construye el `NotificationMessage` vía la plantilla inyectada y
        lo entrega vía el canal inyectado. Nunca propaga -- distingue
        explícitamente (Etapa 6.16.1, §31.x) dos fuentes de fallo distintas:

        - Las dos validaciones de contrato que este servicio ya controla
          (la plantilla no devuelve `NotificationMessage`, o devuelve un
          `alert_id` que no corresponde a `alert.id`): mensajes estáticos
          y propios, nunca derivados de una excepción externa -- se
          conservan tal cual, son información operativa útil y ya
          sanitizada por construcción (nunca interpolan nada externo).
        - Cualquier excepción real de `template.render()` o de
          `channel.deliver()` (que, por contrato, nunca deberían lanzar --
          esto es defensa en profundidad, no el camino esperado): se
          clasifica y sanitiza con `_classify_and_sanitize()`
          (`notification_channels.py`) -- nunca se usa `str(exc)`/
          `repr(exc)`/`exc.args` directamente. Solo se conserva el
          mensaje si `exc` es uno de los cuatro `*TransportError` ya
          sanitizados en su propio transporte; cualquier otra excepción
          se reemplaza por `_UNEXPECTED_DELIVERY_FAILURE_MESSAGE`.
        """
        try:
            message = self._template.render(alert)
        except Exception as exc:
            return AlertDeliveryResult(
                success=False,
                error_message=_classify_and_sanitize(exc=exc, fallback_message=_UNEXPECTED_DELIVERY_FAILURE_MESSAGE),
                delivered_at=self._clock.now(), terminal=False,
            )

        if not isinstance(message, NotificationMessage):
            return AlertDeliveryResult(
                success=False,
                error_message=_truncate_delivery_error(
                    "InspectionNotificationTemplate.render() must return NotificationMessage."
                ),
                delivered_at=self._clock.now(), terminal=False,
            )

        if message.alert_id != alert.id:
            return AlertDeliveryResult(
                success=False,
                error_message=_truncate_delivery_error(
                    "NotificationMessage.alert_id does not match InspectionAlert.id."
                ),
                delivered_at=self._clock.now(), terminal=False,
            )

        try:
            return self._channel.deliver(message)
        except Exception as exc:
            return AlertDeliveryResult(
                success=False,
                error_message=_classify_and_sanitize(exc=exc, fallback_message=_UNEXPECTED_DELIVERY_FAILURE_MESSAGE),
                delivered_at=self._clock.now(), terminal=False,
            )

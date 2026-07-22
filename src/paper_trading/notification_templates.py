"""
Plantillas de notificación de alertas de inspección -- patrón Strategy
(Etapa 6.11, endurecida en 6.11.1 -- ver §26.x). Ver
docs/ARQUITECTURA_PAPER_TRADING.md §26.

Separa "qué se comunica" (esta clase) de "cómo se comunica"
(notification_channels.py). Un canal nunca vuelve a conocer
`InspectionAlert`: solo recibe un `NotificationMessage` ya construido,
agnóstico a cualquier canal concreto (nunca HTML, Markdown, ni nada
específico de Telegram/Slack/Email).

`InspectionNotificationTemplate` es la única abstracción que
`AlertDeliveryService` conoce para construir el contenido: nunca un
`if`/`isinstance` por tipo de alerta fuera de la plantilla misma.
Agregar una plantilla alternativa en el futuro (ej. un formato más
compacto para SMS) significa una clase nueva que implemente el mismo
protocolo, nunca tocar `AlertDeliveryService`/los canales.
"""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Optional, Protocol

from src.paper_trading.alert_models import AlertType, InspectionAlert
from src.paper_trading.reconciliation_models import IssueSeverity


@dataclass(frozen=True)
class NotificationMessage:
    """Contenido de una notificación, ya renderizado y listo para que
    cualquier canal lo transporte. Únicamente información de
    presentación -- nunca HTML, Markdown específico, ni nada propio de
    un canal concreto (Telegram/Slack/Email/URLs).

    `alert_id` (Etapa 6.11.1, §26.x) es un campo explícito, obligatorio
    e inmutable -- no vive dentro de `metadata`. Es la identidad que
    `CompositeNotificationChannel` usa para su idempotencia por canal
    (ver notification_channels.py); al ser un campo propio del
    contrato, `AlertDeliveryService` puede validarlo contra
    `alert.id` **antes** de invocar cualquier canal (§26.x), en vez de
    descubrir un valor incorrecto recién dentro del Composite.

    `metadata` sigue existiendo para cualquier otro identificador no
    presentacional que un canal futuro pueda necesitar (ej.
    `alert_type`, `run_id`), pero ya no es responsable de `alert_id`.
    Inmutable: `metadata` se congela con `MappingProxyType` para que ni
    siquiera el dict subyacente pueda mutarse después de construido el
    mensaje.
    """

    alert_id: str
    title: str
    body: str
    severity: Optional[IssueSeverity]
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.alert_id, str) or not self.alert_id.strip():
            raise ValueError("NotificationMessage.alert_id must be a non-empty string.")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class InspectionNotificationTemplate(Protocol):
    def render(self, alert: InspectionAlert) -> NotificationMessage:
        """Construye el NotificationMessage correspondiente a `alert`.

        Contrato (Etapa 6.11.1, §26.x), validado en runtime por
        `AlertDeliveryService` antes de invocar cualquier canal:

        - debe devolver una instancia de `NotificationMessage`, nunca
          `None` ni ningún otro tipo;
        - `resultado.alert_id` debe ser exactamente `alert.id` (nunca
          otro valor, nunca reconstruido);
        - nunca modifica `alert`;
        - nunca lanza para una `InspectionAlert` válida -- es una
          función pura sobre datos ya validados por quien construyó la
          alerta, y el mismo `alert` de entrada siempre produce el
          mismo `NotificationMessage`.
        """
        ...


_TITLES_BY_ALERT_TYPE = {
    AlertType.NEW_ISSUE: "Nueva incidencia detectada",
    AlertType.RESOLVED_ISSUE: "Incidencia resuelta",
    AlertType.SEVERITY_INCREASED: "Severidad de incidencia incrementada",
    AlertType.SEVERITY_DECREASED: "Severidad de incidencia reducida",
    AlertType.VALUE_CHANGED: "Valor de incidencia modificado",
    AlertType.INSPECTION_FAILED: "Inspección de reconciliación fallida",
    AlertType.SYSTEM_RECOVERED: "Sistema recuperado",
}


def _entity_line(alert: InspectionAlert) -> Optional[str]:
    if alert.issue_identity is None:
        return None
    parts = [alert.issue_identity.entity_type, alert.issue_identity.entity_id]
    if alert.issue_identity.exchange:
        parts.append(alert.issue_identity.exchange)
    if alert.issue_identity.symbol:
        parts.append(alert.issue_identity.symbol)
    return "Entidad: " + " / ".join(parts)


def _code_line(alert: InspectionAlert) -> Optional[str]:
    code = alert.issue_code or (alert.issue_identity.code if alert.issue_identity is not None else None)
    return f"Código: {code}" if code else None


class DefaultInspectionNotificationTemplate:
    """Plantilla por defecto (única usada en producción en esta etapa,
    ver §26): genera un mensaje de texto plano, claro, para los 7 tipos
    de AlertType actuales. Nunca produce HTML/Markdown ni referencia
    ningún canal concreto."""

    def render(self, alert: InspectionAlert) -> NotificationMessage:
        lines = [alert.message]
        for line in (_code_line(alert), _entity_line(alert)):
            if line is not None:
                lines.append(line)
        lines.append(f"Fecha: {alert.created_at.isoformat()}")

        return NotificationMessage(
            alert_id=alert.id,
            title=_TITLES_BY_ALERT_TYPE[alert.alert_type],
            body="\n".join(lines),
            severity=alert.severity,
            metadata={"alert_type": alert.alert_type.value, "run_id": alert.run_id},
        )

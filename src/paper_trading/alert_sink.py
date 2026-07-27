"""
InspectionAlertSink -- abstracción de entrega de alertas (Etapa 6.9).

Ver docs/ARQUITECTURA_PAPER_TRADING.md §23.9. Desde la Etapa 6.10
(§24.8), la implementación canónica de estos canales vive en
`notification_channels.py` (patrón Strategy, con
`CompositeNotificationChannel`, Logging/Null y los cuatro canales
externos reales -- Telegram/Slack/Email/Webhook, Etapas 6.12-6.15,
ninguno placeholder desde la Etapa 6.15); este módulo se conserva
íntegro, con `LoggingInspectionAlertSink`/`NullInspectionAlertSink`
como alias directos de `LoggingNotificationChannel`/
`NullNotificationChannel`, para que ningún import ni prueba existente
de la Etapa 6.9 se rompa.
"""

from typing import Protocol

from src.paper_trading.alert_models import AlertDeliveryResult, InspectionAlert
from src.paper_trading.notification_channels import LoggingNotificationChannel, NullNotificationChannel


class InspectionAlertSink(Protocol):
    def deliver(self, alert: InspectionAlert) -> AlertDeliveryResult:
        """Entrega `alert`. Nunca lanza: captura sus propios errores y los
        refleja en el AlertDeliveryResult devuelto."""
        ...


# Alias de compatibilidad hacia atrás (Etapa 6.10, §24.8): misma
# implementación, mismo nombre, mismo constructor que en la Etapa 6.9.
LoggingInspectionAlertSink = LoggingNotificationChannel
NullInspectionAlertSink = NullNotificationChannel

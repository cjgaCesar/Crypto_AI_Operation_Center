"""
Pruebas para src/paper_trading/notification_channels.py (Etapa 6.10):
patrón Strategy para la entrega de alertas de inspección.
Ver docs/ARQUITECTURA_PAPER_TRADING.md §24.
"""

from datetime import datetime, timezone

import pytest

from src.paper_trading.alert_models import AlertDeliveryResult, AlertType, AlertStatus, InspectionAlert
from src.paper_trading.notification_channels import (
    CompositeNotificationChannel, EmailNotificationChannel, LoggingNotificationChannel,
    NullNotificationChannel, SlackNotificationChannel, TelegramNotificationChannel,
    WebhookNotificationChannel,
)


class FixedClock:
    def __init__(self, fixed: datetime):
        self._fixed = fixed

    def now(self) -> datetime:
        return self._fixed


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _alert(**overrides) -> InspectionAlert:
    defaults = dict(
        id="alert-1", run_id="run-1", alert_type=AlertType.NEW_ISSUE, issue_identity=None,
        issue_code=None, severity=None, title="t", message="m", deduplication_key="k1",
        status=AlertStatus.PENDING, delivery_attempts=0, last_error=None, created_at=_now(),
    )
    defaults.update(overrides)
    return InspectionAlert(**defaults)


class AlwaysSucceedsChannel:
    def __init__(self, name="ok"):
        self.name = name
        self.delivered = []

    def deliver(self, alert):
        self.delivered.append(alert.id)
        return AlertDeliveryResult(success=True, error_message=None, delivered_at=_now())


class AlwaysFailsChannel:
    def __init__(self, name="fail"):
        self.name = name
        self.delivered = []

    def deliver(self, alert):
        self.delivered.append(alert.id)
        return AlertDeliveryResult(success=False, error_message=f"{self.name} failed", delivered_at=_now())


class RaisingChannel:
    def __init__(self, name="raiser"):
        self.name = name
        self.delivered = []

    def deliver(self, alert):
        self.delivered.append(alert.id)
        raise RuntimeError(f"{self.name} exploded")


class TestLoggingChannel:
    def test_delivers_successfully(self):
        channel = LoggingNotificationChannel(clock=FixedClock(_now()))
        result = channel.deliver(_alert())
        assert result.success is True
        assert result.delivered_at == _now()

    def test_uses_injected_clock(self):
        fixed = datetime(2030, 5, 5, tzinfo=timezone.utc)
        channel = LoggingNotificationChannel(clock=FixedClock(fixed))
        result = channel.deliver(_alert())
        assert result.delivered_at == fixed


class TestNullChannel:
    def test_always_succeeds(self):
        channel = NullNotificationChannel(clock=FixedClock(_now()))
        result = channel.deliver(_alert())
        assert result.success is True
        assert result.error_message is None


class TestPlaceholderChannelsRaiseNotImplemented:
    @pytest.mark.parametrize("channel_class", [
        EmailNotificationChannel, SlackNotificationChannel,
        TelegramNotificationChannel, WebhookNotificationChannel,
    ])
    def test_deliver_raises_not_implemented(self, channel_class):
        channel = channel_class()
        with pytest.raises(NotImplementedError):
            channel.deliver(_alert())

    @pytest.mark.parametrize("channel_class", [
        EmailNotificationChannel, SlackNotificationChannel,
        TelegramNotificationChannel, WebhookNotificationChannel,
    ])
    def test_error_message_is_clear(self, channel_class):
        channel = channel_class()
        with pytest.raises(NotImplementedError) as exc_info:
            channel.deliver(_alert())
        assert "etapa posterior" in str(exc_info.value)


class TestCompositeChannelBothSucceed:
    def test_both_channels_executed_and_overall_success(self):
        channel1 = AlwaysSucceedsChannel("c1")
        channel2 = AlwaysSucceedsChannel("c2")
        composite = CompositeNotificationChannel([channel1, channel2], clock=FixedClock(_now()))
        result = composite.deliver(_alert())
        assert channel1.delivered == ["alert-1"]
        assert channel2.delivered == ["alert-1"]
        assert result.success is True


class TestCompositeChannelOneFailsOtherRuns:
    def test_channel_1_fails_channel_2_still_executes(self):
        channel1 = AlwaysFailsChannel("c1")
        channel2 = AlwaysSucceedsChannel("c2")
        composite = CompositeNotificationChannel([channel1, channel2], clock=FixedClock(_now()))
        result = composite.deliver(_alert())
        assert channel1.delivered == ["alert-1"]
        assert channel2.delivered == ["alert-1"]
        assert result.success is False
        assert "c1 failed" in result.error_message

    def test_channel_1_raises_channel_2_still_executes(self):
        channel1 = RaisingChannel("c1")
        channel2 = AlwaysSucceedsChannel("c2")
        composite = CompositeNotificationChannel([channel1, channel2], clock=FixedClock(_now()))
        result = composite.deliver(_alert())
        assert channel1.delivered == ["alert-1"]
        assert channel2.delivered == ["alert-1"]
        assert result.success is False
        assert "c1 exploded" in result.error_message


class TestCompositeChannelThreeChannelsTwoFailOneWorks:
    def test_all_three_are_attempted(self):
        channel1 = AlwaysFailsChannel("c1")
        channel2 = AlwaysSucceedsChannel("c2")
        channel3 = RaisingChannel("c3")
        composite = CompositeNotificationChannel([channel1, channel2, channel3], clock=FixedClock(_now()))
        result = composite.deliver(_alert())
        assert channel1.delivered == ["alert-1"]
        assert channel2.delivered == ["alert-1"]
        assert channel3.delivered == ["alert-1"]
        assert result.success is False
        assert "c1 failed" in result.error_message
        assert "c3 exploded" in result.error_message


class TestCompositeChannelEmpty:
    def test_no_channels_is_a_successful_noop(self):
        composite = CompositeNotificationChannel([], clock=FixedClock(_now()))
        result = composite.deliver(_alert())
        assert result.success is True


class TestCompositeChannelNeverRaises:
    def test_placeholder_channel_inside_composite_never_propagates(self):
        composite = CompositeNotificationChannel(
            [EmailNotificationChannel(), NullNotificationChannel(clock=FixedClock(_now()))],
            clock=FixedClock(_now()),
        )
        result = composite.deliver(_alert())  # no debe lanzar NotImplementedError
        assert result.success is False
        assert "EmailNotificationChannel" in result.error_message

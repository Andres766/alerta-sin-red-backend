"""Manejador de ``RiskAssessed``: envía SMS de respaldo si el riesgo es alto."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from app.domain.entities import AlertNotification, NotificationKind, NotificationStatus
from app.domain.events import RiskAssessed
from app.domain.policies import AlertMessageBuilder, AlertPolicy
from app.domain.ports import SmsGateway, UnitOfWork

logger = logging.getLogger(__name__)


class AlertDispatcher:
    def __init__(
        self,
        uow: UnitOfWork,
        sms: SmsGateway,
        policy: AlertPolicy,
        message_builder: AlertMessageBuilder,
        clock: Callable[[], datetime],
    ) -> None:
        self._uow = uow
        self._sms = sms
        self._policy = policy
        self._messages = message_builder
        self._clock = clock

    def __call__(self, event: RiskAssessed) -> list[AlertNotification]:
        zone, assessment = event.zone, event.assessment
        last_sent = self._uow.alerts.last_sent_for_zone(zone.id)
        if self._policy.should_alert(assessment, last_sent, self._clock()):
            kind, message = NotificationKind.ALERT, self._messages.build(zone, assessment)
        elif self._policy.should_send_all_clear(assessment, last_sent):
            kind, message = (
                NotificationKind.ALL_CLEAR,
                self._messages.build_all_clear(zone, assessment),
            )
        else:
            return []

        notifications: list[AlertNotification] = []
        for subscriber in self._uow.subscribers.active_for_zone(zone.id):
            result = self._sms.send(subscriber.phone, message)
            notification = AlertNotification(
                zone_id=zone.id,
                assessment_id=assessment.id,
                subscriber_id=subscriber.id,
                level=assessment.level,
                channel=self._sms.channel,
                status=NotificationStatus.SENT if result.success else NotificationStatus.FAILED,
                provider_message_id=result.provider_message_id,
                error=result.error,
                kind=kind,
            )
            self._uow.alerts.add(notification)
            notifications.append(notification)

        self._uow.commit()
        sent = sum(n.status is NotificationStatus.SENT for n in notifications)
        logger.info("%s %s para %s: %d/%d SMS enviados", kind.value,
                    assessment.level.value, zone.name, sent, len(notifications))
        return notifications

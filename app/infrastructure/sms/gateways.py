"""Pasarelas SMS intercambiables (patrón Strategy).

Todas cumplen el contrato ``SmsGateway`` y el despachador de alertas no sabe
cuál está usando. Se eligen por configuración mediante ``SmsGatewayFactory``.
"""

from __future__ import annotations

import logging
import uuid

import httpx

from app.core.config import Settings
from app.domain.ports import SmsGateway, SmsResult
from app.domain.value_objects import PhoneNumber

logger = logging.getLogger(__name__)


class ConsoleSmsGateway(SmsGateway):
    """Desarrollo: escribe el SMS en el log (con el número enmascarado)."""

    channel = "console"

    def __init__(self) -> None:
        self.outbox: list[tuple[PhoneNumber, str]] = []

    def send(self, phone: PhoneNumber, message: str) -> SmsResult:
        self.outbox.append((phone, message))
        logger.warning("[SMS simulado] a %s: %s", phone.masked(), message)
        return SmsResult(success=True, provider_message_id=f"console-{uuid.uuid4().hex[:12]}")


class TwilioSmsGateway(SmsGateway):
    """Twilio Programmable Messaging (REST, sin SDK para no añadir dependencias)."""

    channel = "twilio"
    _API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"

    def __init__(self, account_sid: str, auth_token: str, from_number: str, client: httpx.Client):
        self._url = self._API.format(sid=account_sid)
        self._auth = (account_sid, auth_token)
        self._from = from_number
        self._client = client

    def send(self, phone: PhoneNumber, message: str) -> SmsResult:
        try:
            response = self._client.post(
                self._url,
                data={"To": phone.value, "From": self._from, "Body": message},
                auth=self._auth,
            )
            response.raise_for_status()
            return SmsResult(success=True, provider_message_id=response.json().get("sid"))
        except httpx.HTTPError as exc:
            logger.error("Twilio falló para %s: %s", phone.masked(), type(exc).__name__)
            return SmsResult(success=False, error=f"twilio:{type(exc).__name__}")


class AndroidSmsGateway(SmsGateway):
    """Android SMS Gateway (github.com/capcom6/android-sms-gateway).

    Un celular Android con SIM expone una API REST y envía SMS reales sin costo
    por mensaje. Sirve tanto el modo local (``http://IP:8080``) como el cloud
    (``https://api.sms-gate.app/3rdparty/v1``).
    """

    channel = "android_gateway"

    def __init__(self, base_url: str, user: str, password: str, client: httpx.Client) -> None:
        self._url = base_url.rstrip("/") + "/message"
        self._auth = (user, password)
        self._client = client

    def send(self, phone: PhoneNumber, message: str) -> SmsResult:
        try:
            response = self._client.post(
                self._url,
                json={"textMessage": {"text": message}, "phoneNumbers": [phone.value]},
                auth=self._auth,
            )
            response.raise_for_status()
            return SmsResult(success=True, provider_message_id=response.json().get("id"))
        except httpx.HTTPError as exc:
            logger.error("Android Gateway falló para %s: %s", phone.masked(), type(exc).__name__)
            return SmsResult(success=False, error=f"android_gateway:{type(exc).__name__}")


class SmsGatewayFactory:
    """Patrón Factory: crea la estrategia SMS según la configuración."""

    @staticmethod
    def create(settings: Settings, client: httpx.Client) -> SmsGateway:
        if settings.sms_provider == "twilio":
            return TwilioSmsGateway(
                settings.twilio_account_sid or "",
                settings.twilio_auth_token.get_secret_value() if settings.twilio_auth_token else "",
                settings.twilio_from_number or "",
                client,
            )
        if settings.sms_provider == "android_gateway":
            return AndroidSmsGateway(
                settings.android_gateway_url or "",
                settings.android_gateway_user or "",
                settings.android_gateway_password.get_secret_value()
                if settings.android_gateway_password
                else "",
                client,
            )
        return ConsoleSmsGateway()

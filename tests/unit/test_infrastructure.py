import json
import shutil
import time
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from cryptography.fernet import Fernet

from app.core.security import JwtTokenService, PhoneCipher, SlidingWindowRateLimiter
from app.domain.exceptions import AuthenticationError, ModelIntegrityError
from app.domain.ports import TokenClaims
from app.domain.value_objects import Coordinates, PhoneNumber, RiskFeatures, RiskLevel
from app.infrastructure.ml.sklearn_model import SklearnRiskModel
from app.infrastructure.weather.open_meteo import OpenMeteoWeatherProvider

SECRET = "k" * 48


class TestPhoneCipher:
    cipher = PhoneCipher(Fernet.generate_key().decode(), "indice")
    phone = PhoneNumber.parse("3001234567")

    def test_cifra_y_descifra(self):
        token = self.cipher.encrypt(self.phone)
        assert "3001234567" not in token
        assert self.cipher.decrypt(token) == self.phone

    def test_indice_ciego_determinista_y_sin_dato_en_claro(self):
        idx = self.cipher.blind_index(self.phone)
        assert idx == self.cipher.blind_index(PhoneNumber.parse("+573001234567"))
        assert "3001234567" not in idx


class TestJwt:
    service = JwtTokenService(SECRET, "HS256", 30)

    def test_emite_y_valida(self):
        token, ttl = self.service.issue(TokenClaims("a@b.co", "ADMIN"))
        assert ttl == 1800
        assert self.service.decode(token).role == "ADMIN"

    def test_rechaza_token_alterado(self):
        token, _ = self.service.issue(TokenClaims("a@b.co", "OPERATOR"))
        forged = jwt.encode(
            {**jwt.decode(token, options={"verify_signature": False}), "role": "ADMIN"},
            "otro-secreto-" * 4, algorithm="HS256",
        )
        with pytest.raises(AuthenticationError):
            self.service.decode(forged)

    def test_rechaza_alg_none(self):
        unsigned = jwt.encode({"sub": "x", "role": "ADMIN", "iss": "alerta-sin-red",
                               "iat": 0, "exp": 9999999999}, None, algorithm="none")
        with pytest.raises(AuthenticationError):
            self.service.decode(unsigned)

    def test_rechaza_token_expirado(self):
        past = datetime.now(UTC) - timedelta(hours=2)
        expired = jwt.encode({"sub": "x", "role": "ADMIN", "iss": "alerta-sin-red",
                              "iat": past, "exp": past + timedelta(minutes=5)}, SECRET)
        with pytest.raises(AuthenticationError):
            self.service.decode(expired)


def test_rate_limiter_ventana_deslizante():
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=0.2)
    assert limiter.allow("ip") and limiter.allow("ip")
    assert not limiter.allow("ip")
    assert limiter.allow("otra-ip")
    time.sleep(0.25)
    assert limiter.allow("ip")


class TestRiskModel:
    def test_predice_segun_condiciones(self, risk_model):
        storm = RiskFeatures(rain_24h_mm=60, rain_72h_mm=130, rain_7d_mm=200,
                             rain_forecast_24h_mm=60, soil_moisture=0.48,
                             river_discharge_ratio=2.5, slope_deg=30, susceptibility=5)
        dry = RiskFeatures(rain_24h_mm=0, rain_72h_mm=1, rain_7d_mm=5, rain_forecast_24h_mm=0,
                           soil_moisture=0.2, river_discharge_ratio=0.9, slope_deg=5,
                           susceptibility=2)
        assert risk_model.predict(storm).level is RiskLevel.MUY_ALTO
        assert risk_model.predict(dry).level is RiskLevel.BAJO
        assert sum(risk_model.predict(dry).probabilities.values()) == pytest.approx(1)

    def test_rechaza_modelo_alterado(self, settings, tmp_path):
        model, meta = tmp_path / "m.joblib", tmp_path / "m.json"
        shutil.copy(settings.model_path, model)
        shutil.copy(settings.model_metadata_path, meta)
        with model.open("ab") as fh:
            fh.write(b"codigo-malicioso")
        with pytest.raises(ModelIntegrityError):
            SklearnRiskModel.load(model, meta)

    def test_rechaza_orden_de_variables_distinto(self, settings, tmp_path):
        meta = tmp_path / "m.json"
        data = json.loads(settings.model_metadata_path.read_text(encoding="utf-8"))
        data["feature_order"].reverse()
        meta.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ModelIntegrityError):
            SklearnRiskModel.load(settings.model_path, meta)


def test_adaptador_open_meteo_calcula_ventanas():
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    times = [(now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(167, -25, -1)]
    # 1 mm/h en el pasado, 2 mm/h en el pronóstico
    past_len = 168
    precipitation = [1.0] * past_len + [2.0] * 24

    def handler(request: httpx.Request) -> httpx.Response:
        if "flood" in request.url.host:
            discharge = [10.0] * 30 + [25, 30, 20]
            return httpx.Response(200, json={"daily": {"river_discharge": discharge}})
        return httpx.Response(200, json={"hourly": {
            "time": times, "precipitation": precipitation,
            "soil_moisture_3_to_9cm": [0.33] * len(times)}})

    provider = OpenMeteoWeatherProvider(
        "https://api.open-meteo.com/v1/forecast", "https://flood-api.open-meteo.com/v1/flood",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    c = provider.get_conditions(Coordinates(1.21, -77.28))
    assert (c.rain_24h_mm, c.rain_72h_mm, c.rain_7d_mm) == (24, 72, 168)
    assert c.rain_forecast_24h_mm == 48
    assert c.soil_moisture == 0.33
    assert c.river_discharge_ratio == 3.0

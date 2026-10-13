"""Excepciones del dominio.

La capa de dominio nunca conoce HTTP: la capa API traduce estas excepciones a
códigos de estado (ver ``app/api/errors.py``).
"""


class DomainError(Exception):
    """Raíz de todos los errores de negocio."""

    code = "domain_error"


class ValidationError(DomainError):
    code = "validation_error"


class InvalidPhoneNumberError(ValidationError):
    code = "invalid_phone"


class InvalidCoordinatesError(ValidationError):
    code = "invalid_coordinates"


class ConsentRequiredError(ValidationError):
    code = "consent_required"


class NotFoundError(DomainError):
    code = "not_found"


class ZoneNotFoundError(NotFoundError):
    code = "zone_not_found"


class ConflictError(DomainError):
    """La operación choca con el estado actual (duplicado, regla de negocio)."""

    code = "conflict"


class UserAlreadyExistsError(ConflictError):
    code = "user_exists"


class AuthenticationError(DomainError):
    code = "authentication_failed"


class AuthorizationError(DomainError):
    code = "forbidden"


class ExternalServiceError(DomainError):
    """Un servicio externo (clima, SMS) no respondió correctamente."""

    code = "external_service_error"


class WeatherUnavailableError(ExternalServiceError):
    code = "weather_unavailable"


class ModelIntegrityError(DomainError):
    """El archivo del modelo de IA no coincide con su huella SHA-256."""

    code = "model_integrity_error"

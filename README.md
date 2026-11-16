# AlertaSinRed · API (backend)

API de **alertas de riesgo climático offline-first**: un modelo de IA estima el riesgo de
deslizamiento y creciente de ríos en zonas de Nariño y Putumayo, y si el riesgo es alto
envía un SMS de respaldo que no necesita internet.

> Proyecto final · Programación Orientada a la Web · Ingeniería de Software · UCC Pasto
> Frontend (PWA): repositorio `alerta-sin-red-frontend`.

| Componente | Tecnología |
|---|---|
| API | Python 3.13 · FastAPI · Pydantic 2 |
| Persistencia | PostgreSQL 16 + PostGIS 3.4 · SQLAlchemy 2 · GeoAlchemy2 |
| IA | scikit-learn (Random Forest) con datos de Open-Meteo (Forecast + Flood API) |
| SMS | Twilio o Android SMS Gateway (por configuración) |
| Seguridad | Argon2id · JWT · Fernet (teléfonos cifrados) · RBAC · rate limiting |

La arquitectura (hexagonal), los patrones de diseño, el modelo de datos y las decisiones de
seguridad están en [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).

## Puesta en marcha

```bash
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python -m app.cli gen-keys        # pegue los 3 valores en .env
```

**Modo demo (sin base de datos):** en `.env` ponga `REPOSITORY_BACKEND=memory`. Las zonas
y el administrador se crean al arrancar.

**Con PostgreSQL + PostGIS:**

```bash
python -m app.cli init-db         # extensión PostGIS, tablas y migraciones
python -m app.cli seed            # zonas piloto + administrador (ADMIN_EMAIL/ADMIN_PASSWORD)
```

Arranque:

```bash
uvicorn app.main:create_app --factory --reload
```

Documentación interactiva: http://localhost:8000/docs (deshabilitada en producción salvo
`EXPOSE_DOCS=true`).

Para demostrar el envío de SMS aunque no llueva: `WEATHER_PROVIDER=fake` y
`FAKE_WEATHER_SCENARIO=tormenta`. Con `SMS_PROVIDER=console` el SMS se escribe en el log
con el número enmascarado.

## Comandos

| Comando | Qué hace |
|---|---|
| `python -m app.cli gen-keys` | Genera `JWT_SECRET`, `PHONE_ENCRYPTION_KEY` y `PHONE_INDEX_KEY` |
| `python -m app.cli init-db` | Crea PostGIS, tablas y aplica migraciones pendientes |
| `python -m app.cli migrations` | Estado de cada migración del esquema (aplicada o pendiente) |
| `python -m app.cli seed` | Zonas piloto y usuario administrador (idempotente) |
| `python -m app.cli evaluate` | Ejecuta el modelo sobre todas las zonas y envía los SMS |
| `python -m ml.train` | Reentrena el modelo (datos sintéticos, fase 1) |
| `python -m ml.train --data ml/data/eventos.csv` | Reentrena con eventos reales (fase 2) |

## Pruebas y calidad

```bash
pytest            # unitarias, de servicios y de API (repositorios en memoria)
ruff check .      # estilo, imports y reglas de seguridad (Bandit)

# Integración contra PostgreSQL + PostGIS (la base indicada se vacía: use una de pruebas)
TEST_DATABASE_URL=postgresql://alerta:alerta@localhost:5432/alerta_test pytest tests/integration
```

## Endpoints principales (`/api/v1`)

| Método | Ruta | Acceso | Descripción |
|---|---|---|---|
| GET | `/health` | Público | Vida: estado, versión del modelo y proveedores |
| GET | `/health/ready` | Público | Disponibilidad: verifica la base de datos (503 si falla) |
| GET | `/model` | Público | Ficha técnica del modelo de IA: métricas, variables y limitaciones |
| GET | `/risk/snapshot` | Público | Todas las zonas con su última evaluación (lo que la PWA guarda offline) |
| GET | `/zones/nearby?lat=&lon=&radius_km=` | Público | Zonas cercanas (consulta espacial PostGIS) |
| GET | `/zones/{id}` | Público | Una zona con su última evaluación |
| GET | `/zones/{id}/history` | Público | Evaluaciones recientes de una zona |
| GET | `/zones/{id}/days?days=30` | Público | Peor nivel de cada día (hora de Colombia) |
| POST | `/subscriptions` | Público | Suscribe un celular a las alertas SMS de una zona |
| POST | `/subscriptions/{id}/cancel` | Código de baja | Da de baja la suscripción |
| POST | `/auth/login` | Público | Inicio de sesión de operadores (JWT) |
| GET | `/auth/me` | Operador | Datos de la sesión actual |
| POST | `/auth/change-password` | Operador | Cambia la clave propia y cierra las demás sesiones |
| POST | `/admin/evaluations` | Operador | Ejecuta el modelo de IA y despacha SMS |
| POST | `/weather/observations` | Token de ingesta | Recibe el clima por zona desde un trabajo externo y evalúa |
| POST | `/weather/history` | Token de ingesta | Evalúa días pasados con su clima real (sin enviar SMS) |
| GET | `/admin/alerts` · `/admin/stats` | Operador | SMS enviados e indicadores |
| GET/POST | `/admin/users` | Administrador | Lista y crea cuentas |
| POST | `/admin/users/{id}/activate` · `/deactivate` | Administrador | Activa o desactiva cuentas |
| GET | `/admin/assessments.csv?days=` | Operador | Historial de evaluaciones en CSV |
| POST | `/admin/zones` · PATCH `/admin/zones/{id}` | Administrador | Registra o actualiza zonas |
| POST | `/admin/sms/test` | Administrador | SMS de prueba de la pasarela (máx. 5 por hora) |
| GET | `/admin/audit` | Administrador | Bitácora de auditoría |

## Clima desde GitHub Actions

Open-Meteo limita las peticiones por IP y la IP de salida de Render (compartida con muchas
aplicaciones gratuitas) recibe `429`. Por eso el clima no lo descarga el servidor sino un
trabajo programado en GitHub Actions (`.github/workflows/clima.yml`), cuya IP no está
bloqueada:

1. Cada hora, `scripts/push_weather.py` consulta Open-Meteo para cada zona con **el mismo
   adaptador** que usa el servidor (`OpenMeteoWeatherProvider`) y envía las observaciones a
   `POST /weather/observations` con la cabecera `X-Ingest-Token`.
2. El servidor guarda una observación por zona (`weather_observations`) y evalúa el riesgo
   con ella. `StoredWeatherProvider` antepone la observación guardada, si tiene menos de
   `WEATHER_OBSERVATION_MAX_AGE_HOURS` (3 por defecto), al proveedor configurado.
3. En la misma ejecución completa el **historial**: para cada zona revisa qué días de los
   últimos 30 no tienen evaluación (`GET /zones/{id}/days`), reconstruye el clima de esos
   días con `OpenMeteoWeatherProvider.daily_history` y los envía a `POST /weather/history`.
   Esas evaluaciones quedan con su fecha real y la fuente `open-meteo-historico`, y nunca
   envían SMS. Si Render pasa un día dormido, el hueco se rellena en la siguiente ejecución.
4. `.github/workflows/mantener-activo.yml` hace una petición a `/health` cada 10 minutos para
   que la instancia gratuita de Render no se duerma.

GitHub no garantiza la hora de los trabajos programados y descarta algunos con carga alta;
por eso `clima.yml` se programa dos veces por hora. Si Open-Meteo responde `429` al servidor,
el adaptador deja de consultarlo durante 10 minutos (disyuntor) para no agotar el tiempo de
la evaluación.

Configuración: un mismo secreto en GitHub (**Settings → Secrets → Actions →
`WEATHER_INGEST_TOKEN`**) y en Render (**Environment → `WEATHER_INGEST_TOKEN`**), de al menos
32 caracteres (`python -c "import secrets; print(secrets.token_urlsafe(48))"`). Sin la
variable, el endpoint responde `503` y el servidor sigue consultando Open-Meteo directamente.

## Despliegue

`render.yaml` es un Blueprint de Render: crea la API (Docker) y la base PostgreSQL en la
misma región. Render → **New → Blueprint** → elija este repositorio y complete las
variables marcadas como `sync: false`. Detalles en `docs/ARQUITECTURA.md`.

## Estructura

```
app/
├── domain/          entidades, objetos de valor, políticas, eventos y puertos (sin frameworks)
├── application/     casos de uso y bus de eventos
├── infrastructure/  PostgreSQL/PostGIS, memoria, Open-Meteo, SMS, modelo de IA
├── api/             routers, DTOs, dependencias, errores y middleware
├── core/            configuración, seguridad y logging
└── container.py     raíz de composición (inyección de dependencias)
ml/                  generación de datos y entrenamiento
models/              modelo entrenado y metadatos (con huella SHA-256)
tests/               pruebas unitarias y de API
```

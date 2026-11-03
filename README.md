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
| `python -m app.cli seed` | Zonas piloto y usuario administrador (idempotente) |
| `python -m app.cli evaluate` | Ejecuta el modelo sobre todas las zonas y envía los SMS |
| `python -m ml.train` | Reentrena el modelo (datos sintéticos, fase 1) |
| `python -m ml.train --data ml/data/eventos.csv` | Reentrena con eventos reales (fase 2) |

## Pruebas y calidad

```bash
pytest            # unitarias, de servicios y de API (repositorios en memoria)
ruff check .      # estilo, imports y reglas de seguridad (Bandit)
```

## Endpoints principales (`/api/v1`)

| Método | Ruta | Acceso | Descripción |
|---|---|---|---|
| GET | `/health` | Público | Estado, versión del modelo y proveedores |
| GET | `/risk/snapshot` | Público | Todas las zonas con su última evaluación (lo que la PWA guarda offline) |
| GET | `/zones/nearby?lat=&lon=&radius_km=` | Público | Zonas cercanas (consulta espacial PostGIS) |
| GET | `/zones/{id}/history` | Público | Evaluaciones recientes de una zona |
| POST | `/subscriptions` | Público | Suscribe un celular a las alertas SMS de una zona |
| POST | `/subscriptions/{id}/cancel` | Código de baja | Da de baja la suscripción |
| POST | `/auth/login` | Público | Inicio de sesión de operadores (JWT) |
| GET | `/auth/me` | Operador | Datos de la sesión actual |
| POST | `/admin/evaluations` | Operador | Ejecuta el modelo de IA y despacha SMS |
| GET | `/admin/alerts` · `/admin/stats` | Operador | SMS enviados e indicadores |
| GET/POST | `/admin/users` | Administrador | Lista y crea cuentas |
| POST | `/admin/users/{id}/activate` · `/deactivate` | Administrador | Activa o desactiva cuentas |

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

# FERO Retry Scheduler

## 1. Resumen de la implementación

Esta implementación consta de una API REST con FastAPI, almacenamiento persistente de trabajos en SQLite y un worker independiente que consulta periódicamente los trabajos pendientes. Las entregas se realizan mediante HTTP POST, con una política de reintentos configurable, reclamación atómica de trabajos y recuperación mediante leases cuando se interrumpe el procesamiento.

## 2. Puesta en marcha

**Requisito:** Python 3.12.

Desde la raíz del repositorio, crea un entorno virtual e instala las dependencias (Windows PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Inicia la API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

En otra terminal, inicia el worker:

```powershell
.\.venv\Scripts\python.exe -m app.workers.scheduler
```

En Linux/macOS utiliza `.venv/bin/python` en su lugar. La base de datos SQLite y las tablas que falten se inicializan automáticamente; los trabajos existentes se conservan. La documentación interactiva de la API está disponible en <http://127.0.0.1:8000/docs>.

## 3. Uso de la API

**Crear un trabajo:** `POST /jobs/`

```json
{
  "url": "https://postman-echo.com/post",
  "payload": {"event": "order.created", "order_id": 123}
}
```

Devuelve `201 Created`, con un `id` generado y el estado inicial `pending`.

**Consultar su estado:** `GET /jobs/{id}/`

```json
{
  "id": "generated-uuid",
  "status": "completed",
  "attempts": 1,
  "next_retry_at": null
}
```

Los trabajos con datos inválidos devuelven `422`; los identificadores inexistentes, `404`.

## 4. Arquitectura y decisiones de diseño

- **API y worker independientes:** el registro de trabajos no depende de su entrega inmediata; los trabajos sobreviven a los reinicios del worker.
- **Service + Repository:** la lógica de aplicación y la persistencia con SQLAlchemy tienen responsabilidades diferenciadas, sin añadir capas innecesarias.
- **SQLite:** almacenamiento persistente con una configuración operativa mínima, adecuado para el alcance de esta prueba.
- **Reclamación atómica de trabajos:** una actualización condicional en la base de datos reclama los trabajos elegibles e incrementa el contador de intentos, evitando reclamaciones simultáneas bajo el funcionamiento normal de SQLite.
- **Leases con vencimiento:** los trabajos `running` abandonados pueden recuperarse; la finalización condicional rechaza actualizaciones de workers que ya no tienen el control del trabajo. Los trabajos con intentos agotados y lease vencido pasan a `dead`.
- **Política de reintentos independiente:** las decisiones son deterministas, configurables y comprobables sin llamadas HTTP reales.
- **Clave de idempotencia estable:** cada POST externo incluye la cabecera `Idempotency-Key`, derivada del UUID del trabajo mediante SHA-256 (prefijo `fero-v1-`). Los reintentos y las recuperaciones del lease mantienen el mismo valor, sin enviar el UUID original como valor de esa cabecera.

La reclamación del trabajo se confirma antes de realizar la petición HTTP externa, evitando mantener transacciones abiertas durante operaciones de red. La entrega sigue una semántica **at-least-once** (al menos una vez), sin garantía de *exactly-once*: un proceso puede enviar correctamente la petición y fallar antes de registrar el resultado. La cabecera permite que los receptores compatibles identifiquen peticiones duplicadas, pero el receptor debe implementar la deduplicación: el scheduler no puede evitar por sí solo efectos externos repetidos.

**Supuestos:** los trabajos proceden de clientes internos de confianza; los servicios de destino aceptan HTTP POST con JSON; la API y los workers comparten la misma base de datos SQLite.

## 5. Estrategia de reintentos y configuración

El ciclo de vida utiliza los estados `pending`, `running`, `completed`, `failed` y `dead`.

| Resultado | Comportamiento |
| --- | --- |
| HTTP 2xx | `completed` |
| HTTP 429, 500 y 503 (por defecto) | Reintento programado o `dead` si se agotaron los intentos |
| Fallo de transporte o timeout | Reintento programado o `dead` si se agotaron los intentos |
| Otra respuesta distinta de 2xx | `failed` |

La configuración está definida en `app/appsettings.json`:

| Parámetro | Valor predeterminado |
| --- | --- |
| Número máximo de intentos | 5 |
| Retraso inicial / multiplicador / retraso máximo | 2 s / 2 / 60 s |
| Códigos HTTP reintentables | 429, 500, 503 |
| Intervalo de consulta / timeout HTTP / lease | 1 s / 10 s / 60 s |

Los retrasos predeterminados después de los intentos 1–4 son **2, 4, 8 y 16 segundos**. El quinto fallo reintentable termina en `dead`. La ejecución real puede producirse después del instante programado, según el sondeo y la disponibilidad del worker.

## 6. Pruebas y compromisos de diseño

El desarrollo siguió **TDD (RED → GREEN → REFACTOR)**, empezando por las pruebas de la política de reintentos y ampliándose a la persistencia, la validación de la API, la reclamación atómica, los workers concurrentes, la recuperación de leases, el procesamiento HTTP y la propagación estable de claves de idempotencia entre reintentos.

Ejecuta la suite de pruebas:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

La implementación completa superó **136 pruebas con Pytest** en local. Las pruebas del worker utilizan respuestas HTTP controladas y bases de datos aisladas, para que las comprobaciones automatizadas sean deterministas.

La colección Postman (`tests/postman/FERO_Jobs_API.postman_collection.json`) contiene **19 peticiones** para crear trabajos, consultar sus estados, validar entradas y comprobar los resultados de entrega. Una ejecución verificada terminó con **324 validaciones aprobadas, cero fallos y cero errores**. Para ejecutarla, deben estar activos la API y el worker y seleccionarse **No Environment**.

También comprobamos la **entrega HTTP real de extremo a extremo** contra servicios públicos de pruebas, sin depender únicamente de mocks:

- **Postman Echo** (`https://postman-echo.com/post`): HTTP 200 -> `completed` tras un intento.
- **HTTPBin** (`https://httpbin.org`): escenarios HTTP 200, 400, 429, 500 y 503 comprobados mediante Postman; HTTP 400 -> `failed` tras un intento, mientras que los errores reintentables 429/500/503 -> `dead` tras cinco intentos si persisten. Los casos HTTP 400 y 503 también se comprobaron manualmente en los logs del worker.

**Compromisos de diseño y posibles mejoras:** SQLite presenta una concurrencia de escritura limitada frente a PostgreSQL; no se garantiza una entrega *exactly-once* y la deduplicación depende de que el receptor admita la clave de idempotencia. Un servicio de producción también necesitaría autenticación, protección frente a URL de salida peligrosas y SSRF, migraciones de base de datos, observabilidad y, potencialmente, jitter en los reintentos, soporte de `Retry-After` y renovación de leases para peticiones de larga duración.

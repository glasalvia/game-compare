# Game Compare 🎮

**Comparador de precios Steam ↔ Xbox Argentina**

Compara precios de videojuegos entre la tienda de Steam (USD) y la Xbox Store Argentina (ARS), usando IGDB como puente para cross-referenciar juegos idénticos entre ambas plataformas.

---

## Tabla de Contenidos

- [Descripción General](#descripción-general)
- [Arquitectura](#arquitectura)
- [Estructura del Proyecto](#estructura-del-proyecto)
- [Tecnologías](#tecnologías)
- [APIs Utilizadas](#apis-utilizadas)
- [Pipeline de Datos](#pipeline-de-datos)
- [Base de Datos](#base-de-datos)
- [Instalación](#instalación)
- [Uso](#uso)
  - [Poblar la cola de scraping](#poblar-la-cola-de-scraping)
  - [Ejecutar el pipeline](#ejecutar-el-pipeline)
  - [Servidor API + Frontend](#servidor-api--frontend)
  - [Auditoría y métricas](#auditoría-y-métricas)
- [API Endpoints](#api-endpoints)
- [Frontend](#frontend)
- [Mantenimiento](#mantenimiento)
- [Estado Actual](#estado-actual)

---

## Descripción General

Game Compare resuelve una pregunta simple pero hasta ahora difícil de responder para jugadores argentinos: **¿me conviene comprar este juego en Steam o en Xbox?**

El sistema:
1. **Descubre** juegos de la tienda de Steam por categorías (novedades, más vendidos, ofertas)
2. **Cross-referencia** cada juego Steam con su equivalente en Xbox usando IGDB (Internet Game Database)
3. **Obtiene precios** de la Microsoft Display Catalog API para Xbox (en ARS) y de la Steam API para Steam (en USD)
4. **Calcula multiplicadores** ARS/USD para identificar sobreprecios y gangas
5. **Sirve los resultados** vía una API REST y un frontend web retro 8-bit

**Caso de uso principal:** Identificar juegos donde la Xbox Store Argentina cobra significativamente más (o menos) que el equivalente en Steam, ayudando al consumidor a decidir dónde comprar.

---

## Arquitectura

```
┌──────────────────────────────────────────────────────────────────┐
│                      GAME COMPARE SYSTEM                         │
│                                                                  │
│  ┌─────────────┐    ┌──────────────────┐    ┌─────────────────┐ │
│  │ Steam Store │    │   IGDB v4 API    │    │  Xbox Display   │ │
│  │   (HTML +   │    │ (Twitch OAuth2)  │    │  Catalog API    │ │
│  │  appdetails)│    │                  │    │  (public, JSON) │ │
│  └──────┬──────┘    └────────┬─────────┘    └────────┬────────┘ │
│         │                    │                       │          │
│         ▼                    ▼                       ▼          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              definitive_pipeline.py                      │   │
│  │                                                          │   │
│  │  steam_app_id ──► IGDB game_id ──► Xbox store_id        │   │
│  │       │                                    │             │   │
│  │       ▼                                    ▼             │   │
│  │  Steam API                           Display Catalog    │   │
│  │  (precio USD)                        (precio ARS)       │   │
│  │       │                                    │             │   │
│  │       └────────────┬───────────────────────┘             │   │
│  │                    ▼                                     │   │
│  │           igdb_steam_to_xbox                             │   │
│  │           (match + comparación)                          │   │
│  └────────────────────────┬─────────────────────────────────┘   │
│                           │                                     │
│                           ▼                                     │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                 SQLite (games.db)                         │   │
│  │  games │ prices │ igdb_steam_to_xbox │ steam_queue        │   │
│  └────────────────────────┬──────────────────────────────────┘   │
│                           │                                     │
│                           ▼                                     │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │           api/server.py (Flask REST API)                  │   │
│  │                                                          │   │
│  │  GET /api/games      → Lista comparativa                 │   │
│  │  GET /api/game/:id   → Detalle de un juego               │   │
│  │  GET /api/stats      → Métricas globales                 │   │
│  │  GET /api/search     → Búsqueda por título               │   │
│  │  GET /api/config     → Dólar actual (dolarapi.com)       │   │
│  └────────────────────────┬──────────────────────────────────┘   │
│                           │                                     │
│                           ▼                                     │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              frontend/ (SPA 8-bit retro)                  │   │
│  │                                                          │   │
│  │  Tabla comparativa con sorting, filtros, Game Pass tag   │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

### Flujo de matching

```
Steam App ID (ej: 413150 → Stardew Valley)
    │
    ▼
IGDB external_games: uid="413150" → game_id=17000
    │
    ▼
IGDB external_games: game=17000 → UIDs: [413150, 9MWR1NC6VQ6L, ...]
    │
    ▼
Filtro regex: [A-Z0-9]{12} → Xbox Store ID: 9MWR1NC6VQ6L
    │
    ▼
Display Catalog API → ARS $214
Steam API appdetails → USD $4.99
    │
    ▼
Match: Stardew Valley — Steam $4.99 USD ↔ Xbox ARS $214 (×43)
```

---

## Estructura del Proyecto

```
game-compare/
├── api/
│   └── server.py              # Flask REST API (5 endpoints)
├── scrapers/
│   ├── _api_helpers.py          # Funciones compartidas (APIs Steam/IGDB/Xbox + DB)
│   ├── steam_xbox_pipeline.py   # Pipeline Steam→IGDB→Xbox (original)
│   ├── xbox_steam_pipeline.py   # Pipeline invertido IGDB Xbox→Steam
│   ├── populate_steam_queue.py  # Alimentador de cola (categorías Steam)
│   ├── steam_scraper.py         # Descubrimiento Steam via HTML + appdetails
│   └── verify_all.sh            # Auditoría y reporte de BD
├── frontend/
│   ├── index.html              # SPA frontend (8-bit retro)
│   ├── app.js                  # Lógica del frontend
│   └── backups/                # Versiones anteriores del frontend
├── data/
│   ├── games.db                # Base de datos SQLite
│   └── schema.sql              # Schema de referencia
├── research/
│   ├── steam_api_research.md   # Investigación sobre APIs de Steam
│   └── xbox_api_research.md    # Investigación sobre APIs de Xbox/IGDB
├── .env                        # TWITCH_CLIENT_ID + SECRET (IGDB)
├── run_scrape.sh               # Script legacy de scraping (obsoleto)
└── venv/                       # Entorno virtual Python
```

---

## Tecnologías

| Componente | Tecnología |
|---|---|
| Pipeline de datos | Python 3.14 |
| Base de datos | SQLite 3 |
| API REST | Flask + flask-cors |
| Frontend | HTML5 + CSS3 + Vanilla JS (SPA, 8-bit retro theme) |
| HTTP client | `requests` (Python) |
| HTML parsing | `beautifulsoup4` |
| IGDB auth | OAuth2 Client Credentials (Twitch) |

---

## APIs Utilizadas

| API | Autenticación | Propósito | Rate Limit |
|---|---|---|---|
| **Steam Store Search** (HTML) | Ninguna | Descubrimiento de juegos + precios + reviews | Sin límite documentado |
| **Steam appdetails** | Ninguna | Precios USD, géneros, metacritic | ~3 req/s seguro |
| **IGDB v4** (external_games) | OAuth2 (Twitch) | Steam app_id → Xbox store_id | 4 req/s |
| **Microsoft Display Catalog v7.0** | Ninguna | Precios ARS, títulos, Game Pass | 6 req/s seguro |
| **dolarapi.com** | Ninguna | Cotización USD/ARS oficial | Pública |

---

## Pipelines

Game Compare tiene **dos pipelines complementarios**:

| Pipeline | Archivo | Dirección | Fuente de catálogo | Tamaño máximo |
|---|---|---|---|---|
| **Steam → Xbox** | `steam_xbox_pipeline.py` | Steam App ID → IGDB → Xbox Store ID | `steam_queue` (Steam Store HTML) | ~235K juegos |
| **Xbox → Steam** | `xbox_steam_pipeline.py` | IGDB Xbox games → Steam IDs → Match | IGDB `games` endpoint (platform 49,169) | ~10K juegos |

El pipeline Steam→Xbox es útil para descubrimiento amplio (novedades, más vendidos). El pipeline Xbox→Steam es **23x más eficiente** porque el catálogo Xbox es el techo real: solo ~10K juegos vs ~235K de Steam.

### Funciones compartidas: `_api_helpers.py`

Ambos pipelines comparten 8 funciones extraídas a un módulo común:

```python
from scrapers._api_helpers import (
    igdb_token, igdb_call,       # IGDB v4 API
    steam_price,                  # Steam appdetails API
    xbox_price,                   # Microsoft Display Catalog API
    ensure_game, upsert_price,    # DB helpers
    store_match, save_checkpoint, # Orquestación
)
```

### Pipeline de Datos

### 1. `steam_xbox_pipeline.py` — Steam → Xbox

Pipeline original (ex-`definitive_pipeline.py`). Procesa la cola `steam_queue` juego por juego.

Alimenta la tabla `steam_queue` con app_ids de Steam desde categorías configurables.

```bash
cd game-compare && source venv/bin/activate
python scrapers/populate_steam_queue.py
```

**Categorías scrapeadas (configurables en el código):**
- Novedades populares (`filter=popularnew`) — 200 juegos
- Lo más vendido (`filter=topsellers`) — 200 juegos
- Ofertas (`specials=1`) — 200 juegos

La cola deduplica automáticamente: si un app_id ya existe, se saltea.

### 2. `xbox_steam_pipeline.py` — Xbox → Steam (invertido)

Pipeline invertido que consulta IGDB por todos los juegos de plataforma Xbox, identifica sus equivalentes Steam en una sola query por lote de 500, y almacena solo los matches.

```
IGDB games (Xbox platforms 49+169) → extraer Steam IDs + Xbox IDs → precios → store_match()
```

**Ejecución:**
```bash
# Procesar 200 juegos desde el inicio
python -u scrapers/xbox_steam_pipeline.py --limit 200 --verbose

# Desde un offset específico
python -u scrapers/xbox_steam_pipeline.py --offset 1000 --limit 500

# Reanudar desde checkpoint (id=2)
python -u scrapers/xbox_steam_pipeline.py --resume --verbose
```

**Características:**
- **Checkpoint id=2:** Usa `last_igdb_offset` en `pipeline_checkpoint` (id=2), independiente del pipeline Steam.
- **Source:** `'xbox_steam_pipeline_v1'` en `igdb_steam_to_xbox`, diferenciable de `'definitive_pipeline_v3'`.
- **Lote de 500 juegos por request:** Una sola query a IGDB con `external_games.uid,external_games.url,name`.
- **Producto cartesiano:** Si un juego tiene múltiples Steam IDs y múltiples Xbox IDs, procesa todas las combinaciones.

### 3. `steam_xbox_pipeline.py` — Pipeline Steam→Xbox (histórico)

Procesa la cola `steam_queue` juego por juego:

```
Para cada steam_app_id en steam_queue (status=pending):

1. Steam API appdetails
   → precio USD, título, is_free, original_price, discount_pct
   → Guardado en games + prices (si no existe)

2. IGDB external_games — Steam app_id → IGDB game_id
   → Búsqueda: uid="{steam_app_id}" con URL que contenga "steampowered"

3. IGDB external_games — IGDB game_id → Xbox IDs
   → Búsqueda: game={igdb_game_id}
   → Filtro regex: UIDs de 12 caracteres [A-Z0-9] (Xbox BigIDs)

4. Display Catalog API — Xbox store_id → precio ARS
   → ListPrice, MSRP, WholesalePrice, currency, is_free

5. Guardar en igdb_steam_to_xbox
   → steam_price_usd, xbox_price_ars, source='definitive_pipeline_v3'
```

**Ejecución:**
```bash
# Procesar cola completa
python -u scrapers/definitive_pipeline.py --verbose

# Reanudar desde checkpoint
python -u scrapers/definitive_pipeline.py --resume --verbose
```

**Características:**
- **Checkpointing:** Guarda progreso en `pipeline_checkpoint`. Se puede interrumpir y reanudar.
- **Deduplicación:** No re-procesa juegos ya en `igdb_steam_to_xbox` (por app_id).
- **Verificación automática:** Marca `price_verified=1` en `prices` al insertar.
- **Rate limiting:** 0.28s entre requests IGDB, 0.15s entre requests Display Catalog.
- **Batch commit:** Guarda cada 25 juegos procesados.

### 4. `steam_scraper.py` — Descubrimiento Steam (complementario)

Scrapea la tienda de Steam vía HTML search results + appdetails para obtener covers, URLs y plataformas que el pipeline principal no almacena.

```bash
python scrapers/steam_scraper.py [--force]
```

---

## Base de Datos

### Tablas

| Tabla | Filas | Descripción |
|---|---|---|
| `stores` | 2 | Tiendas: `xbox_argentina`, `steam_argentina` |
| `games` | 618 | Juegos de ambas tiendas (title, url, cover, platforms) |
| `prices` | 618 | Precios actuales (price, original_price, discount, verified) |
| `igdb_steam_to_xbox` | 542 | **Tabla principal:** matches Steam↔Xbox con precios comparados |
| `steam_queue` | 381 | Cola de app_ids a procesar por el pipeline |
| `pipeline_checkpoint` | 2 | Checkpoint: id=1 (steam_xbox), id=2 (xbox_steam) |
| `scrape_log` | 7 | Historial de ejecuciones de scraping |

### Schema completo

Ver `data/schema.sql` para el DDL completo con índices y foreign keys.

### Tabla principal: `igdb_steam_to_xbox`

```
steam_app_id     → Steam App ID (ej: 413150)
igdb_game_id     → IGDB game ID (ej: 17000)
xbox_store_id    → Xbox BigID (ej: 9MWR1NC6VQ6L)
xbox_title       → Título en Xbox Store
xbox_price_ars   → Precio en ARS (ListPrice)
xbox_msrp_ars    → MSRP original (sin descuento)
xbox_is_game_pass → 1 si está en Game Pass
steam_price_usd   → Precio en USD (Steam)
steam_original_usd → Precio original Steam
steam_discount_pct → % descuento en Steam
source           → 'legacy' o 'definitive_pipeline_v3'
```

---

## Instalación

### Requisitos

- Python 3.14+
- Cliente y secreto de Twitch (para IGDB API, gratuito en [dev.twitch.tv](https://dev.twitch.tv))

### Setup

```bash
# 1. Clonar
cd game-compare

# 2. Crear entorno virtual
python -m venv venv
source venv/bin/activate

# 3. Instalar dependencias
pip install requests beautifulsoup4 flask flask-cors python-dotenv

# 4. Configurar credenciales IGDB
# Crear .env con:
#   TWITCH_CLIENT_ID=tu_client_id
#   TWITCH_CLIENT_SECRET=tu_client_secret
#   IGDB_CLIENT_ID=tu_client_id
#   IGDB_CLIENT_SECRET=tu_client_secret

# 5. Inicializar base de datos
sqlite3 data/games.db < data/schema.sql
```

---

## Uso

### Poblar la cola de scraping

Descubre juegos de Steam por categorías y los encola:

```bash
cd game-compare && source venv/bin/activate
python scrapers/populate_steam_queue.py
```

### Ejecutar el pipeline

Procesa la cola y genera los matches de precios:

```bash
# Desde cero
python -u scrapers/definitive_pipeline.py --verbose

# Reanudar desde checkpoint (si se interrumpió)
python -u scrapers/definitive_pipeline.py --resume --verbose
```

### Servidor API + Frontend

```bash
cd game-compare && source venv/bin/activate
python api/server.py
```

El servidor arranca en `http://localhost:5000` y sirve tanto la API REST como el frontend SPA.

### Auditoría y métricas

```bash
cd game-compare && bash scrapers/verify_all.sh
```

Genera un reporte con:
- Conteo de juegos por tienda
- Precios verificados vs pendientes
- Total de matches con precio
- Zero-price errors
- Top 10 multiplicadores ARS/USD

---

## API Endpoints

### `GET /api/stats`
Estadísticas globales: conteo de juegos, matches, última actualización, cotización USD/ARS.

```json
{
  "games": {
    "xbox": 277,
    "steam": 341,
    "matched": 433,
    "comparable": 340
  },
  "last_update": {
    "xbox": "2026-07-26T02:53:11",
    "steam": "2026-07-26T17:20:20"
  },
  "usd_ars_rate": 1520,
  "usd_ars_source": "dolarapi.com (oficial)"
}
```

### `GET /api/games`
Lista comparativa de juegos matched. Ordenable y filtrable.

**Parámetros:**
- `sort` — `title`, `xbox_price`, `steam_price`, `multiplier`
- `order` — `asc` o `desc`
- `q` — Búsqueda por título
- `limit` / `offset` — Paginación (máx 500)

**Respuesta (fragmento):**
```json
{
  "games": [{
    "match_id": 7803,
    "match_score": 1.0,
    "xbox": {
      "title": "Stardew Valley",
      "price_ars": 214,
      "price_usd_equiv": 0.14,
      "is_game_pass": false
    },
    "steam": {
      "title": "Stardew Valley",
      "price_usd": 4.99,
      "discount_pct": 0
    },
    "cheapest": "xbox",
    "multiplier": 43.0
  }],
  "total": 340,
  "offset": 0,
  "limit": 50
}
```

### `GET /api/game/<steam_game_id>`
Detalle de un match específico.

### `GET /api/search?q=<keyword>`
Búsqueda de juegos por título en ambas tiendas.

### `GET /api/config`
Configuración del cliente: cotización USD/ARS en vivo desde dolarapi.com.

---

## Frontend

Interfaz web retro 8-bit accesible en `http://localhost:5000/`.

**Características:**
- Tabla comparativa con precio Steam (USD), precio Xbox (ARS), multiplicador
- Badges: Game Pass, Free, descuento
- Ordenamiento por precio, título, multiplicador
- Búsqueda por texto
- Tema oscuro pixel-art (Press Start 2P + Silkscreen fonts)
- Diseño responsive

---

## Mantenimiento

### Ejecución periódica recomendada

1. **Diario / bajo demanda:** Poblar cola con nuevas categorías y ejecutar pipeline
   ```bash
   python scrapers/populate_steam_queue.py
   python -u scrapers/definitive_pipeline.py --resume --verbose
   ```

2. **Semanal:** Auditoría de BD con `verify_all.sh`

3. **Mensual:** Re-scrapeo completo de Steam vía `steam_scraper.py`

### Reanudación tras interrupción

El pipeline es resiliente a interrupciones. Si se corta:
```bash
python -u scrapers/definitive_pipeline.py --resume --verbose
```
Retoma desde el último checkpoint guardado en `pipeline_checkpoint`.

---

## Estado Actual

*(Actualizado: 2026-07-27)*

| Métrica | Valor |
|---|---|
| Juegos en DB (Steam + Xbox) | 618 |
| Precios verificados | 618 (100%) |
| Matches Steam↔Xbox con precio | 433 |
| Tasa de match (juegos Steam → Xbox) | ~25% |
| Pipeline v3 matches (definitive) | 158 |
| Pipeline invertido matches (xbox_steam) | 209 |
| Legacy matches | 175 |
| Errores zero-price | 0 |
| Duplicados | 0 |
| Versiones | steam_xbox_pipeline.py + xbox_steam_pipeline.py |

### Limitaciones conocidas

- **Tasa de match ~25%:** No todos los juegos de Steam existen en Xbox. Es inherente al mercado.
- **IGDB rate limit:** 4 req/s. El pipeline usa 0.28s de delay (~3.5 req/s) para mantenerse seguro.
- **Display Catalog API no tiene search:** Solo se puede consultar por BigID conocido. No se puede buscar por nombre.
- **Steam precios en USD:** Steam Argentina dolarizó en 2023. La comparación requiere conversión USD→ARS vía dolarapi.com.

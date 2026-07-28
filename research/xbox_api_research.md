# Investigación: Microsoft Display Catalog API + IGDB para equivalencias Steam→Xbox

**Fecha:** 2026-07-26
**Autor:** Orquestador FASE-2
**Versión:** 1.0

---

## Resumen Ejecutivo

El pipeline Steam→Xbox funciona con dos APIs públicas (sin costo):

1. **IGDB API v4** — Puente Steam app_id → Xbox store_id
2. **Microsoft Display Catalog API v7.0** — Precios ARS y metadatos Xbox

Ambas están implementadas funcionalmente en `scrapers/reverse_pipeline.py` con 624 mapeos, 145 Xbox IDs y 136 precios. El pipeline está operativo pero tiene baja cobertura (~23% de los juegos Steam procesados obtienen Xbox ID).

---

## 1. Microsoft Display Catalog API

### Endpoint

```
GET https://displaycatalog.mp.microsoft.com/v7.0/products
```

### Parámetros

| Parámetro | Valor | Descripción |
|-----------|-------|-------------|
| `bigIds` | CSV de ProductIDs (ej: `9MVXMVT8ZKWC,9N2DMQBN9RC4`) | IDs de producto Xbox |
| `market` | `AR` | Mercado argentino → precios en ARS |
| `languages` | `es-ar` | Títulos y descripciones en español |
| `actionFilter` | `Purchase` | Filtra solo items comprables (incluye precios) |

### Capacidad de batch

Probado empíricamente: **hasta 100 IDs por request** (HTTP 200 confirmado para 10/20/30/50/100). Excelente para scraping masivo.

### Autenticación

**No requiere autenticación.** API pública. Sin token, sin API key, sin rate-limit documentado.

### Estructura de respuesta (resumida)

```json
{
  "Products": [{
    "ProductId": "9MVXMVT8ZKWC",
    "LocalizedProperties": [{
      "ProductTitle": "Minecraft",
      "DeveloperName": "Mojang/Microsoft Studios",
      "PublisherName": "Microsoft Studios",
      "Images": [{ "Uri": "//store-images.s-microsoft.com/...", "ImagePurpose": "Poster" }]
    }],
    "MarketProperties": [{
      "OriginalReleaseDate": "2017-09-20T00:00:00.0000000Z",
      "ContentRatings": [...]
    }],
    "DisplaySkuAvailabilities": [{
      "Sku": { "Properties": { "SkuDisplayGroupIds": ["01"] } },
      "Availabilities": [{
        "OrderManagementData": {
          "Price": {
            "ListPrice": 25712.0,
            "MSRP": 25712.0,
            "WholesalePrice": 17998.41,
            "CurrencyCode": "ARS",
            "WholesaleCurrencyCode": "ARS"
          }
        }
      }]
    }]
  }]
}
```

### Campos de precio relevantes

| Campo | Descripción | Ejemplo |
|-------|-------------|---------|
| `Price.ListPrice` | Precio final de venta al público | 25712.0 |
| `Price.MSRP` | Precio de lista original (sin descuento) | 25712.0 |
| `Price.WholesalePrice` | Precio mayorista (~70% de ListPrice) | 17998.41 |
| `Price.CurrencyCode` | Moneda (ARS para market=AR) | ARS |
| `Price.IsFree` | Si el juego es gratuito | (no presente si no es free) |

### Precios validados (ejemplos reales)

| ProductId | Título | ListPrice ARS | MSRP ARS |
|-----------|--------|---------------|----------|
| `9MVXMVT8ZKWC` | Minecraft | $25,712 | $25,712 |
| `9N2DMQBN9RC4` | Call of Duty® Black Ops Cold War | $18,900 | $54,000 |
| `BP15SF17LH13` | Battlefield 4 | $39.90 | $399 |
| `9P17KJLSCR59` | Choo-Choo Charles | $56.80 | $284 |
| `9MWR1NC6VQ6L` | Stardew Valley | $214 | $214 |

### Observaciones
- **ListPrice** puede ser menor que MSRP → indica descuento activo
- **WholesalePrice** es consistente (~70% de ListPrice), podría ser precio interno/distribuidor
- Sin `actionFilter=Purchase`, algunos productos no devuelven `DisplaySkuAvailabilities`
- Los SKUs pueden tener múltiples `Availabilities` (ej: Game Pass, compra directa, trial)
- URL de imágenes no incluyen protocolo (`//store-images.s-microsoft.com/...`)

---

## 2. IGDB API v4 (Twitch)

### Autenticación

OAuth2 Client Credentials con Twitch:
```
POST https://id.twitch.tv/oauth2/token
  client_id={TWITCH_CLIENT_ID}
  client_secret={TWITCH_CLIENT_SECRET}
  grant_type=client_credentials
```

Exchanges: cada token dura ~60 días, se auto-renueva en reverse_pipeline.py.

### Endpoint clave: external_games

```
POST https://api.igdb.com/v4/external_games
Headers: Client-ID, Authorization: Bearer {token}
Body (text/plain): where uid="{steam_app_id}"; fields uid,url,game; limit 10;
```

### Pipeline de equivalencia Steam→Xbox

```
Paso 1: external_games where uid="{steam_app_id}"
        → Seleccionar resultado con URL que contenga "steampowered"
        → Obtener IGDB game_id

Paso 2: external_games where game={igdb_game_id}
        → Filtrar UIDs que matcheen regex ^[A-Z0-9]{12}$
        → Estos son los Xbox store IDs (BigIDs)
```

### Ejemplo: Stardew Valley (413150)

```
Paso 1: uid="413150" → game=17000 (con url="steampowered.com/app/413150")
Paso 2: game=17000 → UIDs: [413150, 9MWR1NC6VQ6L, ...]
Resultado: 9MWR1NC6VQ6L → Display Catalog → ARS $214
```

### Ejemplo: CS2 (730)

```
Paso 1: uid="730" → game=242408 (steampowered URL)
Paso 2: game=242408 → solo 1 UID: "730" (sin Xbox ID)
Resultado: CS2 NO está en Xbox → sin match (correcto)
```

### Rate Limits

| API | Límite | Recomendación |
|-----|--------|---------------|
| IGDB v4 | 4 req/s (oficial) | 0.28s delay → ~3.5 req/s (safe) |
| Display Catalog | Sin documentar | 0.15s delay → ~6 req/s (empírico) |

### Problemas conocidos

1. **El campo `category` de external_games no es confiable** — IGDB ha dejado de devolverlo en muchas queries. reverse_pipeline.py ya ignora el filtro por category y usa regex sobre el UID para identificar Xbox IDs.

2. **Solo ~23% de juegos Steam tienen equivalente Xbox** — De 624 juegos procesados, solo 145 obtuvieron Xbox store_id. Esto refleja la realidad del mercado (muchos juegos Steam no están en Xbox y viceversa).

3. **Colisiones de UID** — Algunos UIDs de external_games son numéricos y ambiguos (ej: "730" aparece para 4 juegos distintos en IGDB). reverse_pipeline.py resuelve esto filtrando por la URL que contiene "steampowered".

---

## 3. Esquema Actual de la DB

### Tabla `igdb_steam_to_xbox` (pipeline principal)

```sql
CREATE TABLE igdb_steam_to_xbox (
    steam_game_id INTEGER NOT NULL,   -- FK a games.id
    steam_app_id TEXT NOT NULL,        -- Steam app ID
    igdb_game_id INTEGER,             -- IGDB game ID
    xbox_store_id TEXT,               -- Xbox BigID (12 chars alfanuméricos)
    xbox_title TEXT,                   -- Título del juego en Xbox
    xbox_price_ars REAL,              -- Precio en ARS (ListPrice)
    xbox_msrp_ars REAL,               -- MSRP en ARS
    xbox_wholesale_ars REAL,          -- Wholesale en ARS
    xbox_currency TEXT DEFAULT 'ARS',
    xbox_is_free INTEGER DEFAULT 0,
    xbox_is_game_pass INTEGER DEFAULT 0,
    matched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (steam_game_id, xbox_store_id)
);
```

### Estado actual (2026-07-26)
| Métrica | Valor |
|---------|-------|
| Steam juegos mapeados a IGDB | 624 |
| Con Xbox store_id | 145 (23.2%) |
| Con precio Xbox ARS | 136 (21.8%) |
| Sin match en Xbox | 479 (76.8%) |

---

## 4. Comparativa de Estrategias

### Estrategia A: IGDB (implementada)
**Pipeline:** Steam app_id → IGDB external_games → IGDB game_id → all external_games → regex Xbox IDs → Display Catalog

**Ventajas:**
- Determinístico (no hay ambigüedad de nombres)
- Cobertura con respaldo académico (IGDB es la base de datos de juegos más grande)
- Ya implementado y funcionando

**Desventajas:**
- ~23% de match rate (baja cobertura)
- Rate-limit de IGDB (4 req/s)
- Cada juego necesita 2+ requests a IGDB
- Algunos juegos Xbox populares no aparecen con 12-char ID (pueden usar GUIDs)

### Estrategia B: Search por nombre en Display Catalog
**Pipeline:** Steam app_id → nombre del juego → search por nombre en Display Catalog

**Ventajas:**
- Sin dependencia de IGDB
- Potencialmente mayor cobertura
- Sin rate-limit de IGDB

**Desventajas:**
- Ambigüedad de nombres (ej: "F1 2024" ≠ "F1® 24")
- Display Catalog no tiene endpoint de search documentado
  - `searchgui.microsoft.com/v1/autosuggest` existe pero es inestable
- Requiere fuzzy matching y validación extra

### Estrategia C: Híbrida IGDB + search por nombre
**Pipeline:** IGDB primero, fallback a search por nombre en Display Catalog

**Ventajas:**
- Máxima cobertura (~determinístico + heurístico)
- IGDB da calidad, search da cantidad

**Desventajas:**
- Más complejidad
- Más latencia (más requests)

---

## 5. Recomendación Final

**Estrategia A (IGDB) es la correcta para el MVP.** Con 136 juegos ya mapeados con precio, el pipeline funciona. La baja cobertura es inherente al mercado (no todos los juegos de Steam están en Xbox).

### Mejoras sugeridas para FASE-2

1. **Ejecutar reverse_pipeline.py sobre TODOS los juegos Steam de la DB** — Actualmente procesó solo 624 de 5,749 disponibles (~10%). Con 5,749 juegos, se esperarían ~1,300 matches Xbox.

2. **Agregar soporte para GUIDs además de 12-char IDs** — Algunos Xbox store IDs usan formato GUID (ej: `02753017-32ba-4f9f-b6e5-7c29b2623e78`). Display Catalog no los acepta como BigIDs, pero podrían mapearse vía otros endpoints.

3. **Agregar métricas de cobertura** — Trackear: juegos Steam totales, procesados por IGDB, con Xbox ID, con precio ARS.

4. **Batch optimization** — Display Catalog acepta 100 IDs/request. Implementar batching para reducir requests de ~6k a ~60.

5. **Tabla de debug** — Guardar external_games crudos de IGDB para depuración (ej: UIDs que no pasan el regex pero podrían ser válidos).

---

## 6. Ejemplo de Request/Response Completos

### Display Catalog API

```bash
curl -s "https://displaycatalog.mp.microsoft.com/v7.0/products?bigIds=9MWR1NC6VQ6L&market=AR&languages=es-ar&actionFilter=Purchase"
```

### IGDB API — Steam→Xbox (Stardew Valley)

```bash
# Paso 1: Steam app_id → IGDB game
curl -s -H "Client-ID: $CLIENT_ID" -H "Authorization: Bearer $TOKEN" \
  "https://api.igdb.com/v4/external_games" \
  -d 'where uid="413150"; fields uid,url,game; limit 10;'
→ [{uid:"413150", url:"steampowered.com/app/413150", game:17000}]

# Paso 2: IGDB game → all external_games
curl -s -H "Client-ID: $CLIENT_ID" -H "Authorization: Bearer $TOKEN" \
  "https://api.igdb.com/v4/external_games" \
  -d 'where game=17000; fields uid; limit 50;'
→ [{uid:"413150"}, {uid:"9MWR1NC6VQ6L"}, ...]

# Xbox ID: 9MWR1NC6VQ6L (12 chars alfanuméricos)
```

---

## 7. Archivos Relevantes

| Archivo | Rol |
|---------|-----|
| `scrapers/reverse_pipeline.py` | Pipeline completo Steam→IGDB→Xbox→Display Catalog |
| `scrapers/igdb_matcher.py` | Matcher IGDB standalone (posiblemente legacy) |
| `research/steam_api_research.md` | Investigación previa sobre APIs Steam |
| `.env` | TWITCH_CLIENT_ID + TWITCH_CLIENT_SECRET para IGDB |
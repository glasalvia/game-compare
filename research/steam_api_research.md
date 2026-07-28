# Steam API Research — Scraping sin Autenticación (ARG)

**Fecha:** 2026-07-26  
**Objetivo:** Extraer 100 juegos del catálogo argentino con precios y metadatos sin autenticación.

---

## 1. Tabla Comparativa de APIs

| API | Campos de Precio | Paginación | Precios | Cobertura | Rate Limits | Metadatos Extra |
|-----|-----------------|-----------|---------|-----------|-------------|-----------------|
| **`/api/storesearch/`** | `price.final`, `price.initial` (USD cents, int) | ❌ Máx 10 items | USD (cents) | Solo búsqueda por término | Sin headers de rate-limit | `tiny_image`, `metascore` (str), `platforms` |
| **`/api/featuredcategories`** | `original_price`, `final_price` (USD cents), `discount_percent` | ❌ Curados (Specials: 10, Top Sellers: 10, New Releases: 30) | USD (cents) | Solo curados editoriales | Sin headers | `header_image`, `id`, `discounted` (bool) |
| **`/search/results/` (HTML)** | `data-price-final` (cents), `discount_final_price`, `discount_original_price`, `discount_pct` | ✅ `start` + `count` (máx 100) | USD (cents en atributos, formateados en HTML) | Catálogo completo filtrable (166,809 juegos) | Sin rate-limit headers | `release_date`, `review_summary` + %, `platforms`, `tag_ids`, `desc_ids` |
| **`/search/results/` (JSON)** | ❌ Solo `name` y `logo` | ✅ `start` + `count` | ❌ No devuelve precios | Igual que HTML | Sin headers | ❌ Mínimo (solo nombre + logo) |
| **`/api/appdetails`** | `price_overview.initial`, `.final`, `.discount_percent` (cents), `package_groups[].subs[].price_in_cents_with_discount` | ❌ 1 app por request | USD (cents) | Cualquier app por ID | Sin headers observados | `metacritic.score`, `release_date.date`, `genres[]`, `categories[]`, `header_image`, `short_description`, `developers`, `publishers` |
| **`/api/featured/`** | `original_price`, `final_price`, `discount_percent`, `currency` | ❌ 10 por plataforma | USD (cents) | Solo featured editorial | Sin headers | `large_capsule_image`, `small_capsule_image` |

### Observaciones Clave

- **`/api/storesearch/`**: El campo `total` siempre reporta 10. No importa el valor de `count` que se envíe, siempre devuelve exactamente 10 resultados. Solo útil para autocomplete, no para extracción masiva.
- **`/search/results/` JSON**: Devuelve objetos con solo `name` y `logo`. No incluye `price`, `id`, `release_date`, ni ningún otro metadato. Esencialmente inútil para scraping de precios. No devuelve `total_count`.
- **`/search/results/` HTML**: Es el endpoint más completo. Cada fila de resultado es un `<a>` con atributos `data-ds-appid`, `data-ds-tagids`, `data-ds-descids`, y el precio final en `data-price-final`. El HTML contiene `search_released`, `search_review_summary`, `discount_block`, `platform_img`.
- **`/api/appdetails`**: El más rico en metadata. `price_overview` da precio final/original/descuento. `package_groups[0].subs[0].price_in_cents_with_discount` es el precio real del paquete base. `metacritic` es un objeto `{score, url}`. `release_date` es `{coming_soon, date}`.
- **`/api/featured/`**: Buenos precios (original/final/discount), pero sin géneros, metacritic, ni release_date. Solo 10 items por plataforma.
- **Ninguna API devuelve precios en ARS**. Steam abandonó ARS como moneda; todos los precios para Argentina están en USD (dolarizados desde noviembre 2023).
- **No se observaron rate-limit headers** (`X-RateLimit-*`, `Retry-After`) en ninguna de las pruebas.
- **`/search/results/`** permite `count=100` máximo. `count=50` devuelve 50 resultados. Con `start=0&count=100` se obtienen 100 juegos en una sola request.
- **El HTML search reporta "166,809 results"** con los filtros `category1=998` (solo juegos) sin query.
- **`category1=998`** filtra efectivamente solo juegos (excluye DLC, soundtracks, software).

---

## 2. API Recomendada: Estrategia Híbrida

### Recomendación

**Endpoint principal:** `store.steampowered.com/search/results/` (HTML mode)  
**Endpoint de enriquecimiento:** `store.steampowered.com/api/appdetails`  
**Endpoint complementario:** `store.steampowered.com/api/featured/`

### Justificación

La API de búsqueda HTML es la **única** que permite extraer 100+ juegos con precios en una cantidad razonable de requests (1-2 páginas). La búsqueda sin query ordena por relevancia de Steam (que prioriza popularidad + ventas), dando una muestra representativa del catálogo.

Para enriquecer con géneros y metacritic (que no vienen en la búsqueda HTML), se usa `appdetails` por appid de forma selectiva.

`/api/featured/` complementa con juegos destacados que podrían no aparecer en las primeras páginas de búsqueda.

### Por qué no las otras APIs

| API | Razón del descarte |
|-----|-------------------|
| `/api/storesearch/` | Limitado a 10 resultados. Sin paginación real. |
| `/search/results/` JSON | No devuelve precios ni IDs. Solo nombre + logo. Inútil. |
| `/api/featuredcategories` | Solo ~50 items curados. Sin géneros ni metacritic. |
| Solo `/api/appdetails` | Requiere 100 requests individuales. Inviable para descubrimiento. |

---

## 3. Esquema de Datos Propuesto

```json
{
  "app_id": 730,
  "name": "Counter-Strike 2",
  "price": {
    "currency": "USD",
    "initial_cents": 0,
    "final_cents": 0,
    "discount_percent": 0,
    "is_free": true,
    "formatted": "Free",
    "formatted_initial": null
  },
  "metacritic": {
    "score": null,
    "url": null
  },
  "release_date": {
    "date": "2012-08-21",
    "formatted": "21 Aug, 2012",
    "coming_soon": false
  },
  "genres": ["Action", "FPS"],
  "platforms": {
    "windows": true,
    "mac": false,
    "linux": true
  },
  "header_image": "https://shared.akamai.steamstatic.com/...header.jpg",
  "capsule_image": "https://shared.fastly.steamstatic.com/...capsule_sm_120.jpg",
  "review_summary": "Very Positive",
  "review_percent": 86,
  "review_count": 2580644,
  "developers": ["Valve"],
  "publishers": ["Valve"],
  "short_description": "For over two decades...",
  "scraped_at": "2026-07-26T22:46:00Z"
}
```

### Origen de cada campo

| Campo | Fuente Primaria | Fuente de Enriquecimiento |
|-------|----------------|--------------------------|
| `app_id` | `data-ds-appid` en HTML search | - |
| `name` | `<span class="title">` en HTML search | `appdetails.data.name` |
| `price.*` | `data-price-final` + `discount_block` en HTML search | `appdetails.data.price_overview` |
| `metacritic` | - | `appdetails.data.metacritic` |
| `release_date` | `<div class="search_released">` en HTML | `appdetails.data.release_date` |
| `genres` | - | `appdetails.data.genres[]` |
| `platforms` | `platform_img win/mac/linux` en HTML | `appdetails.data.platforms` |
| `header_image` | - | `appdetails.data.header_image` |
| `capsule_image` | `src` en `<div class="search_capsule">` | - |
| `review_summary` | `data-tooltip-html` en `<span class="search_review_summary">` | - |
| `developers` / `publishers` | - | `appdetails.data.developers`, `publishers` |
| `short_description` | - | `appdetails.data.short_description` |

---

## 4. Estrategia de Selección de 100 Juegos (MVP)

### Propuesta: Búsqueda sin query + diversificación por appdetails

**Fase 1 — Extracción masiva (1-2 requests HTTP):**
```
GET https://store.steampowered.com/search/results/
  ?query=
  &start=0
  &count=100
  &cc=ar
  &category1=998
```

Esto devuelve ~100 juegos ordenados por relevancia de Steam (top sellers/populares). Los primeros 100 representan una mezcla natural de AAA, indies populares, F2P, y lanzamientos recientes.

**Fase 2 — Enriquecimiento (100 requests a appdetails):**
Para cada app_id obtenido, llamar a:
```
GET https://store.steampowered.com/api/appdetails?appids={app_id}&cc=ar
```
Para obtener: géneros, metacritic, descripción, header_image, developers.

### Fundamento de variedad

La búsqueda sin query de Steam por defecto devuelve una mezcla natural que incluye:
- **AAA recientes** (Elden Ring, GTA V Enhanced, Forza Horizon 6)
- **F2P populares** (CS2, Dota 2, Apex Legends, Warframe)
- **Indies exitosos** (Palworld, Shift At Midnight, MECCHA CHAMELEON)
- **Diferentes géneros** (FPS, RPG, simulación, estrategia, battle royale, horror)
- **Rangos de precio variados** (gratis hasta $69.99 USD)
- **Juegos con y sin descuento**

### Plan de paginación

Si se necesitan exactamente 100 y el endpoint HTML devuelve solo 25-50 por página:
- Request 1: `start=0&count=50` → ~50 juegos
- Request 2: `start=50&count=50` → ~50 juegos
- Total: 100 juegos en 2 requests

Si count=100 funciona (confirmado: sí), 1 sola request basta.

---

## 5. Ejemplos de Request/Response Reales

### 5.1 `/api/storesearch/` — Búsqueda por término "a"

**Request:**
```bash
curl -s "https://store.steampowered.com/api/storesearch/?term=a&cc=ar"
```

**Response (primer item):**
```json
{
  "total": 10,
  "items": [
    {
      "type": "app",
      "name": "Assassin's Creed Black Flag Resynced",
      "id": 3751950,
      "price": {
        "currency": "USD",
        "initial": 4799,
        "final": 4799
      },
      "tiny_image": "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/3751950/e38674a3067b5ac028974bbfb42c835d0cf27122/capsule_231x87.jpg",
      "metascore": "",
      "platforms": {
        "windows": true,
        "mac": false,
        "linux": false
      },
      "streamingvideo": false
    }
  ]
}
```

**Observaciones:**
- `total` siempre es 10, sin importar el `count` enviado
- `metascore` es string vacío o número como string ("88")
- `price` ausente en items free-to-play
- Sin `header_image`, solo `tiny_image` (231x87)

---

### 5.2 `/api/featuredcategories` — Categorías destacadas

**Request:**
```bash
curl -s "https://store.steampowered.com/api/featuredcategories?cc=ar"
```

**Response (Daily Deal):**
```json
{
  "6": {
    "id": "cat_dailydeal",
    "name": "Daily Deal",
    "items": [
      {
        "id": 367450,
        "type": 0,
        "discounted": true,
        "currency": "USD",
        "original_price": 579,
        "final_price": 57,
        "discount_percent": 90,
        "name": "Poly Bridge",
        "header_image": "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/367450/header.jpg",
        "purchase_package": 66595
      }
    ]
  }
}
```

**Categorías disponibles:**
- `cat_spotlight` (x6): Weekend deals, free weekend
- `cat_dailydeal` (x1): 1 juego con descuento diario
- `cat_specials` / `specials` (10 items): Juegos en oferta
- `cat_coming_soon` (10 items): Próximos lanzamientos
- `cat_top_sellers` (10 items): Más vendidos
- `cat_new_releases` (30 items): Lanzamientos recientes

**Limitación:** Top sellers muestra "Steam Machine" (hardware) repetido 3 veces. La curación editorial no siempre coincide con lo que se busca.

---

### 5.3 `/search/results/` HTML — Búsqueda paginada sin query

**Request:**
```bash
curl -s "https://store.steampowered.com/search/results/?query=&start=0&count=5&cc=ar&category1=998"
```

**Response (primer item — Counter-Strike 2):**
```html
<a href="https://store.steampowered.com/app/730/CounterStrike_2/?snr=1_7_7_230_150_1"
   data-ds-appid="730" 
   data-ds-itemkey="App_730" 
   data-ds-tagids="[1663,1774,3859,3878,19,5711,5055]"
   data-ds-descids="[2,5]"
   data-ds-crtrids="[4]"
   class="search_result_row ds_collapse_flag"
   data-search-page="1" data-gpnav="item">
    <div class="search_capsule">
        <img src="...capsule_231x87.jpg">
    </div>
    <div class="responsive_search_name_combined">
        <div class="search_name ellipsis">
            <span class="title">Counter-Strike 2</span>
        </div>
        <div class="search_platforms">
            <span class="platform_img win"></span>
            <span class="platform_img linux"></span>
        </div>
        <div class="search_released responsive_secondrow">
            21 Aug, 2012
        </div>
        <div class="search_reviewscore responsive_secondrow">
            <span class="search_review_summary positive" 
                  data-tooltip-html="Very Positive<br>86% of the 2,580,644 user reviews..."></span>
        </div>
        <div class="search_price_discount_combined responsive_secondrow" 
             data-price-final="1499">
            <div class="discount_block no_discount">
                <div class="discount_final_price free">Free</div>
            </div>
        </div>
    </div>
</a>
```

**Ejemplo con descuento (GTA V Enhanced):**
```html
<div class="search_price_discount_combined" data-price-final="1499">
    <div class="discount_block">
        <div class="discount_pct">-50%</div>
        <div class="discount_prices">
            <div class="discount_original_price">$29.99</div>
            <div class="discount_final_price">$14.99</div>
        </div>
    </div>
</div>
```

**Datos extraíbles del HTML:**
- `data-ds-appid` → App ID (730)
- `.title` → Nombre
- `.search_released` → Fecha de lanzamiento
- `.search_review_summary` + `data-tooltip-html` → Review score y %
- `.platform_img` → Plataformas (win/mac/linux)
- `data-price-final` → Precio final en centavos USD
- `.discount_final_price` → Precio formateado
- `.discount_original_price` → Precio original (si hay descuento)
- `.discount_pct` → Porcentaje de descuento
- `.search_capsule img` → Imagen capsule

---

### 5.4 `/api/appdetails` — Detalle completo de un juego

**Request:**
```bash
curl -s "https://store.steampowered.com/api/appdetails?appids=1245620&cc=ar"
```

**Response (ELDEN RING):**
```json
{
  "1245620": {
    "success": true,
    "data": {
      "type": "game",
      "name": "ELDEN RING",
      "steam_appid": 1245620,
      "is_free": false,
      "header_image": "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1245620/header.jpg",
      "metacritic": {
        "score": 94,
        "url": "https://www.metacritic.com/game/pc/elden-ring"
      },
      "release_date": {
        "coming_soon": false,
        "date": "24 Feb, 2022"
      },
      "genres": [
        {"id": "1", "description": "Action"},
        {"id": "3", "description": "RPG"}
      ],
      "price_overview": {
        "currency": "USD",
        "initial": 4799,
        "final": 4799,
        "discount_percent": 0,
        "initial_formatted": "$47.99",
        "final_formatted": "$47.99 USD"
      },
      "package_groups": [
        {
          "name": "default",
          "title": "Buy ELDEN RING",
          "subs": [
            {
              "price_in_cents_with_discount": 4799,
              "option_text": "ELDEN RING - $47.99 USD"
            }
          ]
        }
      ],
      "platforms": {
        "windows": true,
        "mac": false,
        "linux": false
      },
      "developers": ["FromSoftware Inc."],
      "publishers": ["FromSoftware Inc.", "Bandai Namco Entertainment"],
      "short_description": "THE NEW FANTASY ACTION RPG..."
    }
  }
}
```

---

### 5.5 `/api/featured/` — Juegos destacados con precios

**Request:**
```bash
curl -s "https://store.steampowered.com/api/featured/?cc=ar"
```

**Response (featured_win, primer item):**
```json
{
  "id": 4518040,
  "type": 0,
  "name": "Goblins Stole My Panties",
  "discounted": true,
  "discount_percent": 38,
  "original_price": 855,
  "final_price": 530,
  "currency": "USD",
  "large_capsule_image": "...",
  "small_capsule_image": "...",
  "windows_available": true,
  "mac_available": false,
  "linux_available": false,
  "header_image": "...",
  "controller_support": "partial"
}
```

---

### 5.6 HTML Search — Datos de Paginación

**Total de resultados:** 166,809 juegos (con `category1=998`)
**Resultados por página:** Configurable vía `count` (máximo 100)
**Paginación:** Vía `start` (offset), ej: `start=0`, `start=100`, `start=200`

```
Request  count=50  →  50 resultados
Request  count=100 → 100 resultados (máximo observado)
Request  start=500 → Resultados correctos (página 6)
```

**Rate limits:** No se detectaron headers de rate-limiting en 5 requests consecutivas. Sin embargo, se recomienda un delay de 1-2s entre requests para evitar throttling implícito.

---

## 6. Conclusión y Recomendación Final

### Pipeline MVP

```
1. HTML search (count=100) → 100 app_ids + nombres + precios + plataformas + reviews
2. appdetails × 100 (con delay 1s) → géneros + metacritic + header_image + descripción
3. featured/ API → 10-30 juegos adicionales para diversidad (opcional)
```

### Ventajas de esta estrategia

1. **Mínimo de requests:** 101-102 requests HTTP para 100 juegos completos
2. **Precios reales:** USD en centavos, con descuentos detectados
3. **Catálogo representativo:** La búsqueda sin query ordena por relevancia/popularidad
4. **Metadatos ricos:** Géneros, metacritic, fecha, plataformas, reviews, descripciones
5. **Sin autenticación:** Todo funciona con requests GET simples
6. **Sin rate-limit aparente:** Con delays conservadores (1-2s), debería funcionar sin bloqueos

### Campos que NO están disponibles sin autenticación

- Número exacto de jugadores concurrentes (requiere `ISteamUserStats`)
- Wishlists / listas personales
- Historial de precios (requiere SteamDB o IsThereAnyDeal)
- Tags de usuario traducidos (los tag_ids del HTML son numéricos)
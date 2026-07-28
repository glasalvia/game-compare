# Lecciones Aprendidas

## 2026-07-27 — Pipeline Invertido Xbox → Steam

### Proyecto
Refactor del pipeline game-compare: extracción de helpers compartidos, renombrado de `definitive_pipeline.py` → `steam_xbox_pipeline.py`, creación de `xbox_steam_pipeline.py`.

### Resultados
| # | Card | Estado | Intentos | Modelo |
|---|------|--------|----------|--------|
| 1 | Extraer _api_helpers + rename pipeline | completed | 1 | deepseek |
| 2 | Crear xbox_steam_pipeline.py | completed | 1 | deepseek |
| 3 | Ejecutar pipeline --limit 200 | completed | 1 | qwen_mtp |
| 4 | Verificar métricas y duplicados | completed | 1 | — (main directo) |
| 5 | Actualizar README.md | completed | 1 | — (main directo) |

### Archivos creados/modificados
- `scrapers/_api_helpers.py` — 8 funciones + constantes compartidas (nuevo)
- `scrapers/steam_xbox_pipeline.py` — ex-definitive_pipeline.py (renombrado + imports limpios)
- `scrapers/xbox_steam_pipeline.py` — pipeline invertido (nuevo, 507 líneas)
- `README.md` — sección Pipelines (modificado)
- `PLAN.md` — plan del proyecto

### Métricas finales
- Matches `xbox_steam_pipeline_v1`: 209
- Matches `definitive_pipeline_v3`: 158
- Matches `legacy`: 175
- Total: 542 (0 duplicados reales, 516 comparables)

### Lecciones
1. **qwen_mtp timeout:** Subagentes con qwen_mtp para tareas de ejecución larga (>10 min) exceden timeout aunque el proceso siga corriendo. Para tareas que lanzan procesos largos, ejecutar desde el main directamente o usar deepseek.
2. **Cross-edition matches:** IGDB reporta un mismo juego Steam con múltiples Xbox IDs (edición base vs Series X|S). El producto cartesiano del pipeline produce variantes legítimas, no duplicados.
3. **store_match() hardcodea source:** La función en `_api_helpers.py` tiene `source='definitive_pipeline_v3'` hardcodeado. Se resolvió con un wrapper local que hace UPDATE post-insert. A futuro: refactorizar `store_match()` para aceptar `source` como parámetro.
4. **Dev-orchestrator efectividad:** El skill funcionó correctamente para este proyecto de 5 cards en secuencia lineal. Las cards de deepseek fueron las más productivas en código generado/línea.
<!-- /autoplan restore point: n/a (plan file nuevo, sin estado previo) -->
# Plan — página de resultados ambientada en el torneo

**Rama:** `main` · **Creado:** 2026-08-26 · **Autor:** Gabriel Cruz
**Alcance:** `src/cli/render.py`, `simular_usopen.py`, (nuevo) `src/cli/html_report.py` o similar, `output/` (nuevo, generado)
**Vía:** `/autoplan` (voces duales degradadas a `[subagent-only]`: codex no instalado en esta máquina)

---

## 0. Pedido original

> "necesito que los resultados de la predicion sean mostrado en una pagina.
> claramente ambientada en el torneo."

## 0A. Premisas — nombradas y evaluadas

| # | Premisa | Estado | Evidencia |
|---|---|---|---|
| P1 | Hoy los resultados solo existen como tabla Rich en terminal, no hay export a página/archivo | **Confirmada** | `src/cli/render.py` solo tiene `Console.print` (Rich), no hay ninguna escritura a disco de HTML/PDF en todo `src/` |
| P2 | El proyecto es CLI + SQLite puro, sin server web | **Confirmada** | `requirements.txt`: pandas, numpy, requests, rich, pytest — sin Flask/FastAPI/Django. Cero rutas HTTP en el repo |
| P3 | "Ambientada en el torneo" significa estética US Open (no un dashboard genérico) | **Asumida del pedido, razonable** | Es la palabra explícita del usuario; no hay lectura alternativa razonable |
| P4 | Uso personal/local, un usuario, sin necesidad de multi-usuario ni auth | **Confirmada por diseño del repo** | Un solo autor, SQLite local, sin variables de entorno de sesión/usuario en `config.py` |
| P5 | Los datos a mostrar son los que ya calcula el motor (`counts`, `players_by_id`, `meta`) — no hace falta nueva lógica de predicción | **Confirmada** | `render_probabilities` y `render_backtest` en `render.py` ya reciben exactamente esos datos; el pedido es de **presentación**, no de modelo |

Ninguna premisa es incorrecta. P3 es la única con algo de interpretación — la resuelvo con la pregunta de abajo antes de seguir (gate obligatorio, no auto-decidido).

## 0B. Mapa de código existente → sub-problemas

| Sub-problema | Ya existe en | Reusar / extender |
|---|---|---|
| Datos ya calculados (counts, players_by_id, meta) | `simular_usopen.py:180-192` (`render.render_probabilities(...)`) | Reusar tal cual — el nuevo renderer recibe los mismos parámetros |
| Formato de fila (ronda, %, IC95%) | `render.py:_binomial_ci95_pp`, `DISPLAY_ROUNDS`, `LABELS` | Reusar las mismas constantes y el mismo cálculo de IC — cero duplicación (P4 DRY) |
| Datos de backtest (Brier/log-loss/ECE) | `render.render_backtest`, `src/validation/backtest.py` | Mismo patrón: nuevo renderer HTML recibe el mismo `report`/`champion_log_loss` |
| Orquestación CLI (flags, flujo) | `simular_usopen.py:parse_args`, `main()` | Agregar flags, sin tocar la lógica de simulación |

Nada de esto se reinventa. Todo el trabajo nuevo es una capa de presentación adicional que consume las mismas estructuras de datos.

## 0C. Dream state

```
ACTUAL                          ESTE PLAN                         IDEAL A 12 MESES
─────────────────                ─────────────────                 ─────────────────
Tabla Rich en                    CLI genera un archivo             Fase 4 (sorteo oficial
terminal. Se pierde              HTML autocontenido,               en vivo) ya existe →
al cerrar la consola.            ambientado (US Open:              el mismo renderer HTML
No se puede compartir             azul cancha + amarillo            se reusa para un
ni ver en navegador.              pelota), abre solo                "dashboard" que se
Theming = monoespaciado.          en el navegador,                  regenera cada vez que
                                  sin dependencias nuevas.           llega un resultado real
                                  Mismos datos, misma               (auto-refresh, cuadro
                                  fuente de verdad.                  visual del bracket,
                                                                     publicado a GitHub
                                                                     Pages).
```

## 0C-bis. Alternativas de implementación

| Opción | Descripción | Effort (human / CC) | Riesgo | Pros | Cons |
|---|---|---|---|---|---|
| **A — HTML estático autocontenido (recomendada)** | Nueva función en `render.py` (o módulo dedicado) que escribe un `.html` a `output/`, mismo flujo CLI, `webbrowser.open()` (stdlib) para abrirlo | human: ~2-3h / CC: ~20 min | Bajo | Cero dependencias nuevas, funciona offline, coherente con "el CLI es el producto", reproducible por cualquiera que clone el repo | No es "vivo" — para actualizar hay que re-correr el comando (aceptable: así es hoy el resto del CLI) |
| B — Server web local (Flask) | Nuevo server, rutas, plantillas Jinja, puerto local | human: ~1-2 días / CC: ~2h | Medio-alto | Podría reaccionar a datos en vivo (irrelevante hoy: no hay ingesta en vivo, Fase 4 no existe) | Nueva clase de infra entera para un problema que no la necesita — fuera del blast radius, viola P5 (explícito > clever) |
| C — Publicar como Claude Artifact (fuera del repo) | Yo genero el HTML y lo publico como artifact en esta sesión | human: 0 / CC: ~5 min | Bajo técnico, alto en acoplamiento | Vista inmediata sin instalar nada | No es una capability del programa — otro usuario que clona el repo no lo obtiene corriendo `python simular_usopen.py`; depende de esta sesión de Claude, no reproducible ni versionable como el resto del proyecto |

**Decisión (P1 completitud + P5 explícito > clever + P3 pragmático):** Opción A. Es la única que dado el pedido real ("los resultados sean mostrados en una página") entrega una **capability del programa**, no un artefacto de esta conversación. C se ofrece opcionalmente al final como preview adicional, no como el deliverable.

## 0D. Análisis modo-específico (SELECTIVE EXPANSION)

Alcance base (blast radius, <1 día CC — auto-aprobado, P2):
- Nuevo módulo de render HTML (reusa `DISPLAY_ROUNDS`, `LABELS`, `_binomial_ci95_pp` de `render.py` — no duplicar, moverlos si hace falta compartirlos limpio).
- Flag `--html` (y `--no-open`) en `simular_usopen.py`.
- Aplica a **ambos** outputs existentes (`render_probabilities` y `render_backtest`) — mismo archivo, mismo patrón, effort marginal (P1 boil the ocean: no dejar el backtest fuera solo porque el pedido mencionó "predicción").
- Carpeta `output/` nueva, con `.gitignore` (son artefactos generados, no fuente).

Fuera de alcance (deferred, ver sección "NOT in scope"):
- Bracket visual interactivo (árbol del cuadro 128) — depende de Fase 4 (datos de cuadro en vivo con más estructura de emparejamientos por ronda que la que hoy expone `counts`).
- Server/dashboard en vivo — sin caso de uso hasta que exista ingesta en vivo.
- Publicación automática a GitHub Pages — deferred, requiere decisión de CI/CD que el usuario no pidió.

## 0E. Interrogación temporal

- **Hora 1:** `python simular_usopen.py --html` → escribe `output/us_open_2025_serve_return.html`, se abre solo en el navegador default, se ve la tabla de favoritos con theming US Open.
- **Hora 6+:** el usuario corre de nuevo con otro `--model elo` o `--draw-year` → nuevo archivo con nombre distinto (no pisa el anterior), puede abrir ambos y comparar. Si corre `--backtest 2010-2025 --html` → mismo flag, genera el reporte de backtest en vez del de predicción.

## 0F. Confirmación de modo

Modo: **SELECTIVE EXPANSION**. Alcance: presentación únicamente, cero cambios al motor de predicción (ya cubierto y en progreso por `PLAN_MEJORA_SIMULACION.md`, plan separado).

---

## GATE — Confirmación de premisas (única pregunta no auto-decidida de esta fase)

**D1 respondida:** HTML generado por el propio programa (Opción A, sin preview de artifact). Premisas P1-P5 confirmadas sin cambios. Alcance: nuevo flag `--html`/`--no-open` en `simular_usopen.py`, aplica a `render_probabilities` y `render_backtest`.

---

## 1-10. Secciones de revisión CEO

**1. Alineación estratégica:** el pedido es presentación pura, no cambia el modelo de predicción. No compite ni se superpone con `PLAN_MEJORA_SIMULACION.md` (ese plan es de precisión del motor, este es de output). Sin conflicto de roadmap.

**2. Error & Rescue Registry**

| Escenario | Riesgo | Mitigación |
|---|---|---|
| `output/` no existe | `FileNotFoundError` al escribir | `Path.mkdir(parents=True, exist_ok=True)` antes de escribir |
| Nombres de jugadores con caracteres especiales (acentos, ñ) | Mojibake o crash de encoding | Escribir el archivo con `encoding="utf-8"` explícito (Windows no lo asume por default) |
| Nombre de jugador con `<`/`&` (defensivo, no observado en los CSV de Sackmann) | Inyección HTML rota el layout | `html.escape()` sobre cada nombre antes de interpolar |
| `webbrowser.open()` sin navegador disponible (entorno headless/CI) | Excepción no controlada | `try/except` silencioso — el archivo ya se escribió, abrirlo es un plus, no el resultado |
| Re-ejecutar con mismos parámetros (año+modelo) | Pisa el archivo anterior sin aviso | Aceptado a propósito (mismo criterio que la DB: cada ingesta pisa la edición pedida) — se documenta en el `--help` del flag |

**3. Riesgo competitivo/de mercado:** N/A — proyecto personal sin usuarios externos ni competencia.

**4. Alternativas exploradas:** ver 0C-bis (3 opciones, decisión razonada).

**5-10 (seguridad, escalabilidad, dependencias, deuda técnica, compliance, rollback):** examinado — sin hallazgos. Sin inputs de red ni de usuario no confiables (los nombres vienen del propio pipeline de ingesta ya validado por los tests existentes de `tests/test_draw.py` y `tests/test_no_leakage.py`); cero dependencias nuevas (usa solo `pathlib`, `html`, `webbrowser` de la stdlib); rollback trivial (un flag opcional, comportamiento default sin `--html` queda idéntico al actual).

## NOT in scope

- Bracket visual interactivo del cuadro de 128 — depende de datos de emparejamiento por ronda que hoy `counts` no expone con esa granularidad; deferred hasta Fase 4 (sorteo en vivo).
- Server/dashboard en vivo con auto-refresh — sin caso de uso sin ingesta en vivo.
- Publicación automática a GitHub Pages / hosting — decisión de CI/CD no pedida.

## What already exists (reuso, no reinvención)

Ver 0B. Todo el cálculo (counts, IC95%, Brier/log-loss/ECE) se reusa tal cual; el trabajo nuevo es 100% capa de presentación.

## Dream state delta

Este plan cierra la brecha "solo terminal → página compartible" pero no toca la brecha hacia el ideal a 12 meses (dashboard en vivo post-Fase-4), que depende de trabajo de otro plan (ingesta en vivo) no de presentación.

## Completion Summary (Fase 1)

| Ítem | Estado |
|---|---|
| Premisas | 5/5 confirmadas, gate pasado (D1: opción A) |
| Alternativas evaluadas | 3 (A/B/C), A elegida y justificada |
| Alcance | Selective expansion — presentación, ambos comandos (predicción + backtest) |
| Hallazgos críticos | Ninguno |
| Voces duales | Codex no disponible (`[subagent-only]`) — ver consenso abajo |

<!-- AUTONOMOUS DECISION LOG -->
## Decision Audit Trail

| # | Fase | Decisión | Clasificación | Principio | Rationale | Rechazadas |
|---|------|----------|----------------|-----------|-----------|------------|
| 1 | CEO | Formato de salida: HTML generado por el CLI (no server, no artifact-only) | User Challenge → resuelto por el usuario (D1) | P5, P3 | Única opción que es capability reproducible del repo | B (server Flask), C (artifact-only) |
| 2 | CEO | Incluir `render_backtest` en el alcance HTML, no solo predicción | Mecánica | P1 (boil the ocean) | Mismo archivo `render.py`, mismo patrón, effort marginal | Dejar backtest fuera (rechazada: no hay razón para excluirlo) |
| 3 | CEO | Nombre de archivo `output/us_open_<año>_<modelo>.html`, se pisa en reruns idénticos | Mecánica | P5 (explícito) | Mismo criterio que ya usa la DB por edición | Timestamp en el nombre (rechazada: ruido, no hace falta versionar corridas) |
| 4 | CEO | Bracket visual interactivo, server en vivo, GitHub Pages | Boil-lakes fuera de blast radius → diferido | P2, P3 | Requieren infra o datos que no existen hoy (Fase 4) | Incluirlos ahora (rechazada: fuera de <1 día CC, sin caso de uso real) |
| 5 | CEO | Sumar barras de probabilidad (CSS puro, sin librería) sobre las columnas de ronda/campeón | Taste → auto-decidida | P1 (completitud), P3 (pragmático) | Hallazgo del subagente CEO: colorear la tabla no es lo mismo que "ambientarla" — una barra proporcional a la probabilidad usa datos ya calculados (`round_counts[r]/n_simulations`), cero costo extra, y es la palanca más barata para cumplir el pedido real ("claramente ambientada") en vez de solo repintar | Dejar la tabla sin visualización (rechazada: es la crítica más fuerte del subagente y el costo es marginal) |
| 6 | CEO | Suavizar la afirmación de continuidad del "dream state a 12 meses" (el renderer HTML de hoy no necesariamente sobrevive intacto a un dashboard en vivo) | Mecánica | P5 (explícito, no prometer de más) | Hallazgo del subagente: HTML armado a mano (sin motor de templates, por diseño, para no sumar dependencias) normalmente no escala a interactividad en vivo sin reescritura — mejor no dejar esa falsa continuidad para quien planifique Fase 4 | — |

## Step 0.5 — Voces duales (CEO)

**CODEX SAYS (CEO — strategy challenge):** `[codex-unavailable: binary not found]` — no instalado en esta máquina. Voz omitida, no cuenta como confirmación.

**CLAUDE SUBAGENT (CEO — strategic independence):** revisó el plan sin contexto previo. Hallazgos: (1) colorear la tabla no es lo mismo que "ambientarla" — falta una visualización barata (barras CSS de probabilidad) que sí cumple el pedido real, medium severity, **incorporado como decisión #5 arriba**; (2) el gate D1 confirmó el *mecanismo de entrega* (HTML vs server vs artifact), no la *estética* en sí — señala que traté una pregunta como si respondiera la otra; resuelto tratando la estética como decisión de diseño auto-decidida con principio explícito (P5), no como una segunda premisa que requiera parar de nuevo al usuario, y se surfacea como taste choice en el gate final; (3) suavizar la continuidad del dream-state a 12 meses, medium/low, **incorporado como decisión #6**; (4) riesgo competitivo: correctamente N/A, sin cambios.

```
CEO DUAL VOICES — CONSENSUS TABLE:
═══════════════════════════════════════════════════════════════
  Dimensión                            Claude   Codex   Consenso
  ──────────────────────────────────── ──────── ─────── ─────────
  1. Premisas válidas?                  Parcial   N/A     N/A (voz única) — P3 resuelta como taste de diseño
  2. Problema correcto a resolver?       Sí+       N/A     N/A (voz única) — con la mejora de #5
  3. Calibración de alcance correcta?    Sí        N/A     N/A (voz única)
  4. Alternativas suficientemente exploradas? Parcial N/A  N/A (voz única) — falta variante "tabla+barras", agregada
  5. Riesgos competitivos/mercado cubiertos? Sí (N/A aplica) N/A N/A (voz única)
  6. Trayectoria a 6 meses sólida?       Sí, con ajuste N/A N/A (voz única) — dream-state suavizado
═══════════════════════════════════════════════════════════════
Codex no disponible en esta corrida → fuente = [subagent-only]. Ningún ítem cuenta como
CONFIRMED (requiere ambas voces); los hallazgos del subagente se incorporaron igual (audit #5, #6).
```

**Fuente de voces:** `subagent-only`.

> **Fase 1 completa.** Codex: no disponible. Claude subagente: 4 hallazgos (2 incorporados directo, 1 resuelto como taste de diseño, 1 confirmado sin cambios). Consenso: N/A (voz única) — hallazgos aplicados igual. Pasando a Fase 2 (Design Review, UI scope detectado: "página", "ambientada", theming).

---

## Fase 2 — Design Review

**CODEX SAYS (design — UX challenge):** `[codex-unavailable]`.

**CLAUDE SUBAGENT (design — independent review):** revisó sin contexto previo. 9 hallazgos, 4 de severidad alta. Resumen: el plan nombraba la intención de theming en una línea de prosa ("azul cancha + amarillo pelota") y dejaba **todo** lo demás (jerarquía, orden, tipografía, hex concretos, manejo de ceros) a improvisación del implementador — exactamente el riesgo que el propio subagente de CEO ya había anticipado en la Fase 1.

```
DESIGN LITMUS SCORECARD (7 dimensiones, 0-10):
═══════════════════════════════════════════════════════════════
  Dimensión                              Antes de fix   Después (spec abajo)
  ──────────────────────────────────────  ────────────   ───────────────────
  1. Jerarquía de información             3/10           9/10 (masthead + orden por prob.)
  2. Estados (vacío/parcial/error)        5/10           9/10 (guards de cero + "sin datos")
  3. Arco emocional / primera impresión   3/10           9/10 (fuente + orden + barras)
  4. Especificidad visual (vs. genérico)  2/10           9/10 (hex, fuente, layout concretos)
  5. Consistencia entre reportes          4/10           8/10 (CSS compartido embebido)
  6. Accesibilidad (contraste)            N/A (sin specs)  8/10 (amarillo solo de acento, nunca texto)
  7. Alineación con el pedido original    4/10           9/10 (barras = forma del torneo, no color solo)
═══════════════════════════════════════════════════════════════
Fuente: subagent-only (codex no disponible). Consenso: N/A (voz única) — hallazgos aplicados igual.
```

### Auto-decisiones (P5 explícito + P1 completitud dominan en esta fase)

| # | Hallazgo del subagente | Severidad | Decisión | Principio |
|---|---|---|---|---|
| 7 | Sin masthead/metadata — la página no se identifica como "reporte US Open" | high | Banda superior fija: fondo azul cancha, texto blanco/amarillo: "{torneo} {año} · modelo {modelo} · {N} simulaciones · corte de datos {fecha}" | P5 |
| 8 | Sin orden default — tabla de 128 filas por seed entierra la historia real | high | Orden default: probabilidad de Campeón descendente. Seed queda como columna, no como sort key | P5 |
| 9 | Sin `font-family` — cae a serif default del navegador, rompe "ambientada" al instante | high | `font-family: 'Segoe UI', Arial, sans-serif`; `font-variant-numeric: tabular-nums` en columnas numéricas | P5 |
| 10 | Sin hex concretos — cada corrida podría verse distinta según improvisación | high | Paleta fija: azul cancha `#00539F` (headers/masthead), tint `#EAF2FB` (fondo de filas/track de barra), amarillo pelota `#CCFF00` (**solo acento**: fill de barra — nunca texto sobre blanco, falla contraste), tinta `#0B1F33` (texto, no negro puro) | P5 — **taste, surfacear en gate final** |
| 11 | Colisión barra + texto de IC en la celda de Campeón, agregadas ambas sin resolver layout | medium | Barra como track de fondo (`background` clip por %) detrás del número; IC95% como texto chico y apagado debajo del %, no concatenado | P5 |
| 12 | Sin manejo de `n=0`/CI indefinida (jugador eliminado, bye) | medium | Guard explícito: `n=0` o probabilidad indefinida renderiza `—`, nunca `0.0%` ni `NaN` | P1 (completitud — evita output roto) |
| 13 | Predicción y backtest son dos archivos sin identidad visual compartida | medium | Un único bloque `<style>` embebido (constante Python compartida) reusado en ambos templates — mismo masthead, misma paleta. Sin link cruzado entre archivos (rechazado: complejidad extra sin necesidad real para un usuario que abre archivos de una carpeta conocida) | P3 (pragmático) |
| 14 | Métricas de backtest incompletas por modelo no se distinguen de ceros reales | medium | Fila con métrica faltante: estilo atenuado (gris) + etiqueta "sin datos" explícita, nunca celda vacía o `0.0000` | P1 (completitud) |
| 15 | Barras ambiguas: ¿solo Champion o todas las rondas? | medium | **Todas las columnas de ronda** (R32→Campeón), no solo Campeón — el largo decreciente de las barras dibuja la forma del cuadro (curva de supervivencia), que es la palanca más barata para que la tabla "se sienta" el torneo sin construir el bracket interactivo (diferido) | P1 + P5, endosa el hallazgo del subagente |

**Ítem #10 (paleta de colores) se surfacea como taste choice en el gate final** — es la única decisión verdaderamente estética (vs. estructural) de esta lista; el resto son fixes de jerarquía/estado que no admiten alternativa razonable.

> **Fase 2 completa.** Codex: no disponible. Claude subagente: 9 hallazgos (8 auto-corregidos, 1 paleta surfaceada como taste). Consenso: N/A (voz única) — hallazgos aplicados igual. Pasando a Fase 3 (Eng Review).

---

## Fase 3 — Eng Review

**CODEX SAYS (eng — architecture challenge):** `[codex-unavailable]`.

**CLAUDE SUBAGENT (eng — independent review):** leyó el plan **y el código real** (`render.py`, `simular_usopen.py`, `config.py`, `ingest.py`, `repository.py`, `backtest.py`, `test_draw.py`). Hallazgos de alto valor, varios corrigen decisiones de las fases anteriores con evidencia de código:

```
ENG DUAL VOICES — CONSENSUS TABLE:
═══════════════════════════════════════════════════════════════
  Dimensión                            Claude   Codex   Consenso
  ──────────────────────────────────── ──────── ─────── ─────────
  1. Arquitectura sólida?                Con fixes  N/A   N/A (voz única) — módulo/ubicación resueltos abajo
  2. Cobertura de tests suficiente?      No (plan tenía 0) N/A  N/A (voz única) — test plan agregado abajo
  3. Riesgos de performance cubiertos?   Sí (N/A aplica) N/A  N/A (voz única)
  4. Amenazas de seguridad cubiertas?    Sí, con correcciones N/A N/A (voz única)
  5. Paths de error manejados?           Parcial   N/A   N/A (voz única) — corregido abajo
  6. Riesgo de deploy manejable?         Sí (sin deploy) N/A N/A (voz única)
═══════════════════════════════════════════════════════════════
Fuente: subagent-only.
```

### Auto-decisiones (P5 explícito + P3 pragmático dominan en esta fase)

| # | Hallazgo | Decisión | Principio |
|---|---|---|---|
| 16 | Ubicación de módulo sin resolver (¿nuevo módulo o extender render.py?) | Nuevo módulo `src/cli/html_report.py`. `render.py` queda Rich-only | P5 |
| 17 | `_binomial_ci95_pp`/`DISPLAY_ROUNDS`/`LABELS`/`MODEL_LABELS` son privados de `render.py`, reusarlos cross-módulo sin resolver el acoplamiento | Se mueven a `src/cli/formatting.py` (nuevo, compartido), `_binomial_ci95_pp` pasa a `binomial_ci95_pp` (público, es matemática pura sin side effects). `render.py` y `html_report.py` importan de ahí | P4 (DRY) |
| 18 | `output/` hardcodeado en vez de seguir el patrón de `config.py` (`DATA_RAW_DIR`, `DB_PATH`) | Agregar `OUTPUT_DIR = PROJECT_ROOT / "output"` a `config.py` | P5 (consistencia con el propio patrón del repo) |
| 19 | Convención de nombre de archivo definida solo para predicción, no para backtest (que no tiene un solo `draw_year`/`model`) | Backtest: `output/us_open_backtest_<inicio>-<fin>.html` (espeja el formato del flag `--backtest INICIO-FIN`) | P5 |
| 20 | `--top` (default 20, pensado para legibilidad en terminal) heredado sin revisar para HTML | HTML **siempre** muestra el cuadro completo (todos los `counts`, sin cortar por `--top`) — una página scrolleable con header sticky no tiene la restricción de la terminal, y el pedido fue "los resultados" no "los primeros 20" | P1 (completitud) |
| 21 | Decisión #12 (mostrar "—" para count=0) estaba mal planteada: `round_counts[r]==0` es un resultado **legítimo y frecuente** (ranking bajo que nunca llega a esa ronda en 10.000 sims), no un dato faltante | **Revertida.** count=0 se muestra como `0.0%` normal (es señal real). El guard "—" se elimina de la tabla de predicciones — no hay ningún estado de dato faltante ahí que necesite ocultarse | P5 (no inventar un estado que no existe) |
| 22 | Decisión #14 ("insufficient data" styling en backtest) pedía un estado que `ModelResult` no puede producir (todos los campos son floats obligatorios, no hay "parcial") | **Revertida a comportamiento existente.** La tabla HTML de backtest replica exactamente `if r is None: continue` (fila del modelo se omite si no está en `report.models`, igual que ya hace `render_backtest` hoy) — no se inventa un estado nuevo sin trigger real | P5 (YAGNI) |
| 23 | Falta `<meta charset="utf-8">` en el `<head>` — sin esto, algunos navegadores pueden adivinar mal el encoding de un HTML local aunque el archivo se haya escrito en UTF-8 | Agregar `<meta charset="utf-8">` como primera línea del `<head>` en ambos templates | P1 (completitud — cierra el riesgo de mojibake del todo, no solo a medias) |
| 24 | Evidencia citada en la Fase 1 (Error Registry) para "nombres ya validados" era incorrecta: `test_draw.py`/`test_no_leakage.py` no testean contenido/encoding de nombres, solo pairing de R64 y ausencia de leakage temporal | Corrección de texto en la sección 5-10 de Fase 1 (ver abajo) — la conclusión (riesgo bajo, `html.escape()` alcanza) seguía siendo correcta, pero la evidencia citada no | P5 (no dejar una afirmación mal sustentada) |
| 25 | `try/except` silencioso alrededor de `webbrowser.open()` especificado de forma ambigua (podría implementarse como `except:` desnudo) | Especificar `except Exception` explícito (no bare `except:` — evita tragarse `KeyboardInterrupt`/`SystemExit`) | P5 |
| 26 | `webbrowser.open()` con un path crudo de Windows (`str(path)`, backslashes) es poco confiable entre navegadores | Usar `webbrowser.open(output_path.resolve().as_uri())` — URI `file:///C:/...` correcta, relevante en este entorno win32 específicamente | P5 |
| 27 | CSS embebido compartido (decisión #13) si se escribe como f-string/`.format()` requiere escapar cada `{`/`}` literal de la propia sintaxis CSS — fuente de bugs silenciosos al primer edit futuro | El bloque `<style>` es una **constante de string plana, sin interpolación** (ni f-string ni `.format()`). Los valores por fila/celda se interpolan aparte, fuera del bloque CSS | P5 (explícito > clever) |
| 28 | Barras por celda (decisión #15, 768 celdas en el peor caso) necesitan porcentaje redondeado antes de interpolar, si no el HTML sale con `19.399999999999998%` | Redondear a 1 decimal (`round(pct, 1)`) antes de interpolar cualquier ancho/gradiente de barra | P5 |

## Arquitectura — diagrama de dependencias

```
simular_usopen.py (CLI orquestador)
        │
        ├── args.html? ──► src/cli/html_report.py (NUEVO)
        │                        │
        │                        ├── importa DISPLAY_ROUNDS, LABELS, MODEL_LABELS,
        │                        │     binomial_ci95_pp  ← src/cli/formatting.py (NUEVO, compartido)
        │                        │
        │                        ├── render_probabilities_html(counts, players_by_id, meta, output_dir=config.OUTPUT_DIR)
        │                        │     → escribe config.OUTPUT_DIR / us_open_<año>_<modelo>.html
        │                        │     → webbrowser.open(path.resolve().as_uri()) salvo --no-open
        │                        │
        │                        └── render_backtest_html(report, champion_log_loss, output_dir=config.OUTPUT_DIR)
        │                              → escribe config.OUTPUT_DIR / us_open_backtest_<inicio>-<fin>.html
        │
        └── (sin --html) ──► src/cli/render.py (EXISTENTE — sin cambios de lógica de negocio)
                                   │
                                   └── importa DISPLAY_ROUNDS, LABELS, MODEL_LABELS,
                                         binomial_ci95_pp  ← src/cli/formatting.py (movido acá, antes vivían en render.py)

config.py: + OUTPUT_DIR = PROJECT_ROOT / "output"   (nuevo, seguí el patrón de DATA_RAW_DIR/DB_PATH)
.gitignore: + output/                                (artefactos generados, no fuente)
```

Acoplamiento: `html_report.py` y `render.py` son hermanos, ambos dependen de `formatting.py` (nuevo) y de los mismos tipos de datos que ya produce `simular_usopen.py`. Ningún módulo existente cambia su contrato público — `render.py` pierde código (se muda a `formatting.py`) pero mantiene su firma. Cero acoplamiento nuevo hacia `src/simulation/` o `src/data/`.

## Corrección de texto — Fase 1, sección "5-10"

> ~~"cero inputs de red ni de usuario no confiables (los nombres vienen del propio pipeline de ingesta ya validado por los tests existentes de `tests/test_draw.py` y `tests/test_no_leakage.py`)"~~
> **Corregido:** esos tests validan pairing de R64 y ausencia de data leakage temporal respectivamente — ninguno testea contenido/encoding de nombres. La conclusión de riesgo bajo se mantiene (los nombres vienen de un CSV de origen conocido, no de input de usuario), y `html.escape()` sigue siendo la mitigación correcta como defensa en profundidad, no porque ya esté probado.

## Sección 3 — Test Review (obligatoria, no comprimida)

**Diagrama de test — cada codepath nuevo y su cobertura:**

| Codepath nuevo | Tipo de test | Existe hoy | Gap |
|---|---|---|---|
| `binomial_ci95_pp` movida a `formatting.py` | Unit | Sí (implícito, vía render) | Mover el test junto con la función si existe, o agregar uno directo |
| `html.escape()` aplicado a nombres de jugador | Unit | No | **Nuevo test**: nombre con `<`/`&` sintético → verificar que el HTML resultante no rompe estructura |
| Round-trip unicode (ej. "Étcheverry") | Unit/integración | No | **Nuevo test**: escribir con `encoding="utf-8"`, leer de vuelta, comparar string exacto — es el riesgo específico que el propio plan nombra para Windows |
| `count == 0` → se muestra "0.0%" (no "—", tras revertir #21) | Unit | No | **Nuevo test**: `round_counts["CAMPEON"] == 0` renderiza `0.0%`, no crashea, no muestra NaN |
| `--top` ignorado en modo HTML (decisión #20) | Unit | No | **Nuevo test**: `counts` con >20 entradas, `render_probabilities_html` incluye todas, independientemente de `args.top` |
| Modelo ausente de `report.models` en backtest HTML | Unit | Sí (equivalente en `render_backtest`, comportamiento a espejar) | **Nuevo test**: mismo `if r is None: continue`, verificar que no crashea y omite la fila |
| HTML generado es parseable (smoke test) | Smoke | No | **Nuevo test**: `html.parser.HTMLParser` sobre el string de salida, sin excepciones |
| `webbrowser.open()` no crashea si falla | Unit | No | **Nuevo test**: mockear `webbrowser.open` para lanzar excepción, verificar que la función de render no propaga el error (el archivo ya se escribió, abrir es un plus) |
| Redondeo de porcentaje de barra (decisión #28) | Unit | No | **Nuevo test**: input con float "feo" (ej. `19.399999999999998`) → output string tiene 1 decimal |

Sin evals de LLM/prompt aplicables (no hay modelo de lenguaje en este pipeline).

**Artefacto de test plan escrito en disco:** `PLAN_PAGINA_RESULTADOS_test_plan.md` (mismo directorio, ver archivo separado) — contiene la tabla de arriba en formato ejecutable (nombres de test sugeridos por archivo).

## Registro de failure modes (actualizado, Fase 3)

| Escenario | Severidad si no se maneja | Cubierto por |
|---|---|---|
| CSS con interpolación rota por `{`/`}` sin escapar | Alto (rompe el archivo entero, silencioso hasta el próximo edit) | Decisión #27 |
| `webbrowser.open()` con path crudo en Windows | Medio (falla abrir, pero el archivo ya existe) | Decisión #26 |
| Porcentaje de barra con ruido de float | Bajo (cosmético) | Decisión #28 |
| Estado "insuficientes datos" inventado sin trigger real | Medio (código muerto / confuso para el próximo contribuidor) | Decisión #22 (revertida) |
| Guard "—" aplicado a un resultado legítimo (0%) | Medio (oculta información real) | Decisión #21 (revertida) |

## What already exists (Fase 3)

`if r is None: continue` en `render_backtest` (patrón a espejar, no reinventar) — ver decisión #22. `_binomial_ci95_pp` (matemática, se mueve, no se reescribe) — ver decisión #17.

## NOT in scope (Fase 3, sin cambios respecto a Fase 1)

Ver sección "NOT in scope" de Fase 1 — sin adiciones.

## Completion Summary (Fase 3)

| Ítem | Estado |
|---|---|
| Arquitectura | Resuelta: `html_report.py` + `formatting.py` nuevos, `render.py` sin cambios de contrato |
| Diagrama de dependencias | Producido arriba |
| Test plan | Producido arriba + artefacto en disco |
| Hallazgos críticos | 2 decisiones de fases previas revertidas por evidencia de código (#21, #22) |
| Voces duales | Codex no disponible (`[subagent-only]`) |

> **Fase 3 completa.** Codex: no disponible. Claude subagente: 13 hallazgos (11 auto-corregidos, 2 revierten decisiones previas con evidencia de código). Consenso: N/A (voz única) — hallazgos aplicados igual. Sin scope developer-facing detectado (esto es un reporte para el usuario final del script, no una API/CLI para terceros) → **Fase 3.5 (DX) omitida**. Pasando a Fase 4 (Gate final).

---

## Cross-Phase Themes

**Tema: "temático" ≠ "con color".** Surgió de forma independiente en CEO (hallazgo #1: "colorear la tabla no es lo mismo que ambientarla") y en Design (hallazgo endosado #15: las barras son la palanca real, no la paleta). Señal de alta confianza — la respuesta terminó siendo estructural (barras por ronda = forma del cuadro) y no cosmética (paleta). La paleta quedó como el único taste item genuino.

**Tema: no inventar estados sin trigger real.** Surgió en Design (colisión barra+IC sin resolver) y se resolvió en Eng con evidencia de código (`ModelResult` no tiene campos parciales → decisión #22 revertida; `count=0` es señal real no dato faltante → decisión #21 revertida). Patrón: cada fase que solo "diseña en abstracto" corre riesgo de inventar UI para datos que el modelo real no produce — el chequeo contra el código en Fase 3 lo corrigió dos veces.

## Deferred a TODOS.md

Escribo `TODOS.md` (no existía) con los ítems diferidos de Fase 1 (0D): bracket visual interactivo, server/dashboard en vivo, publicación a GitHub Pages — los tres bloqueados por Fase 4 (sorteo oficial en vivo) del plan de mejora del motor, no por esta feature.

## Revisión post-gate — interactividad (pedida por el usuario tras aprobar)

Tras el gate final, el usuario pidió una capa adicional: **la página debe poder disparar
una nueva simulación desde un botón y actualizarse sola**, no solo mostrar un snapshot
estático que hay que regenerar volviendo a la terminal. Esto reabre la Opción B
descartada en la Fase 1 (0C-bis) — ahí se descartó un server porque no había caso de
uso; ahora sí lo hay, explícito y acotado por el propio usuario. No se re-corre el
gauntlet completo de subagentes para este ajuste (desproporcionado para el tamaño del
cambio); se documenta la decisión con el mismo rigor de principios ya usado.

**Decisión (P5 explícito + P3 pragmático, revisada):** dos modos, no uno reemplazando al otro:

| Flag | Qué hace | Server | Dependencias nuevas |
|---|---|---|---|
| `--html` (sin cambios) | Escribe un archivo estático a `output/`, se abre solo. Para compartir/guardar un snapshot | No | Ninguna |
| `--serve` (nuevo) | Levanta un servidor local (`http.server.ThreadingHTTPServer`, stdlib) en `127.0.0.1:<puerto libre>`, sirve la página ya con una corrida inicial, y un botón "Simular de nuevo" (con controles: simulaciones, modelo, año) dispara `POST /api/simulate`, que vuelve a correr el pipeline y devuelve el fragmento HTML de resultados actualizado — la página lo inyecta sin recargar | Sí, solo localhost | Ninguna (`http.server`/`json`/`threading` son stdlib) |

**Por qué no Flask:** el proyecto entero (0B, 0C-bis, decisiones #16-#28) se apoyó en "cero
dependencias nuevas" como principio explícito, verificado contra `requirements.txt` en la
Fase 1. `http.server.ThreadingHTTPServer` cubre el caso de uso real (una persona, local,
sin concurrencia real más allá de no bloquear un GET mientras un POST simula) sin romper
ese principio.

**DRY (P4), clave de esta revisión:** el HTML de la tabla de resultados se genera en
**una sola función** (`html_report.render_results_fragment(...)`), reusada por:
1. `--html` (la envuelve en un documento completo y la escribe a disco).
2. `--serve` (la sirve en el `GET /` inicial Y en cada respuesta de `POST /api/simulate`).

Ningún renderizado se duplica en JavaScript — el fragmento siempre se arma en Python;
el JS del navegador solo hace `fetch` + `element.innerHTML = fragmento`. Cero lógica de
presentación duplicada entre lenguajes.

**Failure modes nuevos (server):**

| Escenario | Mitigación |
|---|---|
| Puerto ocupado | `bind(("127.0.0.1", 0))` — el SO asigna un puerto libre, se imprime la URL real |
| Simulación tarda (10k sims ≈ 21s, ver PLAN_MEJORA_SIMULACION.md) y bloquea otros requests | `ThreadingHTTPServer` (stdlib) — un GET no espera a que termine un POST en curso |
| Parámetros inválidos desde el form (ej. `--model` no reconocido) | Endpoint responde 400 + JSON `{"error": ...}`, el frontend muestra el error inline, no rompe la página |
| Usuario cierra la terminal / Ctrl+C | `serve_forever()` en `try/except KeyboardInterrupt`, mensaje "Servidor detenido." |
| Expuesto sin querer a la red | Bind explícito a `127.0.0.1`, nunca `0.0.0.0` — documentado como requisito, no implícito |

**Alcance del form de controles:** simulaciones (número), modelo (`serve_return`/`elo`),
año de cuadro (número) — mismos parámetros que ya acepta la CLI. Seed y `--top` quedan
fuera del form (seed no fue pedido; `--top` ya se decidió irrelevante para HTML, decisión
#20 — el server también muestra siempre el cuadro completo).

---

## Revisión post-gate #2 — cuadro proyectado (bracket)

Segundo pedido tras la implementación: "quiero que se muestre el bracket". La
estructura de cruces del cuadro (quién juega contra quién en cada ronda) es
determinística desde el `draw` real (orden por `slot_index`, ver
`repository.load_draw`) -- no depende de las N corridas Monte Carlo, así que
no hace falta tocar `run_simulations`/`run_simulations_fast` ni su formato de
salida (`counts` por jugador/ronda no cambia).

**Decisión (P5 explícito, P4 DRY):** `pipeline.build_predicted_bracket`
calcula un **único camino determinístico** de favoritos (P(ganar) ≥ 0.5 en
cada cruce real, vía la probabilidad EXACTA ya existente --
`serve_return.match_probability` o `elo_model.match_probability_from_elo`,
sin Monte Carlo) desde R128 hasta el campeón proyectado. Es la lectura
estándar de "mostrame el bracket" (un cuadro completo y lleno, no una nube de
probabilidades) y no duplica ningún modelo: reusa las mismas funciones de
probabilidad de partido que ya calibró el plan de mejora del motor.

Render: `html_report.render_bracket_fragment`, siete columnas (R128→F) +
columna de Campeón, alineadas con el truco CSS clásico de brackets (todas
las columnas comparten la misma altura total, `justify-content: space-evenly`
hace que las rondas con menos partidos se espacien solas) -- sin JS ni SVG.
Incluido en `render_results_table` (parámetro opcional `model`), así aparece
tanto en `--html` como en `--serve`, y se recalcula en cada
`POST /api/simulate` sin costo relevante (127 llamadas a `match_probability`,
milisegundos).

**Corrección de robustez durante la implementación:** la primera versión de
`build_predicted_bracket` asumía un cuadro de exactamente 128 (igual que el
resto del motor) sin derivarlo de `len(players_by_id)` -- fallaba con
`IndexError` en cualquier tamaño distinto, incluidos los tests unitarios con
cuadros chicos. Se corrigió calculando `log2(n)` rondas y tomando los
últimos N nombres de `MATCH_ROUNDS`, así un cuadro de 2 jugadores arranca
directo en "F" en vez de en "R128". Verificado con tests (`tests/test_html_report.py`).

**Verificado end-to-end:** `--html` real generó 127 cruces + 1 campeón
proyectado (Jannik Sinner, modelo `serve_return`) en un HTML parseable;
`--serve` con `POST /api/simulate` (modelo `elo`) devolvió el fragmento con
bracket y tarjeta de campeón actualizados.

---

## GSTACK REVIEW REPORT

- **Fases corridas:** CEO, Design, Eng. DX omitida (sin scope developer-facing).
- **Voces:** `subagent-only` en las 3 fases (codex no instalado en esta máquina).
- **Gate de premisas:** pasado (D1, respondido por el usuario).
- **Decisiones:** 28 total — 1 user challenge (resuelto por el usuario en D1), 1 taste decision (paleta de color, ítem #10, surfaceada en el gate final), 26 auto-decididas (2 de ellas revierten decisiones previas de fases anteriores con evidencia de código real).
- **Artefactos en disco:** este plan, `PLAN_PAGINA_RESULTADOS_test_plan.md`.
- **Estado:** listo para implementación tras el gate final.

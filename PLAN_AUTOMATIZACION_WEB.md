<!-- /autoplan restore point: /c/Users/Gabo/.gstack/projects/Predecir_USOPEN/main-autoplan-restore-20260829-225014.md -->
# Plan: Automatización + Frontend Web (Fase 2 + Fase 3)
Generado por `/autoplan` el 2026-08-29. Branch: main. Repo: Gab9Cruzz/UsOpen_Prediction.

Pedido original del usuario (resumido): correr la predicción sola todos los días vía
GitHub Actions, exportar un JSON estático, y servir un dashboard "serio" (Tailwind +
Chart.js, bracket interactivo con hover) en GitHub Pages -- sin backend corriendo 24/7.

**Este documento es SOLO el plan** (a pedido explícito: "crea solo el plan para
implementar"). No se tocó código de producción -- los únicos archivos nuevos son este
plan, el restore point, y (al final del proceso) `MANUAL_STEPS.md` + el README
actualizado, que el usuario pidió que el plan mismo produjera como entregables de
"papeleo", no como código.

---

## 0. Qué ya existe (no se repite, ver "Fase 4" ya implementada)

El pedido original describe varias piezas como si no existieran. Ya existen, con más
profundidad de la pedida:

| Lo que pidió el usuario | Ya existe en el repo | Qué falta de verdad |
|---|---|---|
| "Correr la simulación Monte Carlo nuevamente ya sin los jugadores eliminados" | `src/simulation/monte_carlo.py::resolve_known_winner` + `known_results` en los 3 motores (serve_return/monte_carlo/elo) -- un partido real ya jugado se usa como hecho consumado, no se vuelve a sortear | Nada. Solo hay que LLAMAR al pipeline existente desde el workflow. |
| "Actualizará el archivo SQLite" | `src/data/ingest.py::run_ingest` + `src/data/live_draw.py` (sorteo oficial en vivo desde Wikipedia) ya hacen exactamente esto vía `--update-data` | Nada nuevo -- reusar tal cual. |
| "Gráfico de líneas mostrando cómo fluctuó la probabilidad tras cada ronda" | Los datos YA existen: `snapshots_prediccion` (SQLite) + `meta["round_snapshots"]` -- un snapshot de probabilidades por ronda (R128..F), persistido y congelado cuando ya no puede cambiar | Falta el GRÁFICO en sí (Chart.js consumiendo esos datos) y exportarlos a JSON -- eso sí es nuevo. |
| "Bracket interactivo... probabilidad exacta de ese cruce" | `src/cli/pipeline.py::build_predicted_bracket` ya calcula el favorito y la probabilidad EXACTA (sin Monte Carlo) de cada cruce, y `html_report.py::render_bracket_fragment` ya lo dibuja (sin JS, siempre visible) | Falta la interactividad (hover en vez de texto siempre visible) y exportar esa misma estructura a JSON para que la lea JS en vez de Python. |
| "Exportar un archivo estático resultados_simulacion.json" | No existe -- hoy la única salida "estática" es HTML autocontenido (`--html`), pensado para abrir localmente, no para que un frontend JS separado lo consuma | Nuevo: un exportador JSON. |
| "Backend corriendo 24/7" | Ya evitado -- `--serve` es explícitamente local/interactivo (`127.0.0.1` únicamente, ver `src/cli/server.py`), nunca se pensó para hosting público | Nada que cambiar; simplemente el nuevo sitio estático NO reemplaza a `--serve` (sigue sirviendo para explorar localmente con el botón "simular de nuevo") -- son dos consumidores distintos de la misma `run_prediction`. |

**Conclusión:** el pedido original es 100% capa de presentación + automatización.
Cero cambios al motor de datos/simulación. Esto reduce el pedido de "Fase 2 + Fase 3"
completas a un alcance mucho más chico de lo que el texto original sugiere.

---

## 1. Alcance final (post-reconciliación)

1. **Exportador JSON** (`--export-json PATH` en `simular_usopen.py`, reusando
   `run_prediction` tal cual): counts + players_by_id + meta + round_snapshots +
   bracket proyectado, en un JSON plano listo para `fetch()`.
2. **GitHub Actions workflow** (`.github/workflows/actualizar_prediccion.yml`):
   corre el pipeline existente + el exportador, commitea SOLO el JSON (no la DB ni
   los CSV -- ver hallazgo de Eng review sobre por qué) si cambió algo, con
   `permissions: contents: write`.
3. **Frontend nuevo** (`docs/index.html` + `docs/app.js`, Tailwind CDN + Chart.js CDN,
   tema oscuro tipo dashboard de analítica deportiva): lee el JSON, dibuja tabla +
   barras horizontales de probabilidad de campeón + línea de fluctuación por ronda +
   bracket con hover. Convive con (no reemplaza) `--html`/`--serve`.
4. **GitHub Pages**: sirviendo `docs/` desde `main` (o vía `actions/deploy-pages`,
   ver decisión de Eng review). Requiere un toggle manual en Settings -- va a
   `MANUAL_STEPS.md`.
5. **Papeleo**: commits explícitos por paso lógico, PR opcional, y actualización de
   `README.md`/`TODOS.md`.
6. **`MANUAL_STEPS.md`**: todo lo que Claude Code no puede hacer por sí mismo
   (toggles de Settings en GitHub, secrets, habilitar Pages).

**NOT in scope** (ver sección 6 para el detalle con razón de cada uno).

---

## 2. Step 0 — CEO Review (modo: SELECTIVE EXPANSION, auto-decidido por /autoplan)

### 0A. Premise Challenge

1. **¿Es el problema correcto?** El usuario quiere que la predicción se actualice
   sola y sea pública sin mantener un servidor. GitHub Actions + Pages es la
   respuesta estándar para "sitio estático que se actualiza solo, gratis" -- no hay
   una reformulación mejor (Layer 1 del framework Search Before Building: esto es
   exactamente el patrón "JAMstack con cron de CI" tal como se usa en cientos de
   dashboards públicos, no hace falta inventar nada).
2. **¿Cuál es el outcome real?** No es "tener GitHub Actions" -- es "que alguien
   entre a un link y vea la predicción actualizada del día, sin que Gabriel tenga
   que correr nada a mano." El plan de la sección 1 ataca eso directo.
3. **¿Qué pasa si no se hace nada?** Hoy generar `--html` requiere correr Python a
   mano cada vez y compartir el archivo -- funciona, pero no es "un link que se
   actualiza solo." Punto de dolor real, no hipotético (el usuario lo pidió
   explícitamente, dos veces, con detalle técnico propio).

**Premisa que SÍ se challengea (hallazgo nuevo, no estaba en el pedido original):**
el pedido dice "todos los días a la medianoche," sin condición. El US Open es un
torneo de ~2 semanas una vez al año -- correr esto 365 días/año:
- Los ~350 días sin torneo, `run_ingest` va a fallar (no hay R128 histórico NI
  sorteo en vivo en Wikipedia para una edición que ni se anunció) o, peor, va a
  simular sobre el cuadro de la ÚLTIMA edición jugada como si fuera noticia nueva
  (comportamiento actual documentado en el README, correcto para uso manual, mal
  para un cron que postea "actualización" todos los días sin novedad real).
- Correr una GitHub Action diaria que falla ~96% de las veces (350/365) es ruido:
  notificaciones de fallo constantes, minutos de CI gastados sin motivo.

**Recomendación:** acotar el cron a la ventana real del torneo (con no-op seguro
fuera de ella como red de seguridad, no como plan A) -- ver Alternativas (0C-bis) y
la pregunta de confirmación de premisas más abajo.

### 0B. Existing Code Leverage

Ver la tabla de la sección 0 -- mapeado sub-problema por sub-problema. Nada se
reconstruye; todo nuevo es capa de exportación/presentación sobre `run_prediction`.

### 0C. Dream State Mapping

```
ESTADO ACTUAL                    ESTE PLAN                         IDEAL A 12 MESES
Predicción manual,      --->     Un link público que se        --->  Mismo link, pero con
compartida como HTML             actualiza solo cada día del        historial de ediciones
local (--html).                  torneo, dashboard "serio"          pasadas navegable, y
Cero automatización.             con Tailwind+Chart.js.             alertas (push/email)
                                  Cero servidor propio.               cuando cambia el favorito.
```

Este plan mueve directo hacia el ideal (no hay que deshacer nada para llegar del
paso 2 al 3 -- el JSON exportado hoy es la base de datos histórica de mañana).

### 0C-bis. Implementation Alternatives

```
APPROACH A: JSON estático + GitHub Actions + GitHub Pages (RECOMENDADO)
  Resumen: exactamente lo que pidió el usuario -- CI corre el pipeline Python
  existente, exporta JSON, commitea, Pages lo sirve.
  Effort: S (human: ~1 día / CC: ~2-3h de implementación real, este plan ya
  hizo el trabajo de diseño)
  Risk: Bajo -- todo el motor de datos ya existe y está testeado (130 tests).
  Pros: Cero infra nueva que mantener; gratis; el usuario ya sabe exactamente
        qué quiere y coincide con el patrón estándar de la industria (JAMstack).
  Cons: GitHub Actions tiene latencia de cron (no es "tiempo real" al segundo);
        depende de que GitHub esté arriba.
  Reusa: run_prediction, build_predicted_bracket, snapshots_prediccion -- el
         100% del motor.

APPROACH B: Backend liviano siempre corriendo (Render/Fly.io free tier + API)
  Resumen: en vez de JSON estático + cron, un servicio pequeño sirve --serve
  (o una API REST) 24/7, el frontend pega directo por fetch a la API.
  Effort: M (human: ~2-3 días / CC: ~1 día -- hay que adaptar server.py a un
  framework real, manejar el free tier durmiéndose, etc.)
  Risk: Medio -- free tiers de hosting duermen el proceso tras inactividad
        (latencia fría en la primera visita del día), y es infra nueva a
        mantener para un proyecto que hoy es 100% archivos.
  Pros: Datos "en vivo" de verdad (sin esperar al próximo cron), reusa --serve
        casi tal cual.
  Cons: Va exactamente CONTRA lo que el usuario pidió explícitamente
        ("sin necesitar un backend corriendo 24/7") -- constraint explícita
        del pedido, no una preferencia mía.
  Reusa: server.py, run_prediction.

APPROACH C: Todo a mano, sin CI (solo el exportador JSON + Pages)
  Resumen: agregar el exportador JSON y el frontend, pero SIN el workflow de
  GitHub Actions -- Gabriel corre `--export-json` a mano y comitea cuando quiere.
  Effort: XS (human: ~2h / CC: ~1h)
  Risk: Bajo, pero no resuelve el pedido real ("todos los días a la
        medianoche" implica automático, no manual).
  Pros: Más simple, cero riesgo de CI mal configurado.
  Cons: No cumple el pedido explícito de automatización -- es la versión
        "recortada" que el usuario NO pidió.
  Reusa: igual que A, menos el workflow.
```

**RECOMENDACIÓN:** Approach A, con la ventana de cron acotada al torneo (hallazgo
de 0A) en vez de "todos los días del año" literal -- mapea a la preferencia
"explícito sobre clever" (un cron que corre year-round y falla 350 días no es
explícito, es ruido) y a "código bien testeado, no frágil."

*(Auto-decidido por /autoplan, principio P1+P5 -- Approach A es la única que
cumple la restricción explícita del usuario de "sin backend 24/7" Y tiene mayor
completeness que C. No hay TASTE DECISION acá: A domina en cobertura sin violar
ninguna restricción del usuario.)*

### 0D. Selective Expansion — HOLD SCOPE primero

**Complexity check:** ~6-7 archivos nuevos/tocados (workflow YAML, exportador JSON,
`docs/index.html`, `docs/app.js`, README, TODOS.md, MANUAL_STEPS.md) y ~1 servicio
nuevo conceptual (el exportador). Por debajo del umbral de 8 archivos / 2 servicios
-- no dispara reducción de alcance.

**Mínimo necesario:** los 5 puntos de la sección 1. Nada de eso es diferible sin
dejar el pedido incompleto.

**Expansiones candidatas escaneadas (cherry-pick, neutral, ver sección 5 para las
decisiones):**
1. Historial de ediciones pasadas navegable en el dashboard (guardar un JSON por
   año en vez de sobreescribir uno solo).
2. Botón "compartir" / Open Graph tags para que el link se vea bien en redes.
3. Página de error/estado ("todavía no hay sorteo para esta edición") en vez de
   que el sitio quede con el JSON de la edición anterior sin aviso.
4. Alertas por email/push cuando cambia el favorito -- mencionado en el "ideal a
   12 meses," claramente fuera de este PR.
5. Badge de "última actualización: hace X horas" en el dashboard, leído del
   propio JSON (`generated_at`).

### 0E. Temporal Interrogation

```
HORA 1 (fundaciones):     ¿Qué formato exacto tiene el JSON? ¿Un archivo por
                           edición o siempre el mismo path? -- resuelto en la
                           sección 3 (Arquitectura), no se deja para
                           implementación.
HORA 2-3 (lógica core):   ¿Qué pasa si el cron corre y el pipeline tira una
                           excepción (Wikipedia caída, sin R128 todavía)? --
                           resuelto: el workflow no debe fallar "rojo" por eso,
                           ver sección 4 (manejo de errores del workflow).
HORA 4-5 (integración):   ¿El commit del bot dispara el mismo workflow nuevamente
                           (loop)? -- resuelto: cron-only trigger, sin `on: push`.
HORA 6+ (pulido):         ¿Qué pasa la primera vez que se visita el sitio y
                           todavía no corrió ningún cron (JSON no existe)? --
                           resuelto: el primer commit de este PR incluye un JSON
                           inicial generado a mano (`--export-json`), el sitio
                           nunca arranca vacío.
```

---

## 3. Arquitectura (Eng Review)

```
                    ┌─────────────────────────────────────────┐
                    │   GitHub Actions (cron, ventana torneo)  │
                    │                                           │
  Wikipedia ───────►│  1. checkout                              │
  (live_draw.py)    │  2. setup-python + pip install -r reqs   │
  Sackmann CSVs ───►│  3. python simular_usopen.py             │
  (fetchers.py)     │       --update-data --export-json \      │
                    │       docs/data/resultados_simulacion.json│
                    │  4. git diff --quiet docs/data/*.json ||  │
                    │       (git commit && git push)            │
                    └──────────────────┬────────────────────────┘
                                        │ commit solo si cambió
                                        ▼
                    ┌─────────────────────────────────────────┐
                    │   docs/  (servido por GitHub Pages)      │
                    │   ├── index.html  (Tailwind CDN)         │
                    │   ├── app.js      (fetch + Chart.js CDN) │
                    │   └── data/resultados_simulacion.json    │
                    └──────────────────┬────────────────────────┘
                                        │ fetch() en el browser del visitante
                                        ▼
                              Visitante público (sin login,
                              sin backend, HTTPS gratis de Pages)
```

### 3.1 Exportador JSON -- `--export-json PATH`

Nueva flag en `simular_usopen.py`, reusando `run_prediction(...)` sin tocarla.
Forma del JSON (una función nueva, `src/cli/json_export.py::export_json`,
construida a partir de `counts`/`players_by_id`/`meta` -- las mismas piezas que
ya consume `html_report.py`, ningún dato nuevo que calcular):

```json
{
  "meta": {
    "tournament_name": "Us Open",
    "tournament_year": 2026,
    "generated_at": "2026-08-29T22:00:00Z",
    "model": "serve_return",
    "n_simulations": 10000,
    "is_live": true,
    "note": "..."
  },
  "players": [
    {"player_id": "100644", "full_name": "Alexander Zverev", "seed": 1,
     "probabilities": {"R32": 0.78, "R16": 0.63, "QF": 0.51, "SF": 0.36, "F": 0.23, "CAMPEON": 0.096}}
  ],
  "round_snapshots": [
    {"round_name": "R128", "frozen": true,
     "players": {"100644": {"CAMPEON": 0.08, "...": "..."}}}
  ],
  "bracket": [
    {"round": "R128", "matches": [{"favorite_id": "100644", "underdog_id": "132283", "prob": 0.71}]}
  ]
}
```

Nota de diseño: `players`/`bracket` referencian `player_id`, con un solo
diccionario `players` como fuente de nombres -- evita repetir `full_name` en cada
snapshot (el JSON de 7 snapshots × 128 jugadores con nombres repetidos sería ~3x
más pesado sin necesidad).

**Correcciones tras la revisión independiente (subagente Claude, ver "Outside
Voice" al final) -- 3 hallazgos que cambian el diseño de acá arriba:**

- **`export_json` NO es un passthrough de cero cómputo** (como decía la versión
  anterior de este párrafo) -- hay tres conversiones reales que sí son código
  nuevo: (a) `counts`/`round_snapshots[i]["counts"]` son conteos enteros crudos
  (`count`, no probabilidad) -- hoy la normalización `count/n_simulations` vive
  inline en `html_report._round_cell`, no existe como helper reusable, hay que
  escribirla; (b) `build_predicted_bracket` devuelve objetos `Player`/`EloPlayer`
  como `favorite`/`underdog`, no los strings `favorite_id`/`underdog_id` que pide
  el schema -- hace falta mapear `.player_id`; (c) **`meta["known_results"]` es
  `dict[tuple[str,int], str]` -- las claves tupla NO son serializables a JSON**
  (`json.dumps` tira `TypeError` si se intenta volcar `meta` entero tal cual).
  El exportador arma su propio dict de salida campo por campo (nunca
  `json.dumps(meta)` directo) -- este es un gotcha explícito para quien
  implemente, no un detalle menor.

### 3.2 Workflow de GitHub Actions

Hallazgos de esta revisión (Eng, Section "Performance" y "Failure modes" +
revisión independiente del subagente):

- **CRÍTICO, encontrado por la revisión independiente: pasar `--draw-year`
  explícito, SIEMPRE.** `config.DEFAULT_DRAW_YEAR` está hardcodeado a `2025`
  (`src/config.py`). Si el workflow invoca `python simular_usopen.py
  --update-data --export-json ...` SIN `--draw-year`, la automatización va a
  simular el torneo 2025 (ya jugado, terminado) **para siempre**, indefinidamente,
  sin que el job falle ni se note -- exactamente el bug que este plan existe
  para evitar, coló de vuelta por confiar en el default. Fix: el paso del
  workflow SIEMPRE pasa `--draw-year "$(date +%Y)"` (año calendario actual). Esto
  además ELIMINA la necesidad de bumpear un año a mano cada temporada (ver 7.3 --
  el único mantenimiento anual que queda es la ventana del cron, no el año).
- **No commitear `database/us_open.db` ni `data/raw/*.csv` desde CI.** El repo ya
  los tiene commiteados para desarrollo local (decisión previa, fuera de este
  plan), pero un cron diario que pisa un binario SQLite todos los días infla el
  historial de git sin límite (a diferencia de un JSON de texto, que sí comprime
  bien con delta). CI reconstruye la DB desde cero cada corrida (`--update-data`
  ya hace esto) y la descarta al terminar el job -- solo el JSON sale del runner.
- **Commit condicional (`git diff --quiet`).** Sin esto, cada corrida del cron
  genera un commit aunque nada haya cambiado (mismos resultados, mismo seed) --
  ruido en el historial y falsos "hubo una actualización" para quien mire el repo.
- **`permissions: contents: write`** explícito en el workflow -- desde 2023 GitHub
  cambió el default de `GITHUB_TOKEN` a solo lectura en repos nuevos; sin esto el
  push del bot falla en silencio con un 403. (Ver `MANUAL_STEPS.md` para el
  toggle correspondiente en Settings, por si el default del repo ya lo tiene en
  otro lado.)
- **Manejo de errores: distinguir "no-op esperado" de "falla real que hay que
  ver" (afinado por la revisión independiente).** El chequeo de ventana de
  torneo va ANTES de invocar Python (un `if` sobre la fecha, en el propio YAML) --
  fuera de esa ventana, el job ni siquiera corre el pipeline (no-op limpio, exit
  0, sin commit). **Pero DENTRO de la ventana**, si `simular_usopen.py` falla de
  verdad (Wikipedia cambió su formato, la fuente de CSV está caída, un bug real),
  el job NO debe tragarse el error con un `|| true`/`continue-on-error` genérico
  -- tiene que fallar en rojo y notificar. Envolver TODA la invocación en un
  supresor de errores taparía justo las fallas reales durante las dos semanas en
  que la corrección importa de verdad.
- **Cron acotado a la ventana del torneo**, no `0 0 * * *` todo el año (hallazgo
  de 0A, confirmado por la revisión independiente como correcto y no
  sobre-ingenierizado para este proyecto) -- ejemplo: `0 5 * * *` (5am UTC, ~
  medianoche US Eastern) limitado a un rango de fechas vía el chequeo temprano
  descrito arriba.
- **Trigger `schedule` únicamente, nunca `push`/`pull_request_target`** -- ya
  evita el loop de auto-disparo (motivo original, sección 0E), y ADEMÁS es una
  propiedad de seguridad en un repo público (un workflow con permisos de
  escritura disparado por un PR de un tercero es un patrón de ataque conocido;
  acá ni siquiera está en la lista de triggers). Documentado como comentario en
  el propio YAML, no solo en este plan.

### 3.3 Frontend

- **Tailwind vía CDN** (`cdn.tailwindcss.com`) -- cero build step, coherente con
  "sin complicar el setup" del pedido original.
- **Chart.js vía CDN** para las barras horizontales de probabilidad de campeón y
  el gráfico de línea de fluctuación por ronda (reutiliza `round_snapshots` del
  JSON -- eje X = ronda, eje Y = probabilidad, una línea por jugador top-N).
- **Bracket interactivo**: HTML/CSS estático para la estructura (mismo layout que
  ya probó `html_report.py`, portado a Tailwind), JS agrega el hover -- al pasar
  el mouse sobre un cruce, un tooltip muestra `favorite_id` vs `underdog_id` y
  `prob` ya calculados (dato que YA viene en el JSON, cero cómputo en el browser).
- Todo el fetch/parseo va en `docs/app.js`, sin build step ni dependencias npm --
  coincide con "estructura base HTML5 estándar."
- **Manejo de fetch fallido (agregado tras la revisión independiente).** Distinto
  del estado "sin torneo todavía" (que es una condición conocida del lado del
  JSON, ver HORA 6+): si el `fetch()` del JSON devuelve 404 o el archivo está
  truncado/corrupto (p.ej. un commit a mitad de escritura), `app.js` muestra un
  mensaje de error explícito en vez de quedar en blanco o solo tirar un error en
  la consola -- barato de agregar ahora, caro de diagnosticar después si un
  visitante ve una página vacía sin pista de qué pasó.

---

## 4. Test Review

```
CÓDIGO NUEVO                                          COBERTURA
[+] src/cli/json_export.py::export_json
  ├── [GAP] Estructura del JSON (claves, tipos)         -- tests/test_json_export.py (nuevo)
  ├── [GAP] Edición histórica (sin round_snapshots)      -- caso: round_snapshots=[] no rompe el schema
  ├── [GAP] Edición en vivo con snapshots parciales       -- caso: solo R128 generado
  └── [GAP] Caracteres no-ASCII en nombres (ya probado    -- reusar patrón de
            en html_report para el HTML, falta para JSON)   test_html_report.py::test_unicode_roundtrip

[+] .github/workflows/actualizar_prediccion.yml
  ├── [GAP] [→E2E] Dry-run local del workflow (act, o     -- manual, documentado en
            simular el job a mano paso a paso)               MANUAL_STEPS.md, no automatizable con pytest
  ├── [GAP] Commit condicional (no commitea si no cambió) -- se puede probar con un
            test de integración que corre --export-json      test de integración liviano
            dos veces con el mismo seed y compara bytes
  └── [GAP] Manejo de error sin bloquear el job           -- test que el CLI devuelve
                                                              exit code 0 en el caso
                                                              "sin torneo activo"

[+] docs/app.js (frontend)
  ├── [GAP] [→E2E] Carga del JSON y render de la tabla    -- fuera de alcance de pytest
  ├── [GAP] [→E2E] Hover del bracket muestra el tooltip      (proyecto no tiene JS test
  └── [GAP] [→E2E] Gráfico de línea con datos de 1 sola      runner hoy) -- QA manual con
            ronda (torneo recién arrancado, un solo punto)   /qa tras el deploy, ver TODOS.md
```

COVERAGE: 0/10 -- todo nuevo, ningún test escrito todavía (este documento es
SOLO el plan). Los 4 primeros GAPs de `json_export.py` son unit tests directos
(mismo patrón que `tests/test_html_report.py`) y van incluidos en el PR de
implementación. Los `[→E2E]` de frontend/workflow no tienen arnés de test hoy
(proyecto 100% Python/pytest) -- se verifican manualmente post-deploy, anotado
en TODOS.md como deuda si se justifica automatizar más adelante (Playwright para
el frontend, `act` para el workflow).

**REGRESSION RULE:** no aplica -- todo el código tocado es nuevo o se llama sin
modificar (`run_prediction` no cambia de firma).

---

## 5. Decisiones (auto-decididas por /autoplan, principios P1-P6)

| # | Decisión | Clasificación | Principio | Resultado |
|---|---|---|---|---|
| 1 | Cron todo el año vs. acotado a la ventana del torneo | Mecánica | P5 explícito | Acotado + no-op seguro de red |
| 2 | Commitear DB/CSV desde CI vs. solo el JSON | Mecánica | P3 pragmático + repo hygiene | Solo el JSON |
| 3 | Approach A vs B vs C (arquitectura) | Mecánica | P1+P4 | A (JSON+Actions+Pages) |
| 4 | Historial de ediciones navegable (expansión #1) | Taste | P2 boil lakes | Deferir a TODOS.md -- fuera del blast radius de "hacer que el JSON de hoy se vea", más de 1 día de CC |
| 5 | Open Graph / compartir (expansión #2) | Taste | P2 | Deferir a TODOS.md -- cosmético, no bloquea el pedido |
| 6 | Página de "sin datos todavía" (expansión #3) | Mecánica | P2 boil lakes (en blast radius, <1 día CC) | Incluir en el plan (ya integrado en 3.3/HORA 6+) |
| 7 | Alertas email/push (expansión #4) | Taste | P2 | Deferir a TODOS.md -- infra nueva (email/push), claramente fuera de este PR |
| 8 | Badge "última actualización" (expansión #5) | Mecánica | P2 boil lakes (trivial, dato ya en el JSON) | Incluir en el plan |
| 9 | `--draw-year` explícito en el workflow (hallazgo CRÍTICO de la revisión independiente) | Mecánica | P5 explícito (un default silencioso que rompe el propósito del plan no es aceptable) | Incluir -- `--draw-year "$(date +%Y)"` siempre, ver 3.2 |
| 10 | Manejo de error del workflow: no-op solo por ventana de fecha, nunca supresión genérica dentro de la ventana | Mecánica | P5 explícito | Incluir, ver 3.2 |
| 11 | Manejo de fetch fallido/JSON corrupto en `app.js` | Mecánica | P2 boil lakes (en blast radius, barato) | Incluir, ver 3.3 |

No hubo **User Challenges** (Codex no disponible en este entorno -- ver Outside
Voices más abajo -- así que no hay caso de "ambos modelos coinciden en que el
usuario debería cambiar de dirección"; el subagente Claude corrió solo y sus
hallazgos se tratan como taste decisions cuando difieren de este análisis, nunca
como challenge a la dirección del usuario).

---

## 6. NOT in scope

| Ítem | Por qué queda afuera |
|---|---|
| Backend siempre corriendo (Approach B) | El usuario pidió explícitamente "sin necesitar un backend corriendo 24/7" -- va contra una restricción explícita, no una preferencia. |
| Historial de ediciones pasadas navegable | Boil-the-ocean real, pero > 1 día de CC y no bloquea el pedido de hoy -- TODOS.md. |
| Alertas email/push cuando cambia el favorito | Infra nueva (proveedor de email/push), claramente una fase futura ("ideal a 12 meses" en 0C). |
| Test runner de JS (Playwright/Vitest) para `docs/app.js` | El proyecto es 100% Python hoy; agregar tooling de JS testing es una decisión de stack aparte, no algo a colar en este PR. Anotado en TODOS.md. |
| Reemplazar `--html`/`--serve` | Siguen siendo el modo de uso local/interactivo; el sitio estático es un consumidor NUEVO de `run_prediction`, no un reemplazo. |
| El ensamble Elo 70/30 (limitación ya conocida, ver README) | Ortogonal a este plan -- automatización/frontend, no cambios de modelo. |

---

## 7. Qué falta de "papeleo" (a pedido explícito del usuario)

### 7.1 Commits (uno por unidad lógica, no un solo commit gigante)

```
1. feat(export): agrega --export-json a simular_usopen.py + src/cli/json_export.py
   + tests/test_json_export.py
2. ci: agrega .github/workflows/actualizar_prediccion.yml
3. feat(web): agrega docs/index.html + docs/app.js (dashboard Tailwind + Chart.js)
4. feat(web): genera el primer docs/data/resultados_simulacion.json a mano
   (para que el sitio no arranque vacío -- ver HORA 6+ en 0E)
5. docs: reescribe README.md (sección "cómo usarlo" en criollo) + actualiza TODOS.md
```

### 7.2 Pull Request

Dado que se trabaja en `main` directo hoy (repo de un solo desarrollador, sin
ramas activas), recomendación: crear una rama `feature/automatizacion-web`,
abrir PR contra `main`, correr `/review` sobre el diff antes de mergear (mismo
criterio que el resto del proyecto -- CLAUDE.md ya enruta "code review/diff
check" a `/review`).

### 7.3 Manual (ver `MANUAL_STEPS.md`, generado junto con este plan)

1. Habilitar GitHub Pages (Settings → Pages → Source) -- decisión pendiente:
   "GitHub Actions" como source (recomendado, permite el flujo `actions/deploy-
   pages`) vs. "Deploy from a branch" apuntando a `docs/` en `main` (más simple,
   sin action extra). Ver `MANUAL_STEPS.md` para el paso a paso de ambas.
2. Verificar Settings → Actions → General → Workflow permissions = "Read and
   write permissions" (si no, el `git push` del bot falla con 403).
3. Confirmar la fecha real del US Open de cada año futuro y actualizar el rango
   de fechas hardcodeado del workflow (único punto de mantenimiento anual que
   queda -- el año del torneo YA NO necesita bumpearse a mano porque el
   workflow pasa `--draw-year "$(date +%Y)"` dinámicamente, hallazgo #9 de la
   revisión independiente).

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/autoplan` (Phase 1) | Scope & strategy | 1 | CLEAR | Premisa de cron 365d/año challengeada y corregida; 3 approaches evaluados, A elegido; 5 expansiones evaluadas, 2 incluidas / 3 deferidas |
| Codex Review | — | Independiente 2da opinión | 0 | N/A | Codex CLI no instalado en este entorno (`command -v codex` → not found) -- degradado a subagente Claude único, ver abajo |
| Eng Review | `/autoplan` (Phase 3) | Arquitectura & tests | 1 | CLEAR | Hallazgo de performance/higiene de repo: NO commitear DB/CSV desde CI; commit condicional; manejo de error sin romper el job; cron acotado |
| Design Review | `/autoplan` (Phase 2) | Gaps UI/UX | 1 | CLEAR | Dashboard oscuro Tailwind + Chart.js, bracket con hover, estado "sin datos todavía" explícito para el día 1, manejo de fetch fallido |
| DX Review | — | Developer experience gaps | 0 | SKIPPED | Sin scope developer-facing (no hay API/SDK pública, es un dashboard para usuarios finales + automatización interna) |
| Outside Voice (subagente Claude, Codex no disponible) | `/autoplan` (independiente) | 2da opinión sin contexto previo | 1 | ISSUES_FOUND → RESUELTOS | 1 hallazgo CRÍTICO (`--draw-year` faltante en el workflow -- simularía 2025 para siempre en silencio), 2 medium (export_json no es "cero cómputo": normalización de probabilidad + mapeo a ids + `known_results` con claves tupla no serializa a JSON directo; distinguir no-op esperado de falla real suprimida), 1 low (fetch fallido en app.js). Los 4 ya están incorporados en las secciones 3.1/3.2/3.3 de este documento. |

**CROSS-MODEL:** Solo corrió una voz (Codex CLI no instalado en este entorno --
degradado a subagente Claude único). El subagente verificó independientemente
(leyendo el código, no solo el plan) que el inventario de "qué ya existe" de la
sección 0 es preciso, y encontró el hallazgo crítico de `--draw-year` que el
análisis inicial de este documento no había capturado -- ya corregido arriba.
Ningún User Challenge se generó (requiere que DOS modelos coincidan en
contradecir la dirección del usuario; con una sola voz no aplica).

**VERDICT:** CEO + ENG + DESIGN CLEARED — listo para implementar, CON el fix
crítico de `--draw-year` ya incorporado (sección 3.2). DX Review saltada por
scope (no developer-facing). Antes de implementar, confirmar la Decisión #1
(ventana del cron) con el usuario -- es la única premisa que este review
corrigió respecto del pedido original, ver Step 0A.

**Decisiones confirmadas por el usuario (D1-D3, post-review):**
- D1: cron acotado a la ventana del torneo -- CONFIRMADO.
- D2: GitHub Pages "Deploy from a branch" → `docs/` en `main` -- CONFIRMADO.
- D3: este documento es el entregable final de esta sesión -- CONFIRMADO. No se
  implementa código en esta sesión; `MANUAL_STEPS.md` y el README reescrito se
  generan como "papeleo" (documentación), sin tocar `src/`. Implementación queda
  para una sesión futura a pedido explícito del usuario.

NO UNRESOLVED DECISIONS

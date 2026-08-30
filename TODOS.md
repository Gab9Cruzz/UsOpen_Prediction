# TODOS

Diferido de `PLAN_PAGINA_RESULTADOS.md` (Fase 1, `/autoplan`, 2026-08-26). Los tres
ítems estaban bloqueados por Fase 4 del plan de mejora del motor (ingesta de cuadro
oficial / datos en vivo) — **implementada 2026-08-29** (`src/data/live_draw.py`,
condicionamiento por resultados reales en el motor de simulación, snapshots de
predicción por ronda). Siguen diferidos, pero ya no están bloqueados: hay datos en
vivo reales para mostrar.

- [x] Bracket visual interactivo (árbol del cuadro de 128) — **implementado
      (2026-08-30)**: `docs/index.html`/`docs/app.js` lo dibuja con hover sobre
      cada cruce (dato de `build_predicted_bracket`, vía `src/cli/json_export.py`,
      cero cómputo nuevo en el browser). Ver
      [PLAN_AUTOMATIZACION_WEB.md](PLAN_AUTOMATIZACION_WEB.md).
- [x] Server/dashboard en vivo con auto-refresh — **implementado como "GitHub
      Actions + JSON estático + GitHub Pages"** (`.github/workflows/
      actualizar_prediccion.yml`) en vez de auto-refresh de `--serve` (evita
      mantener un backend 24/7, restricción explícita del usuario).
- [x] Publicación automática a GitHub Pages / hosting — **código implementado
      (2026-08-30)**, ver [PLAN_AUTOMATIZACION_WEB.md](PLAN_AUTOMATIZACION_WEB.md)
      para el diseño completo. Falta únicamente el toggle manual de GitHub
      (habilitar Pages + permisos del bot) — ver `MANUAL_STEPS.md`.
- [ ] `entry_type` (Q/WC/LL/PR) se persiste en `cuadro_torneo` (Fase 4) pero no se
      muestra todavía en la tabla/HTML junto al seed -- cosmético, bajo costo si se
      pide.
- [ ] `--model elo` con condicionamiento en vivo (Fase 4, D7) reutiliza el Elo
      "puro" tal cual, no el ensamble 70/30 saque-resto+Elo medido en
      `ensemble_search.py` -- sigue pendiente conectar ESE peso específico (ver
      "Limitaciones conocidas" en este README).

## Diferido de `PLAN_AUTOMATIZACION_WEB.md` (`/autoplan`, 2026-08-29; implementado 2026-08-30)

Expansiones evaluadas durante el review y explícitamente pospuestas (ver ese
plan, sección 5, decisiones #4/#5/#7, y sección 4 para el ítem de testing) —
ninguna bloqueaba el pedido original (JSON + Actions + dashboard, ya
implementado):

- [ ] Historial de ediciones pasadas navegable en el dashboard (un JSON por año
      en vez de sobreescribir siempre el mismo archivo) -- más de 1 día de CC,
      fuera del blast radius de "que el JSON de hoy se vea bien".
- [ ] Open Graph tags / botón "compartir" para que el link del dashboard se vea
      bien al pegarlo en redes -- cosmético, no bloquea nada.
- [ ] Alertas por email/push cuando cambia el favorito del torneo -- infra nueva
      (proveedor de email/push), es la visión a 12 meses del plan, no este PR.
- [ ] Test runner de JS (Playwright/Vitest) para `docs/app.js` -- el proyecto es
      100% Python/pytest hoy; agregar tooling de JS testing es una decisión de
      stack aparte. Hasta entonces, el frontend se verifica con QA manual
      (`/qa`) post-deploy.

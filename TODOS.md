# TODOS

Diferido de `PLAN_PAGINA_RESULTADOS.md` (Fase 1, `/autoplan`, 2026-08-26). Los tres
ítems estaban bloqueados por Fase 4 del plan de mejora del motor (ingesta de cuadro
oficial / datos en vivo) — **implementada 2026-08-29** (`src/data/live_draw.py`,
condicionamiento por resultados reales en el motor de simulación, snapshots de
predicción por ronda). Siguen diferidos, pero ya no están bloqueados: hay datos en
vivo reales para mostrar.

- [x] Bracket visual interactivo (árbol del cuadro de 128) — **con plan y revisión
      completos en [PLAN_AUTOMATIZACION_WEB.md](PLAN_AUTOMATIZACION_WEB.md)
      (2026-08-29)**: el dashboard nuevo lo resuelve con hover sobre cada cruce
      (dato ya calculado por `build_predicted_bracket`, cero cómputo nuevo). Sin
      implementar todavía.
- [x] Server/dashboard en vivo con auto-refresh — **reencuadrado en
      [PLAN_AUTOMATIZACION_WEB.md](PLAN_AUTOMATIZACION_WEB.md) como "GitHub
      Actions + JSON estático + GitHub Pages"** en vez de auto-refresh de
      `--serve` (evita mantener un backend 24/7, restricción explícita del
      usuario). Sin implementar todavía.
- [x] Publicación automática a GitHub Pages / hosting — **ya no es un ítem
      abierto, es [PLAN_AUTOMATIZACION_WEB.md](PLAN_AUTOMATIZACION_WEB.md)**,
      revisado (CEO+Eng+Design CLEARED) el 2026-08-29. Ver ese documento para el
      diseño completo; `MANUAL_STEPS.md` para los pasos manuales de GitHub una
      vez implementado.
- [ ] `entry_type` (Q/WC/LL/PR) se persiste en `cuadro_torneo` (Fase 4) pero no se
      muestra todavía en la tabla/HTML junto al seed -- cosmético, bajo costo si se
      pide.
- [ ] `--model elo` con condicionamiento en vivo (Fase 4, D7) reutiliza el Elo
      "puro" tal cual, no el ensamble 70/30 saque-resto+Elo medido en
      `ensemble_search.py` -- sigue pendiente conectar ESE peso específico (ver
      "Limitaciones conocidas" en este README).

## Diferido de `PLAN_AUTOMATIZACION_WEB.md` (`/autoplan`, 2026-08-29)

Expansiones evaluadas durante el review y explícitamente pospuestas (ver ese
plan, sección 5, decisiones #4/#5/#7, y sección 4 para el ítem de testing) —
ninguna bloquea el pedido original (JSON + Actions + dashboard):

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

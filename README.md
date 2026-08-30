# Predecir US Open

¿Quién va a salir campeón del US Open? Este proyecto lo calcula corriendo el
torneo miles de veces en la compu (simulación Monte Carlo) usando las
estadísticas reales de saque/resto de cada jugador, en vez de adivinar a ojo.
El sorteo real 2026 ya está cargado — corre esto y te dice, con probabilidad,
quién tiene más chances de llegar a cada ronda.

## Empezar en 2 minutos

```bash
pip install -r requirements.txt
python simular_usopen.py --update-data   # primera vez: descarga datos + arma la base (tarda ~1 min)
python simular_usopen.py                  # corridas siguientes: usa lo ya descargado, corre rápido
```

Esto imprime una tabla en la terminal con los favoritos del cuadro y su
probabilidad de llegar a cada ronda (R32, R16, cuartos, semis, final, campeón),
según 10.000 simulaciones. Para algo más lindo para compartir o mirar en el
navegador:

```bash
python simular_usopen.py --html    # genera una página y la abre sola
```

## Comandos que más vas a usar

| Comando | Qué hace |
|---|---|
| `python simular_usopen.py` | Corre la predicción y la muestra en la terminal |
| `python simular_usopen.py --html` | Lo mismo, pero como página web (bracket + tabla), y la abre en el navegador |
| `python simular_usopen.py --serve` | Levanta una página local con un botón "Simular de nuevo" (podés cambiar simulaciones/modelo sin reiniciar nada) |
| `python simular_usopen.py --update-data` | Vuelve a descargar todo y reconstruye la base (usalo si pasaron días y querés los resultados más recientes) |
| `python simular_usopen.py --draw-year 2024` | Simula otra edición ya jugada, en vez del sorteo actual |
| `python simular_usopen.py --simulations 50000` | Más simulaciones = número más preciso, tarda un poco más |
| `python -m pytest tests/ -v` | Corre los tests (130+, todos deberían pasar) |

Si el torneo actual ya arrancó, `--html`/`--serve` también muestran, apiladas,
las predicciones "entrando a cada ronda" a medida que se juegan los partidos
reales (ver [más abajo](#el-sorteo-2026-en-vivo)).

## Qué es esto, en criollo

Cada jugador tiene un "% de puntos que gana sacando" y un "% que gana
restando", calculados con sus partidos reales de los últimos 3 años en
cancha dura, ajustados por si le tocaron rivales fuertes o flojos. Con esos
dos números para cada jugador, el modelo calcula la probabilidad de que gane
cada punto de un partido, y de ahí simula el juego → el set → el partido
completo → el cuadro de 128 jugadores, miles de veces. Cuantas más veces un
jugador "gana" el torneo en esas simulaciones, más alta su probabilidad real
de campeón.

No es una opinión: el modelo se mide contra los resultados reales de 16 años
de US Open (2010-2025, más de 2.000 partidos) y se ajustó paso a paso según
esa medición, no a ojo. Ver [Cómo se mide la precisión](#cómo-se-mide-la-precisión-no-se-afirma)
más abajo si te interesa el detalle.

## El sorteo 2026, en vivo

El sorteo real del US Open 2026 (128 jugadores, seeds, cruces) ya está
publicado y este proyecto lo toma automáticamente — no hace falta cargarlo a
mano. A medida que se juegan partidos reales, la próxima vez que corras el
comando el modelo ya sabe quién ganó cada uno y lo usa como un hecho (no
vuelve a "tirar la moneda" para un partido que ya se jugó de verdad) — así, si
estás entrando a semifinales con 1 de los 4 cuartos de final ya jugado, la
predicción de semis usa ese resultado real y solo simula los 3 partidos que
faltan.

Con `--html`/`--serve` vas a ver, apiladas, las predicciones "entrando a
R128", "entrando a R64", etc. — cada una es la foto de lo que el modelo pensaba
en ese momento del torneo, y deja de recalcularse en cuanto ya no puede
cambiar (todo lo anterior a esa ronda ya se jugó en la realidad).

**Automatización web (en camino):** hay un plan armado y revisado para que
esto se actualice solo todos los días del torneo (GitHub Actions) y se
publique en un dashboard público (GitHub Pages) sin tener que correr nada a
mano — ver [PLAN_AUTOMATIZACION_WEB.md](PLAN_AUTOMATIZACION_WEB.md). Todavía
no está implementado (es el plan, no el código); el paso a paso manual para
cuando se implemente está en [MANUAL_STEPS.md](MANUAL_STEPS.md).

## Modelos disponibles (`--model`)

```bash
python simular_usopen.py --model serve_return   # default: saque/resto simulado juego a juego
python simular_usopen.py --model elo             # Elo de superficie decide cada partido de una
```

`serve_return` (el de por defecto) simula el partido de verdad — juegos, sets,
tie-breaks, con las reglas reales del US Open. `elo` es más simple: usa el
ranking Elo del jugador para decidir el partido completo con una sola
"moneda", sin simular puntos. Mide un poquito mejor en el backtest (Brier
0.190 vs 0.193) pero pierde matices — con el cuadro 2025, por ejemplo, aplana
las probabilidades de los favoritos top.

## Cómo se mide la precisión (no se afirma)

```bash
python simular_usopen.py --backtest 2010-2025
```

Corre el modelo (y comparaciones contra ranking ATP, moneda al 50/50, y Elo)
contra los 2.032 partidos reales del US Open 2010-2025, siempre con corte
temporal estricto (nunca usa datos de la propia edición que está evaluando, ni
de ediciones futuras). Es el mismo comando que se usó para ajustar cada
decisión del modelo — correrlo después de tocar `src/simulation/` o
`src/data/ingest.py` te dice si un cambio mejoró algo de verdad o lo empeoró.

## Todos los comandos

```bash
python simular_usopen.py --update-data           # re-descarga y reconstruye la base
python simular_usopen.py --simulations 50000     # más iteraciones (motor rápido: ~500-600 sims/s)
python simular_usopen.py --exact-simulation      # motor juego a juego original, más lento, para depurar
python simular_usopen.py --model elo             # decide cada partido directamente con Elo (ver arriba)
python simular_usopen.py --draw-year 2024        # otra edición ya jugada
python simular_usopen.py --top 32                # más filas en la tabla de la terminal
python simular_usopen.py -v                       # logging detallado
python simular_usopen.py --backtest 2010-2025    # backtest de precisión (ver arriba)
python simular_usopen.py --html --no-open        # genera la página sin abrir el navegador
python -m pytest tests/ -v                        # corre los tests
```

---

## Detalle técnico

Esta sección es para quien quiera entender CÓMO funciona por dentro, no solo
usarlo.

### Paso a paso del pipeline

1. **Ingesta** (`src/data/fetchers.py`, `src/data/ingest.py`): descarga los
   CSV de partidos ATP y jugadores, filtra partidos de **pista dura** de los
   últimos 3 años, calcula **% de puntos ganados al saque/resto** con
   decaimiento temporal (vida media 12 meses, lo reciente pesa más) y los
   **ajusta por la calidad de los rivales enfrentados**
   (`serve_pct_adj`/`return_pct_adj`), guardando también la tasa cruda sin
   ajustar para comparar.
2. **SQLite** (`database/schema.sql`, volcado con `pandas.to_sql`): tablas
   `jugadores` y `metricas_superficie` (particionadas por `tournament_year`,
   así conviven varias ediciones sin pisarse), `cuadro_torneo` (el sorteo de
   128), y `snapshots_prediccion` (predicciones congeladas por ronda, Fase 4).
3. **Motor de simulación** (`src/simulation/`): `monte_carlo.py` es la lógica
   "de referencia" juego a juego / punto a punto; `models/serve_return.py` es
   una réplica analítica EXACTA del mismo modelo (sin muestreo, programación
   dinámica) que la CLI usa por defecto — un solo sorteo por partido en vez de
   ~100-200, mucho más rápido para simular un cuadro completo miles de veces.
4. **Sorteo oficial en vivo** (`src/data/live_draw.py`, Fase 4): cuando la
   edición pedida todavía no se jugó (sin R128 histórico disponible), el
   motor cae automáticamente al sorteo oficial ya publicado en Wikipedia
   (128 jugadores, seeds, cruces reales), y trackea resultados reales a medida
   que se juegan para condicionar la simulación (ver "El sorteo 2026, en
   vivo" más arriba).
5. **Validación** (`src/validation/`): backtest multi-año con corte temporal
   estricto por edición, Brier/log-loss/ECE con intervalo de confianza,
   contra baselines (ranking ATP, moneda, Elo de superficie).
6. **CLI** (`simular_usopen.py`): orquesta todo lo anterior e imprime la
   tabla con Rich, o genera la página HTML.

### Modelo, en una frase

Probabilidad de punto Barnett-Clarke (saque + resto del rival, ajustados
ambos por la fuerza del calendario que enfrentó cada jugador) alimenta una
simulación juego → set → partido → cuadro de 128, con las reglas reales del
US Open (tie-break a 10 en el set decisivo desde 2022) y las métricas de
saque/resto decaen exponencialmente con el tiempo. Medido contra 2010-2025
(2.032 partidos): Brier 0.193, muy cerca de un Elo de superficie puro (0.190)
pero conservando la estructura juego/set que Elo no tiene.

### Nota sobre la fuente de datos

La fuente canónica (`github.com/JeffSackmann/tennis_atp`) responde 404 en
todos sus endpoints desde algunos entornos de red — `src/config.py` cae
automáticamente a un mirror comunitario (`Aneeshers/tennis-sackmann-archive`,
mismo esquema, CC BY-NC-SA 4.0 con atribución a Jeff Sackmann) cuando la
primera falla. Si tu red sí tiene acceso al repo original, no hace falta
tocar nada — el fallback es transparente.

### Data leakage

Las métricas de cada jugador respetan el corte temporal: solo usan partidos
anteriores a la fecha de inicio de esa edición del US Open, nunca resultados
de la propia edición ni de ediciones futuras (verificado en
`tests/test_no_leakage.py`). El cuadro reconstruido de una edición ya jugada
está verificado 32/32 contra los emparejamientos reales de R64 de 2025
(`tests/test_draw.py`).

### Limitaciones conocidas (por diseño, o pendientes)

- **El ensamble Elo + saque/resto está medido pero no desplegado.** El
  backtest (`src/validation/ensemble_search.py`) confirmó una mejora real
  combinando 70% modelo de saque/resto + 30% Elo, pero conectar ese peso
  específico a la simulación en vivo requiere resolver un choque de
  arquitectura pendiente.
- **Head-to-head y fatiga se probaron y se descartaron**, con evidencia: no
  agregan nada que el modelo de saque/resto y Elo no capturen ya.
- **El motor "exacto" (`--exact-simulation`) solo funciona con cuadros de
  exactamente 128 jugadores** — no bloquea nada porque el cuadro del US Open
  siempre es de 128 (documentado en `tests/test_engine.py`).
- No hay sistema de disponibilidad/retiros/lucky losers: si alguien se retira
  después del sorteo, no se detecta (solo se trackean ganadores reales, no
  bajas).
- La ingesta del sorteo en vivo depende de que Wikipedia mantenga el formato
  de plantilla esperado — si cambia, la ingesta falla con un error explícito
  en vez de simular algo incompleto en silencio.
- El `entry_type` (Q/WC/LL/PR) del sorteo en vivo se guarda pero todavía no
  se muestra en la tabla/HTML (ver `TODOS.md`).

### Tests

```bash
python -m pytest tests/ -v
```

130+ tests: reconstrucción del cuadro, no-leakage, motor de simulación
(incluido el condicionamiento por resultados reales), parsing del sorteo en
vivo, snapshots por ronda, reporte HTML.

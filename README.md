# Predecir US Open

Simulador Monte Carlo del cuadro del US Open, con un motor de datos (ingesta
histórica + SQLite) y un backtest de precisión que mide el modelo contra
ediciones ya jugadas en vez de confiar en la intuición.

```bash
pip install -r requirements.txt
python simular_usopen.py --update-data   # primera vez: descarga + arma la base
python simular_usopen.py                  # corridas siguientes: usa la base ya armada
```

Salida esperada: una tabla con los favoritos del cuadro y su probabilidad de
llegar a R32/R16/QF/SF/Final/Campeón, con intervalo de confianza en la
columna de Campeón, según 10.000 simulaciones (por defecto).

## Ver los resultados en una página (ambientada en el torneo)

```bash
python simular_usopen.py --html          # escribe output/us_open_<año>_<modelo>.html y lo abre
python simular_usopen.py --serve         # servidor local (127.0.0.1) con botón "Simular de nuevo"
```

`--html` genera un archivo autocontenido (sin dependencias nuevas) con la
misma tabla, ambientado en el US Open: **cuadro proyectado** (el bracket
completo R128 → Campeón, con el favorito y su probabilidad en cada cruce,
calculado exacto -- sin Monte Carlo), barras de probabilidad por ronda en la
tabla (la forma decreciente dibuja el cuadro), orden por probabilidad de
Campeón y cuadro completo (no solo el top 20 de la terminal). Sirve para
guardar o compartir un snapshot. `--serve` levanta un servidor local mínimo
con un formulario para volver a simular (simulaciones/modelo/año) sin
reiniciar el proceso -- la tabla y el bracket se actualizan solos, sin
recargar la página. Ambos aplican también a `--backtest`. Detalle completo
de las decisiones de diseño e ingeniería:
**[PLAN_PAGINA_RESULTADOS.md](PLAN_PAGINA_RESULTADOS.md)**.

## El modelo, en una frase

Probabilidad de punto Barnett-Clarke (saque + resto del rival, ajustados
ambos por la fuerza del calendario que enfrentó cada jugador) alimenta una
simulación juego → set → partido → cuadro de 128, con las reglas reales del
US Open (tie-break a 10 en el set decisivo desde 2022) y las métricas de
saque/resto decaen exponencialmente con el tiempo (lo reciente pesa más).
Medido contra 2010-2025 (2.032 partidos): Brier 0.193, muy cerca de un Elo de
superficie puro (0.190) pero conservando la estructura juego/set que Elo no
tiene. Números completos, metodología y cada decisión medida (no a ojo) en
**[PLAN_MEJORA_SIMULACION.md](PLAN_MEJORA_SIMULACION.md)**.

## Qué hace, paso a paso

1. **Ingesta** (`src/data/fetchers.py`, `src/data/ingest.py`): descarga los
   CSV de partidos ATP y jugadores, filtra partidos de **pista dura** de los
   últimos 3 años, calcula **% de puntos ganados al saque/resto** con
   decaimiento temporal (vida media 12 meses) y los **ajusta por la calidad
   de los rivales enfrentados** (`serve_pct_adj`/`return_pct_adj`) además de
   guardar la tasa cruda para comparar.
2. **SQLite** (`database/schema.sql`, volcado con `pandas.to_sql`): tres
   tablas — `jugadores`, `metricas_superficie` (ambas particionadas por
   `tournament_year`, así conviven varias ediciones sin pisarse), `cuadro_torneo`.
3. **Motor de simulación** (`src/simulation/`): `monte_carlo.py` tiene la
   lógica "de referencia" juego a juego / punto a punto; `models/serve_return.py`
   es una réplica analítica EXACTA del mismo modelo (sin muestreo, vía
   programación dinámica) que la CLI usa por defecto para simular un cuadro
   completo mucho más rápido (un sorteo por partido en vez de ~100-200).
4. **Validación** (`src/validation/`): backtest multi-año con corte temporal
   estricto por edición, Brier/log-loss/ECE con intervalo de confianza,
   contra baselines (ranking ATP, moneda, Elo de superficie).
5. **CLI** (`simular_usopen.py`): orquesta todo lo anterior e imprime la
   tabla con Rich.

## Precisión: medida, no afirmada

```bash
python simular_usopen.py --backtest 2010-2025
```

Corre el modelo (y los baselines) contra los 2.032 partidos reales del US
Open 2010-2025, con corte temporal por edición (nunca usa datos de la propia
edición evaluada ni de ediciones futuras), e imprime Brier/log-loss/ECE con
IC95%. Es el mismo comando que se usó para medir cada paso del
[plan de mejora](PLAN_MEJORA_SIMULACION.md) — correrlo después de tocar
`src/simulation/` o `src/data/ingest.py` es la forma de saber si un cambio
mejoró algo o lo empeoró, no una opinión.

```bash
python simular_usopen.py --backtest 2010-2025 --skip-champion-loss   # solo partido a partido, más rápido
```

## Nota importante sobre la fuente de datos

La fuente canónica (`github.com/JeffSackmann/tennis_atp`) responde 404 en
**todos** sus endpoints desde este entorno de red (raw, API y codeload),
mientras que otros repos de GitHub cargan sin problema — es un bloqueo
puntual a ese repo, no una caída general de GitHub. `src/config.py` intenta
primero la fuente canónica y cae a un mirror comunitario
(`Aneeshers/tennis-sackmann-archive`, mismo esquema de columnas, CC
BY-NC-SA 4.0 con atribución a Jeff Sackmann) cuando la primera falla. Si tu
red sí tiene acceso al repo original, no hace falta tocar nada: el fallback
es automático y transparente.

## Nota importante sobre el cuadro simulado

El US Open 2026 todavía no tiene sorteo oficial descargable como dataset
histórico. Sin la ingesta de cuadro oficial en vivo (fuera de alcance
actual, ver "Fuera de alcance" en el plan de mejora), el motor reconstruye
el **cuadro real** de la última edición completa (**US Open 2025**, con los
emparejamientos oficiales de R128, verificado 32/32 contra los resultados
reales de R64 — `tests/test_draw.py`) para simular sobre un torneo genuino
en vez de un draw inventado. Esto se indica explícitamente en la salida de
la CLI. Usá `--draw-year 2024` (o el año que quieras, siempre que haya
datos) para simular otra edición.

Las métricas de cada jugador respetan el corte temporal: solo usan partidos
anteriores a la fecha de inicio de esa edición del US Open (sin data
leakage, verificado en `tests/test_no_leakage.py`).

## Tests

```bash
python -m pytest tests/ -v
```

## Modelos disponibles (`--model`)

```bash
python simular_usopen.py --model serve_return   # default: Barnett-Clarke + ajuste por oponente, juego/set/partido
python simular_usopen.py --model elo            # Elo de superficie decide cada partido directamente (una sola moneda)
```

`elo` usa el ranking Elo (con decaimiento por inactividad, paso 11 de la
Fase C) para decidir cada partido completo de una — sin juegos, sets ni
tie-break. Es el baseline más fuerte medido en el backtest (Brier 0.190 vs
0.193 del default), pero al no simular la estructura del partido pierde
matices que sí capturan las rondas compuestas del modelo por defecto (por
eso, con el cuadro 2025, da probabilidades de campeón más aplanadas —
Djokovic cae del top 3 al top 8, por ejemplo). Necesita más años de
historial que el resto de la CLI (calentamiento del rating), se descargan
solos la primera vez.

## Limitaciones conocidas (por diseño, o pendientes)

- **El ensamble Elo + saque/resto está medido pero no desplegado.** El
  backtest (`src/validation/ensemble_search.py`) confirmó una mejora real
  fuera de muestra combinando 70% modelo de saque/resto + 30% Elo (mejor que
  cualquiera de los dos por separado), pero conectar ESE peso específico a
  la simulación en vivo (a diferencia de `--model elo`, que usa Elo puro sin
  mezclar) requiere resolver un choque de arquitectura — ver la sección
  "Pendiente" del plan de mejora.
- **Head-to-head y fatiga se probaron y se descartaron**, con evidencia: no
  agregan nada que el modelo de saque/resto y Elo no capturen ya (plan de
  mejora, Fase C).
- **`run_simulations`/`simulate_tournament` (el motor "exacto", juego a
  juego) solo funciona con cuadros de exactamente 128 jugadores** — otro
  tamaño potencia de 2 revienta con `IndexError` (limitación real,
  documentada en `tests/test_engine.py`). No bloquea nada porque el cuadro
  del US Open siempre es de 128.
- No hay sistema de disponibilidad/retiros/lucky losers: el cuadro cargado
  se trata como si los 128 jugadores estuvieran activos.
- No hay ingesta del cuadro oficial en vivo (ver nota arriba).

## Comandos

```bash
python simular_usopen.py --update-data          # re-descarga y reconstruye la base
python simular_usopen.py --simulations 50000    # más iteraciones (motor rápido: ~500-600 sims/s)
python simular_usopen.py --exact-simulation      # motor juego a juego original, más lento, para depurar
python simular_usopen.py --model elo             # decide cada partido directamente con Elo (ver arriba)
python simular_usopen.py --draw-year 2024        # otra edición
python simular_usopen.py --top 32                # más filas en la tabla
python simular_usopen.py -v                       # logging detallado
python simular_usopen.py --backtest 2010-2025    # backtest de precisión (ver arriba)
```

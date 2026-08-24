# Predecir US Open — Fase 1: motor de datos + terminal

Implementación de la **Fase 1** del [plan de implementación](PLAN_IMPLEMENTACION_USOPEN.md):
ingesta de datos históricos, esquema SQLite minimalista y un simulador Monte
Carlo que corre desde la terminal.

```bash
pip install -r requirements.txt
python simular_usopen.py --update-data   # primera vez: descarga + arma la base
python simular_usopen.py                  # corridas siguientes: usa la base ya armada
```

Salida esperada: una tabla con los favoritos del cuadro y su probabilidad de
llegar a R32/R16/QF/SF/Final/Campeón, según 10.000 simulaciones (por defecto).

## Qué hace, paso a paso

1. **Ingesta** (`src/data/fetchers.py`, `src/data/ingest.py`): descarga los
   CSV de partidos ATP y jugadores, filtra partidos de **pista dura** de los
   últimos 3 años y calcula, por jugador, **% de puntos ganados al saque** y
   **% de puntos ganados al resto**.
2. **SQLite** (`database/schema.sql`, volcado con `pandas.to_sql`): tres
   tablas — `jugadores`, `metricas_superficie`, `cuadro_torneo`.
3. **Simulador CLI** (`src/simulation/monte_carlo.py`, `simular_usopen.py`):
   lee el cuadro desde SQLite, simula el torneo juego a juego y set a set
   10.000 veces, e imprime la tabla con Rich.

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

Hoy (2026-08-24) el US Open 2026 se está por jugar y su sorteo oficial
todavía no existe como dataset histórico descargable. Sin la ingesta de
cuadro oficial en vivo (Fase 4 del plan), el motor reconstruye el **cuadro
real** de la última edición completa (**US Open 2025**, con los
emparejamientos oficiales de R128) para simular sobre un torneo genuino en
vez de un draw inventado. Esto se indica explícitamente en la salida de la
CLI. Usá `--draw-year 2024` (o el año que quieras, siempre que haya datos)
para simular otra edición.

Las métricas de cada jugador respetan el corte temporal: solo usan partidos
anteriores a la fecha de inicio de esa edición del US Open (sin data
leakage, plan sección 7.6).

## Limitaciones conocidas de esta fase (por diseño)

- El modelo de probabilidad es un baseline analítico (serve %/return % con
  fórmula cerrada de probabilidad de juego). Todavía no hay Elo, regresión
  logística ni XGBoost — eso es Fase 5/6 del plan.
- No hay shrinkage/priors por cantidad de partidos (plan sección 4.11):
  jugadores con pocas muestras en pista dura pueden salir sobre/sub
  valorados. Sí se aplica un prior neutro cuando un jugador del cuadro no
  tiene **ningún** partido en Hard antes del corte (plan sección 4.10).
- No hay sistema de disponibilidad/retiros/lucky losers todavía (Fase 3):
  el cuadro cargado se trata como si los 128 jugadores estuvieran activos.

## Comandos

```bash
python simular_usopen.py --update-data        # re-descarga y reconstruye la base
python simular_usopen.py --simulations 50000   # más iteraciones
python simular_usopen.py --draw-year 2024      # otra edición
python simular_usopen.py --top 32              # más filas en la tabla
python simular_usopen.py -v                     # logging detallado
```

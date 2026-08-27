# Plan de mejora — motor de simulación (precisión)

**Rama:** `main` · **Creado:** 2026-08-24 · **Autor:** Gabriel Cruz
**Alcance:** `src/simulation/`, `src/data/ingest.py`, `src/data/repository.py`, `database/schema.sql`, `src/cli/render.py`

---

## 1. Objetivo

Hoy el motor produce un número (`Sinner 18.4% campeón`) que **nadie puede
verificar**. No existe un backtest, ni una métrica de calibración, ni un test.
"Más preciso" no es hoy una afirmación medible sobre este proyecto.

El objetivo de este plan es doble y en este orden:

1. **Hacer la precisión medible** — backtest sobre ediciones ya jugadas, con
   Brier score, log-loss y curva de calibración. Sin esto, cualquier "mejora"
   es fe.
2. **Mejorar la precisión** — corregir los errores del modelo de probabilidad
   (hay al menos uno grave y confirmado) y agregar la señal que falta.

### Definición operativa de "preciso"

| Métrica | Qué mide | Baseline a batir | Objetivo |
|---|---|---|---|
| **Brier score** (partido a partido, R128→F) | Error cuadrático medio de la probabilidad de victoria | Predecir siempre al mejor ranking ATP | ≤ 0.21 |
| **Log-loss** (partido a partido) | Penaliza la confianza equivocada | Ranking ATP | ≤ 0.60 |
| **Calibración (ECE)** | ¿Cuando digo 70%, gana el 70%? | — | ≤ 0.05 |
| **Log-loss del campeón** | Calidad del pronóstico del torneo completo | Favorito por ranking | mejorar vs baseline |

Evaluado sobre **US Open 2022, 2023, 2024 y 2025**, cada uno con corte temporal
estricto (solo datos anteriores al inicio de esa edición). Cuatro torneos =
508 partidos. Muestra chica: los resultados se reportan **con intervalo de
confianza**, no como números pelados.

---

## 2. Estado actual — medido, no supuesto

Ejecutado contra la base ya construida (`database/us_open.db`, cuadro 2025):

```
cuadro cargado           128 slots, 1 jugador sin métricas en Hard (Elmer Moller)
serve_pct  (min/med/max) 0.5882 / 0.6406 / 0.7003
return_pct (min/med/max) 0.2731 / 0.3558 / 0.4098
partidos por jugador     1 / 50 / 130   <- el mínimo es 1
rendimiento              483 sims/s -> 10.000 sims = 21s, 100.000 = 3.5 min
```

### Lo que ya está bien (verificado, no tocar)

- **La reconstrucción del cuadro es real.** Verifiqué la afirmación del README
  contra los resultados oficiales de R64: ordenar R128 por `match_num` y
  emparejar slots adyacentes reproduce **32/32** de los enfrentamientos reales
  de segunda ronda del US Open 2025. La afirmación se sostiene. Se convierte
  en test de regresión (T1).
- **`game_win_prob` es correcta.** Es la fórmula cerrada estándar
  `p⁴ + 4p⁴q + 10p⁴q²·p_deuce` con `p_deuce = p²/(p²+q²)`. Sin observaciones.
- **El corte temporal no tiene fugas.** `_cutoff_date_for` toma la fecha de
  inicio del torneo objetivo del propio dataset y `compute_surface_metrics`
  filtra `tourney_date < cutoff`. El ranking también
  (`_latest_rank_before_cutoff`). Correcto.
- **Ya existe shrinkage bayesiano** (`K_PRIOR_PTS = 300`) hacia el promedio del
  cohorte. El README dice que no hay shrinkage — el README está desactualizado,
  el código sí lo tiene.

---

## 3. Diagnóstico

### P1 — Bloquean la precisión

#### B1. La combinación de probabilidades de punto comprime toda ventaja a la mitad

`src/simulation/monte_carlo.py:_point_probs`

```python
p_a_serve = (a.serve_pct + (1 - b.return_pct)) / 2
```

Promediar es el error. Sea `μ` el promedio de puntos ganados al saque del tour
en dura. Si el saque de A es `μ + δa` y la debilidad al resto de B es `μ + δb`,
el promedio devuelve `μ + (δa+δb)/2` — **la mitad** de la ventaja combinada. La
fórmula correcta (Barnett–Clarke, estándar en la literatura de tenis) es
sustractiva:

```python
p_a_serve = a.serve_pct + (1 - b.return_pct) - AVG_SERVE_HARD
```

Impacto medido, Sinner (sv .697 / rt .409) contra un rival mediano del cuadro
(sv .641 / rt .356), 4.000 partidos simulados:

| | p(punto al saque) | p(ganar juego) | **p(ganar partido)** |
|---|---|---|---|
| Actual (promedio) | 0.6706 | 0.6455 | **80.4%** |
| Barnett–Clarke | 0.7006 | 0.7121 | **95.5%** |

15 puntos porcentuales en un solo partido, compuesto sobre 7 rondas. Esto solo
ya invalida los números que imprime la CLI hoy.

**Cuidado — no es un cambio de una línea.** Contra un rival débil (sv .588 /
rt .273) Barnett–Clarke puro da **100.0%**, que es absurdo. La sobrecorrección
existe porque los `serve_pct` de entrada **no están ajustados por oponente**
(B2). B1 y B2 se arreglan juntos o se cambia un sesgo por otro.

#### B2. Las tasas de saque/resto no están ajustadas por oponente

`src/data/ingest.py:compute_surface_metrics` acumula puntos crudos. Un jugador
cuyo calendario estuvo lleno de rivales flojos infla su `serve_pct`; uno que
jugó solo Masters lo deshincha. En un cuadro de Grand Slam donde conviven
cabezas de serie y qualifiers, el sesgo es sistemático y **direccionalmente
opuesto** al efecto que se quiere medir.

Arreglo: ajuste iterativo (estilo *opponent-adjusted rates* / Massey), 3-5
iteraciones de punto fijo hasta convergencia, o una regresión ridge con efectos
de saque y de resto por jugador. Se guarda como columna nueva
(`serve_pct_adj`, `return_pct_adj`) conservando la cruda para comparar.

#### B3. No existe validación de ningún tipo

Cero tests, cero backtest, cero calibración. Es el problema raíz: sin esto no
se puede saber si B1 y B2 mejoraron algo o lo empeoraron. **Se construye
primero**, antes de tocar el modelo, para poder medir cada cambio contra el
baseline.

#### B4. `metricas_superficie` no está particionada por año — bloquea el backtest

`ingest.py` hace `DELETE FROM metricas_superficie` en cada ingesta. La base no
puede contener 2022, 2023, 2024 y 2025 al mismo tiempo. El backtest multi-año
es **físicamente imposible** con el esquema actual. Requiere `tournament_year`
en la clave primaria de `metricas_superficie` y `jugadores`.

### P2 — Degradan la precisión

#### B5. El tie-break es dimensionalmente incorrecto

`_simulate_set`:

```python
p_tb_a = (p_a_game + (1 - p_b_game)) / 2   # probabilidades de JUEGO
a_wins_tb = rng.random() < p_tb_a          # usadas como una sola moneda
```

Mezcla probabilidades de **juego** para decidir un **tie-break**, que se juega
punto a punto, y lo resuelve con un único lanzamiento. Un tie-break a 7 con
cambio de saque cada 2 puntos tiene una distribución bastante distinta de una
moneda sesgada. Arreglo: simular el tie-break punto a punto (barato, ~12
puntos) o usar la fórmula cerrada. En un cuadro de Grand Slam los tie-breaks
deciden una fracción grande de los sets entre pares parejos.

#### B6. No se reportan intervalos de confianza

Con 10.000 simulaciones, una probabilidad de campeón cercana a 20% tiene un
error estándar de ±0.4pp. La tabla imprime un decimal, así que diferencias de
0.3pp entre dos jugadores se muestran como señal cuando son ruido de muestreo.
Arreglo: calcular el error estándar binomial y mostrarlo, o subir las
simulaciones hasta que el ancho del intervalo sea menor a la precisión mostrada.

### P3 — Correctitud y sostenibilidad

- **B7.** El orden de saque entre sets siempre se invierte
  (`a_serves_first = not a_serves_first`). Solo es correcto cuando el set tuvo
  un número impar de juegos. Con 6-0, 6-2, 6-4 y 7-6 el saque **no** debería
  cambiar de mano. Falla en cerca de la mitad de los sets.
- **B8.** El set decisivo usa tie-break a 7. El US Open usa **tie-break a 10**
  en el set decisivo desde 2022.
- **B9.** Los 3 años de historial pesan igual. La forma reciente predice mejor:
  falta decaimiento exponencial (vida media ~12 meses).
- **B10.** 483 sims/s en Python puro. Un barrido de calibración (4 torneos ×
  N configuraciones × 10k sims) tarda horas. Vectorizar con numpy, o
  precomputar la matriz 128×128 de probabilidad de partido (fórmula cerrada) y
  gastar un solo sorteo por partido en vez de ~200.
- **B11.** El README dice que no hay shrinkage (lo hay) y enlaza a
  `PLAN_IMPLEMENTACION_USOPEN.md`, **que no existe en el repo**.

---

## 4. Arquitectura propuesta

El motor pasa de una fórmula fija embebida a un **modelo intercambiable**, para
poder comparar variantes contra el mismo backtest.

```
src/simulation/
  models/
    base.py           # Protocol: match_probability(a, b) -> float
    serve_return.py   # B-C ajustado por oponente (modelo por defecto)
    elo.py            # Elo de superficie (Fase C)
    ensemble.py       # combinación ponderada (Fase C)
  engine.py           # cuadro -> N simulaciones (agnóstico del modelo)
  match.py            # punto/juego/set/partido + reglas reales del US Open
src/validation/
  backtest.py         # corre ediciones pasadas con corte temporal
  metrics.py          # Brier, log-loss, ECE, curva de calibración
  baselines.py        # ranking ATP, sembrado, moneda
tests/
  test_match.py       # fórmulas de juego/set/tie-break
  test_draw.py        # T1: 32/32 contra R64 real
  test_no_leakage.py  # ninguna métrica usa datos >= cutoff
  test_engine.py      # invariantes: 1 campeón, probabilidades suman 1
```

La CLI gana `--model`, `--backtest` y `--compare`.

---

## 5. Fases

### Fase A — Medición primero (bloquea todo lo demás)
1. `tests/` con las 4 suites de arriba. T1 (32/32 del cuadro) es la primera.
2. Particionar `metricas_superficie` y `jugadores` por `tournament_year` (B4).
3. `src/validation/`: backtest + Brier/log-loss/ECE + baselines.
4. **Registrar el número del modelo actual.** Ese es el piso contra el que se
   mide todo lo que sigue.

**Criterio de salida:** `python simular_usopen.py --backtest 2022-2025` imprime
Brier, log-loss y ECE del modelo actual y de los baselines.

### Fase B — Arreglar el modelo de probabilidad
5. Ajuste por oponente en la ingesta (B2), columnas nuevas.
6. Barnett–Clarke en `_point_probs` (B1) — **junto con** el paso 5.
7. Tie-break punto a punto + tie-break a 10 en el decisivo (B5, B8).
8. Orden de saque correcto entre sets (B7).
9. Decaimiento temporal de las métricas (B9).
10. Re-correr el backtest tras **cada** paso. Cualquier paso que empeore el
    Brier se revierte y se documenta por qué.

**Criterio de salida:** Brier mejora frente al piso de la Fase A, con el
delta por paso registrado.

### Fase C — Señal nueva
11. Elo de superficie (dura), con ventana temporal y decaimiento.
12. Ensamble Elo + saque/resto, peso elegido por el backtest, no a ojo.
13. Head-to-head y fatiga (partidos en los 14 días previos) — solo se quedan si
    el backtest los avala.

### Fase D — Rendimiento y presentación
14. Vectorizar / precomputar la matriz de partidos (B10).
15. Intervalos de confianza en la tabla (B6).
16. Arreglar el README (B11) y documentar el modelo y su calibración.

---

## 6. Riesgos

| Riesgo | Probabilidad | Mitigación |
|---|---|---|
| 508 partidos es muestra chica; las mejoras pueden ser ruido | Alta | Reportar intervalos; exigir mejora consistente en las 4 ediciones, no solo en el promedio |
| Overfitting al backtest de 4 torneos | Alta | Dejar 2025 como *holdout*, afinar solo sobre 2022-2024 |
| B-C sin ajuste por oponente sobrecorrige (medido: 100%) | **Confirmada** | B1 y B2 se envían juntos, nunca por separado |
| El ajuste por oponente no converge con pocos partidos | Media | Mantener el shrinkage `K=300` y limitar las iteraciones |
| El backtest se vuelve muy lento | Media | Fase D adelanta la vectorización si estorba |

---

## 7. Fuera de alcance (deliberado)

- **XGBoost / redes neuronales.** Con 508 partidos de validación no hay cómo
  distinguir un modelo complejo bueno de uno con suerte. Primero calibración.
- **Ingesta del cuadro oficial en vivo.** Es otro problema (datos), no
  precisión de la simulación.
- **Datos punto a punto** (Match Charting Project). Fuente distinta, ingesta
  distinta. Se anota para después.
- **Simulación punto a punto completa.** Juego a juego alcanza si las
  probabilidades de punto son correctas; arreglar B1/B2 rinde mucho más.
- **Sistema de disponibilidad/retiros** (Fase 3 del plan viejo). Ortogonal.

---

## 8. Qué ya existe y se reutiliza

| Necesidad | Ya resuelto en |
|---|---|
| Corte temporal sin fugas | `ingest.py:_cutoff_date_for` + filtro `< cutoff` |
| Reconstrucción real del cuadro | `ingest.py:build_draw` (verificado 32/32) |
| Shrinkage bayesiano | `ingest.py`, `K_PRIOR_PTS = 300` |
| Prior para jugadores sin datos | `repository.py:load_draw` |
| Fórmula de probabilidad de juego | `monte_carlo.py:game_win_prob` |
| Descarga con mirror de respaldo | `fetchers.py` |
| Separación base <-> simulación | `repository.py` |

---
---

# GSTACK REVIEW REPORT

<!-- /autoplan restore point: ~/.gstack/projects/Predecir_USOPEN/main-autoplan-restore-20260824-165937.md -->

## Fase 1 — CEO Review (estrategia y alcance)

Voces: `[subagent-only]` — Codex CLI no está instalado en esta máquina, así que
la voz externa degradó. Todos los hallazgos de abajo están respaldados por
mediciones ejecutadas contra este repo, no por opinión.

### 0A. Desafío de premisas

| # | Premisa del plan | Veredicto | Evidencia |
|---|---|---|---|
| P1 | "Preciso" significa un motor bien calibrado sobre ediciones históricas | **AMBIGUA** | Hay dos objetivos distintos y el plan elige uno sin decirlo |
| P2 | 4 ediciones (508 partidos) alcanzan para medir mejoras | **FALSA** | Medido: IC95% del Brier = ±0.038. Una mejora real de 0.01 es invisible |
| P3 | Saque/resto es la base correcta del modelo | **PARCIAL** | Elo de superficie es el baseline más fuerte conocido y no está medido |
| P4 | El corte temporal no tiene fugas | **VÁLIDA** | Verificada en código: `_cutoff_date_for` + filtro `< cutoff` en métricas y ranking |
| P5 | Simular el cuadro real de 2025 es buen proxy | **VÁLIDA** | Verificada: reconstrucción 32/32 contra R64 real |

#### P1 — El plan optimiza 2025, pero hoy es 24-ago-2026

Hay dos objetivos posibles y no son el mismo trabajo:

- **(a) Predecir el US Open 2026**, que empieza en estos días. Valor real y
  falsable en dos semanas.
- **(b) Un motor calibrado sobre historia.** Valor metodológico, transferible.

El plan asume (b) en silencio. Medí si (a) es siquiera alcanzable:

```
mirror/atp_matches_2026.csv   HTTP 200, 1.449 partidos
rango de fechas               2026-01-04 -> 2026-05-25 (Roland Garros)
US Open 2026 en el dataset    NO
gira de dura del verano 2026  NO (falta Canada, Cincinnati)
Wimbledon 2026                NO
fuente canonica (Sackmann)    HTTP 404 en todos los anios, incluido 2025
```

**(a) está bloqueado por datos, no por el modelo.** Falta el cuadro 2026 y
faltan los tres meses más predictivos de la temporada. Ninguna mejora al
motor lo desbloquea. La buena noticia: todo lo que mejore el motor sirve
igual para 2026 el día que aparezca el cuadro — el modelo es agnóstico al año.

#### P2 — Limitarse a 4 ediciones es una decisión, y es la equivocada

El mirror tiene datos desde **2000** (verificado: 2000, 2010, 2015, 2018, 2020
responden HTTP 200). El plan usa 4 ediciones por supuesto, no por restricción.
Qué cuesta eso en poder de detección:

| Ventana de backtest | n partidos | SE(Brier) | ancho IC95% |
|---|---|---|---|
| 2022-2025 (lo que dice el plan) | 508 | 0.0098 | **±0.038** |
| 2010-2025 US Open | 2.032 | 0.0049 | ±0.019 |
| US Open + Australian Open 2010-2025 | 4.064 | 0.0035 | ±0.014 |

Con 508 partidos, una mejora real de 0.01 en Brier — que sería un avance
sólido — queda enterrada dentro del intervalo. El plan mediría ruido y lo
llamaría resultado. El costo de ampliar es casi nulo: `run_ingest` ya está
parametrizado por año y `build_draw` por nombre de torneo.

#### P3 — Elo tiene que ser baseline en la Fase A, no señal de la Fase C

El plan gasta la Fase B entera (pasos 5-9) perfeccionando saque/resto y recién
en la Fase C mide Elo. Si Elo solo resulta mejor que el saque/resto arreglado,
esa fase fue esfuerzo mal asignado y no se enteró hasta el final.

No es un argumento para reemplazar saque/resto: Elo da `P(partido)` y colapsa
la simulación a una moneda por partido, perdiendo la estructura juego/set que
hace falta para simular un torneo. Es un argumento para **medirlo temprano y
gratis** como tercer baseline, junto al ranking ATP. Convierte "Elo sería
mejor" de opinión en número.

### 0B. Qué ya existe (mapa de reutilización)

| Sub-problema | Ya resuelto en | Estado |
|---|---|---|
| Corte temporal sin fugas | `ingest.py:_cutoff_date_for` | Reutilizar tal cual |
| Cuadro real reconstruido | `ingest.py:build_draw` | Reutilizar (verificado 32/32) |
| Shrinkage bayesiano | `ingest.py` `K_PRIOR_PTS=300` | Reutilizar, recalibrar en Fase B |
| Prior para jugador sin datos | `repository.py:load_draw` | Reutilizar |
| P(ganar juego) cerrada | `monte_carlo.py:game_win_prob` | Correcta, no tocar |
| Descarga + mirror | `fetchers.py` | Reutilizar; extender a más años |
| Separación base <-> simulación | `repository.py` | Reutilizar; es la razón por la que el backtest es barato |

Nada de lo que el plan propone construir duplica algo que ya exista. El plan
no reinventa.

### 0C. Estado soñado

```
HOY                        ESTE PLAN                   IDEAL A 12 MESES
--------------------       ---------------------       ----------------------
Un numero sin              Brier/log-loss/ECE          Prediccion del US Open
respaldo                   sobre 16 ediciones,         en vivo, ronda a ronda,
                           con IC                      calibrada y publicada

Ventaja partida al         Barnett-Clarke +            Modelo punto a punto con
medio (medido: 80%         ajuste por oponente         datos de Match Charting
vs 95% real)

Sin tests                  4 suites + T1 de            Ensamble Elo + saque/resto
                           regresion del cuadro        + fatiga + h2h, pesos
                                                       elegidos por backtest
Un solo modelo fijo        Modelos intercambiables
                           comparables entre si        Ingesta del cuadro oficial
                                                       (requiere otra fuente)
Backtest imposible         Backtest multi-anio
(esquema lo bloquea)       habilitado
```

**Delta contra el ideal:** este plan cubre calibración, corrección del modelo y
testabilidad. Deja afuera la ingesta en vivo (bloqueada por fuente) y los datos
punto a punto (otra fuente). Es el 60% del camino, y es el 60% que desbloquea
el resto.

### 0C-bis. Alternativas de implementación

| Enfoque | Esfuerzo (humano / CC) | Riesgo | A favor | En contra |
|---|---|---|---|---|
| **A. Medir primero, después arreglar** (el del plan, con P2/P3 corregidos) | ~5 d / ~45 min | Bajo | Cada cambio se mide contra un piso; nada se acepta por fe | El primer número tarda en llegar |
| B. Arreglar B1/B2 ya y validar después | ~2 d / ~20 min | **Alto** | Mejora visible en una tarde | Sin piso no se sabe si mejoró; B-C puro ya mostró 100% absurdo |
| C. Tirar saque/resto y hacer solo Elo | ~3 d / ~25 min | Medio | Baseline fuerte, mucho menos código | Pierde la estructura juego/set; la simulación se vuelve una moneda por partido |

**Elegido: A**, con las dos correcciones de P2 y P3 incorporadas. B viola el
principio de medir antes de mover (y ya tenemos evidencia medida de que
"arreglar" B1 solo empeora otro flanco). C tira código verificado que funciona.

### 0D. Decisiones de alcance

| Decisión | Resolución | Principio | Razón |
|---|---|---|---|
| Backtest 2022-2025 -> **2010-2025** | **AMPLIAR** | P2 boil lakes | En el radio (misma `validation/`), <1d CC, y sin esto el backtest no distingue señal de ruido |
| Elo: Fase C -> **baseline en Fase A** | **AMPLIAR** | P1 completeness | Convierte la mayor apuesta del plan en medición, a costo casi nulo |
| Ingesta del cuadro US Open 2026 | **DIFERIR a TODOS.md** | P3 pragmatismo | Bloqueada por fuente de datos, no por esfuerzo. Requiere scraper nuevo |
| XGBoost / redes | **RECHAZAR** | P1 + P4 | Ni con 4.064 partidos se distingue un modelo complejo bueno de uno con suerte |
| Datos punto a punto (Match Charting) | **DIFERIR a TODOS.md** | P3 | Otra fuente, otra ingesta. Ortogonal a arreglar B1/B2 |
| Reducir alcance (solo arreglar B1) | **RECHAZAR** | P1 | Medido: B1 sin B2 cambia un sesgo por otro (100% contra rival débil) |

### 0E. Interrogatorio temporal

- **Hora 1:** corren los tests. T1 falla o pasa contra el cuadro real. Sabés si
  la base del proyecto es sólida.
- **Hora 3:** el backtest imprime el Brier del modelo actual y del ranking ATP.
  Primer momento en que "preciso" deja de ser una palabra.
- **Hora 6:** B1+B2 aplicados, backtest re-corrido. El delta es visible y
  atribuible.
- **Hora 6+:** si el delta es negativo, se revierte con evidencia en vez de
  discutirlo. Eso es lo que compra la Fase A.

---

## Registro de modos de falla

| # | Modo de falla | Prob. | Impacto | Mitigación | Estado |
|---|---|---|---|---|---|
| F1 | El backtest de 4 ediciones no distingue mejora de ruido | **Confirmada** | Todo el plan mide ruido | Ampliar a 2010-2025 | **Corregido en 0D** |
| F2 | B-C sin ajuste por oponente sobrecorrige | **Confirmada** (100% medido) | Peor que hoy | B1 y B2 juntos, nunca separados | Ya en el plan |
| F3 | Overfitting al backtest | Alta | Mejora falsa | Holdout 2024-2025; afinar solo hasta 2023 | Ampliado por 0D |
| F4 | El ajuste por oponente no converge con pocos partidos | Media | Métricas inestables | Mantener shrinkage K=300; tope de iteraciones | Ya en el plan |
| F5 | Backtest de 16 ediciones demasiado lento (483 sims/s) | **Alta** | Ciclo de iteración inservible | Adelantar la vectorización (B10) a la Fase A | **Brecha nueva** |
| F6 | El mirror comunitario se cae o se atrasa (ya está 3 meses atrasado) | Media | Sin datos frescos | Cachear en `data/raw/` y versionar el hash | **Brecha nueva** |

**F5 y F6 son brechas que el plan original no cubría.**

## Registro de errores y rescate

| Falla | Qué ve el usuario hoy | Qué debería ver |
|---|---|---|
| Falta el CSV de un año | `FileNotFoundError` crudo desde pandas | "Falta atp_matches_2019.csv — corré `--update-data`" |
| El cuadro no está en la base | Ya está bien: mensaje con el comando exacto | Sin cambios |
| Jugador sin métricas en Hard | `WARNING` + prior del cuadro. Correcto | Además: contarlos en el resumen de la CLI |
| Las dos fuentes caen | `FetchError` con el último error | Bien; agregar "probá con caché local" |
| Backtest sobre un año sin datos | No existe todavía | Error explícito con los años disponibles |

## Fuera de alcance (confirmado)

- Ingesta del cuadro oficial del US Open 2026 — bloqueada por fuente, va a TODOS.md
- Datos punto a punto (Match Charting Project) — otra fuente, va a TODOS.md
- XGBoost / redes neuronales — rechazado por tamaño de muestra
- Sistema de disponibilidad/retiros — ortogonal a precisión
- Simulación punto a punto completa — mal retorno frente a arreglar B1/B2

### Tabla de consenso — Fase 1 (CEO)

| Dimensión | Claude | Codex | Consenso |
|---|---|---|---|
| 1. ¿Premisas válidas? | NO (P1, P2, P3) | N/A | Sin consenso (una sola voz) |
| 2. ¿Es el problema correcto? | PARCIAL — ver P1 | N/A | Sin consenso |
| 3. ¿Alcance bien calibrado? | NO — muy angosto (P2) | N/A | Sin consenso |
| 4. ¿Alternativas exploradas? | SÍ (0C-bis) | N/A | Sin consenso |
| 5. ¿Riesgos cubiertos? | NO — faltan F5, F6 | N/A | Sin consenso |
| 6. ¿Trayectoria a 12 meses sólida? | SÍ | N/A | Sin consenso |

Codex no disponible (CLI no instalado) => ninguna dimensión llega a CONFIRMED.
Los hallazgos igual se sostienen: están medidos, no opinados.

---
---

# FASE A — EJECUTADA (2026-08-24)

Con las dos correcciones de la revisión CEO incorporadas (0D: ventana
2010-2025, Elo como baseline de la Fase A). Criterio de salida cumplido:
`python simular_usopen.py --backtest 2010-2025` corre de punta a punta e
imprime Brier, log-loss y ECE del modelo actual y los tres baselines.

## Qué se construyó

- **Tests** (`tests/`): `test_draw.py` (T1), `test_no_leakage.py`,
  `test_match.py`, `test_engine.py`, `test_metrics.py`. **16/18 pasan** — los
  2 que fallan son un hallazgo nuevo, ver B0 abajo, no un error del test.
- **B4 — partición por año**: `database/schema.sql` + `ingest.py` — `jugadores`
  y `metricas_superficie` ahora tienen `tournament_year` en la PK, con
  migración automática de una base pre-B4. Verificado manualmente: 2024 y
  2025 conviven en la misma base sin pisarse.
- **`src/simulation/models/`**: `current.py` (réplica analítica exacta del
  motor de hoy — DP sin Monte Carlo, para que el backtest no pague miles de
  repeticiones por partido) y `elo.py` (Elo de superficie dura, incremental,
  sin fugas).
- **`src/validation/`**: `metrics.py` (Brier/log-loss/ECE/IC), `baselines.py`
  (moneda, ranking ATP, Elo), `backtest.py` (orquesta partido-a-partido y
  log-loss del campeón).
- **CLI**: `--backtest INICIO-FIN`, `--backtest-champion-sims`,
  `--skip-champion-loss` en `simular_usopen.py`.
- **Bug propio corregido antes de confiar en el número**: la primera versión
  de `backtest.py` dejaba que `compute_surface_metrics` viera TODO el
  historial cacheado (2003-2025) en vez de la ventana de 3 años que usa
  `run_ingest` en producción — medía un modelo distinto al que corre hoy.
  Corregido (`_metrics_window`) y re-verificado contra una ventana chica
  antes de correr el backtest completo.

## Hallazgo nuevo — B0: `game_win_prob` está mal (más severo que B1)

El plan daba `game_win_prob` por verificada ("fórmula cerrada estándar...
sin observaciones"). No lo está: le falta el término de deuce.

```python
# Código actual (monte_carlo.py):
p**4 + 4*p**4*q + 10*p**4*q**2*p_deuce
# Correcto:
p**4 + 4*p**4*q + 10*p**4*q**2 + 20*p**3*q**3*p_deuce
```

`game_win_prob(0.5)` da **0.2656** en vez de 0.5 (por simetría, con p=0.5
tiene que dar exactamente 0.5). En el rango real de saque ATP en dura
(0.55–0.70) el bug **subestima** la probabilidad de ganar el juego por
**19 a 26 puntos porcentuales**:

| p (saque) | Actual (bug) | Correcto | Delta |
|---|---|---|---|
| 0.550 | 0.3672 | 0.6231 | +25.6pp |
| 0.641 | 0.5769 | 0.8144 | +23.8pp |
| 0.697 | 0.7043 | 0.8972 | +19.3pp |

A diferencia de B1 (una decisión de diseño que interactúa con B2), esto es
un bug aritmético puro contra una fórmula de texto — bajo riesgo de arreglar
solo, sin esperar a B1+B2. Capturado como test que falla legítimamente
(`test_match.py::test_game_win_prob_at_half_is_half`), no silenciado.
**No se tocó en la Fase A** (medir primero, no corregir); queda primero en
la cola de la Fase B, antes que B1/B2.

## Resultados del backtest — el piso a batir

`python simular_usopen.py --backtest 2010-2025` — 16 ediciones, **2.032
partidos** (coincide con el número proyectado en la revisión CEO, sección
0D).

### Partido a partido (IC95%)

| Modelo | Partidos | Brier ↓ | Log-loss ↓ | ECE ↓ |
|---|---|---|---|---|
| **Modelo actual** | 2032 | 0.2032 ± 0.0052 | 0.5927 ± 0.0112 | 0.0713 |
| **Elo (dura)** | 2032 | **0.1904 ± 0.0085** | **0.5575 ± 0.0206** | **0.0385** |
| Ranking ATP | 2032 | 0.2952 ± 0.0196 | 4.0193 ± 0.2722 | 0.2940 |
| Moneda (50/50) | 2032 | 0.2500 ± 0.0000 | 0.6931 ± 0.0000 | 0.0098 |

### Log-loss del campeón (por edición, IC95%)

| Modelo | Log-loss |
|---|---|
| Modelo actual | 2.6292 ± 0.3431 |
| Ranking ATP | 9.4982 ± 3.2407 |

### Contra los objetivos de la sección 1

| Métrica | Objetivo | Modelo actual | ¿Cumple? |
|---|---|---|---|
| Brier | ≤ 0.21 | 0.2032 | **Sí** |
| Log-loss | ≤ 0.60 | 0.5927 | **Sí** |
| ECE | ≤ 0.05 | 0.0713 | **No** |

## La conclusión que cambia la prioridad de la Fase B

**Elo de superficie — sin ajuste de oponente, sin B0/B1/B2, sin nada del
modelo actual — le gana al modelo actual en LAS TRES métricas**, con
intervalos que casi no se superponen (Brier: modelo actual
[0.198, 0.208] vs Elo [0.182, 0.199]). Y Elo por sí solo ya cumple los tres
objetivos de la sección 1, ECE incluido.

Esto confirma, ahora con número, la advertencia P3 de la revisión CEO: "Elo
es el baseline más fuerte conocido y no está medido" — ya está medido, y
gana. No es argumento para tirar saque/resto (Elo colapsa la simulación a
una moneda por partido, pierde la estructura juego/set — sección 0A.P3), pero
sí cambia qué tan urgente es el ensamble Elo + saque/resto: la Fase C
(paso 12) deja de ser "una mejora incremental a explorar después" y pasa a
ser la forma más corta de superar el piso real. La Fase B (arreglar B0, B1,
B2) sigue siendo necesaria — sin ella, saque/resto solo no le gana ni a Elo —
pero **el objetivo de la Fase B no es "ser preciso", es "dejar de perder
contra Elo"**.

## Próximo paso (no ejecutado en esta sesión — requiere decisión)

1. **B0** (arreglar `game_win_prob`, bajo riesgo, aislado) — re-correr el
   backtest y ver cuánto de la brecha con Elo cierra solo.
2. **B1+B2 juntos** (Barnett-Clarke + ajuste por oponente, como exige el
   plan) — re-correr.
3. Si tras B0+B1+B2 el modelo actual sigue sin superar a Elo en Brier: el
   ensamble (paso 12, adelantado) deja de ser opcional.

Cada paso se mide contra esta tabla antes de seguir al siguiente (regla ya
en el plan, sección 5, Fase B paso 10).

---

## B0 — arreglado y re-medido (2026-08-24)

Aplicado el fix descrito arriba (`monte_carlo.game_win_prob`, ahora suma el
término de deuce en vez de multiplicarlo dentro del término 4-2). Los 27
tests pasan (los 2 que fallaban por B0 ahora pasan sin tocarlos — quedaron
escritos con el valor matemáticamente correcto desde el principio).
Re-corrido `--backtest 2010-2025` completo:

| Modelo | Brier antes → después | Log-loss antes → después | ECE antes → después |
|---|---|---|---|
| Modelo actual | 0.2032±0.0052 → **0.2046±0.0049** | 0.5927±0.0112 → **0.5963±0.0106** | 0.0713 → **0.0766** |
| Log-loss campeón | 2.6292±0.3431 → **2.6887±0.3628** | | |

**El fix no mejora el backtest — el delta es indistinguible de cero dentro
del propio IC95% (±0.005 de ancho contra un cambio de +0.0014).** No es un
resultado nulo por casualidad: B0 corrige la forma en que `p_serve` se
traduce a `p_juego`, aplicada por igual a ambos jugadores, pero el cuello de
botella real ya diagnosticado en B1 está ANTES de esa conversión — el
promedio `(serve + (1-return))/2` ya comprimió la ventaja real a la mitad
antes de que `game_win_prob` la vea. Arreglar la fórmula del juego sin
arreglar la fórmula del punto no puede recuperar una ventaja que ya se
perdió un paso antes. Esto valida el diagnóstico original del plan (B1 es
el bug que manda) y la regla de "B1+B2 juntos" — no la contradice.

**El fix se mantiene igual.** Es una corrección matemática verificable por
simetría (`game_win_prob(0.5)` tiene que dar exactamente 0.5), independiente
de si mueve el Brier — mismo criterio que B7/B8 (correctitud de reglas), no
el mismo criterio que B1 (elección de modelo que si empeora, se revierte).

**Piso vigente para medir B1+B2** (reemplaza el número pre-B0 de la sección
anterior): Brier 0.2046±0.0049, log-loss 0.5963±0.0106, ECE 0.0766, log-loss
campeón 2.6887±0.3628. Objetivo a batir: Elo solo, Brier 0.1904±0.0085.

---

## B1+B2 — implementados juntos y medidos (2026-08-24)

Desde acá el backtest evalúa dos modelos por separado: **"modelo pre-Fase-B"**
(la réplica analítica CONGELADA en `models/current.py`, siempre el mismo
piso de arriba) y **"modelo nuevo"** (el motor real de `monte_carlo.py`,
evaluado con `simulate_match` en vivo — refleja cada paso de la Fase B a
medida que se aplica, sin necesitar una réplica analítica nueva por paso).

### B2 — ajuste por oponente (`ingest._adjust_for_opponents`)

Iteración de punto fijo (5 pasadas): `serve_adj[i] = serve_crudo[i] +
(promedio ponderado de return_adj de los rivales de i − promedio del tour)`,
y simétrico para el resto. **Hallazgo propio durante la implementación (no
estaba en el plan): el sistema tal como está descripto en la sección 3 NO
converge en general** — el producto de las dos matrices de promediado
(saque y resto) siempre tiene autovalor 1 en la dirección "todos suben lo
mismo", y la ecuación queda subdeterminada ahí. Confirmado con un caso de 2
jugadores: sin corrección, 5 iteraciones llevan un `serve_pct` de 0.65 a
0.71 aunque el rival sea exactamente promedio (`tests/test_opponent_adjustment.py`).
**Arreglado**: se re-centra la población entera tras cada iteración (se
resta el desvío medio), lo que ancla el nivel global sin tocar las
diferencias relativas entre jugadores. Verificado en datos reales
(2023-2025): la media de `serve_pct_adj` coincide con la media de
`serve_pct` crudo (0.634 en ambos casos) y el rango no se dispara
(`[0.558, 0.719]` vs `[0.559, 0.719]` crudo) — los 5 favoritos del cuadro
(Sinner, Medvedev, Zverev, Fritz, Rublev) se ajustan hacia ARRIBA 1-2 puntos,
consistente con que enfrentan calendarios más duros en rondas avanzadas.

### B1 — Barnett-Clarke sustractivo (`monte_carlo._point_probs`)

```python
avg_serve = (a.avg_serve_pct + b.avg_serve_pct) / 2
p_a_serve = a.serve_pct + (1 - b.return_pct) - avg_serve  # antes: promedio /2
```

`avg_serve_pct` (μ de Barnett-Clarke) se calcula por edición, con el mismo
corte temporal que el resto de las métricas (no es una constante global fija
-- eso hubiera filtrado datos futuros a ediciones tempranas). Recortado a
`[0.01, 0.99]` como salvaguarda ante combinaciones extremas.

### Resultado — 2010-2025, 2.032 partidos

| Modelo | Brier ↓ | Log-loss ↓ | ECE ↓ |
|---|---|---|---|
| Pre-Fase-B (piso) | 0.2046 ± 0.0049 | 0.5963 ± 0.0106 | 0.0766 |
| **B1+B2** | **0.1959 ± 0.0095** | **0.5735 ± 0.0249** | **0.0594** |
| Elo (dura) | 0.1904 ± 0.0085 | 0.5575 ± 0.0206 | 0.0385 |

Log-loss del campeón: 2.6887±0.3628 (piso) → **2.3266±0.7339** (B1+B2).

**Mejora real, en la dirección correcta, en las tres métricas.** La brecha
con Elo se cierra a más de la mitad (Brier: de 0.0142 a 0.0055 — los IC ya
se superponen bastante: piso-B1+B2 [0.186, 0.205] vs Elo [0.182, 0.199]).
Todavía no le gana a Elo solo, pero ya no es una diferencia abismal. B1+B2
se mantienen — mejora clara, sin necesidad de revertir nada (criterio de la
sección 5, Fase B paso 10).

---

## B5 + B7 + B8 — implementados juntos y medidos (2026-08-24)

Tres correcciones de reglas, agrupadas por ser de bajo riesgo y no
interactuar entre sí como B1/B2:

- **B5** — el tie-break ahora se simula punto a punto
  (`_simulate_tiebreak`), no como una sola moneda con la probabilidad de
  JUEGO. El saque se turna correctamente (1er punto un jugador, después de a
  2).
- **B7** — la rotación de saque entre sets ahora es la real: `_simulate_set`
  devuelve `next_server_is_a` como continuación de la rotación turno a turno
  (el tie-break cuenta como un turno más), no un volteo incondicional. Con
  cantidad PAR de games en el set, el mismo jugador sigue sacando primero en
  el próximo set; con cantidad IMPAR, cambia — la regla real.
- **B8** — el set decisivo usa tie-break a 10 (`DECIDING_SET_TIEBREAK_TARGET`
  en `config.py`), la regla del US Open desde 2022, en vez de a 7.

### Resultado — 2010-2025, 2.032 partidos

| Modelo | Brier ↓ | Log-loss ↓ | ECE ↓ |
|---|---|---|---|
| B1+B2 (paso anterior) | 0.1959 ± 0.0095 | 0.5735 ± 0.0249 | 0.0594 |
| **B1+B2+B5+B7+B8** | **0.1970 ± 0.0098** | **0.5776 ± 0.0262** | **0.0687** |

Log-loss del campeón: 2.3266±0.7339 → **2.4209±0.8793**.

**El delta es indistinguible de cero** (todos los cambios caen bien dentro
de sus propios IC) — mismo patrón que B0. Es el resultado esperado: B5/B7/B8
corrigen la mecánica FINA de cómo se resuelven juegos/sets/tie-breaks, no el
modelo de probabilidad de punto (eso es B1/B2, que sí domina el Brier
agregado). **Se mantienen igual que B0**: son correcciones de reglas
verificables independientemente de si mueven el Brier (mismo criterio que
B0 — revertir el tie-break a 10 en el set decisivo porque el a-7 dio un
número nominal mejor por azar significaría simular a propósito una regla
que el US Open no usa desde 2022). Cada una tiene test de regresión propio
en `tests/test_set_rules.py`.

---

## B9 — decaimiento temporal, implementado y medido (2026-08-24)

`ingest._decay_weight`: peso exponencial por partido según antigüedad
respecto al corte (vida media 365 días, `config.DECAY_HALF_LIFE_DAYS`),
aplicado a los puntos ganados/totales ANTES de agregarlos (así se propaga
solo, sin tocar código, tanto a `serve_pct` crudo como al ajuste por
oponente B2, que consume la misma acumulación). `matches_played` queda sin
ponderar (es informativo).

**Bug propio encontrado y corregido antes de medir**: la primera versión
dejaba que el decaimiento tocara también "modelo pre-Fase-B" (el piso
congelado), porque comparte `compute_surface_metrics` con el modelo nuevo —
el piso pasó de 0.2046 a 0.2065, dejando de representar el número ya
registrado. Corregido: el backtest ahora llama a `compute_surface_metrics`
dos veces por edición, una con `NO_DECAY_HALF_LIFE` (~sin decaimiento, para
el piso) y otra con el decaimiento real (para el modelo nuevo). Re-verificado:
el piso volvió a dar exactamente 0.2046±0.0049, igual que en la Fase A.

### Resultado final — 2010-2025, 2.032 partidos, B1+B2+B5+B7+B8+B9 juntos

| Modelo | Brier ↓ | Log-loss ↓ | ECE ↓ |
|---|---|---|---|
| Pre-Fase-B (piso, congelado) | 0.2046 ± 0.0049 | 0.5963 ± 0.0106 | 0.0761 |
| **Modelo nuevo (Fase B completa)** | **0.1930 ± 0.0092** | **0.5643 ± 0.0236** | **0.0506** |
| Elo (dura) | 0.1904 ± 0.0085 | 0.5575 ± 0.0206 | 0.0385 |

Log-loss del campeón: 2.6887±0.3628 (piso) → **2.2682±0.7402** (Fase B
completa) — una edición de US Open de menos "sorpresa" para el modelo.

### Contra los objetivos de la sección 1

| Métrica | Objetivo | Piso | Fase B completa | ¿Cumple? |
|---|---|---|---|---|
| Brier | ≤ 0.21 | 0.2046 | 0.1930 | Ya cumplía, mejoró más |
| Log-loss | ≤ 0.60 | 0.5963 | 0.5643 | Ya cumplía, mejoró más |
| ECE | ≤ 0.05 | 0.0761 | 0.0506 | **Casi** (a 0.0006 del objetivo) |

### Balance de la Fase B

El modelo pasó de perder contra Elo por un margen claro (Brier 0.2046 vs
0.1904, gap de 0.0142) a estar **estadísticamente empatado con Elo** en las
tres métricas — los intervalos se superponen casi por completo (Brier:
[0.184, 0.202] vs [0.182, 0.199]). No le gana todavía, pero dejó de perder
contra el baseline más fuerte, que era el objetivo real fijado en la Fase A
("el objetivo de la Fase B no es ser preciso, es dejar de perder contra
Elo"). A diferencia de Elo, el modelo conserva la estructura juego/set/set
decisivo — puede simular un cuadro completo, no solo dar P(partido).

**Validación cualitativa, no solo la tabla**: re-corriendo la CLI en vivo
para el US Open 2025 con el modelo nuevo, Sinner pasa de 18.4% (número
citado como sospechoso en la sección 1 del plan) a **47.3%** de probabilidad
de campeón — el favorito real del torneo, con Alcaraz y Djokovic
concentrando la mayoría del resto (21.7% y 19.1%). El efecto compuesto de
arreglar B1 (que comprimía toda ventaja a la mitad) se nota mucho más fuerte
a nivel "ganar el torneo completo" (7 rondas compuestas) que a nivel
partido a partido, que es justamente lo que predecía el diagnóstico
original.

### Qué queda (Fase C, deliberadamente fuera de esta sesión)

- Ensamble Elo + saque/resto (paso 12 del plan, adelantado en importancia
  por la Fase A): con ambos modelos casi empatados y midiendo cosas
  parcialmente distintas, un ensamble ponderado por el backtest es la
  siguiente mejora de mayor probabilidad de éxito.
- Head-to-head y fatiga (paso 13) — solo si el backtest los avala.
- Holdout real: todo lo de arriba se ajustó mirando 2010-2025 completo: antes
  de declarar victoria conviene re-medir separando 2024-2025 como holdout
  (sección 0D de la revisión CEO), afinando cualquier hiperparámetro nuevo
  (K_PRIOR_PTS, vida media de B9, iteraciones de B2) solo contra 2010-2023.

---
---

# FASE C — EJECUTADA (2026-08-24)

Metodología (obligatoria por el riesgo F3 de la revisión CEO, sección 0D):
**todo hiperparámetro nuevo se elige mirando SOLO 2010-2023 (`train`, 1.778
partidos) y se confirma sobre 2024-2025 (`holdout` nunca tocado durante la
búsqueda, 254 partidos)**. Elegir y medir con la misma mano es la forma más
común de creer que algo mejora cuando es sobreajuste al propio backtest.
Implementado en `src/validation/ensemble_search.py`.

## Paso 11 — Elo con decaimiento por inactividad

`models/elo.py`: antes de tocar el rating de un jugador, se lo acerca al
promedio (1500) según los días desde su partido anterior (vida media 365
días) — dos vidas medias sin jugar y el rating volvió casi al promedio, sin
necesidad de una ventana dura que tire datos. Tests en `tests/test_elo.py`
(el rating decae con el tiempo, no decae con vida media infinita, sin fugas
de fecha).

## Paso 12 — Ensamble Elo + saque/resto — VALIDADO, mejora real en holdout

Barrido de `w` en `p = w·modelo_nuevo + (1-w)·elo` sobre TRAIN:

| Modelo | Brier train | **Brier HOLDOUT** | Log-loss HOLDOUT |
|---|---|---|---|
| Modelo nuevo solo | 0.1916 | 0.2026 ± 0.0260 | 0.5838 ± 0.0664 |
| Elo solo | 0.2013 | 0.2053 ± 0.0147 | 0.5965 ± 0.0314 |
| **Ensamble (w=0.70)** | **0.1891** | **0.1982 ± 0.0221** | **0.5730 ± 0.0510** |

`w=0.70` elegido SOLO en train (2010-2023). En holdout (2024-2025, nunca
visto durante la búsqueda) el ensamble le gana a AMBOS componentes por
separado — no es sobreajuste, es mejora real fuera de muestra. 70/30 a favor
del modelo de saque/resto tiene sentido: preserva la estructura juego/set
que Elo no tiene, y Elo aporta señal de fondo (forma reciente cross-superficie)
que el ajuste por oponente de B2 no captura del todo.

## Paso 13 — Head-to-head y fatiga: AMBOS RECHAZADOS

**Head-to-head** (`p_h2h`, shrinkage hacia 50/50 con prior de 1 partido
virtual): peso óptimo elegido en train = **0.00** — el optimizador lo
descarta solo, no mejora ni el propio train. En holdout, restringir a los
partidos con cruce previo (49.8% del total) da un Brier PEOR (0.2098) que el
ensamble sin h2h (0.1982). Interpretación: el historial cabeza a cabeza no
agrega nada que el ajuste por oponente (B2) y Elo no capturen ya, y con
pocos cruces por par de jugadores es sobre todo ruido.

**Fatiga** (partidos jugados en los 14 días previos al corte): la tabla
descriptiva es sorprendentemente limpia y monótona —

| fatigue_diff (p1 − p2) | −3 | −2 | −1 | 0 | +1 | +2 | +3 |
|---|---|---|---|---|---|---|---|
| P(gana p1) | 0.41 | 0.43 | 0.50 | 0.51 | 0.54 | 0.57 | 0.61 |

— pero en la dirección OPUESTA a la hipótesis del plan: jugar MÁS partidos
recientes se asocia a GANAR más, no a llegar más cansado. Ajustando un
logístico en train (`p_fatiga = σ(a + b·fatigue_diff)`, b=+0.108) y
probándolo como componente del ensamble (mismo barrido que h2h): **peso
óptimo = 0.00, Brier train idéntico con o sin fatiga (0.1891)**. La
correlación univariada es real pero no aporta información NUEVA una vez que
ya están el modelo de saque/resto y Elo: jugar más partidos en las dos
semanas previas es sobre todo un proxy de "está en buena forma / es un
cabeza de serie que ganó rondas anteriores", algo que el propio nivel del
jugador (Elo, saque/resto) ya captura. Confirma por qué el plan puso la
condición "solo se quedan si el backtest los avala" — la tabla sola hubiera
llevado a agregar una señal sin valor incremental real.

## Qué se lleva la Fase C

**Se adopta**: Elo con decaimiento (paso 11) + ensamble w=0.70 (paso 12).
**Se descarta, con evidencia**: head-to-head y fatiga (paso 13) — ninguno
sobrevive el holdout una vez controlado por el modelo de saque/resto y Elo.

## Pendiente — no ejecutado esta sesión, requiere decisión de arquitectura

El ensamble está VALIDADO pero solo corre hoy en el backtest
(`ensemble_search.py`), no en la CLI en vivo. Cablearlo requiere resolver un
choque de arquitectura: Elo da una probabilidad de PARTIDO (un escalar), el
motor real simula juego a juego para preservar el marcador. Dos caminos:

1. **Mezclar a nivel de probabilidad de PUNTO**: invertir la fórmula
   cerrada (la misma DP de `models/current.py`, adaptada a las reglas post
   B5/B7/B8) para encontrar qué `p_a_serve` reproduce la P(partido) que da
   Elo, y promediar ese `p_a_serve` con el de Barnett-Clarke (70/30). Preserva
   la simulación juego a juego. Requiere una búsqueda de raíz (binaria,
   función monótona) por partido — más trabajo, cero pérdida de estructura.
2. **Mezclar a nivel de PARTIDO**: usar `w·p_motor + (1-w)·p_elo` como una
   sola moneda por partido dentro de `simulate_tournament`, perdiendo el
   marcador juego a juego para esos partidos (o simulándolo igual pero
   forzando el resultado). Mucho más simple, pero tira la razón por la que
   el motor no es "solo Elo" (sección 0A.P3 de la revisión CEO).

Ninguno se implementó todavía — es una decisión de arquitectura, no de
medición, y el plan pide medir antes de mover. Los números de arriba ya
responden la pregunta que importa ("¿vale la pena el ensamble?" — sí).

---
---

# FASE D — EJECUTADA (2026-08-24)

## Paso 14 (B10) — Vectorizar/precomputar: réplica analítica del motor completo

`src/simulation/models/serve_return.py`: a diferencia de `models/current.py`
(congelado al piso pre-Fase-B), esta réplica importa las funciones EN VIVO
de `monte_carlo.py` -- representa "el modelo que corre hoy" en cualquier
momento, post B1+B2+B5+B7+B8+B9. Calcula la probabilidad EXACTA de partido
vía programación dinámica (DP juego→set→partido, más un DP aparte para el
tie-break) en vez de simular ~100-200 puntos por partido, y la usa para
simular un cuadro completo con **un solo sorteo por partido** en vez de
~150. Sigue siendo Monte Carlo real a nivel de TORNEO (quién gana cada
partido y quién es campeón se sigue sorteando en cada una de las N
repeticiones) — deja de simular el marcador interno, que nunca se mostró.

**Dos bugs reales encontrados y corregidos antes de confiar en el número:**

1. **Recursión infinita en el tie-break con probabilidades parejas.** La
   región de "deuce" de un tie-break a 7 o 10 (ganar por 2, sin límite) es
   un CICLO real cuando el punto está cerca de 50/50 (el marcador puede
   volver al mismo estado relativo una y otra vez) — una DP memoizada de
   arriba hacia abajo no termina ahí (confirmado: `RecursionError` real
   probando con jugadores parejos, no un caso de borde inventado). Se
   resolvió como sistema lineal (12 estados: diferencia de puntos ×
   servidor × primer/segundo punto del par), el mismo tipo de cierre
   algebraico que ya usa `game_win_prob` para el deuce de un juego, pero
   adaptado al saque que se turna de a 2 en un tie-break.
2. **El cache de probabilidades por par de jugadores estaba en el scope
   equivocado** (por torneo simulado, no por corrida completa) — como cada
   par de jugadores aparece como máximo una vez POR torneo, el cache nunca
   pegaba, y la versión "rápida" recalculaba la DP 150 × N veces, quedando
   más lenta que el motor original. Corregido: el cache vive en
   `run_simulations_fast` y se pasa a cada torneo simulado.

**Medido**, cuadro real de 2025, 128 jugadores: ~300-320 sims/s el motor
original → **~550 sims/s** la réplica rápida (con cache tibio; el cuadro por
defecto de 10.000 simulaciones pasó de ~32s a ~18-20s). Verificado contra el
motor real en `tests/test_serve_return.py`: probabilidad de partido dentro
del error de muestreo de miles de `simulate_match` reales, y probabilidades
de campeón de un cuadro de 128 dentro del error de muestreo de
`run_simulations` real.

Es ahora el motor **por defecto** de la CLI; `--exact-simulation` vuelve al
original juego a juego para verificar/depurar.

## Paso 15 (B6) — Intervalos de confianza en la tabla

`src/cli/render.py`: la columna Campeón ahora muestra IC95% binomial
(`± X.Xpp`), con una nota al pie explicando que diferencias más chicas que
el ancho del intervalo no son señal. Con el cuadro 2025 y 10.000
simulaciones (motor rápido): Sinner 48.8% ± 1.0, Alcaraz 22.2% ± 0.8,
Djokovic 16.8% ± 0.7 — distinguibles entre sí; más abajo en la tabla los
intervalos empiezan a superponerse, visible directamente en la salida en
vez de tener que calcularlo aparte.

## Paso 16 (B11) — README arreglado

Reescrito. Ya no dice "no hay shrinkage" (lo hay, y ahora también ajuste por
oponente), ya no enlaza a `PLAN_IMPLEMENTACION_USOPEN.md` (no existe en el
repo) sino a `PLAN_MEJORA_SIMULACION.md`, documenta el modelo actual
(Barnett-Clarke + ajuste por oponente + decaimiento + reglas reales),
el backtest (`--backtest`), el motor rápido por defecto y sus límites
conocidos (128 jugadores exactos, ensamble medido pero no desplegado, h2h/
fatiga descartados con evidencia).

## Estado del proyecto al cierre de la Fase D

Las 4 fases del plan de mejora están ejecutadas y medidas: A (medición),
B (arreglar el modelo: B0 propio + B1-B9), C (Elo + ensamble, h2h/fatiga
descartados con evidencia), D (rendimiento + presentación). 63 tests, todos
verdes. Pendiente real, explícito, no oculto: desplegar el ensamble Elo en
el motor en vivo (decisión de arquitectura, sección de Fase C arriba).

---
---

# EXTENSIÓN — `--model elo` (2026-08-24, a pedido explícito)

Pedido: "usar el ranking Elo directamente para decidir quién gana el
partido completo". Distinto del ensamble pendiente arriba (que MEZCLA Elo
con saque/resto): esto agrega Elo como **modelo seleccionable e
independiente**, tal como preveía la arquitectura de la sección 4 del plan
original ("la CLI gana `--model`").

`src/simulation/models/elo.py`: `EloPlayer` (player_id/full_name/seed/
rating, sin serve_pct/return_pct — no hace falta), `simulate_match_elo`
(una moneda, `match_probability_from_elo`), `simulate_tournament_elo` y
`run_simulations_elo` (misma estructura de ronda a ronda que
`monte_carlo.run_simulations`, intercambiables). `simular_usopen.py` gana
`--model {serve_return,elo}` (default `serve_return`, el ya validado);
`--model elo` carga años adicionales de historial para el calentamiento del
rating (se descargan solos) y arma el cuadro con `_load_elo_draw`.

11 tests nuevos/extendidos en `tests/test_elo.py` (moneda pareja ~50/50,
favorece al rating más alto, suma de campeones = N simulaciones, rechaza
cuadros que no son potencia de 2, el favorito claro gana el torneo mucho
más seguido que el resto). 68 tests en total, todos verdes.

**Nota de expectativas** (visible también en el `--help` y en la nota de la
CLI): Elo puro es el baseline más fuerte medido en el backtest (Brier
0.1904 vs 0.1930 del modelo por defecto — prácticamente empatados, sección
de Fase B arriba), pero al decidir el partido con una sola moneda en vez de
juego a juego, las probabilidades de campeón salen más aplanadas que con el
modelo por defecto: con el cuadro 2025, Djokovic pasa del top 3 (serve_return)
al top 8 (elo puro) — el ranking Elo decae por inactividad y no compone la
estructura de 7 rondas de la misma manera que la simulación juego/set.
Ninguno de los dos es "más correcto" en abstracto — son la misma pregunta
medida con información distinta, y el backtest de arriba es la referencia
para elegir.

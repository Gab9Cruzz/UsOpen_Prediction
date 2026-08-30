"""Configuración central del motor de datos.

Fase 1 del plan (ver PLAN_IMPLEMENTACION_USOPEN.md, sección 17): mantener la
configuración fuera de la lógica de negocio para que el resto de módulos
(ingesta, simulación, CLI) no tengan constantes hardcodeadas.
"""

from __future__ import annotations

from pathlib import Path

# --- Rutas del proyecto -----------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DB_PATH = PROJECT_ROOT / "database" / "us_open.db"
SCHEMA_PATH = PROJECT_ROOT / "database" / "schema.sql"
# PLAN_PAGINA_RESULTADOS.md (decisión #18): destino de los reportes HTML
# (--html), generado y descartable -- no es fuente, ver .gitignore.
OUTPUT_DIR = PROJECT_ROOT / "output"

# --- Fuente de datos históricos ---------------------------------------------
# Fuente canónica: https://github.com/JeffSackmann/tennis_atp
# Desde este entorno esa fuente responde 404 en TODOS los endpoints
# (raw, API, codeload) mientras que otros repos de GitHub sí cargan, así que
# el bloqueo es específico a ese repo/entorno de red y no un problema de
# GitHub en general. Se usa un mirror comunitario verificado con el mismo
# esquema de columnas y licencia (CC BY-NC-SA 4.0, con atribución a Jeff
# Sackmann) como fuente de respaldo. Si tu red sí tiene acceso al repo
# original, cambiá PRIMARY_BASE_URL por el mirror y listo.
PRIMARY_BASE_URL = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master"
MIRROR_BASE_URL = (
    "https://raw.githubusercontent.com/Aneeshers/tennis-sackmann-archive/main/atp"
)
SOURCE_URLS = [PRIMARY_BASE_URL, MIRROR_BASE_URL]

PLAYERS_FILE = "atp_players.csv"
MATCHES_FILE_TEMPLATE = "atp_matches_{year}.csv"

# --- Ventana de métricas -----------------------------------------------------
SURFACE = "Hard"
YEARS_BACK = 3  # incluye el año del torneo objetivo + 2 anteriores
# B9 (plan de mejora): decaimiento exponencial de las métricas de saque/resto
# -- un partido de hace 1 mes predice mejor que uno de hace 3 años. Vida
# media en días; a esta distancia en el pasado, un partido pesa la mitad que
# uno de hoy.
DECAY_HALF_LIFE_DAYS = 365

# --- Torneo objetivo ---------------------------------------------------------
# El sorteo oficial 2026 aún no existe como dataset histórico (el torneo se
# juega en estas fechas). Mientras no exista Fase 4 (ingesta de cuadro
# oficial / live), el motor reconstruye el cuadro REAL de la última edición
# completa para poder simular con emparejamientos genuinos y no un draw
# ficticio. Esto es intencional y se deja explícito en el output de la CLI.
TOURNAMENT_NAME = "Us Open"
DEFAULT_DRAW_YEAR = 2025

# --- Monte Carlo --------------------------------------------------------------
DEFAULT_SIMULATIONS = 10_000
DEFAULT_SEED = 42
BEST_OF = 5  # Grand Slam masculino
# B8 (plan de mejora): el set decisivo del US Open usa tie-break a 10 puntos
# desde 2022, no a 7 como el resto de los sets.
DECIDING_SET_TIEBREAK_TARGET = 10

# Rondas de un cuadro de 128, en orden de juego. Vive acá (no en
# src/cli/pipeline.py, donde se usaba antes) porque src/data/live_draw.py
# también la necesita para nombrar rondas al parsear el estado real del
# cuadro, y src/data no puede importar de src/cli (capas: data no depende de
# cli, ver plan sección 1.1) -- moverla al módulo de configuración, que
# ambas capas ya importan, evita esa dependencia invertida sin duplicar la
# lista en dos lugares.
MATCH_ROUNDS = ["R128", "R64", "R32", "R16", "QF", "SF", "F"]
# Cuántos partidos tiene cada ronda de un cuadro de 128 -- lo usa
# src/cli/pipeline.py para saber si una ronda ya está 100% jugada en la
# realidad (y por lo tanto su snapshot de predicción puede "congelarse").
MATCHES_PER_ROUND = {"R128": 64, "R64": 32, "R32": 16, "R16": 8, "QF": 4, "SF": 2, "F": 1}

# --- Fase 4: sorteo oficial en vivo (Wikipedia) ------------------------------
# Cuando build_draw (reconstrucción histórica de Sackmann, ver ingest.py) no
# encuentra R128 para la edición pedida -- porque el torneo todavía no se
# jugó -- run_ingest cae a esto: el sorteo ya publicado, parseado desde
# Wikipedia (los editores arman el bracket completo en cuanto se anuncia,
# formato `{{16TeamBracket-Compact-Tennis5}}` por sección + `{{8TeamBracket-
# Tennis5}}` para cuartos/semis/final -- ver src/data/live_draw.py). Deja de
# usarse solo, sin tocar código, en cuanto Sackmann publique los resultados
# reales de esa edición.
WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"
# Título del artículo de Wikipedia por torneo (normalizado a minúsculas) --
# hoy solo cubre el US Open masculino, que es todo lo que soporta el resto
# del proyecto (SURFACE/TOURNAMENT_NAME arriba tampoco distinguen otro cuadro).
LIVE_DRAW_WIKI_TITLES = {
    "us open": "{year} US Open – Men's singles",
}
LIVE_DRAW_SOURCE = "wikipedia_live"
LIVE_DRAW_CACHE_TEMPLATE = "live_draw_{tournament}_{year}.json"

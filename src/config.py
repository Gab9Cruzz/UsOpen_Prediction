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

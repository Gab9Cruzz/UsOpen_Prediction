"""Descarga y cachea los CSV crudos de Jeff Sackmann (o su mirror de respaldo).

No contiene lógica de parsing/normalización ni de SQLite (eso vive en
`ingest.py`), siguiendo la separación de capas del plan (sección 1.1 y 12.1).
"""

from __future__ import annotations

import logging
from pathlib import Path

import requests

from src import config

logger = logging.getLogger(__name__)


class FetchError(RuntimeError):
    """No se pudo obtener un archivo desde ninguna fuente configurada."""


def _download(filename: str) -> bytes:
    last_error: Exception | None = None
    for base_url in config.SOURCE_URLS:
        url = f"{base_url}/{filename}"
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 200 and resp.content:
                logger.info("Descargado %s desde %s", filename, base_url)
                return resp.content
            last_error = RuntimeError(f"HTTP {resp.status_code} en {url}")
        except requests.RequestException as exc:
            last_error = exc
        logger.warning("Fuente no disponible para %s: %s", url, last_error)
    raise FetchError(f"No se pudo descargar {filename} desde ninguna fuente: {last_error}")


def fetch_file(filename: str, force: bool = False) -> Path:
    """Descarga `filename` a data/raw/ (si no existe o force=True) y devuelve la ruta."""
    config.DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.DATA_RAW_DIR / filename
    if dest.exists() and not force:
        logger.info("Usando caché local: %s", dest)
        return dest
    content = _download(filename)
    dest.write_bytes(content)
    return dest


def fetch_matches(years: list[int], force: bool = False) -> list[Path]:
    return [
        fetch_file(config.MATCHES_FILE_TEMPLATE.format(year=year), force=force)
        for year in years
    ]


def fetch_players(force: bool = False) -> Path:
    return fetch_file(config.PLAYERS_FILE, force=force)


def fetch_all(draw_year: int, years_back: int, force: bool = False) -> dict:
    """Descarga todo lo necesario: N años de partidos (hasta e incluyendo draw_year) + jugadores."""
    years = list(range(draw_year - years_back + 1, draw_year + 1))
    matches_paths = fetch_matches(years, force=force)
    players_path = fetch_players(force=force)
    return {"years": years, "matches": matches_paths, "players": players_path}

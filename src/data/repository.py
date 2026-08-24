"""Lectura de SQLite -> objetos de dominio para el simulador.

Separa "leer de la base" de "simular" (plan sección 1.2): el motor Monte
Carlo nunca toca SQLite directamente.
"""

from __future__ import annotations

import logging
import sqlite3

from src import config
from src.simulation.monte_carlo import Player

logger = logging.getLogger(__name__)


def draw_is_ready(tournament_name: str, tournament_year: int, db_path=config.DB_PATH) -> bool:
    """True si el cuadro de esa edición está completo y sus 128 jugadores
    existen en `jugadores` (jugadores/metricas_superficie no están
    particionados por año: reingestar otra edición los reescribe por
    completo, así que un cuadro viejo puede quedar "huérfano")."""
    try:
        with sqlite3.connect(db_path) as conn:
            count = conn.execute(
                """
                SELECT COUNT(*) FROM cuadro_torneo c
                JOIN jugadores j ON j.player_id = c.player_id
                WHERE c.tournament_name = ? AND c.tournament_year = ? AND c.round_name = 'R128'
                """,
                (tournament_name, tournament_year),
            ).fetchone()[0]
    except sqlite3.OperationalError:
        return False
    return count == 128


def load_draw(
    tournament_name: str, tournament_year: int, db_path=config.DB_PATH
) -> tuple[list[Player], dict[str, Player]]:
    # LEFT JOIN a propósito: un jugador sin partidos en Hard antes del corte
    # (p.ej. un wildcard joven que venía de challengers en polvo de ladrillo)
    # no debe desaparecer del cuadro (rompería el emparejamiento de slots
    # adyacentes). Se le asigna un prior en vez de excluirlo -- plan sección
    # 4.10/4.11: "nunca completar con cero si no existe evidencia", "usar
    # priors" para jugadores con pocos partidos.
    query = """
        SELECT c.slot_index, c.player_id, c.seed,
               j.full_name, m.serve_pct, m.return_pct
        FROM cuadro_torneo c
        JOIN jugadores j ON j.player_id = c.player_id
        LEFT JOIN metricas_superficie m ON m.player_id = c.player_id
        WHERE c.tournament_name = ? AND c.tournament_year = ? AND c.round_name = 'R128'
        ORDER BY c.slot_index
    """
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(query, (tournament_name, tournament_year)).fetchall()

    if not rows:
        raise RuntimeError(
            "El cuadro no está en la base de datos. Corré primero: "
            "python simular_usopen.py --update-data"
        )

    known_serve = [r[4] for r in rows if r[4] is not None]
    known_return = [r[5] for r in rows if r[5] is not None]
    prior_serve = sum(known_serve) / len(known_serve) if known_serve else 0.62
    prior_return = sum(known_return) / len(known_return) if known_return else 0.38

    draw = []
    for _slot, player_id, seed, full_name, serve_pct, return_pct in rows:
        if serve_pct is None or return_pct is None:
            logger.warning(
                "Sin métricas en Hard antes del corte para %s (%s); usando prior promedio del cuadro",
                full_name, player_id,
            )
            serve_pct = prior_serve if serve_pct is None else serve_pct
            return_pct = prior_return if return_pct is None else return_pct
        draw.append(
            Player(
                player_id=player_id,
                full_name=full_name,
                seed=int(seed) if seed is not None else None,
                serve_pct=serve_pct,
                return_pct=return_pct,
            )
        )
    players_by_id = {p.player_id: p for p in draw}
    return draw, players_by_id

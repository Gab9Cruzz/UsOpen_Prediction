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
                JOIN jugadores j ON j.player_id = c.player_id AND j.tournament_year = c.tournament_year
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
               j.full_name, m.serve_pct, m.return_pct, m.serve_pct_adj, m.return_pct_adj
        FROM cuadro_torneo c
        JOIN jugadores j ON j.player_id = c.player_id AND j.tournament_year = c.tournament_year
        LEFT JOIN metricas_superficie m
            ON m.player_id = c.player_id AND m.tournament_year = c.tournament_year
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

    # `avg_serve_hard` es el promedio CRUDO del cuadro (μ de Barnett-Clarke,
    # B1): el ajuste por oponente (B2) ya lo usó como ancla, no se debe volver
    # a mezclar con las tasas ajustadas. El prior de jugadores sin métricas sí
    # se calcula en escala AJUSTADA, porque es lo que va a `Player.serve_pct`.
    known_serve_raw = [r[4] for r in rows if r[4] is not None]
    known_return_raw = [r[5] for r in rows if r[5] is not None]
    avg_serve_hard = sum(known_serve_raw) / len(known_serve_raw) if known_serve_raw else 0.62
    avg_return_hard = sum(known_return_raw) / len(known_return_raw) if known_return_raw else 0.38

    known_serve_adj = [r[6] for r in rows if r[6] is not None]
    known_return_adj = [r[7] for r in rows if r[7] is not None]
    prior_serve_adj = sum(known_serve_adj) / len(known_serve_adj) if known_serve_adj else avg_serve_hard
    prior_return_adj = sum(known_return_adj) / len(known_return_adj) if known_return_adj else avg_return_hard

    draw = []
    for _slot, player_id, seed, full_name, _serve_pct, _return_pct, serve_pct_adj, return_pct_adj in rows:
        if serve_pct_adj is None or return_pct_adj is None:
            logger.warning(
                "Sin métricas en Hard antes del corte para %s (%s); usando prior promedio del cuadro",
                full_name, player_id,
            )
            serve_pct_adj = prior_serve_adj if serve_pct_adj is None else serve_pct_adj
            return_pct_adj = prior_return_adj if return_pct_adj is None else return_pct_adj
        draw.append(
            Player(
                player_id=player_id,
                full_name=full_name,
                seed=int(seed) if seed is not None else None,
                serve_pct=serve_pct_adj,
                return_pct=return_pct_adj,
                avg_serve_pct=avg_serve_hard,
            )
        )
    players_by_id = {p.player_id: p for p in draw}
    return draw, players_by_id

"""Lectura de SQLite -> objetos de dominio para el simulador.

Separa "leer de la base" de "simular" (plan sección 1.2): el motor Monte
Carlo nunca toca SQLite directamente.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime

from src import config
from src.simulation.monte_carlo import Player

logger = logging.getLogger(__name__)


def draw_is_ready(tournament_name: str, tournament_year: int, db_path=None) -> bool:
    """True si el cuadro de esa edición está completo y sus 128 jugadores
    existen en `jugadores` (jugadores/metricas_superficie no están
    particionados por año: reingestar otra edición los reescribe por
    completo, así que un cuadro viejo puede quedar "huérfano").

    `db_path=None` (no `=config.DB_PATH`) a propósito: un default evaluado
    en la firma de la función se fija UNA sola vez, al importar el módulo --
    si algo reasigna `config.DB_PATH` después (p.ej. un test que aísla su
    propia base con `monkeypatch.setattr(config, "DB_PATH", ...)`), esta
    función seguiría usando el valor viejo. Resolviendo `config.DB_PATH`
    ADENTRO del cuerpo se lee el valor ACTUAL en cada llamada. Mismo criterio
    en el resto de las funciones de este módulo (bug real, encontrado
    escribiendo los tests de Fase 4 -- ver tests/test_snapshots.py)."""
    db_path = db_path or config.DB_PATH
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
    tournament_name: str, tournament_year: int, db_path=None
) -> tuple[list[Player], dict[str, Player]]:
    db_path = db_path or config.DB_PATH  # ver el comentario en draw_is_ready sobre por qué no =config.DB_PATH
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


# --- Fase 4: sorteo en vivo + snapshots de predicción por ronda -------------


def is_live_draw(tournament_name: str, tournament_year: int, db_path=None) -> bool:
    """True si el cuadro de esa edición viene del sorteo oficial en vivo
    (`src/data/live_draw.py`, `source = config.LIVE_DRAW_SOURCE`) en vez de
    reconstruido de resultados históricos. Solo para esas ediciones tiene
    sentido trackear resultados en vivo y generar snapshots por ronda
    (`src/cli/pipeline.py::run_prediction`) -- una edición histórica ya
    tiene TODOS sus resultados reales, no hay nada "en progreso" que trackear."""
    db_path = db_path or config.DB_PATH  # ver el comentario en draw_is_ready
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                """
                SELECT 1 FROM cuadro_torneo
                WHERE tournament_name = ? AND tournament_year = ? AND round_name = 'R128' AND source = ?
                LIMIT 1
                """,
                (tournament_name, tournament_year, config.LIVE_DRAW_SOURCE),
            ).fetchone()
    except sqlite3.OperationalError:
        return False
    return row is not None


def save_snapshot(
    tournament_name: str,
    tournament_year: int,
    round_name: str,
    model: str,
    n_simulations: int,
    counts: dict[str, dict[str, int]],
    frozen: bool,
    db_path=None,
) -> None:
    """Guarda (upsert) el snapshot de predicción "entrando a `round_name`"
    -- ver el docstring de la tabla `snapshots_prediccion` en schema.sql."""
    db_path = db_path or config.DB_PATH  # ver el comentario en draw_is_ready
    with sqlite3.connect(db_path) as conn:
        conn.executescript(config.SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute(
            """
            INSERT INTO snapshots_prediccion
                (tournament_name, tournament_year, round_name, model, n_simulations, counts_json, frozen, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (tournament_name, tournament_year, round_name, model) DO UPDATE SET
                n_simulations = excluded.n_simulations,
                counts_json = excluded.counts_json,
                frozen = excluded.frozen,
                generated_at = excluded.generated_at
            """,
            (
                tournament_name, tournament_year, round_name, model,
                n_simulations, json.dumps(counts), int(frozen), datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()


def load_snapshots(
    tournament_name: str, tournament_year: int, model: str, db_path=None
) -> list[dict]:
    """Todos los snapshots guardados de esa edición/modelo, en orden de
    ronda (`config.MATCH_ROUNDS`) -- lo que consume `html_report.py` para
    apilarlos "R128 arriba, F abajo" tal como se pidió."""
    db_path = db_path or config.DB_PATH  # ver el comentario en draw_is_ready
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT round_name, n_simulations, counts_json, frozen, generated_at
                FROM snapshots_prediccion
                WHERE tournament_name = ? AND tournament_year = ? AND model = ?
                """,
                (tournament_name, tournament_year, model),
            ).fetchall()
    except sqlite3.OperationalError:
        return []

    by_round = {
        round_name: {
            "round_name": round_name,
            "n_simulations": n_simulations,
            "counts": json.loads(counts_json),
            "frozen": bool(frozen),
            "generated_at": generated_at,
        }
        for round_name, n_simulations, counts_json, frozen, generated_at in rows
    }
    return [by_round[r] for r in config.MATCH_ROUNDS if r in by_round]

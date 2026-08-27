"""B9 — decaimiento exponencial de las métricas de saque/resto
(`ingest._decay_weight` / `compute_surface_metrics`)."""

from __future__ import annotations

import pandas as pd
import pytest

from src.data.ingest import _decay_weight, compute_surface_metrics

CUTOFF = 20250825
HALF_LIFE = 365


def test_decay_weight_is_one_at_cutoff():
    assert _decay_weight(CUTOFF, CUTOFF, HALF_LIFE) == pytest.approx(1.0)


def test_decay_weight_is_half_at_one_half_life():
    one_half_life_ago = 20240825  # ~365 días antes de CUTOFF
    assert _decay_weight(one_half_life_ago, CUTOFF, HALF_LIFE) == pytest.approx(0.5, abs=0.01)


def test_decay_weight_is_quarter_at_two_half_lives():
    two_half_lives_ago = 20230826
    assert _decay_weight(two_half_lives_ago, CUTOFF, HALF_LIFE) == pytest.approx(0.25, abs=0.01)


def test_decay_weight_never_negative_for_future_dates():
    # No debería pasar (compute_surface_metrics ya filtra tourney_date <
    # cutoff), pero la función no debe devolver pesos > 1 ni raros si algo
    # la llama con una fecha posterior al corte.
    assert _decay_weight(CUTOFF + 100, CUTOFF, HALF_LIFE) <= 1.0


def _match(date: int, winner_id: int, loser_id: int, w_serve_pct: float) -> dict:
    svpt = 80
    w_won = round(svpt * w_serve_pct)
    return {
        "surface": "Hard", "tourney_date": date, "match_num": 1,
        "winner_id": winner_id, "winner_name": "Player", "winner_rank": 10,
        "loser_id": loser_id, "loser_name": "Opponent", "loser_rank": 50,
        "w_svpt": svpt, "w_1stWon": w_won, "w_2ndWon": 0,
        "l_svpt": 80, "l_1stWon": 40, "l_2ndWon": 0,
    }


def test_recent_match_weighs_more_than_old_match_with_same_player():
    # Mismo jugador (id=1) gana dos partidos con serve_pct MUY distinto:
    # 0.90 reciente (hace 10 días) y 0.30 viejo (hace ~2 vidas medias). Sin
    # decaimiento, el promedio simple daría ~0.60; con decaimiento el
    # resultado debe quedar mucho más cerca de 0.90 (lo reciente pesa más).
    recent = _match(20250815, winner_id=1, loser_id=2, w_serve_pct=0.90)  # 10 días antes del corte
    old = _match(20230826, winner_id=1, loser_id=3, w_serve_pct=0.30)  # ~2 vidas medias antes
    df = pd.DataFrame([recent, old])

    out = compute_surface_metrics(df, "Hard", CUTOFF, half_life_days=HALF_LIFE)
    row = out[out["player_id"] == "1"].iloc[0]

    # serve_pct crudo (antes de shrinkage hacia el promedio del cohorte,
    # pero acá el cohorte ES el propio jugador, así que el shrinkage tira
    # hacia su propio promedio ponderado -- no distorsiona la comparación).
    assert row["serve_pct"] > 0.65  # mucho más cerca de 0.90 que del promedio simple 0.60


def test_no_decay_when_half_life_is_huge():
    """Con una vida media enorme (~sin decaimiento), el resultado debe
    acercarse al promedio simple de ambos partidos."""
    recent = _match(20250815, winner_id=1, loser_id=2, w_serve_pct=0.90)
    old = _match(20230826, winner_id=1, loser_id=3, w_serve_pct=0.30)
    df = pd.DataFrame([recent, old])

    out = compute_surface_metrics(df, "Hard", CUTOFF, half_life_days=1_000_000)
    row = out[out["player_id"] == "1"].iloc[0]
    assert row["serve_pct"] == pytest.approx(0.60, abs=0.05)

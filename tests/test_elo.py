"""Elo de superficie con decaimiento por inactividad (paso 11, Fase C) y el
modelo `--model elo` (decide el partido completo directamente, a pedido)."""

from __future__ import annotations

import random

import pandas as pd
import pytest

from src.simulation.models.elo import (
    INITIAL_ELO,
    EloPlayer,
    build_elo_snapshots,
    match_probability_from_elo,
    run_simulations_elo,
    simulate_match_elo,
)


def _match(date: int, winner_id: int, loser_id: int, match_num: int = 1) -> dict:
    return {
        "surface": "Hard", "tourney_date": date, "match_num": match_num,
        "winner_id": winner_id, "loser_id": loser_id,
    }


def test_match_probability_from_elo_equal_ratings_is_half():
    assert match_probability_from_elo(1500, 1500) == pytest.approx(0.5)


def test_match_probability_from_elo_favors_higher_rating():
    assert match_probability_from_elo(1600, 1400) > 0.5


def test_winner_rating_increases_loser_decreases():
    df = pd.DataFrame([_match(20200101, winner_id=1, loser_id=2)])
    snap = build_elo_snapshots(df, "Hard", cutoffs=[20200102])[20200102]
    assert snap["1"] > INITIAL_ELO
    assert snap["2"] < INITIAL_ELO


def test_snapshot_excludes_matches_on_or_after_cutoff():
    df = pd.DataFrame([_match(20200101, winner_id=1, loser_id=2)])
    snap_before = build_elo_snapshots(df, "Hard", cutoffs=[20200101])[20200101]
    assert snap_before == {}  # el partido del 20200101 no debe contar para un corte EN esa fecha


def test_inactivity_decays_rating_toward_mean():
    """Un jugador que ganó mucho y después no jugó por años debe verse, en
    un corte lejano, más cerca del promedio que en un corte inmediato."""
    # jugador 1 gana varios partidos seguidos en enero 2015 -> rating alto
    df = pd.DataFrame(
        [_match(20150101 + i, winner_id=1, loser_id=100 + i, match_num=i) for i in range(8)]
    )
    snap_soon = build_elo_snapshots(df, "Hard", cutoffs=[20150201], half_life_days=365)[20150201]
    snap_far = build_elo_snapshots(df, "Hard", cutoffs=[20200101], half_life_days=365)[20200101]  # ~5 años después, sin jugar

    rating_soon = snap_soon["1"]
    rating_far = snap_far["1"]
    assert rating_soon > INITIAL_ELO  # subió por las victorias
    assert rating_far > INITIAL_ELO  # sigue por encima del promedio...
    assert rating_far < rating_soon  # ...pero mucho más cerca que recién ganado


def test_no_decay_with_huge_half_life():
    df = pd.DataFrame([_match(20150101, winner_id=1, loser_id=2)])
    snap_soon = build_elo_snapshots(df, "Hard", cutoffs=[20150201], half_life_days=1e9)[20150201]
    snap_far = build_elo_snapshots(df, "Hard", cutoffs=[20250101], half_life_days=1e9)[20250101]
    assert snap_soon["1"] == pytest.approx(snap_far["1"], abs=1e-3)


# --- `--model elo`: decide el partido completo directamente -----------------


def _elo_player(pid: str, rating: float) -> EloPlayer:
    return EloPlayer(player_id=pid, full_name=pid, seed=None, rating=rating)


def test_simulate_match_elo_equal_ratings_is_roughly_half():
    a, b = _elo_player("a", 1500), _elo_player("b", 1500)
    rng = random.Random(5)
    n = 3000
    wins = sum(1 for _ in range(n) if simulate_match_elo(rng, a, b) is a)
    se = (0.5 * 0.5 / n) ** 0.5
    assert abs(wins / n - 0.5) < 5 * se


def test_simulate_match_elo_favors_higher_rating():
    strong, weak = _elo_player("strong", 1700), _elo_player("weak", 1400)
    rng = random.Random(5)
    n = 2000
    wins = sum(1 for _ in range(n) if simulate_match_elo(rng, strong, weak) is strong)
    assert wins / n > match_probability_from_elo(1700, 1400) - 0.05


def test_run_simulations_elo_champion_counts_sum_to_n():
    draw = [_elo_player(f"p{i}", 1500 + 5 * i) for i in range(128)]
    n = 300
    counts = run_simulations_elo(draw, n_simulations=n, seed=7)
    assert sum(c["CAMPEON"] for c in counts.values()) == n


def test_run_simulations_elo_favors_higher_rated_player():
    draw = [_elo_player(f"p{i}", 1500) for i in range(128)]
    draw[0] = _elo_player("favorite", 1900)  # muy por encima del resto
    counts = run_simulations_elo(draw, n_simulations=500, seed=1)
    favorite_champion_rate = counts["favorite"]["CAMPEON"] / 500
    others_avg = sum(counts[p.player_id]["CAMPEON"] for p in draw if p.player_id != "favorite") / 500 / 127
    assert favorite_champion_rate > others_avg * 5  # el favorito claro gana el torneo mucho más seguido


def test_run_simulations_elo_rejects_non_power_of_two_draw():
    draw = [_elo_player(f"p{i}", 1500) for i in range(10)]
    with pytest.raises(ValueError):
        run_simulations_elo(draw, n_simulations=10, seed=1)

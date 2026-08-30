"""`--model ensemble`: conecta el peso 70/30 saque/resto + Elo medido en
`src/validation/ensemble_search.py` a la simulación real, como una opción
NUEVA que no toca `--model elo` (sigue siendo Elo "puro", ver
`tests/test_elo.py`)."""

from __future__ import annotations

import random

import pytest

from src.simulation.models import elo as elo_model
from src.simulation.models import serve_return
from src.simulation.models.ensemble import (
    SERVE_RETURN_WEIGHT,
    EnsemblePlayer,
    match_probability,
    run_simulations,
    simulate_match,
)


def _player(pid: str, serve_pct: float, return_pct: float, rating: float) -> EnsemblePlayer:
    return EnsemblePlayer(
        player_id=pid, full_name=pid, seed=None, serve_pct=serve_pct, return_pct=return_pct, rating=rating,
    )


def test_match_probability_is_the_weighted_blend():
    a = _player("a", serve_pct=0.68, return_pct=0.38, rating=1600)
    b = _player("b", serve_pct=0.60, return_pct=0.30, rating=1450)

    p_sr = serve_return.match_probability(a, b)
    p_elo = elo_model.match_probability_from_elo(a.rating, b.rating)
    expected = SERVE_RETURN_WEIGHT * p_sr + (1 - SERVE_RETURN_WEIGHT) * p_elo

    assert match_probability(a, b) == pytest.approx(expected)


def test_match_probability_weight_one_is_pure_serve_return():
    a = _player("a", serve_pct=0.68, return_pct=0.38, rating=1600)
    b = _player("b", serve_pct=0.60, return_pct=0.30, rating=1450)
    assert match_probability(a, b, weight=1.0) == pytest.approx(serve_return.match_probability(a, b))


def test_match_probability_weight_zero_is_pure_elo():
    a = _player("a", serve_pct=0.68, return_pct=0.38, rating=1600)
    b = _player("b", serve_pct=0.60, return_pct=0.30, rating=1450)
    assert match_probability(a, b, weight=0.0) == pytest.approx(
        elo_model.match_probability_from_elo(a.rating, b.rating)
    )


def test_simulate_match_favors_the_stronger_player():
    # Fuerte en ambos componentes -- si el blend estuviera mal (p.ej.
    # invertido) esto lo detectaría igual que si solo mirara un componente.
    strong = _player("strong", serve_pct=0.70, return_pct=0.40, rating=1700)
    weak = _player("weak", serve_pct=0.58, return_pct=0.26, rating=1400)
    rng = random.Random(5)
    n = 2000
    wins = sum(1 for _ in range(n) if simulate_match(rng, strong, weak) is strong)
    assert wins / n > match_probability(strong, weak) - 0.05


def test_run_simulations_champion_counts_sum_to_n():
    # N chico a propósito: `ensemble` hereda el costo de
    # `serve_return.match_probability` (~15 resoluciones de sistema lineal
    # por par, ver su docstring) -- el cache por par ya evita recalcular R128
    # una y otra vez, pero las rondas post-R128 generan pares NUEVOS en cada
    # simulación (los ganadores varían), así que el costo real crece con N.
    # Este test solo verifica un invariante de conteo, no una propiedad
    # estadística -- cualquier N >= 1 alcanza.
    draw = [_player(f"p{i}", 0.62 + 0.001 * i, 0.35, 1500 + 5 * i) for i in range(128)]
    n = 60
    counts = run_simulations(draw, n_simulations=n, seed=7)
    assert sum(c["CAMPEON"] for c in counts.values()) == n


def test_run_simulations_favors_stronger_player():
    draw = [_player(f"p{i}", 0.62, 0.35, 1500) for i in range(128)]
    draw[0] = _player("favorite", 0.75, 0.45, 1900)  # muy por encima del resto en ambos componentes
    n = 150
    counts = run_simulations(draw, n_simulations=n, seed=1)
    favorite_champion_rate = counts["favorite"]["CAMPEON"] / n
    others_avg = sum(counts[p.player_id]["CAMPEON"] for p in draw if p.player_id != "favorite") / n / 127
    assert favorite_champion_rate > others_avg * 5


def test_run_simulations_rejects_non_power_of_two_draw():
    draw = [_player(f"p{i}", 0.62, 0.35, 1500) for i in range(10)]
    with pytest.raises(ValueError):
        run_simulations(draw, n_simulations=10, seed=1)


# --- Integración con el bracket proyectado (pipeline.build_predicted_bracket) --


def test_pipeline_bracket_dispatches_to_ensemble():
    from src.cli.pipeline import build_predicted_bracket

    strong = _player("strong", serve_pct=0.72, return_pct=0.42, rating=1750)
    weak = _player("weak", serve_pct=0.58, return_pct=0.26, rating=1400)
    players_by_id = {"strong": strong, "weak": weak}

    rounds, champion = build_predicted_bracket(players_by_id, "ensemble")
    assert champion is strong
    assert rounds[0][0]["prob"] == pytest.approx(match_probability(strong, weak))

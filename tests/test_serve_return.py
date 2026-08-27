"""`models/serve_return.py`: réplica analítica EXACTA (DP, sin muestreo) del
motor en vivo post Fase B. Verificada contra miles de `simulate_match`
reales -- si esto falla, la DP se desincronizó de `monte_carlo.py`."""

from __future__ import annotations

import random

import pytest

from src.simulation.models.serve_return import match_probability, run_simulations_fast
from src.simulation.monte_carlo import Player, run_simulations, simulate_match


def _player(pid: str, serve: float, ret: float, avg_serve_pct: float = 0.62) -> Player:
    return Player(
        player_id=pid, full_name=pid, seed=None, serve_pct=serve, return_pct=ret,
        avg_serve_pct=avg_serve_pct,
    )


def test_symmetric_players_is_half():
    a = _player("a", 0.65, 0.35)
    b = _player("b", 0.65, 0.35)
    assert match_probability(a, b) == pytest.approx(0.5, abs=1e-6)


def test_better_server_favored():
    strong = _player("strong", 0.70, 0.40)
    weak = _player("weak", 0.60, 0.30)
    assert match_probability(strong, weak) > 0.5


def test_probability_is_valid():
    a = _player("a", 0.75, 0.20)
    b = _player("b", 0.55, 0.30)
    p = match_probability(a, b)
    assert 0.0 <= p <= 1.0


@pytest.mark.parametrize(
    "serve_a,return_a,serve_b,return_b",
    [
        (0.697, 0.409, 0.641, 0.356),  # favorito claro
        (0.65, 0.35, 0.64, 0.34),      # parejo
        (0.60, 0.30, 0.68, 0.42),      # el otro lado favorito
    ],
)
def test_matches_live_monte_carlo_estimate(serve_a, return_a, serve_b, return_b):
    a = _player("a", serve_a, return_a)
    b = _player("b", serve_b, return_b)
    analytic = match_probability(a, b)

    rng = random.Random(2026)
    n = 6000
    wins = sum(1 for _ in range(n) if simulate_match(rng, a, b) is a)
    empirical = wins / n

    se = (empirical * (1 - empirical) / n) ** 0.5
    assert abs(analytic - empirical) < 5 * se + 0.01


def test_extreme_probabilities_do_not_recurse_infinitely():
    """Regresión del bug real encontrado: con probabilidades de punto muy
    cercanas a 50/50, la región de deuce del tie-break es un ciclo, no un
    DAG -- la primera versión de `_tiebreak_win_prob` daba `RecursionError`.
    """
    a = _player("a", 0.6201, 0.3799)  # casi exactamente el promedio del tour
    b = _player("b", 0.6199, 0.3801)
    p = match_probability(a, b)
    assert 0.0 <= p <= 1.0
    assert p == pytest.approx(0.5, abs=0.05)


def test_fast_tournament_simulation_matches_real_engine():
    """`run_simulations_fast` (B10: un sorteo por partido vía probabilidad
    analítica) debe dar las mismas probabilidades de torneo, dentro del
    error de muestreo, que `run_simulations` (juego a juego, motor real).

    128 jugadores: `simulate_tournament`/`_fast` solo soportan cuadros de
    exactamente 128 (limitación documentada en `test_engine.py`)."""
    draw = [
        _player(f"p{i}", 0.55 + 0.001 * i, 0.30 + 0.0005 * i)
        for i in range(128)
    ]
    n = 3000
    real = run_simulations(draw, n_simulations=n, seed=11)
    fast = run_simulations_fast(draw, n_simulations=n, seed=11)

    for p in draw:
        p_real = real[p.player_id]["CAMPEON"] / n
        p_fast = fast[p.player_id]["CAMPEON"] / n
        se = (0.5 * 0.5 / n) ** 0.5  # cota conservadora
        assert abs(p_real - p_fast) < 6 * se + 0.02, p.player_id


def test_fast_tournament_simulation_champion_counts_sum_to_n():
    draw = [_player(f"p{i}", 0.62, 0.38) for i in range(128)]
    n = 300
    counts = run_simulations_fast(draw, n_simulations=n, seed=3)
    assert sum(c["CAMPEON"] for c in counts.values()) == n

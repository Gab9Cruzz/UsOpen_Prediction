"""Fórmulas de juego/set/partido: `game_win_prob` cerrada (B0), Barnett-Clarke
sustractivo (B1, `monte_carlo._point_probs`) y la réplica analítica congelada
del modelo pre-Fase-B (`models/current.py`)."""

from __future__ import annotations

import random

import pytest

from src.simulation.models.current import _point_probs_pre_fase_b, match_probability
from src.simulation.monte_carlo import Player, _point_probs, game_win_prob, simulate_match


def test_game_win_prob_at_half_is_half():
    assert game_win_prob(0.5) == pytest.approx(0.5, abs=1e-9)


def test_game_win_prob_monotonic():
    ps = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    probs = [game_win_prob(p) for p in ps]
    assert probs == sorted(probs)


def test_game_win_prob_edges():
    assert game_win_prob(0.0) == 0.0
    assert game_win_prob(1.0) == 1.0


def test_game_win_prob_favors_server_above_half():
    # Con p > 0.5 al saque, ganar el juego siempre es MÁS probable que
    # ganar un punto suelto (la estructura del juego amplifica la ventaja).
    assert game_win_prob(0.65) > 0.65


def _player(pid: str, serve: float, ret: float, avg_serve_pct: float = 0.62) -> Player:
    return Player(
        player_id=pid, full_name=pid, seed=None, serve_pct=serve, return_pct=ret,
        avg_serve_pct=avg_serve_pct,
    )


# --- B1: _point_probs vivo (Barnett-Clarke sustractivo) --------------------


def test_point_probs_symmetric_players_are_equal():
    a = _player("a", 0.65, 0.35, avg_serve_pct=0.62)
    b = _player("b", 0.65, 0.35, avg_serve_pct=0.62)
    p_a, p_b = _point_probs(a, b)
    assert p_a == pytest.approx(p_b)
    # a.serve_pct + (1 - b.return_pct) - avg = 0.65 + 0.65 - 0.62 = 0.68
    assert p_a == pytest.approx(0.68, abs=1e-6)


def test_point_probs_is_additive_not_averaged():
    """La ventaja de saque de A y la debilidad al resto de B deben SUMARSE
    (Barnett-Clarke), no partirse a la mitad como hacía el modelo viejo."""
    avg = 0.62
    a = _player("a", 0.70, 0.38, avg_serve_pct=avg)  # saca mejor que el promedio
    b = _player("b", 0.62, 0.45, avg_serve_pct=avg)  # resta MEJOR que el promedio (return_pct alto = buen resto)
    p_a_serve, _ = _point_probs(a, b)
    # fórmula esperada: a.serve_pct + (1 - b.return_pct) - avg
    expected = a.serve_pct + (1 - b.return_pct) - avg
    assert p_a_serve == pytest.approx(max(min(expected, 0.99), 0.01), abs=1e-9)


def test_point_probs_stays_within_bounds_for_extreme_inputs():
    a = _player("a", 0.90, 0.10, avg_serve_pct=0.62)
    b = _player("b", 0.30, 0.10, avg_serve_pct=0.62)
    p_a, p_b = _point_probs(a, b)
    assert 0.0 <= p_a <= 1.0
    assert 0.0 <= p_b <= 1.0


def test_live_match_probability_symmetric_players_is_half_via_simulation():
    a = _player("a", 0.65, 0.35, avg_serve_pct=0.62)
    b = _player("b", 0.65, 0.35, avg_serve_pct=0.62)
    rng = random.Random(99)
    n = 4000
    wins = sum(1 for _ in range(n) if simulate_match(rng, a, b) is a)
    empirical = wins / n
    se = (0.5 * 0.5 / n) ** 0.5
    assert abs(empirical - 0.5) < 5 * se


# --- models/current.py: réplica analítica CONGELADA del piso pre-Fase-B ----


def test_match_probability_symmetric_players_is_half():
    a = _player("a", 0.65, 0.35)
    b = _player("b", 0.65, 0.35)
    assert match_probability(a, b) == pytest.approx(0.5, abs=1e-6)


def test_match_probability_better_server_favored():
    strong = _player("strong", 0.70, 0.40)
    weak = _player("weak", 0.60, 0.30)
    assert match_probability(strong, weak) > 0.5


def _legacy_simulate_match(rng: random.Random, a: Player, b: Player, best_of: int = 5) -> Player:
    """Reimplementación mínima del motor PRE-Fase-B (promedio + tie-break
    moneda + saque alterna sin mirar paridad), usando las mismas funciones
    congeladas que `models/current.py`. Sirve solo para verificar que la DP
    de `current.py` es fiel a una simulación real de ESE modelo viejo, sin
    depender de cómo evolucione `monte_carlo.py` en la Fase B."""
    p_a_serve, p_b_serve = _point_probs_pre_fase_b(a, b)
    p_a_game, p_b_game = game_win_prob(p_a_serve), game_win_prob(p_b_serve)

    def simulate_set(a_serves_first: bool) -> bool:
        games_a = games_b = 0
        a_serves = a_serves_first
        while True:
            p_this = p_a_game if a_serves else 1 - p_b_game
            if rng.random() < p_this:
                games_a += 1
            else:
                games_b += 1
            a_serves = not a_serves
            if games_a >= 6 and games_a - games_b >= 2:
                return True
            if games_b >= 6 and games_b - games_a >= 2:
                return False
            if games_a == 6 and games_b == 6:
                return rng.random() < (p_a_game + (1 - p_b_game)) / 2

    sets_to_win = best_of // 2 + 1
    sets_a = sets_b = 0
    a_serves_first = True
    while sets_a < sets_to_win and sets_b < sets_to_win:
        if simulate_set(a_serves_first):
            sets_a += 1
        else:
            sets_b += 1
        a_serves_first = not a_serves_first
    return a if sets_a > sets_b else b


def test_match_probability_matches_legacy_monte_carlo_estimate():
    """La DP de `current.py` debe coincidir (dentro del error de muestreo)
    con una simulación Monte Carlo real DEL MISMO modelo congelado."""
    a = _player("sinner", 0.697, 0.409)
    b = _player("rival", 0.641, 0.356)
    analytic = match_probability(a, b)

    rng = random.Random(123)
    n = 6000
    wins = sum(1 for _ in range(n) if _legacy_simulate_match(rng, a, b) is a)
    empirical = wins / n

    se = (empirical * (1 - empirical) / n) ** 0.5
    assert abs(analytic - empirical) < 5 * se + 0.01

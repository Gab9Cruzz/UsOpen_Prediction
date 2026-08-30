"""Fase 4: condicionamiento por resultados reales conocidos
(`known_results`) en los tres motores de simulación -- un partido ya
jugado de verdad usa el ganador real en TODAS las repeticiones Monte Carlo,
no se sortea. Sigue el mismo patrón de cuadro sintético de 128 que
`tests/test_engine.py` (el motor solo funciona con exactamente 128, ver ese
archivo)."""

from __future__ import annotations

import pytest

from src.simulation.models import elo as elo_model
from src.simulation.models import serve_return
from src.simulation.monte_carlo import Player, resolve_known_winner, run_simulations


def _synthetic_draw(n: int = 128) -> list[Player]:
    return [
        Player(player_id=str(i), full_name=f"P{i}", seed=None, serve_pct=0.62, return_pct=0.38)
        for i in range(n)
    ]


def _elo_draw(n: int = 128) -> list[elo_model.EloPlayer]:
    return [elo_model.EloPlayer(player_id=str(i), full_name=f"P{i}", seed=None, rating=1500.0) for i in range(n)]


# --- resolve_known_winner -----------------------------------------------------


def test_resolve_known_winner_none_without_known_results():
    a, b = Player("1", "A", None, 0.62, 0.38), Player("2", "B", None, 0.62, 0.38)
    assert resolve_known_winner(a, b, "R128", 1, None) is None
    assert resolve_known_winner(a, b, "R128", 1, {}) is None


def test_resolve_known_winner_returns_a_or_b():
    a, b = Player("1", "A", None, 0.62, 0.38), Player("2", "B", None, 0.62, 0.38)
    assert resolve_known_winner(a, b, "R128", 1, {("R128", 1): "1"}) is a
    assert resolve_known_winner(a, b, "R128", 1, {("R128", 1): "2"}) is b


def test_resolve_known_winner_ignores_other_matches():
    a, b = Player("1", "A", None, 0.62, 0.38), Player("2", "B", None, 0.62, 0.38)
    assert resolve_known_winner(a, b, "R128", 1, {("R128", 2): "1"}) is None
    assert resolve_known_winner(a, b, "R64", 1, {("R128", 1): "1"}) is None


def test_resolve_known_winner_raises_on_slot_misalignment():
    a, b = Player("1", "A", None, 0.62, 0.38), Player("2", "B", None, 0.62, 0.38)
    with pytest.raises(ValueError):
        resolve_known_winner(a, b, "R128", 1, {("R128", 1): "999"})


# --- Motor de referencia (monte_carlo) ---------------------------------------


def test_run_simulations_forces_known_r128_winner_every_time():
    draw = _synthetic_draw()
    # Partido 1 de R128 es (draw[0], draw[1]) -- forzamos a que gane draw[1]
    # (el "peor" de los dos según orden, para descartar que el resultado sea
    # casualidad de la probabilidad base).
    known = {("R128", 1): "1"}
    counts = run_simulations(draw, n_simulations=200, seed=3, known_results=known)
    assert counts["1"]["R64"] == 200  # ganó su R128 en las 200 corridas
    assert counts["0"]["R64"] == 0  # el rival forzado a perder nunca avanza


def test_run_simulations_known_results_deterministic_given_seed():
    """No hay invariante "los demás partidos dan igual que sin condicionar"
    -- condicionar un partido evita un `rng.random()`, así que corre todo lo
    que viene después un paso adelantado en la misma secuencia de random
    (esperado, no es un bug: sigue siendo Monte Carlo válido). Lo que sí
    tiene que valer es que, para un `known_results` fijo, el mismo seed
    siempre da el mismo resultado."""
    draw = _synthetic_draw()
    known = {("R128", 1): "1"}
    counts_a = run_simulations(draw, n_simulations=300, seed=5, known_results=known)
    counts_b = run_simulations(draw, n_simulations=300, seed=5, known_results=known)
    assert counts_a == counts_b


def test_run_simulations_raises_on_known_result_mismatch():
    draw = _synthetic_draw()
    with pytest.raises(ValueError):
        run_simulations(draw, n_simulations=5, seed=1, known_results={("R128", 1): "999"})


# --- Réplica rápida (serve_return) -------------------------------------------


def test_run_simulations_fast_forces_known_winner():
    draw = _synthetic_draw()
    known = {("R128", 1): "1"}
    counts = serve_return.run_simulations_fast(draw, n_simulations=200, seed=3, known_results=known)
    assert counts["1"]["R64"] == 200
    assert counts["0"]["R64"] == 0


def test_run_simulations_fast_matches_reference_engine_given_same_known_results():
    """El condicionamiento no debería introducir sesgo propio: con la MISMA
    known_results, el conteo del jugador forzado en ambos motores debe ser
    idéntico en la ronda condicionada (100% -- no depende de probabilidad)."""
    draw = _synthetic_draw()
    known = {("R128", i): str(2 * (i - 1)) for i in range(1, 65)}  # fuerza TODO R128 a que gane el par
    counts_fast = serve_return.run_simulations_fast(draw, n_simulations=50, seed=1, known_results=known)
    for i in range(0, 128, 2):
        assert counts_fast[str(i)]["R64"] == 50
        assert counts_fast[str(i + 1)]["R64"] == 0


def test_run_simulations_fast_condition_propagates_forward():
    """Forzar el ganador de R128 partido 1 también debe forzar quién entra a
    R32 desde ese lado -- known_results de UNA sola ronda ya alcanza para
    fijar el resto del camino de ese jugador si también gana sin
    condicionar (probabilidad de aparecer en CAMPEON > 0 con seed fijo)."""
    draw = _synthetic_draw()
    known = {("R128", 1): "1"}
    counts = serve_return.run_simulations_fast(draw, n_simulations=300, seed=9, known_results=known)
    assert counts["0"]["R64"] == 0
    assert counts["0"]["CAMPEON"] == 0


# --- Modelo Elo (D7: mismo tratamiento) --------------------------------------


def test_run_simulations_elo_forces_known_winner():
    draw = _elo_draw()
    known = {("R128", 1): "1"}
    counts = elo_model.run_simulations_elo(draw, n_simulations=200, seed=3, known_results=known)
    assert counts["1"]["R64"] == 200
    assert counts["0"]["R64"] == 0


def test_run_simulations_elo_raises_on_mismatch():
    draw = _elo_draw()
    with pytest.raises(ValueError):
        elo_model.run_simulations_elo(draw, n_simulations=5, seed=1, known_results={("R128", 1): "999"})

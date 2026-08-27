"""Invariantes del motor de simulación: exactamente un campeón por corrida,
conteos no crecientes ronda a ronda, y el cuadro debe ser potencia de 2.

`simulate_tournament` recorre `ROUND_ORDER` completo (7 rondas, R64..CAMPEON)
sin importar el tamaño real del cuadro: solo funciona con exactamente 128
jugadores (2**7). Un cuadro de otro tamaño potencia de 2 (16, 32, 64...)
revienta con IndexError a mitad de camino -- confirmado por
`test_non_128_power_of_two_crashes` abajo. Es una limitación real del motor
(no estaba en el diagnóstico original del plan de mejora), pero no bloquea la
Fase A porque el cuadro del US Open siempre es de 128; queda anotada para
`TODOS.md`. Por eso el resto de los tests usa cuadros sintéticos de 128."""

from __future__ import annotations

import pytest

from src.simulation.monte_carlo import ROUND_ORDER, Player, run_simulations


def _synthetic_draw(n: int) -> list[Player]:
    return [
        Player(player_id=str(i), full_name=f"P{i}", seed=None, serve_pct=0.62, return_pct=0.38)
        for i in range(n)
    ]


def test_champion_counts_sum_to_n_simulations():
    draw = _synthetic_draw(128)
    n = 300
    counts = run_simulations(draw, n_simulations=n, seed=7)
    total_campeon = sum(c["CAMPEON"] for c in counts.values())
    assert total_campeon == n


def test_r128_count_equals_n_simulations_for_everyone():
    draw = _synthetic_draw(128)
    n = 200
    counts = run_simulations(draw, n_simulations=n, seed=1)
    for player_id in counts:
        assert counts[player_id]["R128"] == n


def test_counts_non_increasing_across_rounds():
    draw = _synthetic_draw(128)
    n = 200
    counts = run_simulations(draw, n_simulations=n, seed=2)
    for player_id, round_counts in counts.items():
        values = [round_counts[r] for r in ROUND_ORDER]
        assert all(values[i] >= values[i + 1] for i in range(len(values) - 1))


def test_rejects_non_power_of_two_draw():
    draw = _synthetic_draw(10)
    with pytest.raises(ValueError):
        run_simulations(draw, n_simulations=10, seed=1)


def test_deterministic_given_seed():
    draw = _synthetic_draw(128)
    counts_a = run_simulations(draw, n_simulations=150, seed=42)
    counts_b = run_simulations(draw, n_simulations=150, seed=42)
    assert counts_a == counts_b


def test_non_128_power_of_two_crashes():
    """Documenta la limitación descrita arriba: NO es un cuadro real del US
    Open (siempre 128), pero si algún día `run_simulations` empieza a
    aceptar otros tamaños silenciosamente (en vez de reventar), este test
    debe volver a mirarse -- hoy el contrato real es "128, no cualquier
    potencia de 2"."""
    draw = _synthetic_draw(16)
    with pytest.raises(IndexError):
        run_simulations(draw, n_simulations=5, seed=1)

"""Baselines contra los que se mide "modelo actual" y, después, la Fase B.

Tres, alineados con la Fase 1 (CEO review) del plan:
- `coin_flip`: piso absoluto, 50% siempre.
- `rank_favorite`: "predecir siempre al mejor ranking ATP" (sección 1 del
  plan) — una predicción dura (0/1), no una probabilidad calibrada; se
  recorta a [EPS, 1-EPS] solo para que el log-loss no sea infinito cuando se
  equivoca.
- `elo`: Elo de superficie dura (revisión CEO, sección 0D: "Elo tiene que ser
  baseline en la Fase A, no señal de la Fase C"). Usa `models/elo.py`.
"""

from __future__ import annotations

from src.validation.metrics import EPS

COIN_FLIP_PROB = 0.5


def coin_flip(*_args, **_kwargs) -> float:
    return COIN_FLIP_PROB


def rank_favorite(rank_a: float | None, rank_b: float | None) -> float:
    """P(a gana) = 1 si a tiene mejor (menor) ranking, 0 si b, 0.5 si faltan
    datos o están empatados. Recortado a [EPS, 1-EPS] (ver docstring del
    módulo)."""
    if rank_a is None or rank_b is None or rank_a == rank_b:
        return COIN_FLIP_PROB
    return (1 - EPS) if rank_a < rank_b else EPS


def elo(elo_a: float | None, elo_b: float | None) -> float:
    from src.simulation.models.elo import match_probability_from_elo, INITIAL_ELO

    return match_probability_from_elo(
        elo_a if elo_a is not None else INITIAL_ELO,
        elo_b if elo_b is not None else INITIAL_ELO,
    )

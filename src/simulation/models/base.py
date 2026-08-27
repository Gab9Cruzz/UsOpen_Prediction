"""Contrato común de los modelos de probabilidad de partido."""

from __future__ import annotations

from typing import Protocol

from src.simulation.monte_carlo import Player


class MatchModel(Protocol):
    """Cualquier modelo que sepa estimar P(a le gana a b)."""

    def match_probability(self, a: Player, b: Player) -> float:
        """Probabilidad de que `a` le gane a `b` (best-of-5, reglas US Open)."""
        ...

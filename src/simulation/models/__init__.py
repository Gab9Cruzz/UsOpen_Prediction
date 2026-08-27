"""Modelos de probabilidad de partido, intercambiables (plan sección 4).

Cada modelo implementa el `Protocol` de `base.py`: `match_probability(a, b)`
devuelve P(a le gana a b) de forma analítica (sin Monte Carlo), para que el
backtest (`src/validation/backtest.py`) pueda evaluar miles de partidos
históricos sin pagar el costo de simular cada uno cientos de veces.
"""

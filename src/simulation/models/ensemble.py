"""Ensamble Elo + saque/resto (Fase C, paso 12): blendea las probabilidades
de partido de ambos modelos con el peso medido y CONFIRMADO en
`src/validation/ensemble_search.py` (`sweep_weight` barrió w en [0,1] sobre
2010-2023 y el resultado -- 70% saque/resto + 30% Elo de superficie -- se
sostuvo sobre el holdout 2024-2025, nunca tocado durante la búsqueda; ver
README, sección "Limitaciones conocidas").

Se expone como `--model ensemble`, una opción NUEVA y separada de
`--model elo` -- `--model elo` sigue siendo
Elo "puro" tal cual se pidió explícitamente (una sola moneda por partido, sin
juegos/sets/tie-break, ver el docstring de `EloPlayer`); este módulo no lo
toca ni cambia su comportamiento.

Mismo criterio de "una moneda por partido" que `elo.py`: la moneda acá usa
la probabilidad YA blendeada, no se re-simula juego a juego -- mezclar dos
niveles de granularidad distintos (partido completo vs. punto a punto)
inventaría un modelo que `ensemble_search.py` nunca midió. El backtest que
valida el peso 0.7/0.3 blendea PROBABILIDADES de partido (`p_new`/`p_elo`),
no puntos.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from src.simulation.models import elo as elo_model
from src.simulation.models import serve_return
from src.simulation.monte_carlo import ROUND_ORDER, KnownResults, Player, resolve_known_winner

# Medido por `ensemble_search.sweep_weight(df, "p_new", "p_elo")` sobre
# 2010-2023, confirmado sobre el holdout 2024-2025 (ver README, sección
# "Limitaciones conocidas"). "p_new" ahí es la probabilidad del modelo de
# saque/resto -- de ahí el nombre de esta constante.
SERVE_RETURN_WEIGHT = 0.7


@dataclass
class EnsemblePlayer(Player):
    """`Player` (saque/resto: hereda `serve_pct`/`return_pct`/`avg_serve_pct`)
    + su rating Elo de superficie -- un solo objeto que alcanza para calcular
    AMBAS probabilidades del mismo jugador, sin duplicar los campos de saque/
    resto que ya tiene `Player`. Al heredar de `Player`, sirve tal cual como
    entrada de `serve_return.match_probability` -- ninguna conversión extra."""

    rating: float = elo_model.INITIAL_ELO


def match_probability(a: EnsemblePlayer, b: EnsemblePlayer, weight: float = SERVE_RETURN_WEIGHT) -> float:
    """P(a le gana a b): `weight` al modelo de saque/resto exacto
    (`serve_return.match_probability`, réplica analítica del motor punto a
    punto) + `1 - weight` al Elo de superficie."""
    p_sr = serve_return.match_probability(a, b)
    p_elo = elo_model.match_probability_from_elo(a.rating, b.rating)
    return weight * p_sr + (1 - weight) * p_elo


def simulate_match(
    rng: random.Random,
    a: EnsemblePlayer,
    b: EnsemblePlayer,
    weight: float = SERVE_RETURN_WEIGHT,
    cache: dict[tuple[str, str], float] | None = None,
) -> EnsemblePlayer:
    """Decide el partido completo con UNA moneda, igual que `elo.simulate_match_elo`
    -- pero la moneda usa la probabilidad blendeada de `match_probability`.

    `cache`: `match_probability` hereda el costo de `serve_return.match_probability`
    (~15 resoluciones de sistema lineal 12x12 por partido, ver su docstring)
    -- sin cachear por par de `player_id`, simular un cuadro de 128 miles de
    veces recalcula el mismo par una y otra vez (los 64 cruces de R128 son
    SIEMPRE los mismos en las N repeticiones) y la corrida completa tarda
    minutos en vez de segundos. Mismo criterio que
    `serve_return.simulate_tournament_fast`."""
    key = (a.player_id, b.player_id)
    if cache is not None and key in cache:
        p_a = cache[key]
    else:
        p_a = match_probability(a, b, weight)
        if cache is not None:
            cache[key] = p_a
    return a if rng.random() < p_a else b


def simulate_tournament(
    rng: random.Random,
    draw: list[EnsemblePlayer],
    known_results: KnownResults | None = None,
    weight: float = SERVE_RETURN_WEIGHT,
    cache: dict[tuple[str, str], float] | None = None,
) -> dict[str, str]:
    """Misma estructura ronda a ronda que `elo.simulate_tournament_elo`
    (incluido el condicionamiento por `known_results`, Fase 4/D7 -- paridad
    con los otros dos modelos), decidiendo cada cruce con `simulate_match`."""
    reached: dict[str, str] = {p.player_id: "R128" for p in draw}
    current_round = draw
    round_names = ROUND_ORDER[1:]
    played_rounds = ROUND_ORDER[:-1]

    for played_round, round_name in zip(played_rounds, round_names):
        winners: list[EnsemblePlayer] = []
        for i in range(0, len(current_round), 2):
            a, b = current_round[i], current_round[i + 1]
            match_index = i // 2 + 1
            winner = resolve_known_winner(a, b, played_round, match_index, known_results)
            if winner is None:
                winner = simulate_match(rng, a, b, weight, cache)
            reached[winner.player_id] = round_name
            winners.append(winner)
        current_round = winners

    assert len(current_round) == 1
    return reached


def run_simulations(
    draw: list[EnsemblePlayer],
    n_simulations: int,
    seed: int,
    known_results: KnownResults | None = None,
    weight: float = SERVE_RETURN_WEIGHT,
    cache: dict[tuple[str, str], float] | None = None,
) -> dict[str, dict[str, int]]:
    """Corre N simulaciones del torneo con el modelo ensamble y acumula,
    por jugador, cuántas veces alcanzó cada ronda. Misma firma/formato de
    salida que `elo.run_simulations_elo`/`serve_return.run_simulations_fast`
    -- intercambiable en la CLI (ver `src/cli/pipeline._run_engine`).

    `cache`: opcionalmente provisto por el caller para compartirlo ADEMÁS
    entre varias LLAMADAS (p.ej. los snapshots por ronda de una edición en
    vivo, ver `pipeline._generate_round_snapshots`); si no se pasa, se crea
    uno nuevo, compartido igual entre las N repeticiones de ESTA llamada
    (ver el docstring de `simulate_match` -- imprescindible para el
    rendimiento, no solo una optimización opcional)."""
    if len(draw) & (len(draw) - 1) != 0:
        raise ValueError(f"El cuadro debe tener una potencia de 2 de jugadores, recibió {len(draw)}")

    counts: dict[str, dict[str, int]] = {p.player_id: {r: 0 for r in ROUND_ORDER} for p in draw}
    rng = random.Random(seed)
    if cache is None:
        cache = {}

    for _ in range(n_simulations):
        reached = simulate_tournament(rng, draw, known_results=known_results, weight=weight, cache=cache)
        for player_id, round_name in reached.items():
            idx = ROUND_ORDER.index(round_name)
            for r in ROUND_ORDER[: idx + 1]:
                counts[player_id][r] += 1

    return counts

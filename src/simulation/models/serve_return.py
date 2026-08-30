"""Modelo por defecto (B-C ajustado por oponente): réplica analítica EXACTA
del motor que corre HOY en `monte_carlo.py` (post Fase B: B1 Barnett-Clarke +
B2 ajuste por oponente + B5 tie-break punto a punto + B7 rotación de saque
real + B8 tie-break a 10 en el decisivo).

B10 del plan de mejora (Fase D, "rendimiento"): `simulate_match` gasta
~100-200 sorteos de RNG por partido (juego a juego, punto a punto en el
tie-break) para terminar necesitando solo el ganador -- ni la CLI ni el
backtest muestran el marcador. Este módulo calcula la probabilidad EXACTA de
que gane cada jugador vía programación dinámica (cero muestreo) y permite
gastar UN solo sorteo por partido al simular un cuadro completo. Sigue
siendo Monte Carlo real a nivel de TORNEO -- quién gana cada partido, y por
lo tanto quién es campeón, se sigue sorteando en cada una de las N
simulaciones -- solo deja de simular la subestructura juego/set que nadie
lee.

A diferencia de `models/current.py` (que está CONGELADO al piso pre-Fase-B a
propósito), este módulo importa las funciones EN VIVO de `monte_carlo.py`:
tiene que seguir representando "el modelo que corre hoy", igual que
`_mc_match_probability` en el backtest.

Verificado contra el motor real en `tests/test_serve_return.py` (misma
técnica que `models/current.py`: comparar contra miles de `simulate_match`
reales, y contra `run_simulations` para las probabilidades de torneo).
"""

from __future__ import annotations

import random

import numpy as np

from src import config
from src.simulation.monte_carlo import (
    ROUND_ORDER,
    KnownResults,
    Player,
    _point_probs,
    game_win_prob,
    resolve_known_winner,
)

_DEUCE_STATES = [
    (diff, server_is_a, first_of_pair)
    for diff in (-1, 0, 1)
    for server_is_a in (True, False)
    for first_of_pair in (True, False)
]


def _solve_deuce_region(p_a_serve: float, p_b_serve: float) -> dict[tuple[int, bool, bool], float]:
    """P(A gana el tie-break | diferencia de puntos, quién saca, primer o
    segundo punto del par) UNA VEZ que ambos llegaron a `target-1` -- región
    de "deuce" del tie-break.

    Con probabilidades de punto parejas, esta región es un ciclo real (el
    marcador puede volver al mismo estado relativo una y otra vez, p.ej.
    +1 -> 0 -> +1 -> 0 ...), así que no es un DAG: no se puede resolver con
    recursión memoizada de arriba hacia abajo (se probó, daba
    `RecursionError` / recursión infinita). Se resuelve como sistema lineal
    (12 estados: diferencia en {-1,0,1} × quién saca × primer/segundo punto
    del par), igual en espíritu al cierre algebraico de `game_win_prob` para
    el deuce de un juego, adaptado al saque que se turna de a 2 puntos acá."""
    idx = {s: i for i, s in enumerate(_DEUCE_STATES)}
    n = len(_DEUCE_STATES)
    A = np.eye(n)
    b = np.zeros(n)
    for s in _DEUCE_STATES:
        diff, server_is_a, first_of_pair = s
        i = idx[s]
        p_a_wins_point = p_a_serve if server_is_a else 1 - p_b_serve
        next_server, next_first = (server_is_a, False) if first_of_pair else (not server_is_a, True)

        new_diff_a = diff + 1
        if new_diff_a == 2:
            b[i] += p_a_wins_point * 1.0
        else:
            A[i, idx[(new_diff_a, next_server, next_first)]] -= p_a_wins_point

        new_diff_b = diff - 1
        if new_diff_b != -2:
            A[i, idx[(new_diff_b, next_server, next_first)]] -= (1 - p_a_wins_point)
        # si new_diff_b == -2, B gana (aporta 0 a la ecuación de A, no suma nada a b[i])

    V = np.linalg.solve(A, b)
    return {_DEUCE_STATES[i]: float(V[i]) for i in range(n)}


def _tiebreak_win_prob(p_a_serve: float, p_b_serve: float, a_serves_first: bool, target: int) -> float:
    """P(A gana el tie-break) -- réplica de `_simulate_tiebreak`: recursión
    finita mientras el marcador está lejos de `target` (acotada, sin ciclos:
    la suma de puntos crece estrictamente), y lookup en la región de deuce
    ya resuelta algebraicamente (`_solve_deuce_region`) una vez que ambos
    llegan a `target - 1`.

    El saque se turna de a 2 (`first_of_pair`), salvo el primerísimo punto
    del breaker que lo sirve un solo jugador -- se resuelve aparte y se
    entra a la recursión general ya en modo "de a pares" desde el punto 2.
    """
    deuce = _solve_deuce_region(p_a_serve, p_b_serve)
    memo: dict[tuple[int, int, bool, bool], float] = {}

    def rec(pa: int, pb: int, server_is_a: bool, first_of_pair: bool) -> float:
        if pa >= target and pa - pb >= 2:
            return 1.0
        if pb >= target and pb - pa >= 2:
            return 0.0
        if pa >= target - 1 and pb >= target - 1:
            return deuce[(pa - pb, server_is_a, first_of_pair)]
        key = (pa, pb, server_is_a, first_of_pair)
        if key in memo:
            return memo[key]
        p_a_wins_point = p_a_serve if server_is_a else 1 - p_b_serve
        if first_of_pair:
            next_server, next_first = server_is_a, False
        else:
            next_server, next_first = (not server_is_a), True
        result = (
            p_a_wins_point * rec(pa + 1, pb, next_server, next_first)
            + (1 - p_a_wins_point) * rec(pa, pb + 1, next_server, next_first)
        )
        memo[key] = result
        return result

    p_first_wins = p_a_serve if a_serves_first else 1 - p_b_serve
    return (
        p_first_wins * rec(1, 0, not a_serves_first, True)
        + (1 - p_first_wins) * rec(0, 1, not a_serves_first, True)
    )


def _set_outcomes(
    p_a_game: float, p_b_game: float, p_a_serve: float, p_b_serve: float,
    a_serves_first: bool, tiebreak_target: int,
) -> dict[tuple[bool, bool], float]:
    """Distribución P(a_gano_el_set, quien_saca_primero_el_proximo_set) vía
    DP exacta -- réplica de `_simulate_set`, incluida la rotación real de
    saque (B7: el tie-break cuenta como un turno más, sin importar quién lo
    gana)."""
    memo: dict[tuple[int, int, bool], dict[tuple[bool, bool], float]] = {}

    def rec(ga: int, gb: int, a_serves: bool) -> dict[tuple[bool, bool], float]:
        if ga == 6 and gb == 6:
            p_tb = _tiebreak_win_prob(p_a_serve, p_b_serve, a_serves, tiebreak_target)
            next_server = not a_serves
            return {(True, next_server): p_tb, (False, next_server): 1 - p_tb}
        key = (ga, gb, a_serves)
        if key in memo:
            return memo[key]
        p_a_wins_game = p_a_game if a_serves else 1 - p_b_game
        result: dict[tuple[bool, bool], float] = {}
        for won_prob, new_ga, new_gb in ((p_a_wins_game, ga + 1, gb), (1 - p_a_wins_game, ga, gb + 1)):
            new_a_serves = not a_serves
            if new_ga >= 6 and new_ga - new_gb >= 2:
                outcomes = {(True, new_a_serves): 1.0}
            elif new_gb >= 6 and new_gb - new_ga >= 2:
                outcomes = {(False, new_a_serves): 1.0}
            else:
                outcomes = rec(new_ga, new_gb, new_a_serves)
            for k, v in outcomes.items():
                result[k] = result.get(k, 0.0) + won_prob * v
        memo[key] = result
        return result

    return rec(0, 0, a_serves_first)


def match_probability(a: Player, b: Player, best_of: int = config.BEST_OF) -> float:
    """P(a le gana a b), calculada exactamente como el límite de
    `simulate_match` (motor EN VIVO, post Fase B) con infinitas repeticiones."""
    p_a_serve, p_b_serve = _point_probs(a, b)
    p_a_game = game_win_prob(p_a_serve)
    p_b_game = game_win_prob(p_b_serve)
    sets_to_win = best_of // 2 + 1

    memo: dict[tuple[int, int, bool], float] = {}

    def rec(sets_a: int, sets_b: int, a_serves_first: bool) -> float:
        if sets_a == sets_to_win:
            return 1.0
        if sets_b == sets_to_win:
            return 0.0
        key = (sets_a, sets_b, a_serves_first)
        if key in memo:
            return memo[key]
        is_deciding_set = sets_a == sets_to_win - 1 and sets_b == sets_to_win - 1
        tb_target = config.DECIDING_SET_TIEBREAK_TARGET if is_deciding_set else 7
        outcomes = _set_outcomes(p_a_game, p_b_game, p_a_serve, p_b_serve, a_serves_first, tb_target)
        result = 0.0
        for (a_won, next_server_is_a), prob in outcomes.items():
            if a_won:
                result += prob * rec(sets_a + 1, sets_b, next_server_is_a)
            else:
                result += prob * rec(sets_a, sets_b + 1, next_server_is_a)
        memo[key] = result
        return result

    return rec(0, 0, True)


def simulate_tournament_fast(
    rng: random.Random,
    draw: list[Player],
    cache: dict[tuple[str, str], float] | None = None,
    known_results: KnownResults | None = None,
) -> dict[str, str]:
    """Réplica rápida de `monte_carlo.simulate_tournament`: en vez de
    simular cada partido juego a juego (~100-200 sorteos), calcula su
    probabilidad exacta vía `match_probability` y gasta un solo sorteo. El
    campeón, y cada ronda alcanzada, siguen siendo aleatorios -- lo que deja
    de simularse es el marcador interno de cada partido, que no se muestra.

    `cache`: opcionalmente compartido entre MUCHAS corridas de este torneo
    (`run_simulations_fast` pasa uno persistente) -- `match_probability` es
    determinística (mismos `Player`, mismo resultado) y los 64 cruces de
    R128 son SIEMPRE los mismos en las N repeticiones, así que cachear solo
    dentro de un torneo (que nunca repite un par) no ahorra nada; hay que
    cachear ENTRE torneos. Sin este cache, `match_probability` -- que hace
    ~15 resoluciones de sistema lineal 12x12 por partido -- se recalcula
    127 × N veces y la versión "rápida" queda más lenta que el motor real.

    `known_results` (Fase 4): ver `monte_carlo.simulate_tournament` -- misma
    convención de rondas "jugada" vs "alcanzada"."""
    if cache is None:
        cache = {}

    def p_a_wins(a: Player, b: Player) -> float:
        key = (a.player_id, b.player_id)
        if key not in cache:
            cache[key] = match_probability(a, b)
        return cache[key]

    reached: dict[str, str] = {p.player_id: "R128" for p in draw}
    current_round = draw
    round_names = ROUND_ORDER[1:]
    played_rounds = ROUND_ORDER[:-1]

    for played_round, round_name in zip(played_rounds, round_names):
        winners: list[Player] = []
        for i in range(0, len(current_round), 2):
            a, b = current_round[i], current_round[i + 1]
            match_index = i // 2 + 1
            winner = resolve_known_winner(a, b, played_round, match_index, known_results)
            if winner is None:
                winner = a if rng.random() < p_a_wins(a, b) else b
            reached[winner.player_id] = round_name
            winners.append(winner)
        current_round = winners

    assert len(current_round) == 1
    return reached


def run_simulations_fast(
    draw: list[Player],
    n_simulations: int = config.DEFAULT_SIMULATIONS,
    seed: int = config.DEFAULT_SEED,
    known_results: KnownResults | None = None,
    cache: dict[tuple[str, str], float] | None = None,
) -> dict[str, dict[str, int]]:
    """Réplica rápida de `monte_carlo.run_simulations` -- ver
    `simulate_tournament_fast`. Misma firma, mismo formato de salida.

    `cache`: opcionalmente provisto por el caller (Fase 4,
    `pipeline._generate_round_snapshots`) para compartirlo ADEMÁS entre
    varias LLAMADAS a esta función -- p.ej. las 7 rondas condicionadas de
    una edición en vivo son 7 torneos "distintos" (distinto `known_results`)
    mezclando en gran parte los MISMOS jugadores, así que sin compartir el
    cache entre llamadas se recalcula `match_probability` (~15 resoluciones
    de sistema lineal por par) una vez por ronda para los mismos pares. Si
    no se pasa, se crea uno nuevo (comportamiento de siempre, compartido
    solo dentro de las N repeticiones de ESTA llamada)."""
    if len(draw) & (len(draw) - 1) != 0:
        raise ValueError(f"El cuadro debe tener una potencia de 2 de jugadores, recibió {len(draw)}")

    counts: dict[str, dict[str, int]] = {p.player_id: {r: 0 for r in ROUND_ORDER} for p in draw}
    rng = random.Random(seed)
    if cache is None:
        cache = {}

    for _ in range(n_simulations):
        reached = simulate_tournament_fast(rng, draw, cache=cache, known_results=known_results)
        for player_id, round_name in reached.items():
            idx = ROUND_ORDER.index(round_name)
            for r in ROUND_ORDER[: idx + 1]:
                counts[player_id][r] += 1

    return counts

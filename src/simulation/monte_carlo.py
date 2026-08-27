"""Motor Monte Carlo de referencia -- simula juego a juego, set a set y
punto a punto en el tie-break (ver PLAN_MEJORA_SIMULACION.md para la
metodología completa y los números de calibración).

Modelo de probabilidad de punto: Barnett-Clarke sustractivo (B1) sobre
tasas de saque/resto ajustadas por la fuerza del calendario (B2,
`ingest._adjust_for_opponents`) y con decaimiento temporal (B9). Reglas
reales del US Open: tie-break punto a punto (B5), rotación de saque
continua entre sets (B7), tie-break a 10 en el set decisivo desde 2022 (B8).

Este módulo es la implementación "de referencia": la aleatoriedad entra en
cada juego/set/partido simulado, no en una probabilidad de partido
pre-calculada -- útil para verificar el modelo, pero cara (~100-200 sorteos
de RNG por partido). `models/serve_return.py` es una réplica analítica
EXACTA (programación dinámica, cero muestreo) del mismo modelo, verificada
contra este motor, y es la que usa la CLI por defecto para simular un
cuadro completo (B10, Fase D) -- un solo sorteo por partido en vez de ~150.

Nota: `simulate_tournament`/`run_simulations` (acá y en `serve_return.py`)
recorren siempre las 7 rondas de `ROUND_ORDER` sin mirar el tamaño real del
cuadro -- solo funcionan con exactamente 128 jugadores (ver
`tests/test_engine.py::test_non_128_power_of_two_crashes`). No es un
problema hoy porque el cuadro del US Open siempre es de 128.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from src import config


@dataclass
class Player:
    player_id: str
    full_name: str
    seed: float | None
    serve_pct: float
    return_pct: float
    # μ de Barnett-Clarke (B1): promedio CRUDO de saque del cohorte/superficie
    # al que pertenece este jugador (mismo valor para todo el cuadro de una
    # edición). Default = fallback histórico de saque en dura (repository.py
    # ya lo usaba como prior), para no romper código/tests que construyen
    # Player sin especificarlo.
    avg_serve_pct: float = 0.62


ROUND_ORDER = ["R128", "R64", "R32", "R16", "QF", "SF", "F", "CAMPEON"]


def game_win_prob(p: float) -> float:
    """P(ganar el juego) dado p = P(ganar un punto al saque). Fórmula cerrada estándar.

    Corrección B0 (PLAN_MEJORA_SIMULACION.md, Fase A): la versión anterior
    multiplicaba el término "gana 4-2" (10 p^4 q^2) por p_deuce en vez de
    sumar el término de deuce como un componente aparte. Faltaba
    directamente la probabilidad de llegar a deuce (3-3, 20 p^3 q^3) y
    ganarlo. Verificado: con esta fórmula game_win_prob(0.5) == 0.5 exacto
    (por simetría, tiene que darlo); la versión anterior daba 0.2656.
    """
    q = 1 - p
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    p_deuce = p * p / (p * p + q * q)
    return (
        p**4
        + 4 * p**4 * q
        + 10 * p**4 * q**2
        + 20 * p**3 * q**3 * p_deuce
    )


def _point_probs(a: Player, b: Player) -> tuple[float, float]:
    """P(A gana punto sirviendo), P(B gana punto sirviendo).

    B1 (PLAN_MEJORA_SIMULACION.md): fórmula de Barnett-Clarke, sustractiva en
    vez de promedio. Promediar `(serve + (1-return))/2` comprime cualquier
    ventaja combinada a la mitad (medido: 80.4% contra el 95.5% real en un
    caso de prueba) porque no hay ningún término que la conserve completa.
    Barnett-Clarke resta el promedio del tour (`AVG_SERVE_HARD`, acá
    `avg_serve_pct` de cada jugador) en vez de promediar, así la ventaja de
    A al saque y la debilidad de B al resto se SUMAN en vez de partirse al
    medio.

    Requiere que `serve_pct`/`return_pct` ya vengan ajustadas por oponente
    (B2, `ingest._adjust_for_opponents`): sin ese ajuste, esta fórmula
    sobrecorrige (medido: 100% contra un rival débil) porque la tasa cruda
    de saque ya viene inflada o deshinchada por la calidad del calendario.
    B1 y B2 se despliegan siempre juntos, nunca por separado (plan sección 3,
    riesgo confirmado).
    """
    avg_serve = (a.avg_serve_pct + b.avg_serve_pct) / 2
    p_a_serve = a.serve_pct + (1 - b.return_pct) - avg_serve
    p_b_serve = b.serve_pct + (1 - a.return_pct) - avg_serve
    p_a_serve = min(max(p_a_serve, 0.01), 0.99)
    p_b_serve = min(max(p_b_serve, 0.01), 0.99)
    return p_a_serve, p_b_serve


def _simulate_tiebreak(
    rng: random.Random, p_a_serve: float, p_b_serve: float, a_serves_first: bool, target: int = 7
) -> bool:
    """B5: tie-break simulado punto a punto (no una sola moneda con la
    probabilidad de JUEGO). `target`=7 en un set normal, =10 en el set
    decisivo del US Open desde 2022 (B8). El saque se turna: el primer
    servidor saca 1 punto, después cada jugador saca 2 seguidos."""
    points_a = points_b = 0
    server_is_a = a_serves_first
    played = 0
    while True:
        p_a_wins_point = p_a_serve if server_is_a else 1 - p_b_serve
        if rng.random() < p_a_wins_point:
            points_a += 1
        else:
            points_b += 1
        played += 1
        if points_a >= target and points_a - points_b >= 2:
            return True
        if points_b >= target and points_b - points_a >= 2:
            return False
        if played % 2 == 1:  # cambia de servidor después del punto 1, 3, 5, ...
            server_is_a = not server_is_a


def _simulate_set(
    rng: random.Random,
    p_a_serve: float, p_b_serve: float, p_a_game: float, p_b_game: float,
    a_serves_first: bool, tiebreak_target: int = 7,
) -> tuple[int, int, bool, bool]:
    """Simula un set (juego a juego). Devuelve (games_a, games_b, a_gano,
    next_server_is_a) -- B7: `next_server_is_a` es la continuación REAL de
    la rotación de saque (el jugador que sacó último en el set/tie-break no
    saca primero en el siguiente), no un volteo incondicional por set."""
    games_a = games_b = 0
    a_serves = a_serves_first
    while True:
        if games_a == 6 and games_b == 6:
            # B5: tie-break punto a punto, no una moneda con p de JUEGO.
            # El tie-break cuenta como un único "turno" más en la rotación
            # continua de saque (B7): un solo volteo, sin importar cuántos
            # puntos duró.
            a_wins_tb = _simulate_tiebreak(rng, p_a_serve, p_b_serve, a_serves, target=tiebreak_target)
            next_server_is_a = not a_serves
            if a_wins_tb:
                return 7, 6, True, next_server_is_a
            return 6, 7, False, next_server_is_a

        p_this_game_a_wins = p_a_game if a_serves else 1 - p_b_game
        if rng.random() < p_this_game_a_wins:
            games_a += 1
        else:
            games_b += 1
        a_serves = not a_serves

        if games_a >= 6 and games_a - games_b >= 2:
            return games_a, games_b, True, a_serves
        if games_b >= 6 and games_b - games_a >= 2:
            return games_a, games_b, False, a_serves


def simulate_match(rng: random.Random, a: Player, b: Player, best_of: int = config.BEST_OF) -> Player:
    """Simula un partido completo (best-of-`best_of` sets) y devuelve al ganador."""
    p_a_serve, p_b_serve = _point_probs(a, b)
    p_a_game = game_win_prob(p_a_serve)
    p_b_game = game_win_prob(p_b_serve)

    sets_to_win = best_of // 2 + 1
    sets_a = sets_b = 0
    a_serves_first = True
    while sets_a < sets_to_win and sets_b < sets_to_win:
        # B8: el set decisivo (todo lo demás definido, falta solo este) usa
        # tie-break a 10 en el US Open desde 2022, no a 7.
        is_deciding_set = sets_a == sets_to_win - 1 and sets_b == sets_to_win - 1
        tiebreak_target = config.DECIDING_SET_TIEBREAK_TARGET if is_deciding_set else 7
        _, _, a_won_set, a_serves_first = _simulate_set(
            rng, p_a_serve, p_b_serve, p_a_game, p_b_game, a_serves_first, tiebreak_target=tiebreak_target
        )
        if a_won_set:
            sets_a += 1
        else:
            sets_b += 1
        # B7: `a_serves_first` para el próximo set ya viene de la rotación
        # continua que devolvió `_simulate_set` -- no se vuelve a tocar acá.
    return a if sets_a > sets_b else b


def simulate_tournament(rng: random.Random, draw: list[Player]) -> dict[str, str]:
    """Simula un cuadro completo de eliminación directa.

    Devuelve {player_id: ronda_mas_lejana_alcanzada}.
    """
    reached: dict[str, str] = {p.player_id: "R128" for p in draw}
    current_round = draw
    # de R64 a CAMPEON: el último elemento simula la final y produce al campeón
    round_names = ROUND_ORDER[1:]

    for round_name in round_names:
        winners: list[Player] = []
        for i in range(0, len(current_round), 2):
            a, b = current_round[i], current_round[i + 1]
            winner = simulate_match(rng, a, b)
            reached[winner.player_id] = round_name
            winners.append(winner)
        current_round = winners

    assert len(current_round) == 1  # queda exactamente el campeón
    return reached


def run_simulations(
    draw: list[Player], n_simulations: int = config.DEFAULT_SIMULATIONS, seed: int = config.DEFAULT_SEED
) -> dict[str, dict[str, int]]:
    """Corre N simulaciones del torneo y acumula, por jugador, cuántas veces alcanzó cada ronda."""
    if len(draw) & (len(draw) - 1) != 0:
        raise ValueError(f"El cuadro debe tener una potencia de 2 de jugadores, recibió {len(draw)}")

    counts: dict[str, dict[str, int]] = {
        p.player_id: {r: 0 for r in ROUND_ORDER} for p in draw
    }
    rng = random.Random(seed)

    for _ in range(n_simulations):
        reached = simulate_tournament(rng, draw)
        max_idx = {}
        for player_id, round_name in reached.items():
            idx = ROUND_ORDER.index(round_name)
            max_idx[player_id] = idx
        for player_id, idx in max_idx.items():
            for r in ROUND_ORDER[: idx + 1]:
                counts[player_id][r] += 1

    return counts

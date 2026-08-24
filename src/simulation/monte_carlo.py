"""Motor Monte Carlo de Fase 1.

Modelo de probabilidad: baseline analítico basado en % de puntos ganados al
saque y al resto en la superficie (Hard), en la línea del "Elo Hard" que pide
la sección 8.1 del plan como benchmark inicial -- acá se usa serve/return %
en vez de Elo porque es lo que la Fase 1 calcula; Elo y ML llegan en las
Fases 5-6.

Cada partido se simula juego a juego y set a set (no punto a punto, por
costo computacional), usando la fórmula cerrada estándar de probabilidad de
ganar un juego de tenis dado un p de punto ganado al saque. Esto es Monte
Carlo real: la aleatoriedad entra en cada juego/set/partido simulado, no en
una probabilidad de partido pre-calculada.

Regla inmutable del plan (sección 9.3): el cuadro se actualiza ronda a ronda
y sólo avanzan jugadores activos; acá, con datos pre-torneo, todos los 128
del cuadro cargado son "activos" por definición (la Fase 3 introduce el
sistema de estados/retiros que puede vaciar un slot antes de simular).
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


ROUND_ORDER = ["R128", "R64", "R32", "R16", "QF", "SF", "F", "CAMPEON"]


def game_win_prob(p: float) -> float:
    """P(ganar el juego) dado p = P(ganar un punto al saque). Fórmula cerrada estándar."""
    q = 1 - p
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    p_deuce = p * p / (p * p + q * q)
    return (
        p**4
        + 4 * p**4 * q
        + 10 * p**4 * q**2 * p_deuce
    )


def _point_probs(a: Player, b: Player) -> tuple[float, float]:
    """P(A gana punto sirviendo), P(B gana punto sirviendo).

    Combina el saque de quien sirve con el resto de quien devuelve (mitad y
    mitad) porque ambas habilidades determinan el punto.
    """
    p_a_serve = (a.serve_pct + (1 - b.return_pct)) / 2
    p_b_serve = (b.serve_pct + (1 - a.return_pct)) / 2
    return p_a_serve, p_b_serve


def _simulate_set(rng: random.Random, p_a_game: float, p_b_game: float, a_serves_first: bool) -> tuple[int, int, bool]:
    """Simula un set (juego a juego). Devuelve (games_a, games_b, a_gano)."""
    games_a = games_b = 0
    a_serves = a_serves_first
    while True:
        p_this_game_a_wins = p_a_game if a_serves else 1 - p_b_game
        if rng.random() < p_this_game_a_wins:
            games_a += 1
        else:
            games_b += 1
        a_serves = not a_serves

        if games_a >= 6 and games_a - games_b >= 2:
            return games_a, games_b, True
        if games_b >= 6 and games_b - games_a >= 2:
            return games_a, games_b, False
        if games_a == 6 and games_b == 6:
            # tie-break: se aproxima con el promedio de ambos % de punto
            p_tb_a = (p_a_game + (1 - p_b_game)) / 2
            a_wins_tb = rng.random() < p_tb_a
            if a_wins_tb:
                return 7, 6, True
            return 6, 7, False


def simulate_match(rng: random.Random, a: Player, b: Player, best_of: int = config.BEST_OF) -> Player:
    """Simula un partido completo (best-of-`best_of` sets) y devuelve al ganador."""
    p_a_serve, p_b_serve = _point_probs(a, b)
    p_a_game = game_win_prob(p_a_serve)
    p_b_game = game_win_prob(p_b_serve)

    sets_to_win = best_of // 2 + 1
    sets_a = sets_b = 0
    a_serves_first = True
    while sets_a < sets_to_win and sets_b < sets_to_win:
        _, _, a_won_set = _simulate_set(rng, p_a_game, p_b_game, a_serves_first)
        if a_won_set:
            sets_a += 1
        else:
            sets_b += 1
        a_serves_first = not a_serves_first  # alterna quién saca primero en el próximo set
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

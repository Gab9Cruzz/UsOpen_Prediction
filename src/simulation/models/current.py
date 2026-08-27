"""Réplica analítica (sin Monte Carlo) del modelo que corre hoy en producción
(`src/simulation/monte_carlo.py`).

Por qué existe esto y no se llama directo a `simulate_match`: el backtest
(Fase A del plan de mejora) evalúa ~2.000 partidos históricos (2010-2025). Si
para cada uno estimáramos P(a le gana a b) corriendo `simulate_match` miles de
veces, el backtest sería lento y el propio muestreo agregaría ruido a la
métrica que se está midiendo. En cambio, este módulo calcula la MISMA
probabilidad que `simulate_match` produciría en el límite de infinitas
repeticiones, vía programación dinámica exacta sobre los estados de
juego/set/partido — cero aleatoriedad, mismo resultado esperado.

Deliberadamente reproduce los bugs conocidos del motor de ANTES de la Fase B
(B1 promedio en vez de Barnett-Clarke, B5 tie-break resuelto como una sola
moneda, B7 el saque alterna entre sets sin mirar la paridad de games): es el
piso registrado en PLAN_MEJORA_SIMULACION.md (Brier 0.2046 ± 0.0049,
2010-2025, tras arreglar B0) contra el que se mide cada paso de la Fase B.

CONGELADO A PROPÓSITO: `_point_probs` está copiada acá en vez de importada de
`monte_carlo.py`, porque la Fase B la reescribe (B1: Barnett-Clarke) — si
este archivo la importara en vivo, dejaría de representar el piso pre-Fase-B
y la comparación "antes vs. después" perdería sentido. `game_win_prob` sí se
importa: es la fórmula de juego ya corregida (B0) y no se espera que vuelva a
cambiar.
"""

from __future__ import annotations

from src import config
from src.simulation.monte_carlo import Player, game_win_prob


def _point_probs_pre_fase_b(a: Player, b: Player) -> tuple[float, float]:
    """Copia congelada de la fórmula de `_point_probs` previa a B1 (promedio,
    no Barnett-Clarke) — ver docstring del módulo."""
    p_a_serve = (a.serve_pct + (1 - b.return_pct)) / 2
    p_b_serve = (b.serve_pct + (1 - a.return_pct)) / 2
    return p_a_serve, p_b_serve


def _set_win_prob(p_a_game: float, p_b_game: float, a_serves_first: bool) -> float:
    """P(A gana el set) vía DP exacta sobre (games_a, games_b, quién saca).

    Réplica exacta de `_simulate_set`: mismas condiciones de corte (6 juegos
    con 2 de ventaja) y mismo tie-break "moneda con la probabilidad promedio
    de juego" en 6-6 (bug B5, preservado a propósito — ver docstring del
    módulo).
    """
    memo: dict[tuple[int, int, bool], float] = {}

    def rec(games_a: int, games_b: int, a_serves: bool) -> float:
        if games_a >= 6 and games_a - games_b >= 2:
            return 1.0
        if games_b >= 6 and games_b - games_a >= 2:
            return 0.0
        if games_a == 6 and games_b == 6:
            return (p_a_game + (1 - p_b_game)) / 2  # bug B5: tie-break ~ una moneda
        key = (games_a, games_b, a_serves)
        if key in memo:
            return memo[key]
        p_a_wins_this_game = p_a_game if a_serves else 1 - p_b_game
        result = (
            p_a_wins_this_game * rec(games_a + 1, games_b, not a_serves)
            + (1 - p_a_wins_this_game) * rec(games_a, games_b + 1, not a_serves)
        )
        memo[key] = result
        return result

    return rec(0, 0, a_serves_first)


def _match_win_prob(set_probs: list[float], sets_to_win: int) -> float:
    """P(A gana >= sets_to_win) vía DP sobre una secuencia de sets con
    probabilidad ya fija por posición (no dependen de resultados previos,
    porque el bug B7 hace que `a_serves_first` de cada set sea determinístico
    de antemano, no condicional al resultado del set anterior)."""
    memo: dict[tuple[int, int, int], float] = {}

    def rec(idx: int, sets_a: int, sets_b: int) -> float:
        if sets_a == sets_to_win:
            return 1.0
        if sets_b == sets_to_win:
            return 0.0
        key = (idx, sets_a, sets_b)
        if key in memo:
            return memo[key]
        p = set_probs[idx]
        result = p * rec(idx + 1, sets_a + 1, sets_b) + (1 - p) * rec(idx + 1, sets_a, sets_b + 1)
        memo[key] = result
        return result

    return rec(0, 0, 0)


def match_probability(a: Player, b: Player, best_of: int = config.BEST_OF) -> float:
    """P(a le gana a b), calculada exactamente como el límite de
    `simulate_match` con infinitas repeticiones (mismo modelo, mismos bugs
    conocidos B1/B5/B7 — ver docstring del módulo)."""
    p_a_serve, p_b_serve = _point_probs_pre_fase_b(a, b)
    p_a_game = game_win_prob(p_a_serve)
    p_b_game = game_win_prob(p_b_serve)

    sets_to_win = best_of // 2 + 1
    a_serves_first = True
    set_probs = []
    for _ in range(best_of):
        set_probs.append(_set_win_prob(p_a_game, p_b_game, a_serves_first))
        a_serves_first = not a_serves_first  # bug B7: alterna siempre, sin mirar paridad de games

    return _match_win_prob(set_probs, sets_to_win)

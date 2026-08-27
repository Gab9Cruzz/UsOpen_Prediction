"""Elo de superficie (dura), incremental y sin fugas de fecha.

Uso doble (revisión CEO del plan, sección 0D): sirve HOY como tercer baseline
del backtest de la Fase A (junto a ranking ATP y moneda), y es el mismo
código que la Fase C reusa para el ensamble Elo + saque/resto — no se
duplica lógica entre "Elo baseline" y "Elo señal".

Elo estándar (K fijo, sin ajustes de margen de victoria): se recorre el
historial en orden cronológico UNA sola vez y se toman "fotos" del rating de
cada jugador en cada fecha de corte pedida, de forma que evaluar N ediciones
de backtest sea O(partidos) y no O(ediciones × partidos).

Paso 11 de la Fase C (plan sección 5): "Elo de superficie, con ventana
temporal y decaimiento". Un Elo acumulado de toda la carrera nunca "olvida"
un pico de forma de hace 10 años. En vez de una ventana dura (que tira datos)
se usa decaimiento por inactividad: cada vez que se toca el rating de un
jugador, primero se lo acerca a la media según cuánto tiempo pasó desde su
último partido -- un jugador activo casi no decae entre partido y partido;
uno inactivo 2 años vuelve casi al promedio antes de que su próximo
resultado cuente. Esto da el efecto de "ventana temporal" (lo viejo pesa
poco) sin necesitar truncar el historial a mano.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from src.simulation.monte_carlo import ROUND_ORDER

INITIAL_ELO = 1500.0
K_FACTOR = 32.0
INACTIVITY_HALF_LIFE_DAYS = 365.0
ELO_WARMUP_YEARS = 5  # historia extra antes de la edición simulada, para que el Elo no arranque en frío -- mismo valor que usa el backtest (src/validation/backtest.py)


def _expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def _days_between(date_a: int, date_b: int) -> int:
    return abs((datetime.strptime(str(int(date_a)), "%Y%m%d") - datetime.strptime(str(int(date_b)), "%Y%m%d")).days)


def _decay_toward_mean(rating: float, days_inactive: int, half_life_days: float) -> float:
    factor = 0.5 ** (days_inactive / half_life_days)
    return INITIAL_ELO + (rating - INITIAL_ELO) * factor


def build_elo_snapshots(
    matches: pd.DataFrame,
    surface: str,
    cutoffs: list[int],
    half_life_days: float = INACTIVITY_HALF_LIFE_DAYS,
) -> dict[int, dict[str, float]]:
    """Recorre `matches` (filtrados a `surface`) en orden cronológico y
    devuelve, para cada fecha de corte en `cutoffs`, el diccionario
    {player_id: elo} calculado SOLO con partidos anteriores a esa fecha.

    Antes de aplicar cada partido, decae el rating de ambos jugadores hacia
    el promedio según los días transcurridos desde su partido anterior (ver
    docstring del módulo). El snapshot que se toma en cada `cutoff` TAMBIÉN
    decae los ratings de todos los jugadores tocados hasta ese punto según
    la inactividad acumulada hasta esa fecha -- si no, un jugador lesionado
    desde hace 8 meses conservaría intacto el rating de su último partido.

    Sin fuga: el snapshot de un `cutoff` se toma antes de aplicar cualquier
    partido con `tourney_date >= cutoff` (misma regla que
    `ingest._cutoff_date_for` / `compute_surface_metrics`).
    """
    df = matches[matches["surface"] == surface].dropna(subset=["winner_id", "loser_id", "tourney_date"])
    df = df.sort_values(["tourney_date", "match_num"], na_position="last")

    sorted_cutoffs = sorted(set(cutoffs))
    snapshots: dict[int, dict[str, float]] = {}
    ratings: dict[str, float] = {}
    last_played: dict[str, int] = {}
    next_cutoff_idx = 0

    def _snapshot_as_of(as_of_date: int) -> dict[str, float]:
        return {
            pid: _decay_toward_mean(r, _days_between(as_of_date, last_played[pid]), half_life_days)
            for pid, r in ratings.items()
        }

    for _, m in df.iterrows():
        date = int(m["tourney_date"])
        while next_cutoff_idx < len(sorted_cutoffs) and date >= sorted_cutoffs[next_cutoff_idx]:
            snapshots[sorted_cutoffs[next_cutoff_idx]] = _snapshot_as_of(sorted_cutoffs[next_cutoff_idx])
            next_cutoff_idx += 1

        w_id = str(int(m["winner_id"]))
        l_id = str(int(m["loser_id"]))
        r_w = _decay_toward_mean(ratings.get(w_id, INITIAL_ELO), _days_between(date, last_played.get(w_id, date)), half_life_days)
        r_l = _decay_toward_mean(ratings.get(l_id, INITIAL_ELO), _days_between(date, last_played.get(l_id, date)), half_life_days)
        exp_w = _expected_score(r_w, r_l)
        ratings[w_id] = r_w + K_FACTOR * (1 - exp_w)
        ratings[l_id] = r_l + K_FACTOR * (0 - (1 - exp_w))
        last_played[w_id] = date
        last_played[l_id] = date

    # cortes que caen después del último partido del dataset (o no se alcanzó
    # ningún partido con esa fecha exacta): se les da el estado final, decaído
    # hasta ESE corte.
    while next_cutoff_idx < len(sorted_cutoffs):
        snapshots[sorted_cutoffs[next_cutoff_idx]] = _snapshot_as_of(sorted_cutoffs[next_cutoff_idx])
        next_cutoff_idx += 1

    return snapshots


def match_probability_from_elo(rating_a: float, rating_b: float) -> float:
    """P(a le gana a b) según la fórmula Elo estándar."""
    return _expected_score(rating_a, rating_b)


@dataclass
class EloPlayer:
    """Jugador para el modelo `--model elo`: a diferencia de
    `monte_carlo.Player`, no carga serve_pct/return_pct -- el Elo decide el
    partido completo directamente (una sola moneda por partido, sin
    estructura juego/set), a pedido explícito: "usar el ranking Elo
    directamente para decidir quién gana el partido completo"."""

    player_id: str
    full_name: str
    seed: int | None
    rating: float


def simulate_match_elo(rng: random.Random, a: EloPlayer, b: EloPlayer) -> EloPlayer:
    """Decide el partido completo con UNA moneda: P(a gana) = Elo estándar
    entre `a.rating` y `b.rating`. Sin juegos, sin sets, sin tie-break --
    el ranking Elo decide directamente, tal como se pidió."""
    p_a = match_probability_from_elo(a.rating, b.rating)
    return a if rng.random() < p_a else b


def simulate_tournament_elo(rng: random.Random, draw: list[EloPlayer]) -> dict[str, str]:
    """Simula un cuadro completo de eliminación directa usando SOLO Elo
    (`simulate_match_elo`) para decidir cada partido -- misma estructura de
    ronda a ronda que `monte_carlo.simulate_tournament`."""
    reached: dict[str, str] = {p.player_id: "R128" for p in draw}
    current_round = draw
    round_names = ROUND_ORDER[1:]

    for round_name in round_names:
        winners: list[EloPlayer] = []
        for i in range(0, len(current_round), 2):
            a, b = current_round[i], current_round[i + 1]
            winner = simulate_match_elo(rng, a, b)
            reached[winner.player_id] = round_name
            winners.append(winner)
        current_round = winners

    assert len(current_round) == 1
    return reached


def run_simulations_elo(
    draw: list[EloPlayer], n_simulations: int, seed: int
) -> dict[str, dict[str, int]]:
    """Corre N simulaciones del torneo usando el modelo Elo directo (ver
    `simulate_tournament_elo`) y acumula, por jugador, cuántas veces alcanzó
    cada ronda. Misma firma/formato de salida que `monte_carlo.run_simulations`
    y `serve_return.run_simulations_fast` -- intercambiable en la CLI."""
    if len(draw) & (len(draw) - 1) != 0:
        raise ValueError(f"El cuadro debe tener una potencia de 2 de jugadores, recibió {len(draw)}")

    counts: dict[str, dict[str, int]] = {p.player_id: {r: 0 for r in ROUND_ORDER} for p in draw}
    rng = random.Random(seed)

    for _ in range(n_simulations):
        reached = simulate_tournament_elo(rng, draw)
        for player_id, round_name in reached.items():
            idx = ROUND_ORDER.index(round_name)
            for r in ROUND_ORDER[: idx + 1]:
                counts[player_id][r] += 1

    return counts

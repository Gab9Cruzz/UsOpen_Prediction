"""Brier score, log-loss, ECE e intervalos de confianza.

Convención de orientación (importa para que la calibración no sea trivial):
para cada partido se evalúa `p = P(player1 gana)` y `y = 1 si player1 ganó
de verdad, si no 0`, donde `player1`/`player2` son una asignación FIJA y
arbitraria (en `backtest.py`, el jugador con `player_id` menor). Si en cambio
siempre evaluáramos "P(el que ganó, gane)", `y` sería 1 en el 100% de los
casos y la curva de calibración (ECE) sería inútil por construcción — todo
bin mostraría 100% de aciertos sin importar la probabilidad predicha.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EPS = 1e-6  # evita log(0) en el log-loss cuando el modelo dice 0% o 100%


def brier_values(probs: list[float], outcomes: list[int]) -> list[float]:
    return [(p - y) ** 2 for p, y in zip(probs, outcomes)]


def brier_score(probs: list[float], outcomes: list[int]) -> float:
    if not probs:
        raise ValueError("No hay partidos para evaluar")
    return sum(brier_values(probs, outcomes)) / len(probs)


def log_loss_values(probs: list[float], outcomes: list[int]) -> list[float]:
    values = []
    for p, y in zip(probs, outcomes):
        p_clipped = min(max(p, EPS), 1 - EPS)
        values.append(-(y * math.log(p_clipped) + (1 - y) * math.log(1 - p_clipped)))
    return values


def log_loss(probs: list[float], outcomes: list[int]) -> float:
    if not probs:
        raise ValueError("No hay partidos para evaluar")
    values = log_loss_values(probs, outcomes)
    return sum(values) / len(values)


@dataclass
class CalibrationBin:
    p_min: float
    p_max: float
    n: int
    mean_predicted: float | None
    actual_rate: float | None


def calibration_curve(probs: list[float], outcomes: list[int], n_bins: int = 10) -> list[CalibrationBin]:
    bins: list[CalibrationBin] = []
    for i in range(n_bins):
        p_min, p_max = i / n_bins, (i + 1) / n_bins
        idx = [
            j for j, p in enumerate(probs)
            if (p_min <= p < p_max) or (i == n_bins - 1 and p == p_max)
        ]
        if not idx:
            bins.append(CalibrationBin(p_min, p_max, 0, None, None))
            continue
        mean_pred = sum(probs[j] for j in idx) / len(idx)
        actual = sum(outcomes[j] for j in idx) / len(idx)
        bins.append(CalibrationBin(p_min, p_max, len(idx), mean_pred, actual))
    return bins


def expected_calibration_error(probs: list[float], outcomes: list[int], n_bins: int = 10) -> float:
    """ECE: promedio ponderado (por cantidad de partidos en cada bin) de
    |probabilidad predicha - tasa real de victorias| en ese bin."""
    bins = calibration_curve(probs, outcomes, n_bins)
    n_total = sum(b.n for b in bins)
    if n_total == 0:
        raise ValueError("No hay partidos para evaluar")
    return sum(
        b.n * abs(b.mean_predicted - b.actual_rate) for b in bins if b.n > 0
    ) / n_total


def mean_with_ci(values: list[float], confidence: float = 0.95) -> tuple[float, float]:
    """(media, semi-ancho del IC) vía aproximación normal sobre la muestra de
    valores por partido (Brier/log-loss individuales). Con pocas ediciones el
    supuesto de independencia es aproximado -- por eso el plan pide reportar
    el intervalo en vez de un número pelado, no que se lo tome como exacto."""
    n = len(values)
    if n == 0:
        raise ValueError("No hay valores para promediar")
    mean = sum(values) / n
    if n == 1:
        return mean, float("nan")
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    se = math.sqrt(variance / n)
    z = 1.96 if abs(confidence - 0.95) < 1e-9 else _z_for(confidence)
    return mean, z * se


def _z_for(confidence: float) -> float:
    # Aproximación suficiente para los niveles de confianza que usa el proyecto.
    table = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}
    closest = min(table, key=lambda c: abs(c - confidence))
    return table[closest]

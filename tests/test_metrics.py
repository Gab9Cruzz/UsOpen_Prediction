"""Sanity checks de las métricas del backtest (`src/validation/metrics.py`):
si estas fórmulas están mal, todo lo que mide el plan de mejora está mal."""

from __future__ import annotations

import math

import pytest

from src.validation.metrics import (
    brier_score,
    expected_calibration_error,
    log_loss,
    mean_with_ci,
)


def test_brier_score_of_perfect_predictions_is_zero():
    assert brier_score([1.0, 0.0, 1.0], [1, 0, 1]) == pytest.approx(0.0)


def test_brier_score_of_coin_flip_is_quarter():
    # (0.5-1)^2 y (0.5-0)^2 valen 0.25 cada uno, sin importar el resultado.
    assert brier_score([0.5, 0.5, 0.5, 0.5], [1, 0, 1, 0]) == pytest.approx(0.25)


def test_brier_score_worst_case_is_one():
    assert brier_score([0.0, 1.0], [1, 0]) == pytest.approx(1.0)


def test_log_loss_of_confident_correct_prediction_is_near_zero():
    assert log_loss([0.999999], [1]) < 0.001


def test_log_loss_of_coin_flip_is_ln2():
    assert log_loss([0.5, 0.5], [1, 0]) == pytest.approx(math.log(2), abs=1e-6)


def test_log_loss_does_not_blow_up_on_zero_or_one():
    # Sin el recorte a [EPS, 1-EPS] esto sería log(0) = -inf.
    assert math.isfinite(log_loss([1.0], [0]))
    assert math.isfinite(log_loss([0.0], [1]))


def test_ece_of_perfectly_calibrated_predictions_is_near_zero():
    # 100 partidos a 70%, donde exactamente el 70% gana: calibración perfecta.
    probs = [0.7] * 100
    outcomes = [1] * 70 + [0] * 30
    assert expected_calibration_error(probs, outcomes, n_bins=10) < 0.02


def test_ece_of_badly_calibrated_predictions_is_high():
    # Predice 90% pero solo gana el 50%: mal calibrado.
    probs = [0.9] * 100
    outcomes = [1] * 50 + [0] * 50
    assert expected_calibration_error(probs, outcomes, n_bins=10) > 0.3


def test_mean_with_ci_shrinks_with_more_samples():
    values_small = [0.1, 0.3, 0.2, 0.4, 0.15]
    values_large = values_small * 20  # misma distribución, 20x más muestras
    _, ci_small = mean_with_ci(values_small)
    _, ci_large = mean_with_ci(values_large)
    assert ci_large < ci_small

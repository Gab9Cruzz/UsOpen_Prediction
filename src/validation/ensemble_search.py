"""Fase C del plan de mejora: ensamble Elo + saque/resto (paso 12) y señales
nuevas — head-to-head y fatiga (paso 13).

Metodología (revisión CEO, sección 0D, riesgo F3): el peso del ensamble y
cualquier señal nueva se ELIGEN mirando solo 2010-2023 (`TRAIN_END_YEAR`) y
se CONFIRMAN sobre 2024-2025 como holdout nunca tocado durante la búsqueda.
Elegir con una mano y medir con la misma es la forma más común de creer que
algo mejora cuando en realidad es sobreajuste al propio backtest.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from src import config
from src.data import ingest
from src.simulation.models import elo as elo_model
from src.validation import baselines, metrics
from src.validation.backtest import (
    ELO_WARMUP_YEARS,
    MC_REPS_PER_MATCH,
    _edition_matches,
    _ensure_cached,
    _make_player,
    _metrics_window,
    _mc_match_probability,
    _player_lookup,
    _years_needed,
)

logger = logging.getLogger(__name__)

TRAIN_END_YEAR = 2023  # inclusive -- todo lo de 2024 en adelante es holdout
H2H_PRIOR = 1.0  # "puntos virtuales" de shrinkage hacia 50/50 para el h2h (pocos jugadores se cruzan más de 2-3 veces)
FATIGUE_WINDOW_DAYS = 14


def _yyyymmdd_minus_days(date_int: int, days: int) -> int:
    d = datetime.strptime(str(int(date_int)), "%Y%m%d") - timedelta(days=days)
    return int(d.strftime("%Y%m%d"))


def _h2h_wins_table(window: pd.DataFrame) -> dict[tuple[str, str], int]:
    """(winner_id, loser_id) -> cantidad de veces que winner le ganó a loser
    en `window` (todas las superficies -- una rivalidad no es solo en dura)."""
    counts = window.groupby(["winner_id", "loser_id"]).size()
    return {(str(int(w)), str(int(l))): int(n) for (w, l), n in counts.items()}


def _fatigue_counts(window: pd.DataFrame, cutoff: int, days: int = FATIGUE_WINDOW_DAYS) -> dict[str, int]:
    """partidos jugados por cada jugador en los `days` días antes del corte
    (carga de trabajo pre-torneo, todas las superficies)."""
    start = _yyyymmdd_minus_days(cutoff, days)
    recent = window[(window["tourney_date"] >= start) & (window["tourney_date"] < cutoff)]
    counts: dict[str, int] = {}
    for col in ("winner_id", "loser_id"):
        for pid in recent[col].dropna().astype(int).astype(str):
            counts[pid] = counts.get(pid, 0) + 1
    return counts


def _h2h_prob(wins_p1: int, wins_p2: int) -> float:
    total = wins_p1 + wins_p2
    if total == 0:
        return 0.5
    return (wins_p1 + H2H_PRIOR) / (total + 2 * H2H_PRIOR)


def collect_match_predictions(
    start_year: int,
    end_year: int,
    tournament_name: str = config.TOURNAMENT_NAME,
    surface: str = config.SURFACE,
    years_back: int = config.YEARS_BACK,
    mc_reps_per_match: int = MC_REPS_PER_MATCH,
    seed: int = config.DEFAULT_SEED,
) -> pd.DataFrame:
    """Una fila por partido histórico evaluado, con las probabilidades de
    cada componente (modelo nuevo, Elo, h2h) y las señales crudas de fatiga
    -- para poder probar combinaciones sin re-correr la parte cara
    (`simulate_match` x `mc_reps_per_match`) por cada experimento."""
    edition_years = list(range(start_year, end_year + 1))
    years = _years_needed(start_year, end_year, years_back, ELO_WARMUP_YEARS)
    _ensure_cached(years)
    all_matches = ingest.load_matches_for_years(years)
    # h2h/fatiga: TODAS las superficies, no solo Hard -- se recorta a `years`
    # (mismo rango ya descargado) para no pagar otra descarga.
    all_matches_all_surfaces = all_matches  # ya sin filtrar por superficie acá

    cutoffs = {y: ingest.cutoff_date_for(tournament_name, y, all_matches) for y in edition_years}
    elo_snapshots = elo_model.build_elo_snapshots(all_matches, surface, list(cutoffs.values()))
    rng = random.Random(seed)

    rows: list[dict] = []

    for year in edition_years:
        cutoff = cutoffs[year]
        edition_matches = _edition_matches(all_matches, tournament_name, year)
        if edition_matches.empty:
            continue

        window = _metrics_window(all_matches, year, years_back)
        surface_metrics = ingest.compute_surface_metrics(window, surface, cutoff)
        lookup_adj, prior_serve_adj, prior_return_adj = _player_lookup(surface_metrics, adjusted=True)
        avg_serve_hard = surface_metrics.attrs.get("avg_serve_hard", prior_serve_adj)
        elo_ratings = elo_snapshots.get(cutoff, {})

        h2h_before_cutoff = all_matches_all_surfaces[all_matches_all_surfaces["tourney_date"] < cutoff]
        h2h_table = _h2h_wins_table(h2h_before_cutoff)
        fatigue = _fatigue_counts(all_matches_all_surfaces, cutoff)

        for _, m in edition_matches.iterrows():
            winner_id, loser_id = str(int(m["winner_id"])), str(int(m["loser_id"]))
            p1_id, p2_id = sorted((winner_id, loser_id), key=int)
            y = 1 if p1_id == winner_id else 0

            player1 = _make_player(p1_id, lookup_adj, prior_serve_adj, prior_return_adj, avg_serve_pct=avg_serve_hard)
            player2 = _make_player(p2_id, lookup_adj, prior_serve_adj, prior_return_adj, avg_serve_pct=avg_serve_hard)
            p_new = _mc_match_probability(rng, player1, player2, n_reps=mc_reps_per_match)
            p_elo = baselines.elo(elo_ratings.get(p1_id), elo_ratings.get(p2_id))

            wins_p1 = h2h_table.get((p1_id, p2_id), 0)
            wins_p2 = h2h_table.get((p2_id, p1_id), 0)
            p_h2h = _h2h_prob(wins_p1, wins_p2)

            rows.append(
                {
                    "year": year, "p1_id": p1_id, "p2_id": p2_id, "y": y,
                    "p_new": p_new, "p_elo": p_elo, "p_h2h": p_h2h,
                    "h2h_meetings": wins_p1 + wins_p2,
                    "fatigue_p1": fatigue.get(p1_id, 0), "fatigue_p2": fatigue.get(p2_id, 0),
                }
            )

    return pd.DataFrame(rows)


def _brier(df: pd.DataFrame, probs: pd.Series) -> float:
    return metrics.brier_score(list(probs), list(df["y"]))


def sweep_weight(df: pd.DataFrame, col_a: str, col_b: str, steps: int = 21) -> tuple[float, float]:
    """Barre w en [0,1] para p = w*col_a + (1-w)*col_b, devuelve (mejor w,
    mejor Brier) sobre `df` (se llama SOLO con datos de train)."""
    best_w, best_brier = 0.0, float("inf")
    for i in range(steps):
        w = i / (steps - 1)
        p = w * df[col_a] + (1 - w) * df[col_b]
        b = _brier(df, p)
        if b < best_brier:
            best_w, best_brier = w, b
    return best_w, best_brier


@dataclass
class HoldoutResult:
    label: str
    train_brier: float
    holdout_brier: float
    holdout_brier_ci: float
    holdout_log_loss: float
    holdout_log_loss_ci: float


def evaluate(df: pd.DataFrame, probs_col_expr, label: str, train_end_year: int = TRAIN_END_YEAR) -> HoldoutResult:
    """`probs_col_expr`: función df -> Series de probabilidades."""
    train = df[df["year"] <= train_end_year]
    holdout = df[df["year"] > train_end_year]
    p_train = probs_col_expr(train)
    p_holdout = probs_col_expr(holdout)
    brier_mean, brier_ci = metrics.mean_with_ci(metrics.brier_values(list(p_holdout), list(holdout["y"])))
    logloss_mean, logloss_ci = metrics.mean_with_ci(metrics.log_loss_values(list(p_holdout), list(holdout["y"])))
    return HoldoutResult(
        label=label,
        train_brier=_brier(train, p_train),
        holdout_brier=brier_mean,
        holdout_brier_ci=brier_ci,
        holdout_log_loss=logloss_mean,
        holdout_log_loss_ci=logloss_ci,
    )

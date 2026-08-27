"""Backtest multi-año (Fase A del plan de mejora).

Evalúa el modelo actual y los baselines (moneda, ranking ATP, Elo de
superficie) contra partidos YA JUGADOS del US Open, con corte temporal
estricto por edición (nunca se usa nada de la propia edición evaluada, ni de
ediciones posteriores, para calcular las métricas de entrada).

Ventana por defecto 2010-2025 (16 ediciones, ~2.000 partidos) — no 2022-2025
(4 ediciones, 508 partidos) como decía la versión original del plan: medido
en la revisión CEO (sección 0D), con 508 partidos el IC95% del Brier es
±0.038, que entierra cualquier mejora real de 0.01. Ampliar la ventana es
casi gratis (`run_ingest` ya está parametrizado por año) y es lo que hace que
el backtest distinga señal de ruido.
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field

import pandas as pd

from src import config
from src.data import fetchers, ingest
from src.simulation import monte_carlo
from src.simulation.models import current as current_model
from src.simulation.models import elo as elo_model
from src.simulation.monte_carlo import Player
from src.validation import baselines, metrics

logger = logging.getLogger(__name__)

EVALUATED_ROUNDS = ["R128", "R64", "R32", "R16", "QF", "SF", "F"]
ELO_WARMUP_YEARS = elo_model.ELO_WARMUP_YEARS  # fuente única: src/simulation/models/elo.py (también la usa `--model elo` en la CLI)
MODEL_NAMES = ["modelo_actual", "modelo_nuevo", "ranking_atp", "elo_hard", "moneda"]
MC_REPS_PER_MATCH = 2000  # repeticiones de simulate_match por partido histórico, para estimar P(a le gana a b) del modelo nuevo (post B1+B2+B5+B7+B8+B9)
# "modelo_actual" (models/current.py) está CONGELADO a propósito: tiene que
# seguir midiendo lo mismo (Brier 0.2046, el piso ya registrado en el plan)
# sin importar qué le agreguemos a `compute_surface_metrics` después (B9
# decay lo cambiaría de otro modo, porque comparte el mismo pipeline de
# datos). Vida media gigante = sin decaimiento, réplica exacta del cálculo
# crudo de la Fase A.
NO_DECAY_HALF_LIFE = 1e9


@dataclass
class ModelResult:
    name: str
    n_matches: int
    brier: float
    brier_ci: float
    log_loss: float
    log_loss_ci: float
    ece: float
    by_year_brier: dict[int, float] = field(default_factory=dict)


@dataclass
class BacktestReport:
    start_year: int
    end_year: int
    n_editions: int
    tournament_name: str
    surface: str
    models: dict[str, ModelResult]
    champion_log_loss: dict[str, tuple[float, float]] = field(default_factory=dict)  # nombre -> (media, ci)


def _years_needed(start_year: int, end_year: int, years_back: int, extra_warmup: int) -> list[int]:
    first = start_year - years_back + 1 - extra_warmup
    return list(range(first, end_year + 1))


def _ensure_cached(years: list[int]) -> None:
    missing = [y for y in years if not (config.DATA_RAW_DIR / config.MATCHES_FILE_TEMPLATE.format(year=y)).exists()]
    if missing:
        logger.info("Descargando %d año(s) faltante(s) para el backtest: %s", len(missing), missing)
        fetchers.fetch_matches(missing)
    fetchers.fetch_players()


def _player_lookup(
    metrics_df: pd.DataFrame, adjusted: bool
) -> tuple[dict[str, tuple[float, float]], float, float]:
    """player_id -> (serve_pct, return_pct) de esa edición (cruda o ajustada
    por B2 según `adjusted`), más el prior de cohorte (promedio, en la MISMA
    escala) para jugadores del cuadro sin métricas -- misma regla de
    fallback que `repository.load_draw` (plan sección 4.10/4.11)."""
    if metrics_df.empty:
        return {}, 0.62, 0.38
    serve_col = "serve_pct_adj" if adjusted else "serve_pct"
    return_col = "return_pct_adj" if adjusted else "return_pct"
    lookup = {
        row["player_id"]: (row[serve_col], row[return_col]) for _, row in metrics_df.iterrows()
    }
    prior_serve = metrics_df[serve_col].mean()
    prior_return = metrics_df[return_col].mean()
    return lookup, prior_serve, prior_return


def _make_player(
    player_id: str, lookup: dict, prior_serve: float, prior_return: float, avg_serve_pct: float = 0.62
) -> Player:
    serve_pct, return_pct = lookup.get(player_id, (prior_serve, prior_return))
    return Player(
        player_id=player_id, full_name=player_id, seed=None,
        serve_pct=serve_pct, return_pct=return_pct, avg_serve_pct=avg_serve_pct,
    )


def _mc_match_probability(rng: random.Random, a: Player, b: Player, n_reps: int = MC_REPS_PER_MATCH) -> float:
    """P(a le gana a b) estimada corriendo `simulate_match` (el motor real,
    tal como está HOY en `monte_carlo.py`) `n_reps` veces. Usado para
    "modelo_nuevo": a diferencia de "modelo_actual" (réplica analítica
    CONGELADA en `models/current.py`), este modelo evoluciona con cada paso
    de la Fase B (B1, B2, B5, B7, B8, B9...) sin necesitar una réplica
    analítica nueva cada vez -- el costo es ruido de muestreo (~0.9pp por
    partido con n_reps=2000), que promediado sobre miles de partidos del
    backtest es despreciable frente al ancho de los IC ya reportados."""
    wins = sum(1 for _ in range(n_reps) if monte_carlo.simulate_match(rng, a, b) is a)
    return wins / n_reps


def _metrics_window(all_matches: pd.DataFrame, year: int, years_back: int) -> pd.DataFrame:
    """Los mismos `years_back` años que usaría `run_ingest` para esta edición
    (`draw_year - years_back + 1 .. draw_year`), no todo el historial
    cacheado. `all_matches` acá trae 2003-2025 de una sola vez (para no
    re-descargar por edición); sin este recorte, `compute_surface_metrics` y
    el ranking verían la carrera completa de cada jugador en vez de la
    ventana de 3 años que usa "el modelo actual" en producción -- mediría un
    modelo distinto al que corre hoy."""
    lo_year = year - years_back + 1
    match_year = all_matches["tourney_date"] // 10000
    return all_matches[(match_year >= lo_year) & (match_year <= year)]


def _edition_matches(all_matches: pd.DataFrame, tournament_name: str, year: int) -> pd.DataFrame:
    mask = (
        all_matches["tourney_name"].str.contains(tournament_name, case=False, na=False)
        & (all_matches["tourney_date"] // 10000 == year)
        & (all_matches["round"].isin(EVALUATED_ROUNDS))
    )
    return all_matches.loc[mask]


def run_match_level_backtest(
    start_year: int,
    end_year: int,
    tournament_name: str = config.TOURNAMENT_NAME,
    surface: str = config.SURFACE,
    years_back: int = config.YEARS_BACK,
    mc_reps_per_match: int = MC_REPS_PER_MATCH,
    seed: int = config.DEFAULT_SEED,
) -> BacktestReport:
    edition_years = list(range(start_year, end_year + 1))
    years = _years_needed(start_year, end_year, years_back, ELO_WARMUP_YEARS)
    _ensure_cached(years)
    all_matches = ingest.load_matches_for_years(years)

    cutoffs = {y: ingest.cutoff_date_for(tournament_name, y, all_matches) for y in edition_years}
    elo_snapshots = elo_model.build_elo_snapshots(all_matches, surface, list(cutoffs.values()))
    rng = random.Random(seed)  # para "modelo_nuevo" (Monte Carlo vía simulate_match); un solo rng para todo el backtest, reproducible con `seed`

    probs: dict[str, list[float]] = {name: [] for name in MODEL_NAMES}
    outcomes: dict[str, list[int]] = {name: [] for name in MODEL_NAMES}
    by_year_briers: dict[str, dict[int, list[float]]] = {name: {} for name in MODEL_NAMES}

    for year in edition_years:
        cutoff = cutoffs[year]
        edition_matches = _edition_matches(all_matches, tournament_name, year)
        if edition_matches.empty:
            logger.warning("Sin partidos de %s %d en el rango descargado, se salta la edición", tournament_name, year)
            continue

        window = _metrics_window(all_matches, year, years_back)
        # "modelo_actual" (congelado en models/current.py) se mide con las
        # tasas CRUDAS SIN decaimiento (B9), tal como se midió en la Fase A
        # -- llamada aparte con NO_DECAY_HALF_LIFE, ver constante arriba.
        surface_metrics_frozen = ingest.compute_surface_metrics(
            window, surface, cutoff, adjust_iterations=0, half_life_days=NO_DECAY_HALF_LIFE
        )
        lookup_raw, prior_serve_raw, prior_return_raw = _player_lookup(surface_metrics_frozen, adjusted=False)

        # "modelo_nuevo" (el motor real de monte_carlo.py) necesita las tasas
        # AJUSTADAS por oponente (B2, van con B1) y con decaimiento (B9).
        surface_metrics = ingest.compute_surface_metrics(window, surface, cutoff)
        lookup_adj, prior_serve_adj, prior_return_adj = _player_lookup(surface_metrics, adjusted=True)
        avg_serve_hard = surface_metrics.attrs.get("avg_serve_hard", prior_serve_raw)
        ranks = ingest.latest_rank_before_cutoff(window, cutoff)["rank"].to_dict()
        elo_ratings = elo_snapshots.get(cutoff, {})

        year_briers: dict[str, list[float]] = {name: [] for name in MODEL_NAMES}

        for _, m in edition_matches.iterrows():
            winner_id, loser_id = str(int(m["winner_id"])), str(int(m["loser_id"]))
            # Orientación fija (no "el que ganó"), para que la calibración no sea trivial (ver metrics.py).
            p1_id, p2_id = sorted((winner_id, loser_id), key=int)
            y = 1 if p1_id == winner_id else 0

            player1_raw = _make_player(p1_id, lookup_raw, prior_serve_raw, prior_return_raw)
            player2_raw = _make_player(p2_id, lookup_raw, prior_serve_raw, prior_return_raw)
            p_current = current_model.match_probability(player1_raw, player2_raw)

            player1_adj = _make_player(p1_id, lookup_adj, prior_serve_adj, prior_return_adj, avg_serve_pct=avg_serve_hard)
            player2_adj = _make_player(p2_id, lookup_adj, prior_serve_adj, prior_return_adj, avg_serve_pct=avg_serve_hard)
            p_new = _mc_match_probability(rng, player1_adj, player2_adj, n_reps=mc_reps_per_match)

            p_rank = baselines.rank_favorite(ranks.get(p1_id), ranks.get(p2_id))
            p_elo = baselines.elo(elo_ratings.get(p1_id), elo_ratings.get(p2_id))
            p_coin = baselines.coin_flip()

            for name, p in zip(MODEL_NAMES, (p_current, p_new, p_rank, p_elo, p_coin)):
                probs[name].append(p)
                outcomes[name].append(y)
                year_briers[name].append((p - y) ** 2)

        for name in MODEL_NAMES:
            if year_briers[name]:
                by_year_briers[name][year] = sum(year_briers[name]) / len(year_briers[name])

    models: dict[str, ModelResult] = {}
    for name in MODEL_NAMES:
        if not probs[name]:
            continue
        brier_mean, brier_ci = metrics.mean_with_ci(metrics.brier_values(probs[name], outcomes[name]))
        logloss_mean, logloss_ci = metrics.mean_with_ci(metrics.log_loss_values(probs[name], outcomes[name]))
        ece = metrics.expected_calibration_error(probs[name], outcomes[name])
        models[name] = ModelResult(
            name=name,
            n_matches=len(probs[name]),
            brier=brier_mean,
            brier_ci=brier_ci,
            log_loss=logloss_mean,
            log_loss_ci=logloss_ci,
            ece=ece,
            by_year_brier=by_year_briers[name],
        )

    return BacktestReport(
        start_year=start_year,
        end_year=end_year,
        n_editions=len(edition_years),
        tournament_name=tournament_name,
        surface=surface,
        models=models,
    )


def run_champion_log_loss(
    start_year: int,
    end_year: int,
    tournament_name: str = config.TOURNAMENT_NAME,
    surface: str = config.SURFACE,
    years_back: int = config.YEARS_BACK,
    n_simulations: int = 2000,
    seed: int = config.DEFAULT_SEED,
) -> dict[str, tuple[float, float]]:
    """Log-loss de "quién gana el torneo completo" (plan sección 1, 4ta
    métrica): -log(P(el campeón REAL era el campeón según el modelo)),
    promediado sobre ediciones con IC. Corre el motor Monte Carlo EN VIVO
    (`monte_carlo.run_simulations`, tal como está HOY -- refleja cada paso de
    la Fase B automáticamente) sobre el cuadro real reconstruido de cada
    edición, con las tasas ajustadas por oponente (B2, van junto con B1)."""
    edition_years = list(range(start_year, end_year + 1))
    years = _years_needed(start_year, end_year, years_back, 0)
    _ensure_cached(years)
    all_matches = ingest.load_matches_for_years(years)

    losses_model: list[float] = []
    losses_rank: list[float] = []

    for year in edition_years:
        try:
            cutoff = ingest.cutoff_date_for(tournament_name, year, all_matches)
            draw_df = ingest.build_draw(all_matches, tournament_name, year)
        except ValueError:
            logger.warning("Sin cuadro R128 reconstruible de %s %d, se salta", tournament_name, year)
            continue

        edition_matches = _edition_matches(all_matches, tournament_name, year)
        final = edition_matches[edition_matches["round"] == "F"]
        if final.empty:
            continue
        champion_id = str(int(final.iloc[0]["winner_id"]))

        window = _metrics_window(all_matches, year, years_back)
        surface_metrics = ingest.compute_surface_metrics(window, surface, cutoff)
        lookup, prior_serve, prior_return = _player_lookup(surface_metrics, adjusted=True)
        avg_serve_hard = surface_metrics.attrs.get("avg_serve_hard", prior_serve)
        ranks = ingest.latest_rank_before_cutoff(window, cutoff)["rank"].to_dict()

        draw = [
            _make_player(row["player_id"], lookup, prior_serve, prior_return, avg_serve_pct=avg_serve_hard)
            for _, row in draw_df.sort_values("slot_index").iterrows()
        ]
        counts = monte_carlo.run_simulations(draw, n_simulations=n_simulations, seed=seed)
        p_model = counts.get(champion_id, {}).get("CAMPEON", 0) / n_simulations
        losses_model.append(-math.log(max(p_model, metrics.EPS)))

        # baseline "favorito por ranking": el mejor ranking del cuadro es el campeón, con prob. 1
        draw_ranks = {p.player_id: ranks.get(p.player_id) for p in draw}
        known = {pid: r for pid, r in draw_ranks.items() if r is not None}
        favorite_id = min(known, key=known.get) if known else None
        p_rank = (1 - metrics.EPS) if favorite_id == champion_id else metrics.EPS
        losses_rank.append(-math.log(p_rank))

    result: dict[str, tuple[float, float]] = {}
    if losses_model:
        result["modelo_nuevo"] = metrics.mean_with_ci(losses_model)
    if losses_rank:
        result["ranking_atp"] = metrics.mean_with_ci(losses_rank)
    return result

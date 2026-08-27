"""Pipeline de predicción (ingesta si hace falta + simulación), extraído de
`simular_usopen.py` para que la CLI y el modo `--serve` (`src/cli/server.py`)
lo reusen sin duplicar lógica (PLAN_PAGINA_RESULTADOS.md, revisión post-gate:
"la interactividad no debe duplicar el pipeline de simulación en dos lugares").
"""

from __future__ import annotations

import math
import sqlite3

from src import config
from src.data import fetchers, ingest, repository
from src.simulation import monte_carlo
from src.simulation.models import elo as elo_model
from src.simulation.models import serve_return


def _load_elo_draw(draw: list, tournament_name: str, draw_year: int) -> list[elo_model.EloPlayer]:
    """Construye el cuadro en formato `EloPlayer` (player_id/full_name/seed
    de `draw`, más su rating Elo de superficie) para `--model elo`.

    El Elo no vive en `metricas_superficie` (se recalcula del historial
    crudo, como en el backtest): hace falta más años de los que carga
    `run_ingest` normalmente (`YEARS_BACK` + `ELO_WARMUP_YEARS` de
    calentamiento, para que el rating no arranque en frío)."""
    years_needed = list(range(
        draw_year - config.YEARS_BACK + 1 - elo_model.ELO_WARMUP_YEARS, draw_year + 1
    ))
    missing = [y for y in years_needed if not (config.DATA_RAW_DIR / config.MATCHES_FILE_TEMPLATE.format(year=y)).exists()]
    if missing:
        print(f"Descargando {len(missing)} año(s) adicionales para el Elo (calentamiento)...")
        fetchers.fetch_matches(missing)

    all_matches = ingest.load_matches_for_years(years_needed)
    cutoff = ingest.cutoff_date_for(tournament_name, draw_year, all_matches)
    ratings = elo_model.build_elo_snapshots(all_matches, config.SURFACE, [cutoff])[cutoff]

    return [
        elo_model.EloPlayer(
            player_id=p.player_id, full_name=p.full_name, seed=p.seed,
            rating=ratings.get(p.player_id, elo_model.INITIAL_ELO),
        )
        for p in draw
    ]


def run_prediction(
    draw_year: int,
    model: str,
    simulations: int,
    seed: int,
    exact_simulation: bool = False,
    update_data: bool = False,
) -> tuple[dict[str, dict[str, int]], dict[str, object], dict]:
    """Corre ingesta (si hace falta) + simulación Monte Carlo del cuadro y
    devuelve `(counts, players_by_id, meta)` -- la misma tripleta que
    consumen `render.render_probabilities` y `html_report.render_*_html`.

    Única fuente de esta lógica: la usan tanto `simular_usopen.main()` como
    `src/cli/server.py` (modo `--serve`), para no duplicar el pipeline entre
    la corrida única por CLI y las corridas repetidas que dispara el botón
    de la página interactiva."""
    needs_ingest = (
        update_data
        or not config.DB_PATH.exists()
        or not repository.draw_is_ready(config.TOURNAMENT_NAME, draw_year)
    )
    if needs_ingest:
        print("Actualizando datos (descarga + ingesta)...")
        ingest.run_ingest(draw_year=draw_year, force_download=update_data)

    draw, players_by_id = repository.load_draw(config.TOURNAMENT_NAME, draw_year)

    with sqlite3.connect(config.DB_PATH) as conn:
        # `metricas_superficie` está particionada por tournament_year (B4):
        # filtrar por la edición pedida, si no con varias ediciones cargadas
        # (p.ej. tras correr --backtest) esto podía traer el cutoff de
        # cualquier otra edición al azar.
        cutoff_row = conn.execute(
            "SELECT cutoff_date FROM metricas_superficie WHERE tournament_year = ? LIMIT 1",
            (draw_year,),
        ).fetchone()
    cutoff_date = cutoff_row[0] if cutoff_row else "?"

    print(f"Corriendo {simulations:,} simulaciones del cuadro ({len(draw)} jugadores, modelo: {model})...")
    if model == "elo":
        elo_draw = _load_elo_draw(draw, config.TOURNAMENT_NAME, draw_year)
        players_by_id = {p.player_id: p for p in elo_draw}
        counts = elo_model.run_simulations_elo(elo_draw, n_simulations=simulations, seed=seed)
    elif exact_simulation:
        counts = monte_carlo.run_simulations(draw, n_simulations=simulations, seed=seed)
    else:
        counts = serve_return.run_simulations_fast(draw, n_simulations=simulations, seed=seed)

    note = (
        f"Cuadro real de {config.TOURNAMENT_NAME} {draw_year} reconstruido desde resultados "
        "históricos (Sackmann). El sorteo oficial en vivo llega en la Fase 4 del plan; "
        "hasta entonces se simula la última edición completa disponible."
        + (
            " Modelo: Elo de superficie decide cada partido directamente (una sola moneda, "
            "sin juegos/sets) -- ver --help."
            if model == "elo" else ""
        )
    )

    meta = {
        "tournament_name": config.TOURNAMENT_NAME,
        "tournament_year": draw_year,
        "draw_size": len(draw),
        "cutoff_date": cutoff_date,
        "note": note,
        "model": model,
    }
    return counts, players_by_id, meta


# --- Cuadro proyectado (bracket) --------------------------------------------
# Pedido explícito del usuario tras el gate: "quiero que se muestre el
# bracket" -- ver PLAN_PAGINA_RESULTADOS.md, revisión post-gate #2.

MATCH_ROUNDS = ["R128", "R64", "R32", "R16", "QF", "SF", "F"]


def _win_probability_fn(model: str):
    """P(a le gana a b) exacta según el modelo pedido -- NO Monte Carlo, es
    el límite analítico (`serve_return.match_probability`) o el Elo directo
    (`elo_model.match_probability_from_elo`), la misma fórmula que decide
    cada partido en la simulación real."""
    if model == "elo":
        return lambda a, b: elo_model.match_probability_from_elo(a.rating, b.rating)
    return lambda a, b: serve_return.match_probability(a, b)


def build_predicted_bracket(players_by_id: dict[str, object], model: str) -> tuple[list[list[dict]], object]:
    """Cuadro proyectado determinístico: en cada cruce real del draw, el
    favorito es quien tiene P(ganar) >= 0.5 según el modelo exacto, y avanza
    a enfrentar al favorito del cruce siguiente -- así hasta la final. Es UN
    solo camino "más probable" (lo que la gente espera ver cuando pide "el
    bracket"), no una nube de probabilidades como la tabla de rondas.

    `players_by_id` tiene que venir en orden de slot real de R128 -- los
    dicts de Python preservan orden de inserción (3.7+) y `run_prediction`
    siempre lo construye a partir del `draw`/`elo_draw` ordenado por
    `slot_index` (ver `repository.load_draw`), así que reusarlo acá no
    requiere volver a leer la base ni repetir la ingesta.

    Devuelve `(rounds, champion)`: `rounds` es una lista de rondas (tantas
    como `log2(len(players_by_id))`, usando los últimos N nombres de
    `MATCH_ROUNDS` -- así un draw más chico que 128, como en los tests
    unitarios, arranca en la ronda que le corresponde: un draw de 2 jugadores
    es directamente "F", uno de 4 es "SF"+"F", etc.), cada una una lista de
    partidos `{"favorite", "underdog", "prob"}`; `champion` es el jugador que
    gana la última."""
    win_prob = _win_probability_fn(model)
    current = list(players_by_id.values())
    n = len(current)
    if n < 2 or (n & (n - 1)) != 0:
        raise ValueError(f"El cuadro debe tener una potencia de 2 de jugadores (>= 2), recibió {n}")
    num_rounds = int(math.log2(n))
    if num_rounds > len(MATCH_ROUNDS):
        raise ValueError(
            f"Cuadro de {n} jugadores no soportado (máximo {2 ** len(MATCH_ROUNDS)}, el tamaño real del US Open)"
        )
    round_names = MATCH_ROUNDS[len(MATCH_ROUNDS) - num_rounds:]

    rounds: list[list[dict]] = []
    for round_name in round_names:
        matches: list[dict] = []
        winners = []
        for i in range(0, len(current), 2):
            a, b = current[i], current[i + 1]
            p_a = win_prob(a, b)
            if p_a >= 0.5:
                favorite, underdog, prob = a, b, p_a
            else:
                favorite, underdog, prob = b, a, 1 - p_a
            matches.append({"round": round_name, "favorite": favorite, "underdog": underdog, "prob": prob})
            winners.append(favorite)
        rounds.append(matches)
        current = winners

    return rounds, current[0]

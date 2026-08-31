"""Pipeline de predicción (ingesta si hace falta + simulación), extraído de
`simular_usopen.py` para que la CLI y el modo `--serve` (`src/cli/server.py`)
lo reusen sin duplicar lógica (PLAN_PAGINA_RESULTADOS.md, revisión post-gate:
"la interactividad no debe duplicar el pipeline de simulación en dos lugares").
"""

from __future__ import annotations

import math
import sqlite3

from src import config
from src.data import fetchers, ingest, live_draw, repository
from src.simulation import monte_carlo
from src.simulation.models import ensemble as ensemble_model
from src.simulation.models import elo as elo_model
from src.simulation.models import serve_return


def _compute_elo_ratings(tournament_name: str, draw_year: int) -> dict[str, float]:
    """Ratings Elo de superficie de cada jugador del draw, en la fecha de
    corte de la edición -- compartido por `--model elo` y `--model ensemble`
    (ninguno de los dos vuelve a pagar la descarga/recorrido del historial).

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
    # Fase 4: `resolve_cutoff` (no `cutoff_date_for`) -- para una edición en
    # vivo (sin R128 histórico todavía) cae a "hoy" en vez de reventar, igual
    # que `ingest.run_ingest` para el resto de las métricas.
    cutoff = ingest.resolve_cutoff(tournament_name, draw_year, all_matches)
    return elo_model.build_elo_snapshots(all_matches, config.SURFACE, [cutoff])[cutoff]


def _load_elo_draw(draw: list, tournament_name: str, draw_year: int) -> list[elo_model.EloPlayer]:
    """Construye el cuadro en formato `EloPlayer` (player_id/full_name/seed
    de `draw`, más su rating Elo de superficie) para `--model elo`."""
    ratings = _compute_elo_ratings(tournament_name, draw_year)
    return [
        elo_model.EloPlayer(
            player_id=p.player_id, full_name=p.full_name, seed=p.seed,
            rating=ratings.get(p.player_id, elo_model.INITIAL_ELO),
        )
        for p in draw
    ]


def _load_ensemble_draw(draw: list, tournament_name: str, draw_year: int) -> list[ensemble_model.EnsemblePlayer]:
    """Construye el cuadro en formato `EnsemblePlayer` (los mismos campos de
    saque/resto de `draw`, más el rating Elo) para `--model ensemble` -- ver
    el docstring de `src/simulation/models/ensemble.py` para el peso 70/30."""
    ratings = _compute_elo_ratings(tournament_name, draw_year)
    return [
        ensemble_model.EnsemblePlayer(
            player_id=p.player_id, full_name=p.full_name, seed=p.seed,
            serve_pct=p.serve_pct, return_pct=p.return_pct, avg_serve_pct=p.avg_serve_pct,
            rating=ratings.get(p.player_id, elo_model.INITIAL_ELO),
        )
        for p in draw
    ]


def _run_engine(
    model: str,
    exact_simulation: bool,
    sim_draw: list,
    simulations: int,
    seed: int,
    known_results: monte_carlo.KnownResults | None,
    match_prob_cache: dict[tuple[str, str], float] | None = None,
) -> dict[str, dict[str, int]]:
    """Despacha al motor correcto (mismo `sim_draw` para las N corridas de
    todos los snapshots de una edición en vivo -- solo cambia
    `known_results` entre una y otra, ver `_generate_round_snapshots`).

    `match_prob_cache`: lo usan `serve_return` y `ensemble` (no `elo` --
    `match_probability_from_elo` es una fórmula cerrada, no vale la pena
    cachearla) -- compartirlo ENTRE llamadas (una por ronda-snapshot) evita
    recalcular `match_probability` para los mismos pares una y otra vez
    (medido: sin esto, generar los 7 snapshots tardaba visiblemente más que
    una corrida normal -- ver el docstring de `serve_return.run_simulations_fast`
    y, para `ensemble`, el de `ensemble.simulate_match`)."""
    if model == "elo":
        return elo_model.run_simulations_elo(sim_draw, n_simulations=simulations, seed=seed, known_results=known_results)
    if model == "ensemble":
        return ensemble_model.run_simulations(
            sim_draw, n_simulations=simulations, seed=seed, known_results=known_results, cache=match_prob_cache,
        )
    if exact_simulation:
        return monte_carlo.run_simulations(sim_draw, n_simulations=simulations, seed=seed, known_results=known_results)
    return serve_return.run_simulations_fast(
        sim_draw, n_simulations=simulations, seed=seed, known_results=known_results, cache=match_prob_cache,
    )


def _generate_round_snapshots(
    tournament_name: str,
    draw_year: int,
    model: str,
    exact_simulation: bool,
    sim_draw: list,
    simulations: int,
    seed: int,
    known_results: monte_carlo.KnownResults,
) -> list[dict]:
    """Fase 4 (D2/D5/D6): un snapshot de predicción por ronda de
    `config.MATCH_ROUNDS` -- "entrando a la ronda X" = condicionado en TODOS
    los resultados reales ya conocidos de rondas anteriores a X (parcial o
    completo), simulando el resto. R128 siempre se genera (es la base, sin
    condicionar nada); R64..F solo si el torneo ya arrancó (`known_results`
    no vacío) -- antes de eso las 7 rondas darían la misma tabla sin
    conditioning real, 7x el cómputo sin ninguna información nueva.

    D6: una ronda cuyo snapshot guardado ya está `frozen` (todas las rondas
    anteriores a ella están 100% jugadas en la realidad -- su conditioning
    no puede cambiar más) no se recalcula, se reusa tal cual."""
    existing = {s["round_name"]: s for s in repository.load_snapshots(tournament_name, draw_year, model)}
    has_started = bool(known_results)
    rounds_to_generate = [config.MATCH_ROUNDS[0]] + (config.MATCH_ROUNDS[1:] if has_started else [])
    match_prob_cache: dict[tuple[str, str], float] = {}  # compartido entre TODAS las rondas -- ver docstring de _run_engine

    snapshots: list[dict] = []
    for round_name in rounds_to_generate:
        prior_rounds = config.MATCH_ROUNDS[: config.MATCH_ROUNDS.index(round_name)]
        all_prior_decided = all(
            sum(1 for (r, _m) in known_results if r == p) >= config.MATCHES_PER_ROUND[p] for p in prior_rounds
        )

        cached = existing.get(round_name)
        if cached is not None and cached["frozen"]:
            snapshots.append(cached)
            continue

        filtered_known = {(r, m): pid for (r, m), pid in known_results.items() if r in prior_rounds}
        counts = _run_engine(model, exact_simulation, sim_draw, simulations, seed, filtered_known, match_prob_cache)
        repository.save_snapshot(tournament_name, draw_year, round_name, model, simulations, counts, frozen=all_prior_decided)
        snapshots.append(
            {"round_name": round_name, "n_simulations": simulations, "counts": counts, "frozen": all_prior_decided}
        )
    return snapshots


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
    `counts` es siempre "la tabla más informada disponible ahora" -- para
    una edición histórica, la única simulación; para una edición en vivo
    (Fase 4), el último snapshot de `meta["round_snapshots"]` (ver abajo).

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

    # Fase 4 (D8): el ESTADO del cuadro (quién ganó qué hasta ahora) se pide
    # siempre fresco a Wikipedia, nunca de la ingesta ya hecha -- una edición
    # en vivo puede tener resultados nuevos entre una corrida y la siguiente
    # aunque `needs_ingest` haya sido False.
    is_live = repository.is_live_draw(config.TOURNAMENT_NAME, draw_year)
    known_results: monte_carlo.KnownResults = {}
    if is_live:
        print("Consultando el estado en vivo del cuadro (Wikipedia)...")
        state = live_draw.fetch_live_bracket_state(config.TOURNAMENT_NAME, draw_year)
        known_results = state.known_results

    print(f"Corriendo {simulations:,} simulaciones del cuadro ({len(draw)} jugadores, modelo: {model})...")
    if model == "elo":
        sim_draw = _load_elo_draw(draw, config.TOURNAMENT_NAME, draw_year)
        players_by_id = {p.player_id: p for p in sim_draw}
    elif model == "ensemble":
        sim_draw = _load_ensemble_draw(draw, config.TOURNAMENT_NAME, draw_year)
        players_by_id = {p.player_id: p for p in sim_draw}
    else:
        sim_draw = draw

    round_snapshots: list[dict] = []
    if is_live:
        round_snapshots = _generate_round_snapshots(
            config.TOURNAMENT_NAME, draw_year, model, exact_simulation, sim_draw, simulations, seed, known_results,
        )
        counts = round_snapshots[-1]["counts"]
    else:
        counts = _run_engine(model, exact_simulation, sim_draw, simulations, seed, known_results=None)

    if is_live:
        note = (
            f"Cuadro oficial de {config.TOURNAMENT_NAME} {draw_year} EN VIVO (Fase 4): sorteo real "
            "tomado de Wikipedia, actualizado con los resultados reales a medida que se juega el "
            "torneo -- ver los snapshots por ronda más abajo."
        )
    else:
        note = (
            f"Cuadro real de {config.TOURNAMENT_NAME} {draw_year} reconstruido desde resultados "
            "históricos (Sackmann)."
        )
    if model == "elo":
        note += (
            " Modelo: Elo de superficie decide cada partido directamente (una sola moneda, "
            "sin juegos/sets) -- ver --help."
        )
    elif model == "ensemble":
        note += (
            f" Modelo: ensamble {ensemble_model.SERVE_RETURN_WEIGHT:.0%} saque/resto + "
            f"{1 - ensemble_model.SERVE_RETURN_WEIGHT:.0%} Elo de superficie (peso medido y confirmado "
            "en el backtest, ver --help)."
        )

    meta = {
        "tournament_name": config.TOURNAMENT_NAME,
        "tournament_year": draw_year,
        "draw_size": len(draw),
        "cutoff_date": cutoff_date,
        "note": note,
        "model": model,
        "is_live": is_live,
        "known_results": known_results,
        "round_snapshots": round_snapshots,
    }
    return counts, players_by_id, meta


# --- Cuadro proyectado (bracket) --------------------------------------------
# Pedido explícito del usuario tras el gate: "quiero que se muestre el
# bracket" -- ver PLAN_PAGINA_RESULTADOS.md, revisión post-gate #2.
# `MATCH_ROUNDS` vive en config.py (Fase 4: live_draw.py también la necesita
# y src/data no puede importar de src/cli, ver el comentario en config.py).
MATCH_ROUNDS = config.MATCH_ROUNDS


def _win_probability_fn(model: str):
    """P(a le gana a b) exacta según el modelo pedido -- NO Monte Carlo, es
    el límite analítico (`serve_return.match_probability`) o el Elo directo
    (`elo_model.match_probability_from_elo`), la misma fórmula que decide
    cada partido en la simulación real."""
    if model == "elo":
        return lambda a, b: elo_model.match_probability_from_elo(a.rating, b.rating)
    if model == "ensemble":
        return lambda a, b: ensemble_model.match_probability(a, b)
    return lambda a, b: serve_return.match_probability(a, b)


def build_predicted_bracket(
    players_by_id: dict[str, object], model: str, known_results: monte_carlo.KnownResults | None = None
) -> tuple[list[list[dict]], object]:
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
    gana la última.

    `known_results` (Fase 4): si el partido de este cruce ya se jugó de
    verdad, el "favorito" mostrado es el ganador REAL (prob=1.0), no el que
    de casualidad tenga p>=0.5 -- el cuadro proyectado de una edición en vivo
    debe reflejar lo que ya pasó, no una proyección que lo contradiga."""
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
            known = monte_carlo.resolve_known_winner(a, b, round_name, i // 2 + 1, known_results)
            if known is not None:
                favorite = known
                underdog = b if known is a else a
                prob = 1.0
            else:
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


def compute_match_predictions(
    players_by_id: dict[str, object], model: str, known_results: monte_carlo.KnownResults
) -> dict[tuple[str, int], str]:
    """`(ronda, índice de partido)` -> `player_id` que el modelo daba como
    favorito ENTRANDO a esa ronda, solo para los cruces que YA se jugaron de
    verdad. Fuente única de "¿el modelo le pegó a este partido?": la usan
    tanto `compute_round_accuracy` (agregado por ronda) como el cuadro
    proyectado del dashboard (verde/rojo por cruce).

    Para cada ronda con al menos un resultado real, reconstruye el cuadro
    predicho condicionado SOLO en los resultados de rondas ANTERIORES (mismo
    criterio que `_generate_round_snapshots`). Condicionar en la ronda misma
    sería trampa: `build_predicted_bracket(known_results=<todo>)` devuelve el
    ganador REAL como "favorito" (prob=1.0) para un partido ya jugado, así
    que compararlo contra la realidad daría 100% de acierto siempre.

    Los cruces de un partido ya jugado son siempre los REALES, no una
    proyección: un partido no puede estar decidido si los dos partidos que lo
    alimentan no lo están, así que al condicionar en las rondas previas los
    dos jugadores de ese cruce quedan fijados por la realidad."""
    predictions: dict[tuple[str, int], str] = {}
    for round_name in MATCH_ROUNDS:
        if not any(r == round_name for (r, _m) in known_results):
            continue

        prior_rounds = MATCH_ROUNDS[: MATCH_ROUNDS.index(round_name)]
        filtered_known = {(r, m): pid for (r, m), pid in known_results.items() if r in prior_rounds}
        rounds, _champion = build_predicted_bracket(players_by_id, model, known_results=filtered_known)
        # `next(..., None)`: un draw más chico que 128 (tests unitarios) no
        # tiene todas las rondas de MATCH_ROUNDS -- se saltea en vez de
        # reventar con StopIteration.
        round_matches = next(
            (matches for matches in rounds if matches and matches[0]["round"] == round_name), None
        )
        if round_matches is None:
            continue

        for i, m in enumerate(round_matches, start=1):
            if (round_name, i) in known_results:
                predictions[(round_name, i)] = m["favorite"].player_id
    return predictions


def compute_round_accuracy(
    players_by_id: dict[str, object],
    model: str,
    known_results: monte_carlo.KnownResults,
    match_predictions: dict[tuple[str, int], str] | None = None,
) -> list[dict]:
    """Aciertos del modelo por ronda ya jugada (pedido del usuario: "¿se
    puede ver un indicador de cuantos aciertos tuvo el modelo por ronda?"),
    agregando `compute_match_predictions`.

    Ronda sin ningún resultado real todavía: `total=0` (el frontend debe
    mostrarla como "--", no como 0% -- 0% sugeriría que el modelo falló
    todo, cuando en realidad no hay nada que medir aún). Ronda con
    resultados parciales (partido en curso): `total` cuenta solo los
    partidos ya decididos, no los `MATCHES_PER_ROUND[ronda]` completos.

    `match_predictions`: si el caller ya las calculó (p.ej. el exportador
    JSON, que las necesita ADEMÁS para pintar el cuadro proyectado), se
    reusan -- reconstruir el bracket una vez por ronda no es gratis."""
    if match_predictions is None:
        match_predictions = compute_match_predictions(players_by_id, model, known_results)

    results: list[dict] = []
    for round_name in MATCH_ROUNDS:
        decided = [
            (predicted_id, known_results[(r, i)])
            for (r, i), predicted_id in match_predictions.items()
            if r == round_name
        ]
        results.append(
            {
                "round_name": round_name,
                "correct": sum(1 for predicted, actual in decided if predicted == actual),
                "total": len(decided),
            }
        )
    return results

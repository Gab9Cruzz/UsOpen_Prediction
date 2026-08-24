#!/usr/bin/env python
"""Entry point de la CLI. Sin lógica de negocio acá (plan sección 12.1):
sólo parseo de argumentos y orquestación de los módulos en src/.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3

from src import config
from src.data import ingest, repository
from src.cli import render
from src.simulation import monte_carlo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulador Monte Carlo del cuadro del US Open (Fase 1: motor de datos + terminal)."
    )
    parser.add_argument(
        "--update-data", action="store_true",
        help="(Re)descarga los CSV de Sackmann y reconstruye jugadores/métricas/cuadro en SQLite.",
    )
    parser.add_argument(
        "--simulations", type=int, default=config.DEFAULT_SIMULATIONS,
        help=f"Número de iteraciones Monte Carlo (default: {config.DEFAULT_SIMULATIONS}).",
    )
    parser.add_argument(
        "--draw-year", type=int, default=config.DEFAULT_DRAW_YEAR,
        help=f"Edición del US Open a simular (default: {config.DEFAULT_DRAW_YEAR}, última completa disponible).",
    )
    parser.add_argument("--seed", type=int, default=config.DEFAULT_SEED, help="Seed para reproducibilidad.")
    parser.add_argument("--top", type=int, default=20, help="Cuántos jugadores mostrar en la tabla.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Logging detallado.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # jugadores/metricas_superficie no están particionados por año: cada
    # ingesta las reescribe para la edición pedida. Si se pide un draw_year
    # distinto al último ingerido, hay que reingestar (con los CSV ya
    # cacheados, salvo que se pida --update-data explícitamente).
    needs_ingest = (
        args.update_data
        or not config.DB_PATH.exists()
        or not repository.draw_is_ready(config.TOURNAMENT_NAME, args.draw_year)
    )
    if needs_ingest:
        print("Actualizando datos (descarga + ingesta)...")
        ingest.run_ingest(draw_year=args.draw_year, force_download=args.update_data)

    draw, players_by_id = repository.load_draw(config.TOURNAMENT_NAME, args.draw_year)

    with sqlite3.connect(config.DB_PATH) as conn:
        cutoff_row = conn.execute(
            "SELECT cutoff_date FROM metricas_superficie LIMIT 1"
        ).fetchone()
    cutoff_date = cutoff_row[0] if cutoff_row else "?"

    print(f"Corriendo {args.simulations:,} simulaciones del cuadro ({len(draw)} jugadores)...")
    counts = monte_carlo.run_simulations(draw, n_simulations=args.simulations, seed=args.seed)

    note = (
        f"Cuadro real de {config.TOURNAMENT_NAME} {args.draw_year} reconstruido desde resultados "
        "históricos (Sackmann). El sorteo oficial en vivo llega en la Fase 4 del plan; "
        "hasta entonces se simula la última edición completa disponible."
    )

    render.render_probabilities(
        counts,
        players_by_id,
        n_simulations=args.simulations,
        top_n=args.top,
        meta={
            "tournament_name": config.TOURNAMENT_NAME,
            "tournament_year": args.draw_year,
            "draw_size": len(draw),
            "cutoff_date": cutoff_date,
            "note": note,
        },
    )


if __name__ == "__main__":
    main()

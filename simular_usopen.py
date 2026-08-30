#!/usr/bin/env python
"""Entry point de la CLI. Sin lógica de negocio acá: sólo parseo de
argumentos y orquestación de los módulos en src/. Ver README.md para el uso
y PLAN_MEJORA_SIMULACION.md para el modelo y su calibración.
"""

from __future__ import annotations

import argparse
import logging

from src import config
from src.cli import html_report, json_export, render
from src.cli.pipeline import run_prediction
from src.validation import backtest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulador Monte Carlo del cuadro del US Open, con backtest de precisión (ver PLAN_MEJORA_SIMULACION.md)."
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
    parser.add_argument(
        "--exact-simulation", action="store_true",
        help=(
            "Simula cada partido juego a juego (motor original) en vez de la réplica analítica "
            "rápida (B10, Fase D: mismo modelo, un solo sorteo por partido en vez de ~100-200). "
            "Más lento; solo para verificar/depurar. No aplica con --model elo/ensemble (esas dos siempre "
            "deciden el partido completo con una sola moneda, por diseño)."
        ),
    )
    parser.add_argument(
        "--model", choices=["serve_return", "elo", "ensemble"], default="serve_return",
        help=(
            "serve_return (default): Barnett-Clarke + ajuste por oponente, simulado juego/set/partido "
            "(medido: Brier 0.193 sobre 2010-2025, PLAN_MEJORA_SIMULACION.md). "
            "elo: usa el ranking Elo de superficie directamente para decidir cada partido completo "
            "(una sola moneda por partido, sin juegos/sets/tie-break) -- medido: Brier 0.190, "
            "el baseline más fuerte del backtest, pero sin la estructura juego/set del modelo por defecto. "
            "ensemble: blend 70%% serve_return + 30%% Elo (peso medido en src/validation/ensemble_search.py, "
            "confirmado sobre el holdout 2024-2025) -- una sola moneda por partido, como elo, pero con la "
            "probabilidad ya blendeada."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Logging detallado.")
    parser.add_argument(
        "--backtest", metavar="INICIO-FIN", default=None,
        help=(
            "Corre el backtest de precisión (Fase A del plan de mejora) en vez de simular: "
            "Brier/log-loss/ECE del modelo actual y los baselines (ranking ATP, Elo, moneda) "
            "sobre ediciones ya jugadas. Ej: --backtest 2010-2025"
        ),
    )
    parser.add_argument(
        "--backtest-champion-sims", type=int, default=2000,
        help="Simulaciones Monte Carlo por edición para el log-loss del campeón dentro de --backtest (default: 2000).",
    )
    parser.add_argument(
        "--skip-champion-loss", action="store_true",
        help="Con --backtest: omite el log-loss del campeón (solo métricas partido a partido, más rápido).",
    )
    parser.add_argument(
        "--html", action="store_true",
        help=(
            "Además de la tabla en terminal, escribe un reporte HTML autocontenido a output/ "
            "(ambientado en el US Open, ver PLAN_PAGINA_RESULTADOS.md) y lo abre en el navegador. "
            "Funciona con --backtest también."
        ),
    )
    parser.add_argument(
        "--no-open", action="store_true",
        help="Con --html o --serve: no abrir el navegador automáticamente.",
    )
    parser.add_argument(
        "--serve", action="store_true",
        help=(
            "Levanta un servidor local interactivo (solo 127.0.0.1) con un botón para volver a "
            "simular (ajustando simulaciones/modelo/año) sin reiniciar el proceso. No aplica con "
            "--backtest."
        ),
    )
    parser.add_argument(
        "--export-json", metavar="PATH", default=None,
        help=(
            "Exporta la predicción a un JSON estático en PATH (counts normalizados a probabilidad + "
            "bracket proyectado + snapshots por ronda), pensado para que un frontend separado lo lea "
            "con fetch() sin backend (ver PLAN_AUTOMATIZACION_WEB.md). No aplica con --backtest."
        ),
    )
    return parser.parse_args()


def _run_backtest(args: argparse.Namespace) -> None:
    start_str, _, end_str = args.backtest.partition("-")
    start_year, end_year = int(start_str), int(end_str)
    print(f"Backtest {config.TOURNAMENT_NAME} {start_year}-{end_year} (puede tardar varios minutos: descarga + métricas)...")
    report = backtest.run_match_level_backtest(start_year, end_year)
    champion_loss = None
    if not args.skip_champion_loss:
        print("Calculando log-loss del campeón por edición...")
        champion_loss = backtest.run_champion_log_loss(
            start_year, end_year, n_simulations=args.backtest_champion_sims
        )
    render.render_backtest(report, champion_loss)

    if args.html:
        path = html_report.render_backtest_html(report, champion_loss, auto_open=not args.no_open)
        print(f"Reporte HTML: {path}")


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.backtest:
        _run_backtest(args)
        return

    if args.serve:
        # Modo interactivo (PLAN_PAGINA_RESULTADOS.md, revisión post-gate):
        # levanta un server local, corre la simulación inicial adentro y
        # bloquea hasta Ctrl+C -- no imprime la tabla de terminal (la página
        # ya la muestra, y el botón permite volver a correrla).
        from src.cli import server

        server.run_server(
            {
                "draw_year": args.draw_year,
                "model": args.model,
                "simulations": args.simulations,
                "seed": args.seed,
                "exact_simulation": args.exact_simulation,
                "update_data": args.update_data,
            }
        )
        return

    counts, players_by_id, meta = run_prediction(
        draw_year=args.draw_year,
        model=args.model,
        simulations=args.simulations,
        seed=args.seed,
        exact_simulation=args.exact_simulation,
        update_data=args.update_data,
    )

    render.render_probabilities(
        counts, players_by_id, n_simulations=args.simulations, top_n=args.top, meta=meta,
    )

    if args.html:
        path = html_report.render_probabilities_html(
            counts, players_by_id, n_simulations=args.simulations, meta=meta, auto_open=not args.no_open,
        )
        print(f"Reporte HTML: {path}")

    if args.export_json:
        path = json_export.export_json(
            counts, players_by_id, meta=meta, n_simulations=args.simulations, path=args.export_json,
        )
        print(f"JSON exportado: {path}")


if __name__ == "__main__":
    main()

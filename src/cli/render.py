"""Render de la tabla de resultados en terminal (Rich)."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from src.cli.formatting import DISPLAY_ROUNDS, LABELS, MODEL_LABELS, binomial_ci95_pp


def render_probabilities(
    counts: dict[str, dict[str, int]],
    players_by_id: dict[str, object],
    n_simulations: int,
    top_n: int = 20,
    meta: dict | None = None,
) -> None:
    console = Console()

    if meta:
        console.print(
            f"[bold]{meta.get('tournament_name', '')} {meta.get('tournament_year', '')}[/bold]"
            f"  ·  cuadro de {meta.get('draw_size', '?')}"
            f"  ·  {n_simulations:,} simulaciones"
            f"  ·  corte de datos: {meta.get('cutoff_date', '?')}"
        )
        if meta.get("note"):
            console.print(f"[dim]{meta['note']}[/dim]")
        console.print()

    ranked = sorted(
        counts.items(), key=lambda kv: kv[1]["CAMPEON"], reverse=True
    )[:top_n]

    table = Table(title="Favoritos US Open — probabilidades por ronda", show_lines=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Jugador", style="bold")
    table.add_column("Seed", justify="right")
    for r in DISPLAY_ROUNDS:
        label = f"{LABELS[r]} (IC95%)" if r == "CAMPEON" else LABELS[r]
        table.add_column(label, justify="right")

    for i, (player_id, round_counts) in enumerate(ranked, start=1):
        player = players_by_id[player_id]
        row = [str(i), player.full_name, str(player.seed) if player.seed else "-"]
        for r in DISPLAY_ROUNDS:
            pct = 100.0 * round_counts[r] / n_simulations
            if r == "CAMPEON":
                ci = binomial_ci95_pp(round_counts[r], n_simulations)
                row.append(f"{pct:.1f}% ± {ci:.1f}")
            else:
                row.append(f"{pct:.1f}%")
        table.add_row(*row)

    console.print(table)
    console.print(
        "[dim]IC95% = intervalo de confianza binomial del 95% sobre el campeón (B6, plan de mejora): "
        "diferencias más chicas que el ancho del intervalo entre dos jugadores no son distinguibles "
        f"con {n_simulations:,} simulaciones.[/dim]"
    )


def render_backtest(report, champion_log_loss: dict | None = None) -> None:
    """Imprime Brier/log-loss/ECE del modelo actual y los baselines
    (criterio de salida de la Fase A del plan de mejora)."""
    console = Console()
    console.print(
        f"[bold]Backtest {report.tournament_name} {report.start_year}-{report.end_year}[/bold]"
        f"  ·  {report.n_editions} ediciones  ·  superficie {report.surface}"
    )
    console.print()

    table = Table(title="Partido a partido (Brier / log-loss / ECE, IC95%)")
    table.add_column("Modelo", style="bold")
    table.add_column("Partidos", justify="right")
    table.add_column("Brier (menor mejor)", justify="right")
    table.add_column("Log-loss (menor mejor)", justify="right")
    table.add_column("ECE (menor mejor)", justify="right")

    for name in ["modelo_actual", "modelo_nuevo", "elo_hard", "ranking_atp", "moneda"]:
        r = report.models.get(name)
        if r is None:
            continue
        table.add_row(
            MODEL_LABELS.get(name, name),
            str(r.n_matches),
            f"{r.brier:.4f} ± {r.brier_ci:.4f}",
            f"{r.log_loss:.4f} ± {r.log_loss_ci:.4f}",
            f"{r.ece:.4f}",
        )
    console.print(table)

    if champion_log_loss:
        console.print()
        champ_table = Table(title="Log-loss del campeón (por edición, IC95%)")
        champ_table.add_column("Modelo", style="bold")
        champ_table.add_column("Log-loss (menor mejor)", justify="right")
        for name, (mean, ci) in champion_log_loss.items():
            champ_table.add_row(MODEL_LABELS.get(name, name), f"{mean:.4f} ± {ci:.4f}")
        console.print(champ_table)

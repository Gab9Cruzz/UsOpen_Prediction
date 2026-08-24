"""Render de la tabla de resultados en terminal (Rich)."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

DISPLAY_ROUNDS = ["R32", "R16", "QF", "SF", "F", "CAMPEON"]
LABELS = {"R32": "R32", "R16": "R16", "QF": "QF", "SF": "SF", "F": "Final", "CAMPEON": "Campeón"}


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
        table.add_column(LABELS[r], justify="right")

    for i, (player_id, round_counts) in enumerate(ranked, start=1):
        player = players_by_id[player_id]
        row = [str(i), player.full_name, str(player.seed) if player.seed else "-"]
        for r in DISPLAY_ROUNDS:
            pct = 100.0 * round_counts[r] / n_simulations
            row.append(f"{pct:.1f}%")
        table.add_row(*row)

    console.print(table)

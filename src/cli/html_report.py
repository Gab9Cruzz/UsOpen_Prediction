"""Render de los resultados como página HTML autocontenida, ambientada en el
US Open (PLAN_PAGINA_RESULTADOS.md).

Dos consumidores de este módulo:
- `--html`: `render_probabilities_html` / `render_backtest_html` escriben un
  archivo estático a `config.OUTPUT_DIR` y lo abren en el navegador.
- `--serve` (`src/cli/server.py`): usa las mismas funciones de fragmento
  (`render_results_fragment` / `render_backtest_fragment`) para servir la
  página inicial Y para responder cada `POST /api/simulate` -- el HTML de la
  tabla se genera en un solo lugar, nunca se duplica en JavaScript (decisión
  de la revisión post-gate, ver el plan).

Regla de la Fase 3 (decisión #27): el bloque `<style>` es una constante de
string PLANA, sin interpolación (ni f-string ni `.format()`), para no tener
que escapar cada `{`/`}` de la sintaxis CSS. Los valores por fila/celda se
interpolan aparte, siempre fuera de `PAGE_STYLE`.
"""

from __future__ import annotations

import html
import webbrowser
from pathlib import Path

from src import config
from src.cli.formatting import DISPLAY_ROUNDS, LABELS, MODEL_LABELS, binomial_ci95_pp
from src.cli.pipeline import build_predicted_bracket

# --- Paleta (PLAN_PAGINA_RESULTADOS.md, Fase 2, decisión #10 -- taste,
# aprobada en el gate final) ------------------------------------------------
# Azul cancha (headers/masthead), tint de fila/track de barra, amarillo
# pelota (SOLO acento: relleno de barra -- nunca texto sobre blanco, falla
# contraste), tinta (texto, no negro puro).
COURT_BLUE = "#00539F"
COURT_TINT = "#EAF2FB"
BALL_YELLOW = "#CCFF00"
INK = "#0B1F33"

PAGE_STYLE = """
* { box-sizing: border-box; }
body {
    margin: 0;
    font-family: 'Segoe UI', Arial, sans-serif;
    color: #0B1F33;
    background: #FFFFFF;
}
.masthead {
    background: #00539F;
    color: #FFFFFF;
    padding: 20px 28px;
}
.masthead h1 {
    margin: 0 0 4px 0;
    font-size: 1.4rem;
    letter-spacing: 0.02em;
}
.masthead .meta {
    font-size: 0.85rem;
    opacity: 0.9;
}
.masthead .note {
    font-size: 0.78rem;
    opacity: 0.75;
    margin-top: 6px;
    max-width: 70ch;
}
.content {
    padding: 20px 28px 40px 28px;
}
.table-wrap {
    overflow-x: auto;
    border: 1px solid #d7e3f0;
    border-radius: 6px;
}
table {
    border-collapse: collapse;
    width: 100%;
    font-variant-numeric: tabular-nums;
    font-size: 0.88rem;
}
thead th {
    position: sticky;
    top: 0;
    background: #00539F;
    color: #FFFFFF;
    text-align: right;
    padding: 10px 12px;
    white-space: nowrap;
}
thead th:nth-child(-n+3) { text-align: left; }
tbody td {
    padding: 8px 12px;
    border-top: 1px solid #EAF2FB;
    text-align: right;
    white-space: nowrap;
}
tbody td:nth-child(-n+3) { text-align: left; }
tbody tr:nth-child(even) { background: #EAF2FB; }
.player-name { font-weight: 600; }
.round-cell { position: relative; min-width: 90px; }
.bar-track {
    position: absolute;
    left: 12px;
    right: 12px;
    top: 6px;
    bottom: 6px;
    background: rgba(0, 83, 159, 0.08);
    border-radius: 3px;
    z-index: 0;
}
.bar-fill {
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    background: #CCFF00;
    border-radius: 3px;
    z-index: 1;
}
.pct { position: relative; z-index: 2; }
.ci { position: relative; z-index: 2; font-size: 0.72rem; opacity: 0.65; }
.insufficient { color: #8a8f98; font-style: italic; }
.footer-note {
    font-size: 0.78rem;
    color: #5a6472;
    margin-top: 14px;
    max-width: 90ch;
}
.controls {
    margin: 0 0 18px 0;
    padding: 14px 16px;
    background: #EAF2FB;
    border-radius: 6px;
    display: flex;
    gap: 14px;
    align-items: flex-end;
    flex-wrap: wrap;
}
.controls label {
    display: flex;
    flex-direction: column;
    font-size: 0.78rem;
    color: #0B1F33;
    gap: 4px;
}
.controls input, .controls select {
    font: inherit;
    padding: 6px 8px;
    border: 1px solid #b9cde3;
    border-radius: 4px;
}
.controls button {
    background: #00539F;
    color: #FFFFFF;
    border: none;
    border-radius: 4px;
    padding: 9px 18px;
    font-size: 0.88rem;
    font-weight: 600;
    cursor: pointer;
}
.controls button:disabled { opacity: 0.6; cursor: wait; }
.controls .status { font-size: 0.82rem; color: #5a6472; }
.controls .status.error { color: #b3261e; }
.section-title {
    font-size: 1rem;
    margin: 0 0 10px 0;
    color: #0B1F33;
}
.bracket-wrap {
    overflow-x: auto;
    border: 1px solid #d7e3f0;
    border-radius: 6px;
    background: #fafcff;
    padding: 16px;
    margin-bottom: 26px;
}
.bracket {
    display: flex;
    gap: 14px;
}
.bracket-round {
    display: flex;
    flex-direction: column;
    min-width: 168px;
    flex: none;
}
.bracket-round-label {
    text-align: center;
    font-weight: 700;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #00539F;
    margin-bottom: 8px;
}
.bracket-round-matches {
    display: flex;
    flex-direction: column;
    justify-content: space-evenly;
    flex: 1;
}
.bracket-match {
    border: 1px solid #d7e3f0;
    border-radius: 4px;
    padding: 5px 8px;
    font-size: 0.76rem;
    background: #FFFFFF;
    line-height: 1.35;
}
.bracket-match .fav { font-weight: 700; color: #0B1F33; }
.bracket-match .fav-pct { color: #00539F; font-weight: 700; margin-left: 4px; }
.bracket-match .und { color: #8a8f98; }
.champion-column { justify-content: center; }
.champion-card {
    text-align: center;
    font-weight: 800;
    font-size: 1.05rem;
    padding: 16px 10px;
    border-radius: 6px;
    background: #00539F;
    color: #FFFFFF;
    border: 2px solid #CCFF00;
}
"""

BRACKET_ROUND_LABELS = ["R128", "R64", "R32", "R16", "QF", "SF", "F"]
_BRACKET_ROW_PX = 46


def _head(title: str) -> str:
    return (
        "<!DOCTYPE html>\n<html lang=\"es\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        f"<title>{html.escape(title)}</title>\n"
        "<style>\n" + PAGE_STYLE + "\n</style>\n</head>\n<body>\n"
    )


_TAIL = "\n</body>\n</html>\n"


def render_page(title: str, body_html: str) -> str:
    """Envuelve `body_html` en el documento completo (doctype/head/estilo
    embebido/body). Pública para que `server.py` arme la página inicial sin
    tocar los helpers privados `_head`/`_TAIL` (mismo criterio de la
    decisión #17: no importar símbolos privados cross-módulo)."""
    return _head(title) + body_html + _TAIL


def render_masthead(meta: dict, n_simulations: int) -> str:
    """Banda superior (torneo/año/modelo/N sims/corte de datos). Pública y
    separada de `render_results_table` para que `server.py` pueda pintarla
    una sola vez al cargar la página y refrescar solo la tabla en cada
    `POST /api/simulate` -- no tiene sentido re-renderizar el masthead en
    cada click (revisión post-gate)."""
    return _masthead_html(
        meta.get("tournament_name", ""),
        meta.get("tournament_year", ""),
        str(meta.get("model", "?")),
        n_simulations,
        meta.get("cutoff_date", "?"),
        meta.get("note"),
    )


def _masthead_html(tournament_name: str, tournament_year, model_label: str, n_simulations: int, cutoff_date: str, note: str | None) -> str:
    note_html = f'<div class="note">{html.escape(note)}</div>' if note else ""
    return (
        '<div class="masthead">'
        f"<h1>{html.escape(str(tournament_name))} {html.escape(str(tournament_year))}</h1>"
        '<div class="meta">'
        f"modelo: {html.escape(model_label)} · {n_simulations:,} simulaciones · corte de datos: {html.escape(str(cutoff_date))}"
        "</div>"
        f"{note_html}"
        "</div>"
    )


def _round_cell(count: int, n_simulations: int, is_champion: bool) -> str:
    pct = 100.0 * count / n_simulations if n_simulations else 0.0
    bar_pct = round(min(max(pct, 0.0), 100.0), 1)
    pct_text = f"{pct:.1f}%"
    ci_html = ""
    if is_champion:
        ci = binomial_ci95_pp(count, n_simulations) if n_simulations else 0.0
        ci_html = f'<div class="ci">± {ci:.1f} pp</div>'
    return (
        '<td class="round-cell">'
        '<div class="bar-track">'
        f'<div class="bar-fill" style="width:{bar_pct}%"></div>'
        "</div>"
        f'<span class="pct">{pct_text}</span>'
        f"{ci_html}"
        "</td>"
    )


def render_bracket_fragment(rounds: list[list[dict]], champion: object) -> str:
    """Cuadro proyectado (R128 -> Campeón): un solo camino determinístico de
    favoritos, con la probabilidad de cada cruce. `rounds`/`champion` vienen
    de `pipeline.build_predicted_bracket` -- ver ese docstring para el
    porqué de "un solo camino" en vez de una nube de probabilidades.

    Alineación vertical (truco CSS clásico de brackets sin JS ni SVG): todas
    las columnas comparten la MISMA altura total (la de la ronda R128, la
    que tiene más partidos) y usan `justify-content: space-evenly` -- así
    las columnas con menos partidos se espacian solas para "converger"
    visualmente hacia la final, sin tener que calcular posiciones a mano."""
    unit_height = max(len(rounds[0]), 1) * _BRACKET_ROW_PX
    labels = BRACKET_ROUND_LABELS[len(BRACKET_ROUND_LABELS) - len(rounds):]
    parts = [
        '<div class="bracket-wrap">',
        '<h2 class="section-title">Cuadro proyectado (favorito en cada cruce, sin Monte Carlo -- probabilidad exacta del modelo)</h2>',
        '<div class="bracket">',
    ]
    for label, matches in zip(labels, rounds):
        parts.append('<div class="bracket-round">')
        parts.append(f'<div class="bracket-round-label">{html.escape(label)}</div>')
        parts.append(f'<div class="bracket-round-matches" style="height:{unit_height}px">')
        for m in matches:
            favorite, underdog, prob = m["favorite"], m["underdog"], m["prob"]
            parts.append(
                '<div class="bracket-match">'
                f'<div class="fav">{html.escape(favorite.full_name)}'
                f'<span class="fav-pct">{prob * 100:.0f}%</span></div>'
                f'<div class="und">{html.escape(underdog.full_name)}</div>'
                "</div>"
            )
        parts.append("</div></div>")

    parts.append('<div class="bracket-round">')
    parts.append('<div class="bracket-round-label">Campeón</div>')
    parts.append(f'<div class="bracket-round-matches champion-column" style="height:{unit_height}px">')
    parts.append(f'<div class="champion-card">🏆 {html.escape(champion.full_name)}</div>')
    parts.append("</div></div>")

    parts.append("</div></div>")
    return "".join(parts)


def render_results_table(
    counts: dict[str, dict[str, int]],
    players_by_id: dict[str, object],
    n_simulations: int,
    extra_content: str = "",
    model: str | None = None,
) -> str:
    """El `<div class="content">...` (controles opcionales + bracket
    proyectado + tabla), SIN el masthead -- es la pieza que `server.py`
    reusa tal cual en el `GET /` inicial y en cada respuesta de
    `POST /api/simulate`. Orden por probabilidad de Campeón descendente,
    cuadro COMPLETO (sin recortar por `--top` -- decisión #20: una página no
    tiene la limitación de legibilidad de la terminal).

    `model`: si se pasa, antepone el cuadro proyectado (bracket) calculado
    con `pipeline.build_predicted_bracket` -- opcional para no romper
    llamadas existentes que no lo necesiten (p.ej. tests unitarios de solo
    tabla)."""
    parts = ['<div class="content">', extra_content]

    if model is not None:
        rounds, champion = build_predicted_bracket(players_by_id, model)
        parts.append(render_bracket_fragment(rounds, champion))

    ranked = sorted(counts.items(), key=lambda kv: kv[1]["CAMPEON"], reverse=True)

    parts.append('<div class="table-wrap"><table><thead><tr>')
    parts.append("<th>#</th><th>Jugador</th><th>Seed</th>")
    for r in DISPLAY_ROUNDS:
        label = f"{LABELS[r]} (IC95%)" if r == "CAMPEON" else LABELS[r]
        parts.append(f"<th>{html.escape(label)}</th>")
    parts.append("</tr></thead><tbody>")

    for i, (player_id, round_counts) in enumerate(ranked, start=1):
        player = players_by_id[player_id]
        seed = str(player.seed) if getattr(player, "seed", None) else "-"
        parts.append("<tr>")
        parts.append(f"<td>{i}</td>")
        parts.append(f'<td class="player-name">{html.escape(player.full_name)}</td>')
        parts.append(f"<td>{html.escape(seed)}</td>")
        for r in DISPLAY_ROUNDS:
            parts.append(_round_cell(round_counts[r], n_simulations, is_champion=(r == "CAMPEON")))
        parts.append("</tr>")

    parts.append("</tbody></table></div>")
    parts.append(
        '<div class="footer-note">IC95% = intervalo de confianza binomial del 95% sobre el campeón '
        "(B6, plan de mejora): diferencias más chicas que el ancho del intervalo entre dos jugadores "
        f"no son distinguibles con {n_simulations:,} simulaciones.</div>"
    )
    parts.append("</div>")
    return "".join(parts)


def render_results_fragment(
    counts: dict[str, dict[str, int]],
    players_by_id: dict[str, object],
    n_simulations: int,
    meta: dict | None = None,
) -> str:
    """Masthead + tabla juntos -- conveniencia para el modo estático
    (`--html`), que solo renderiza una vez y no necesita separar las dos
    piezas como sí hace `--serve` (ver `render_masthead`/`render_results_table`)."""
    meta = meta or {}
    return render_masthead(meta, n_simulations) + render_results_table(
        counts, players_by_id, n_simulations, model=meta.get("model"),
    )


def render_probabilities_html(
    counts: dict[str, dict[str, int]],
    players_by_id: dict[str, object],
    n_simulations: int,
    meta: dict,
    output_dir: Path = config.OUTPUT_DIR,
    auto_open: bool = True,
) -> Path:
    tournament_year = meta.get("tournament_year", "0")
    model = meta.get("model", "modelo")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"us_open_{tournament_year}_{model}.html"

    title = f"{meta.get('tournament_name', 'US Open')} {tournament_year} — predicción"
    fragment = render_results_fragment(counts, players_by_id, n_simulations, meta)
    output_path.write_text(render_page(title, fragment), encoding="utf-8")

    if auto_open:
        _open_in_browser(output_path)
    return output_path


def render_backtest_fragment(report, champion_log_loss: dict | None = None) -> str:
    parts = [
        '<div class="masthead">'
        f"<h1>Backtest {html.escape(report.tournament_name)} {report.start_year}-{report.end_year}</h1>"
        '<div class="meta">'
        f"{report.n_editions} ediciones · superficie {html.escape(report.surface)}"
        "</div></div>",
        '<div class="content">',
        '<div class="table-wrap"><table><thead><tr>'
        "<th>Modelo</th><th>Partidos</th><th>Brier (menor mejor)</th>"
        "<th>Log-loss (menor mejor)</th><th>ECE (menor mejor)</th>"
        "</tr></thead><tbody>",
    ]
    # Decisión #22 (Fase 3): espeja el comportamiento existente de
    # `render_backtest` -- un modelo ausente de `report.models` se omite,
    # sin inventar un estado "datos insuficientes" que el modelo de datos
    # (ModelResult, todos los campos obligatorios) no puede producir.
    for name in ["modelo_actual", "modelo_nuevo", "elo_hard", "ranking_atp", "moneda"]:
        r = report.models.get(name)
        if r is None:
            continue
        label = html.escape(MODEL_LABELS.get(name, name))
        parts.append(
            f"<tr><td>{label}</td><td>{r.n_matches}</td>"
            f"<td>{r.brier:.4f} ± {r.brier_ci:.4f}</td>"
            f"<td>{r.log_loss:.4f} ± {r.log_loss_ci:.4f}</td>"
            f"<td>{r.ece:.4f}</td></tr>"
        )
    parts.append("</tbody></table></div>")

    if champion_log_loss:
        parts.append(
            '<div class="table-wrap" style="margin-top:16px"><table><thead><tr>'
            "<th>Modelo</th><th>Log-loss del campeón (menor mejor)</th>"
            "</tr></thead><tbody>"
        )
        for name, (mean, ci) in champion_log_loss.items():
            label = html.escape(MODEL_LABELS.get(name, name))
            parts.append(f"<tr><td>{label}</td><td>{mean:.4f} ± {ci:.4f}</td></tr>")
        parts.append("</tbody></table></div>")

    parts.append("</div>")
    return "".join(parts)


def render_backtest_html(
    report,
    champion_log_loss: dict | None = None,
    output_dir: Path = config.OUTPUT_DIR,
    auto_open: bool = True,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"us_open_backtest_{report.start_year}-{report.end_year}.html"

    title = f"Backtest {report.tournament_name} {report.start_year}-{report.end_year}"
    fragment = render_backtest_fragment(report, champion_log_loss)
    output_path.write_text(render_page(title, fragment), encoding="utf-8")

    if auto_open:
        _open_in_browser(output_path)
    return output_path


def _open_in_browser(path: Path) -> None:
    """Decisión #25/#26 (Fase 3): URI `file:///` explícita (no un path crudo
    de Windows) y `except Exception` explícito -- no tragarse
    KeyboardInterrupt/SystemExit con un `except:` desnudo. Si no hay
    navegador disponible, el archivo ya se escribió; abrirlo es un plus."""
    try:
        webbrowser.open(path.resolve().as_uri())
    except Exception:
        pass

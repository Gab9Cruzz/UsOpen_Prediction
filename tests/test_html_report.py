"""Tests del reporte HTML (PLAN_PAGINA_RESULTADOS.md, Fase 3 -- ver también
PLAN_PAGINA_RESULTADOS_test_plan.md)."""

from __future__ import annotations

from html.parser import HTMLParser

from src.cli import html_report
from src.simulation.monte_carlo import Player


def _make_counts(n_simulations: int, entries: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    """Completa las rondas no especificadas de `DISPLAY_ROUNDS` con 0, para
    no repetir las seis claves en cada test."""
    from src.cli.formatting import DISPLAY_ROUNDS

    return {
        pid: {r: rounds.get(r, 0) for r in DISPLAY_ROUNDS}
        for pid, rounds in entries.items()
    }


def _players(*specs: tuple[str, str, float | None]) -> dict[str, Player]:
    return {
        pid: Player(player_id=pid, full_name=name, seed=seed, serve_pct=0.65, return_pct=0.35)
        for pid, name, seed in specs
    }


class _NonFailingParser(HTMLParser):
    """Smoke test: no lanza excepción parseando el HTML generado."""


def test_escapes_player_names_with_html_chars():
    players = _players(("p1", '<script>alert("x")</script>', 1))
    counts = _make_counts(100, {"p1": {"CAMPEON": 10}})
    fragment = html_report.render_results_table(counts, players, 100)
    assert "<script>alert" not in fragment
    assert "&lt;script&gt;" in fragment


def test_unicode_roundtrip(tmp_path):
    players = _players(("p1", "Étcheverry", 5), ("p2", "Rival", 6))
    counts = _make_counts(100, {"p1": {"CAMPEON": 10}, "p2": {"CAMPEON": 5}})
    meta = {"tournament_name": "Us Open", "tournament_year": 2025, "model": "serve_return", "cutoff_date": "2025-08-25"}
    path = html_report.render_probabilities_html(
        counts, players, 100, meta, output_dir=tmp_path, auto_open=False,
    )
    text = path.read_text(encoding="utf-8")
    assert "Étcheverry" in text


def test_zero_probability_renders_as_percentage_not_dash():
    # count=0 es un resultado legítimo (bajo seed que nunca llega a esa
    # ronda en las simulaciones) -- decisión #21: se muestra como "0.0%",
    # nunca como "—" ni NaN.
    players = _players(("p1", "Jugador Bajo Seed", None))
    counts = _make_counts(1000, {"p1": {"CAMPEON": 0}})
    fragment = html_report.render_results_table(counts, players, 1000)
    assert "0.0%" in fragment
    assert "NaN" not in fragment
    assert ">—<" not in fragment


def test_html_ignores_top_n_shows_full_draw():
    # Decisión #20: la página HTML siempre muestra el cuadro completo,
    # independientemente de --top (que solo aplica a la tabla de terminal).
    specs = [(f"p{i}", f"Jugador {i}", i) for i in range(1, 31)]
    players = _players(*specs)
    counts = _make_counts(100, {pid: {"CAMPEON": i} for i, (pid, _, _) in enumerate(specs)})
    fragment = html_report.render_results_table(counts, players, 100)
    for _, name, _ in specs:
        assert name in fragment


def test_backtest_html_skips_missing_model():
    class _Result:
        def __init__(self, n_matches, brier, brier_ci, log_loss, log_loss_ci, ece):
            self.n_matches, self.brier, self.brier_ci = n_matches, brier, brier_ci
            self.log_loss, self.log_loss_ci, self.ece = log_loss, log_loss_ci, ece

    class _Report:
        tournament_name = "Us Open"
        start_year = 2020
        end_year = 2025
        n_editions = 6
        surface = "Hard"
        models = {"modelo_actual": _Result(100, 0.20, 0.01, 0.60, 0.02, 0.03)}

    fragment = html_report.render_backtest_fragment(_Report())
    assert "Modelo pre-Fase-B" in fragment
    assert "Modelo nuevo" not in fragment  # ausente de report.models -> omitido, sin crashear


def test_generated_html_is_parseable():
    players = _players(("p1", "Jugador Uno", 1), ("p2", "Jugador Dos", 2))
    counts = _make_counts(100, {"p1": {"CAMPEON": 15}, "p2": {"CAMPEON": 5}})
    meta = {"tournament_name": "Us Open", "tournament_year": 2025, "model": "serve_return", "cutoff_date": "2025-08-25"}
    full_html = html_report.render_page("Título", html_report.render_results_fragment(counts, players, 100, meta))
    _NonFailingParser().feed(full_html)  # no debe lanzar excepción


def test_webbrowser_open_failure_does_not_propagate(tmp_path, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("no hay navegador disponible")

    monkeypatch.setattr(html_report.webbrowser, "open", _boom)
    players = _players(("p1", "Jugador Uno", 1), ("p2", "Jugador Dos", 2))
    counts = _make_counts(100, {"p1": {"CAMPEON": 10}, "p2": {"CAMPEON": 5}})
    meta = {"tournament_name": "Us Open", "tournament_year": 2025, "model": "serve_return", "cutoff_date": "2025-08-25"}
    # No debe propagar la excepción -- el archivo ya se escribió, abrirlo es un plus.
    path = html_report.render_probabilities_html(counts, players, 100, meta, output_dir=tmp_path, auto_open=True)
    assert path.exists()


def test_bar_percentage_rounds_cleanly():
    # 19.399999999999998... debe salir con 1 decimal en el `width:`.
    cell = html_report._round_cell(97, 500, is_champion=False)
    assert "width:19.4%" in cell
    assert "19.399999999999998" not in cell


def test_predictions_filename_convention(tmp_path):
    from src.simulation.models.elo import EloPlayer

    # model="elo" en meta -> players_by_id trae EloPlayer (con `.rating`), tal
    # como los deja `pipeline.run_prediction` en la corrida real -- no Player.
    players = {
        "p1": EloPlayer(player_id="p1", full_name="Jugador Uno", seed=1, rating=1600),
        "p2": EloPlayer(player_id="p2", full_name="Jugador Dos", seed=2, rating=1500),
    }
    counts = _make_counts(100, {"p1": {"CAMPEON": 10}, "p2": {"CAMPEON": 5}})
    meta = {"tournament_name": "Us Open", "tournament_year": 2025, "model": "elo", "cutoff_date": "2025-08-25"}
    path = html_report.render_probabilities_html(counts, players, 100, meta, output_dir=tmp_path, auto_open=False)
    assert path.name == "us_open_2025_elo.html"


def test_backtest_filename_convention(tmp_path):
    class _Report:
        tournament_name = "Us Open"
        start_year = 2010
        end_year = 2025
        n_editions = 16
        surface = "Hard"
        models = {}

    path = html_report.render_backtest_html(_Report(), output_dir=tmp_path, auto_open=False)
    assert path.name == "us_open_backtest_2010-2025.html"


def test_build_predicted_bracket_small_draw_uses_correct_round_labels():
    # Draw de 4 jugadores: el bracket empieza en "SF", no en "R128" -- la
    # alineación de labels tiene que tomar los ÚLTIMOS N nombres, no los
    # primeros (si no, un draw chico como este de test mostraría labels de
    # rondas que no juega).
    from src.cli.pipeline import build_predicted_bracket

    players = {
        "p1": Player(player_id="p1", full_name="Fuerte Uno", seed=1, serve_pct=0.70, return_pct=0.40),
        "p2": Player(player_id="p2", full_name="Débil Uno", seed=None, serve_pct=0.58, return_pct=0.28),
        "p3": Player(player_id="p3", full_name="Fuerte Dos", seed=2, serve_pct=0.69, return_pct=0.39),
        "p4": Player(player_id="p4", full_name="Débil Dos", seed=None, serve_pct=0.57, return_pct=0.27),
    }
    rounds, champion = build_predicted_bracket(players, "serve_return")
    assert len(rounds) == 2  # SF, F
    assert len(rounds[0]) == 2  # dos semifinales
    assert len(rounds[1]) == 1  # una final
    # El más fuerte del cuadro (mejor saque/resto) tiene que ser el campeón proyectado.
    assert champion.player_id == "p1"


def test_build_predicted_bracket_rejects_non_power_of_two():
    from src.cli.pipeline import build_predicted_bracket

    players = _players(("p1", "A", 1), ("p2", "B", 2), ("p3", "C", 3))
    try:
        build_predicted_bracket(players, "serve_return")
        assert False, "debería haber lanzado ValueError"
    except ValueError:
        pass


def test_render_bracket_fragment_labels_align_with_round_count():
    from src.cli.pipeline import build_predicted_bracket

    players = {
        "p1": Player(player_id="p1", full_name="Fuerte", seed=1, serve_pct=0.70, return_pct=0.40),
        "p2": Player(player_id="p2", full_name="Débil", seed=None, serve_pct=0.58, return_pct=0.28),
    }
    rounds, champion = build_predicted_bracket(players, "serve_return")
    fragment = html_report.render_bracket_fragment(rounds, champion)
    assert ">F<" in fragment  # única ronda de un draw de 2 -> "F", no "R128"
    assert "Fuerte" in fragment
    assert "🏆" in fragment


def test_results_table_includes_bracket_when_model_given():
    players = _players(("p1", "Fuerte", 1), ("p2", "Débil", None))
    counts = _make_counts(100, {"p1": {"CAMPEON": 90}, "p2": {"CAMPEON": 10}})
    with_model = html_report.render_results_table(counts, players, 100, model="serve_return")
    without_model = html_report.render_results_table(counts, players, 100)
    assert "bracket-wrap" in with_model
    assert "bracket-wrap" not in without_model


def test_round_snapshots_omitted_with_only_baseline():
    """Fase 4: un solo snapshot (R128, pre-torneo) sería un duplicado exacto
    de la tabla principal -- no debe agregar la sección."""
    players = _players(("p1", "Fuerte", 1), ("p2", "Débil", None))
    counts = _make_counts(100, {"p1": {"CAMPEON": 90}, "p2": {"CAMPEON": 10}})
    snapshots = [{"round_name": "R128", "n_simulations": 100, "counts": counts, "frozen": True}]
    fragment = html_report.render_results_table(counts, players, 100, round_snapshots=snapshots)
    assert "snapshot-block" not in fragment


def test_round_snapshots_render_when_tournament_started():
    players = _players(("p1", "Fuerte", 1), ("p2", "Débil", None))
    counts_r128 = _make_counts(100, {"p1": {"CAMPEON": 60}, "p2": {"CAMPEON": 40}})
    counts_r64 = _make_counts(100, {"p1": {"CAMPEON": 100}, "p2": {"CAMPEON": 0}})
    snapshots = [
        {"round_name": "R128", "n_simulations": 100, "counts": counts_r128, "frozen": True},
        {"round_name": "R64", "n_simulations": 100, "counts": counts_r64, "frozen": False},
    ]
    fragment = html_report.render_results_table(counts_r64, players, 100, round_snapshots=snapshots)
    assert fragment.count("snapshot-block") == 2
    assert "Entrando a R128" in fragment
    assert "Entrando a R64" in fragment
    assert "🔒 congelada" in fragment  # solo el snapshot de R128 está frozen=True


def test_round_snapshots_omitted_when_empty():
    players = _players(("p1", "Fuerte", 1), ("p2", "Débil", None))
    counts = _make_counts(100, {"p1": {"CAMPEON": 90}, "p2": {"CAMPEON": 10}})
    fragment = html_report.render_results_table(counts, players, 100, round_snapshots=[])
    assert "snapshot-block" not in fragment


def test_bracket_shows_real_winner_when_known_result_given():
    from src.simulation.monte_carlo import Player as MCPlayer

    players = {
        "p1": MCPlayer(player_id="p1", full_name="Favorito", seed=1, serve_pct=0.70, return_pct=0.40),
        "p2": MCPlayer(player_id="p2", full_name="Sorpresa", seed=None, serve_pct=0.40, return_pct=0.20),
    }
    counts = _make_counts(100, {"p1": {"CAMPEON": 90}, "p2": {"CAMPEON": 10}})
    # p2 (el "underdog" según el modelo) ya ganó de verdad ese partido real.
    known = {("F", 1): "p2"}
    fragment = html_report.render_results_table(counts, players, 100, model="serve_return", known_results=known)
    assert "🏆 Sorpresa" in fragment


def test_output_dir_created_if_missing(tmp_path):
    missing_dir = tmp_path / "no_existe_todavia"
    assert not missing_dir.exists()
    players = _players(("p1", "Jugador Uno", 1), ("p2", "Jugador Dos", 2))
    counts = _make_counts(100, {"p1": {"CAMPEON": 10}, "p2": {"CAMPEON": 5}})
    meta = {"tournament_name": "Us Open", "tournament_year": 2025, "model": "serve_return", "cutoff_date": "2025-08-25"}
    html_report.render_probabilities_html(counts, players, 100, meta, output_dir=missing_dir, auto_open=False)
    assert missing_dir.exists()

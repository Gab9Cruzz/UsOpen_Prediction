"""Tests del exportador JSON (PLAN_AUTOMATIZACION_WEB.md, sección 4 -- los
GAPs de `json_export.py` listados en el Test Review)."""

from __future__ import annotations

import json

from src.cli import json_export
from src.cli.formatting import DISPLAY_ROUNDS
from src.simulation.monte_carlo import Player


def _make_counts(n_simulations: int, entries: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    return {
        pid: {r: rounds.get(r, 0) for r in DISPLAY_ROUNDS}
        for pid, rounds in entries.items()
    }


def _players(*specs: tuple[str, str, float | None]) -> dict[str, Player]:
    return {
        pid: Player(player_id=pid, full_name=name, seed=seed, serve_pct=0.65, return_pct=0.35)
        for pid, name, seed in specs
    }


def _base_meta(**overrides) -> dict:
    meta = {
        "tournament_name": "Us Open",
        "tournament_year": 2025,
        "model": "serve_return",
        "cutoff_date": "2025-08-25",
        "note": "nota",
        "is_live": False,
        "known_results": {},
        "round_snapshots": [],
    }
    meta.update(overrides)
    return meta


def test_export_structure_has_expected_top_level_keys():
    players = _players(("p1", "Fuerte", 1), ("p2", "Débil", None))
    counts = _make_counts(100, {"p1": {"CAMPEON": 90}, "p2": {"CAMPEON": 10}})
    payload = json_export.build_export(counts, players, _base_meta(), n_simulations=100)
    assert set(payload.keys()) == {"meta", "players", "round_snapshots", "bracket", "round_accuracy"}
    assert payload["meta"]["tournament_name"] == "Us Open"
    assert payload["meta"]["n_simulations"] == 100
    assert payload["meta"]["generated_at"].endswith("Z")


def test_players_sorted_by_champion_probability_descending():
    players = _players(("p1", "Fuerte", 1), ("p2", "Débil", 2))
    counts = _make_counts(100, {"p1": {"CAMPEON": 10}, "p2": {"CAMPEON": 90}})
    payload = json_export.build_export(counts, players, _base_meta(), n_simulations=100)
    assert [p["player_id"] for p in payload["players"]] == ["p2", "p1"]
    assert payload["players"][0]["probabilities"]["CAMPEON"] == 0.9


def test_probabilities_are_normalized_not_raw_counts():
    players = _players(("p1", "Fuerte", 1), ("p2", "Débil", None))
    counts = _make_counts(200, {"p1": {"R32": 150, "CAMPEON": 20}, "p2": {"R32": 50, "CAMPEON": 0}})
    payload = json_export.build_export(counts, players, _base_meta(), n_simulations=200)
    probs = payload["players"][0]["probabilities"]
    assert probs["R32"] == 0.75
    assert probs["CAMPEON"] == 0.1


def test_bracket_uses_player_id_strings_not_player_objects():
    players = _players(("p1", "Fuerte", 1), ("p2", "Débil", None))
    counts = _make_counts(100, {"p1": {"CAMPEON": 90}, "p2": {"CAMPEON": 10}})
    payload = json_export.build_export(counts, players, _base_meta(), n_simulations=100)
    match = payload["bracket"][0]["matches"][0]
    assert isinstance(match["favorite_id"], str)
    assert isinstance(match["underdog_id"], str)
    assert match["favorite_id"] in {"p1", "p2"}


def test_historical_edition_has_empty_round_snapshots():
    # Edición ya jugada: round_snapshots=[] no debe romper el schema.
    players = _players(("p1", "Fuerte", 1), ("p2", "Débil", None))
    counts = _make_counts(100, {"p1": {"CAMPEON": 90}, "p2": {"CAMPEON": 10}})
    payload = json_export.build_export(counts, players, _base_meta(round_snapshots=[]), n_simulations=100)
    assert payload["round_snapshots"] == []


def test_live_edition_with_partial_snapshots():
    # Torneo recién arrancado: solo el snapshot de R128 generado todavía.
    players = _players(("p1", "Fuerte", 1), ("p2", "Débil", None))
    counts_r128 = _make_counts(100, {"p1": {"CAMPEON": 60}, "p2": {"CAMPEON": 40}})
    snapshots = [{"round_name": "R128", "n_simulations": 100, "counts": counts_r128, "frozen": False}]
    meta = _base_meta(is_live=True, round_snapshots=snapshots)
    payload = json_export.build_export(counts_r128, players, meta, n_simulations=100)
    assert len(payload["round_snapshots"]) == 1
    snap = payload["round_snapshots"][0]
    assert snap["round_name"] == "R128"
    assert snap["frozen"] is False
    assert snap["players"]["p1"]["CAMPEON"] == 0.6
    # Nombre no repetido en el snapshot -- solo el player_id (ver docstring).
    assert "full_name" not in snap["players"]["p1"]


def test_non_ascii_names_survive_json_roundtrip(tmp_path):
    players = _players(("p1", "Étcheverry", 5), ("p2", "Muñoz", 6))
    counts = _make_counts(100, {"p1": {"CAMPEON": 10}, "p2": {"CAMPEON": 5}})
    path = json_export.export_json(counts, players, _base_meta(), n_simulations=100, path=tmp_path / "out.json")
    text = path.read_text(encoding="utf-8")
    assert "Étcheverry" in text
    assert "Muñoz" in text
    data = json.loads(text)
    names = {p["full_name"] for p in data["players"]}
    assert {"Étcheverry", "Muñoz"} <= names


def test_export_json_creates_parent_dir_and_is_valid_json(tmp_path):
    players = _players(("p1", "Fuerte", 1), ("p2", "Débil", None))
    counts = _make_counts(100, {"p1": {"CAMPEON": 90}, "p2": {"CAMPEON": 10}})
    out_path = tmp_path / "docs" / "data" / "resultados_simulacion.json"
    assert not out_path.parent.exists()
    result_path = json_export.export_json(counts, players, _base_meta(), n_simulations=100, path=out_path)
    assert result_path == out_path
    assert out_path.exists()
    json.loads(out_path.read_text(encoding="utf-8"))  # no debe lanzar excepción


def test_known_results_with_tuple_keys_does_not_break_export():
    # meta["known_results"] es dict[tuple[str,int], str] -- gotcha explícito
    # del plan (sección 3.1, hallazgo #3): el exportador nunca hace
    # json.dumps(meta) directo, así que esto no debe tirar TypeError.
    players = {
        "p1": Player(player_id="p1", full_name="Favorito", seed=1, serve_pct=0.70, return_pct=0.40),
        "p2": Player(player_id="p2", full_name="Sorpresa", seed=None, serve_pct=0.40, return_pct=0.20),
    }
    counts = _make_counts(100, {"p1": {"CAMPEON": 90}, "p2": {"CAMPEON": 10}})
    known_results = {("F", 1): "p2"}
    meta = _base_meta(is_live=True, known_results=known_results)
    payload = json_export.build_export(counts, players, meta, n_simulations=100)
    json.dumps(payload)  # no debe lanzar TypeError
    # El bracket refleja el ganador real, no el favorito del modelo.
    assert payload["bracket"][0]["matches"][0]["favorite_id"] == "p2"


def test_round_accuracy_round_without_results_has_zero_total():
    # Sin resultados reales todavía (torneo no arrancó, o ronda futura):
    # total=0, no 0% -- el frontend distingue "sin datos" de "acertó 0".
    players = _players(("p1", "Favorito", 1), ("p2", "Sorpresa", None))
    counts = _make_counts(100, {"p1": {"CAMPEON": 90}, "p2": {"CAMPEON": 10}})
    payload = json_export.build_export(counts, players, _base_meta(), n_simulations=100)
    accuracy = {r["round_name"]: r for r in payload["round_accuracy"]}
    assert accuracy["F"] == {"round_name": "F", "correct": 0, "total": 0}


def test_round_accuracy_scores_against_prior_round_prediction_not_actual_winner():
    # El modelo favorece a p1 (mejor serve/return) -- si p2 ganó la final de
    # verdad, eso es un FALLO del modelo, no debe salir 1/1 acierto (esa
    # sería la trampa de comparar contra el favorito ya "sabido").
    players = {
        "p1": Player(player_id="p1", full_name="Favorito", seed=1, serve_pct=0.70, return_pct=0.40),
        "p2": Player(player_id="p2", full_name="Sorpresa", seed=None, serve_pct=0.40, return_pct=0.20),
    }
    counts = _make_counts(100, {"p1": {"CAMPEON": 90}, "p2": {"CAMPEON": 10}})
    known_results = {("F", 1): "p2"}
    meta = _base_meta(is_live=True, known_results=known_results)
    payload = json_export.build_export(counts, players, meta, n_simulations=100)
    accuracy = {r["round_name"]: r for r in payload["round_accuracy"]}
    assert accuracy["F"] == {"round_name": "F", "correct": 0, "total": 1}

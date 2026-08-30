"""Fase 4: persistencia de snapshots de predicción por ronda
(`repository.save_snapshot`/`load_snapshots`), detección de sorteo en vivo
(`repository.is_live_draw`), y la política de congelado/recálculo de
`pipeline._generate_round_snapshots` (D6)."""

from __future__ import annotations

import sqlite3

from src import config
from src.cli import pipeline
from src.data import repository


def _fresh_db(tmp_path):
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(config.SCHEMA_PATH.read_text(encoding="utf-8"))
    return db_path


def _insert_cuadro_row(db_path, source: str, tournament_year: int = 2026):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO cuadro_torneo (tournament_name, tournament_year, round_name, slot_index, player_id, seed, entry_type, source) "
            "VALUES ('Us Open', ?, 'R128', 1, '100001', 1, NULL, ?)",
            (tournament_year, source),
        )
        conn.commit()


# --- is_live_draw -------------------------------------------------------------


def test_is_live_draw_true_when_source_matches(tmp_path):
    db_path = _fresh_db(tmp_path)
    _insert_cuadro_row(db_path, config.LIVE_DRAW_SOURCE)
    assert repository.is_live_draw("Us Open", 2026, db_path=db_path) is True


def test_is_live_draw_false_for_historical_source(tmp_path):
    db_path = _fresh_db(tmp_path)
    _insert_cuadro_row(db_path, "sackmann_r128_reconstructed")
    assert repository.is_live_draw("Us Open", 2026, db_path=db_path) is False


def test_is_live_draw_false_when_db_missing(tmp_path):
    assert repository.is_live_draw("Us Open", 2026, db_path=tmp_path / "no_existe.db") is False


# --- save_snapshot / load_snapshots -------------------------------------------


def test_save_and_load_snapshot_roundtrip(tmp_path):
    db_path = _fresh_db(tmp_path)
    counts = {"100001": {"R128": 100, "CAMPEON": 12}}
    repository.save_snapshot("Us Open", 2026, "R64", "serve_return", 100, counts, frozen=True, db_path=db_path)

    snapshots = repository.load_snapshots("Us Open", 2026, "serve_return", db_path=db_path)
    assert len(snapshots) == 1
    assert snapshots[0]["round_name"] == "R64"
    assert snapshots[0]["frozen"] is True
    assert snapshots[0]["counts"] == counts


def test_save_snapshot_upserts_same_round(tmp_path):
    db_path = _fresh_db(tmp_path)
    repository.save_snapshot("Us Open", 2026, "QF", "serve_return", 100, {"a": {"CAMPEON": 1}}, frozen=False, db_path=db_path)
    repository.save_snapshot("Us Open", 2026, "QF", "serve_return", 200, {"a": {"CAMPEON": 2}}, frozen=True, db_path=db_path)

    snapshots = repository.load_snapshots("Us Open", 2026, "serve_return", db_path=db_path)
    assert len(snapshots) == 1  # pisó, no duplicó
    assert snapshots[0]["n_simulations"] == 200
    assert snapshots[0]["frozen"] is True


def test_load_snapshots_orders_by_match_rounds(tmp_path):
    db_path = _fresh_db(tmp_path)
    for round_name in ["F", "R128", "QF"]:  # a propósito, fuera de orden
        repository.save_snapshot("Us Open", 2026, round_name, "serve_return", 10, {}, frozen=False, db_path=db_path)

    snapshots = repository.load_snapshots("Us Open", 2026, "serve_return", db_path=db_path)
    assert [s["round_name"] for s in snapshots] == ["R128", "QF", "F"]


def test_load_snapshots_separates_by_model(tmp_path):
    db_path = _fresh_db(tmp_path)
    repository.save_snapshot("Us Open", 2026, "R128", "serve_return", 10, {"a": 1}, frozen=True, db_path=db_path)
    repository.save_snapshot("Us Open", 2026, "R128", "elo", 10, {"b": 2}, frozen=True, db_path=db_path)

    assert repository.load_snapshots("Us Open", 2026, "serve_return", db_path=db_path)[0]["counts"] == {"a": 1}
    assert repository.load_snapshots("Us Open", 2026, "elo", db_path=db_path)[0]["counts"] == {"b": 2}


# --- pipeline._generate_round_snapshots (D6: congelado) -----------------------


def _synthetic_players(n: int = 128):
    from src.simulation.monte_carlo import Player

    return [Player(str(i), f"P{i}", None, 0.62, 0.38) for i in range(n)]


def test_generate_round_snapshots_only_baseline_before_tournament_starts(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.executescript(config.SCHEMA_PATH.read_text(encoding="utf-8"))

    draw = _synthetic_players()
    snapshots = pipeline._generate_round_snapshots(
        "Us Open", 2026, "serve_return", False, draw, 20, 1, known_results={},
    )
    assert [s["round_name"] for s in snapshots] == ["R128"]
    assert snapshots[0]["frozen"] is True  # R128 nunca se condiciona en nada -- congelado desde el primer cálculo


def test_generate_round_snapshots_all_rounds_once_started(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.executescript(config.SCHEMA_PATH.read_text(encoding="utf-8"))

    draw = _synthetic_players()
    known = {("R128", 1): "1"}  # el torneo ya arrancó, aunque sea un solo partido
    snapshots = pipeline._generate_round_snapshots(
        "Us Open", 2026, "serve_return", False, draw, 20, 1, known_results=known,
    )
    assert [s["round_name"] for s in snapshots] == config.MATCH_ROUNDS
    # Ninguna ronda más allá de R128 puede estar "congelada" todavía: falta
    # jugar 63 de los 64 partidos de R128 (D6: frozen requiere que TODAS las
    # rondas anteriores estén 100% jugadas).
    for snap in snapshots[1:]:
        assert snap["frozen"] is False


def test_generate_round_snapshots_freezes_round_when_all_prior_matches_decided(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.executescript(config.SCHEMA_PATH.read_text(encoding="utf-8"))

    draw = _synthetic_players()
    known = {("R128", i): str(2 * (i - 1)) for i in range(1, 65)}  # los 64 partidos de R128, ya jugados
    snapshots = pipeline._generate_round_snapshots(
        "Us Open", 2026, "serve_return", False, draw, 20, 1, known_results=known,
    )
    by_round = {s["round_name"]: s for s in snapshots}
    assert by_round["R128"]["frozen"] is True
    assert by_round["R64"]["frozen"] is True  # todo R128 (lo anterior a R64) ya se jugó -- congela
    assert by_round["R32"]["frozen"] is False  # R64 todavía no se jugó nada


def test_generate_round_snapshots_skips_recompute_of_frozen_round(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.executescript(config.SCHEMA_PATH.read_text(encoding="utf-8"))

    draw = _synthetic_players()
    known = {("R128", 1): "1"}
    first = pipeline._generate_round_snapshots("Us Open", 2026, "serve_return", False, draw, 20, 1, known_results=known)
    r128_first = next(s for s in first if s["round_name"] == "R128")
    assert r128_first["frozen"] is True

    # Segunda corrida, con OTRO seed -- si R128 se recalculara, un seed
    # distinto podría (no tiene por qué, pero no hay garantía de que no) dar
    # otro resultado; como está congelado, `_generate_round_snapshots` debe
    # devolver el mismo conteo guardado sin volver a simular.
    second = pipeline._generate_round_snapshots("Us Open", 2026, "serve_return", False, draw, 20, 999, known_results=known)
    r128_second = next(s for s in second if s["round_name"] == "R128")
    assert r128_second["counts"] == r128_first["counts"]

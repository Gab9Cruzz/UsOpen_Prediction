"""Ninguna métrica de entrada puede usar datos de la fecha de corte en
adelante (plan sección 7.6/14.2). `compute_surface_metrics` y
`_latest_rank_before_cutoff` ya filtran `tourney_date < cutoff`; estos tests
prueban con un partido sintético exactamente EN el corte que, si algún día
alguien cambia `<` por `<=`, debe empezar a fallar."""

from __future__ import annotations

import pandas as pd

from src.data.ingest import _cutoff_date_for, _latest_rank_before_cutoff, compute_surface_metrics

CUTOFF = 20250825  # arranque ficticio del US Open 2025


def _match(date: int, winner_id=1, loser_id=2, winner_rank=5, loser_rank=50) -> dict:
    return {
        "surface": "Hard",
        "tourney_date": date,
        "tourney_name": "Us Open",
        "round": "R128",
        "match_num": 1,
        "winner_id": winner_id, "winner_name": "Winner", "winner_rank": winner_rank,
        "loser_id": loser_id, "loser_name": "Loser", "loser_rank": loser_rank,
        "w_svpt": 80, "w_1stWon": 40, "w_2ndWon": 10,
        "l_svpt": 75, "l_1stWon": 30, "l_2ndWon": 8,
    }


def test_compute_surface_metrics_excludes_matches_on_or_after_cutoff():
    before = _match(CUTOFF - 1, winner_id=1, loser_id=2)
    on_cutoff = _match(CUTOFF, winner_id=3, loser_id=4)  # NO debe entrar
    after = _match(CUTOFF + 1, winner_id=5, loser_id=6)  # NO debe entrar
    df = pd.DataFrame([before, on_cutoff, after])

    out = compute_surface_metrics(df, "Hard", CUTOFF)

    included_ids = set(out["player_id"])
    assert included_ids == {"1", "2"}


def test_latest_rank_before_cutoff_excludes_matches_on_or_after_cutoff():
    before = _match(CUTOFF - 1, winner_id=1, loser_id=2, winner_rank=5, loser_rank=50)
    on_cutoff = _match(CUTOFF, winner_id=1, loser_id=2, winner_rank=1, loser_rank=1)  # NO debe pisar el rank previo
    df = pd.DataFrame([before, on_cutoff])

    ranks = _latest_rank_before_cutoff(df, CUTOFF)

    assert ranks.loc["1", "rank"] == 5
    assert ranks.loc["2", "rank"] == 50


def test_cutoff_date_for_reads_from_dataset_not_hardcoded():
    df = pd.DataFrame([_match(20240826), _match(20230828)])
    df.loc[0, "tourney_name"] = "Us Open"
    df.loc[0, "tourney_date"] = 20240826
    df.loc[1, "tourney_name"] = "Us Open"
    df.loc[1, "tourney_date"] = 20230828
    assert _cutoff_date_for("Us Open", 2024, df) == 20240826
    assert _cutoff_date_for("Us Open", 2023, df) == 20230828

"""T1 — test de regresión del cuadro (plan sección 2, "Lo que ya está bien"):
reconstruir el R128 vía `build_draw` y emparejar los ganadores de matches
adyacentes debe reproducir 32/32 de los enfrentamientos reales de R64 del US
Open 2025. Si esto deja de dar 32/32, `build_draw` se rompió."""

from __future__ import annotations

import pandas as pd
import pytest

from src import config
from src.data.ingest import build_draw

CSV_PATH = config.DATA_RAW_DIR / "atp_matches_2025.csv"

pytestmark = pytest.mark.skipif(
    not CSV_PATH.exists(), reason=f"Falta {CSV_PATH.name} en data/raw — correr --update-data primero"
)


@pytest.fixture(scope="module")
def matches_2025() -> pd.DataFrame:
    return pd.read_csv(CSV_PATH, low_memory=False)


def test_r128_to_r64_pairings_match_real_bracket(matches_2025: pd.DataFrame):
    draw_df = build_draw(matches_2025, "Us Open", 2025).sort_values("slot_index").reset_index(drop=True)
    assert len(draw_df) == 128

    predicted_pairs = set()
    for i in range(0, len(draw_df), 4):
        winner_match_k = draw_df.iloc[i]["player_id"]        # slot base: ganador del R128 match k
        winner_match_k1 = draw_df.iloc[i + 2]["player_id"]   # slot base del siguiente match: ganador del match k+1
        predicted_pairs.add(frozenset({winner_match_k, winner_match_k1}))
    assert len(predicted_pairs) == 32

    mask = (
        matches_2025["tourney_name"].str.contains("Us Open", case=False, na=False)
        & (matches_2025["tourney_date"] // 10000 == 2025)
        & (matches_2025["round"] == "R64")
    )
    r64 = matches_2025.loc[mask]
    actual_pairs = {
        frozenset({str(int(row["winner_id"])), str(int(row["loser_id"]))})
        for _, row in r64.iterrows()
    }

    matched = predicted_pairs & actual_pairs
    assert len(matched) == 32, f"Solo {len(matched)}/32 emparejamientos de R64 coinciden con el cuadro real"


def test_build_draw_slots_are_1_to_128_without_gaps(matches_2025: pd.DataFrame):
    draw_df = build_draw(matches_2025, "Us Open", 2025)
    assert sorted(draw_df["slot_index"]) == list(range(1, 129))
    assert draw_df["player_id"].notna().all()

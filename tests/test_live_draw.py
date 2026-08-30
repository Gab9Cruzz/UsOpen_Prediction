"""Fase 4 (sorteo en vivo): parsing de las plantillas de bracket de
Wikipedia, resolución de nombres contra Sackmann, y el fallback a cache
cuando Wikipedia no responde. Todo offline -- ningún test acá pega a la red
de verdad, se monkeypatchean las funciones de fetch (mismo criterio que
`tests/test_draw.py`, que solo corre contra un CSV ya descargado)."""

from __future__ import annotations

import json

import pytest

from src import config
from src.data import live_draw

# Wikitext real (recortado a lo necesario) tomado de la Sección 1 del US Open
# 2026 -- sorteo anunciado, ningún partido jugado todavía.
UNPLAYED_SECTION = """
==== Section 1 ====
{{16TeamBracket-Compact-Tennis5
| RD1-seed01=1
| RD1-team01={{flagicon|GER}} [[Alexander Zverev|A Zverev]]
| RD1-seed02=
| RD1-team02={{flagicon|ITA}} [[Lorenzo Sonego|L Sonego]]
| RD1-seed03=
| RD1-team03={{flagicon|FRA}} [[Quentin Halys|Q Halys]]
| RD1-seed04=
| RD1-team04={{flagicon|ARG}} [[Facundo Díaz Acosta|F Díaz Acosta]]
| RD1-seed05=Q
| RD1-team05={{flagicon|BUL}} [[Grigor Dimitrov|G Dimitrov]]
| RD1-seed06=
| RD1-team06={{flagicon|AUS}} [[Alexei Popyrin|A Popyrin]]
| RD1-seed07=
| RD1-team07={{flagicon|GER}} [[Yannick Hanfmann|Y Hanfmann]]
| RD1-seed08=25
| RD1-team08={{flagicon|CHI}} [[Alejandro Tabilo|A Tabilo]]
| RD1-seed09=21
| RD1-team09={{flagicon|ITA}} [[Luciano Darderi|L Darderi]]
| RD1-seed10=Q
| RD1-team10={{flagicon|GBR}} [[Harry Wendelken|H Wendelken]]
| RD1-seed11=Q
| RD1-team11={{flagicon|CZE}} [[Dalibor Svrčina|D Svrčina]]
| RD1-seed12=
| RD1-team12={{flagicon|FRA}} [[Valentin Royer|V Royer]]
| RD1-seed13=WC
| RD1-team13={{flagicon|AUS}} [[Dane Sweeny|D Sweeny]]
| RD1-seed14=
| RD1-team14={{flagicon|FRA}} [[Corentin Moutet|C Moutet]]
| RD1-seed15=
| RD1-team15={{flagicon|GBR}} [[Arthur Fery|A Fery]]
| RD1-seed16=13
| RD1-team16={{flagicon|ITA}} [[Lorenzo Musetti|L Musetti]]
| RD2-seed01=
| RD2-team01=
| RD2-seed02=
| RD2-team02=
}}
"""

# Wikitext real (recortado) de la Sección 1 del US Open 2025, YA jugada hasta
# la cuarta ronda (Sinner gana la sección) -- para probar la detección de
# ganador real vía negrita.
PLAYED_SECTION = """
==== Section 1 ====
{{16TeamBracket-Compact-Tennis5
| RD1-seed01=1
| RD1-team01='''{{flagicon|ITA}} [[Jannik Sinner|J Sinner]]'''
| RD1-seed02=
| RD1-team02={{flagicon|CZE}} [[Vít Kopřiva|V Kopřiva]]
| RD2-seed01=1
| RD2-team01='''{{flagicon|ITA}} [[Jannik Sinner|J Sinner]]'''
| RD2-seed02=
| RD2-team02={{flagicon|AUS}} [[Alexei Popyrin|A Popyrin]]
| RD3-seed01=1
| RD3-team01='''{{flagicon|ITA}} [[Jannik Sinner|J Sinner]]'''
| RD3-seed02=27
| RD3-team02={{flagicon|CAN}} [[Denis Shapovalov|D Shapovalov]]
| RD4-seed01=1
| RD4-team01='''{{flagicon|ITA}} [[Jannik Sinner|J Sinner]]'''
| RD4-seed02=23
| RD4-team02={{flagicon|KAZ}} [[Alexander Bublik|A Bublik]]
}}
"""

FINALS_UNPLAYED = """
=== Finals ===
{{8TeamBracket-Tennis5
| RD1-seed1=
| RD1-team1=
| RD1-seed2=
| RD1-team2=
}}
"""


def test_parse_bracket_wikitext_extracts_all_slots():
    parsed = live_draw._parse_bracket_wikitext(UNPLAYED_SECTION)
    assert set(parsed[1].keys()) == set(range(1, 17))
    slot1 = parsed[1][1]
    assert slot1.seed == 1
    assert slot1.entry_type is None
    assert slot1.country == "GER"
    assert slot1.wiki_title == "Alexander Zverev"
    assert slot1.won is False


def test_parse_bracket_wikitext_entry_type_when_no_seed():
    parsed = live_draw._parse_bracket_wikitext(UNPLAYED_SECTION)
    slot5 = parsed[1][5]
    assert slot5.seed is None
    assert slot5.entry_type == "Q"


def test_parse_bracket_wikitext_empty_slot_has_no_title():
    parsed = live_draw._parse_bracket_wikitext(UNPLAYED_SECTION)
    assert parsed[2][1].wiki_title is None
    assert parsed[2][1].won is False


def test_parse_bracket_wikitext_detects_bold_winner():
    parsed = live_draw._parse_bracket_wikitext(PLAYED_SECTION)
    assert parsed[1][1].won is True
    assert parsed[1][1].wiki_title == "Jannik Sinner"
    assert parsed[1][2].won is False


def test_draw_skeleton_slot_indices_span_two_sections():
    parsed_a = live_draw._parse_bracket_wikitext(UNPLAYED_SECTION)
    parsed_b = live_draw._parse_bracket_wikitext(UNPLAYED_SECTION)  # misma data, alcanza para el offset
    skeleton = live_draw._draw_skeleton_from_sections([parsed_a, parsed_b])
    assert len(skeleton) == 32
    assert [row["slot_index"] for row in skeleton] == list(range(1, 33))
    assert skeleton[0]["wiki_title"] == "Alexander Zverev"
    assert skeleton[16]["wiki_title"] == "Alexander Zverev"  # segunda sección, mismo offset+1


def test_draw_skeleton_raises_on_incomplete_section():
    incomplete = "==== Section 1 ====\n{{16TeamBracket-Compact-Tennis5\n| RD1-seed01=1\n| RD1-team01={{flagicon|GER}} [[Alexander Zverev]]\n}}\n"
    parsed = live_draw._parse_bracket_wikitext(incomplete)
    with pytest.raises(live_draw.LiveDrawError):
        live_draw._draw_skeleton_from_sections([parsed])


def test_known_results_from_sections_uses_global_match_index():
    parsed = live_draw._parse_bracket_wikitext(PLAYED_SECTION)
    known = live_draw._known_results_from_sections([parsed])
    # Sinner es slot 1 de la sección 0 -> partido 1 de R128, R64, R32 y R16.
    assert known[("R128", 1)] == "Jannik Sinner"
    assert known[("R64", 1)] == "Jannik Sinner"
    assert known[("R32", 1)] == "Jannik Sinner"
    assert known[("R16", 1)] == "Jannik Sinner"
    # El rival del R128 (Kopřiva) no ganó nada -- no debe aparecer como ganador de nada.
    assert "Vít Kopřiva" not in known.values()


def test_known_results_from_sections_second_section_offsets_match_index():
    parsed = live_draw._parse_bracket_wikitext(PLAYED_SECTION)
    known = live_draw._known_results_from_sections([parsed, parsed])
    # Misma sección repetida como "sección 2" (índice 1): partido 1 de esa
    # sección es el partido 9 global de R128 (8 partidos por sección).
    assert known[("R128", 9)] == "Jannik Sinner"
    assert known[("R16", 2)] == "Jannik Sinner"  # 1 partido de R16 por sección


def test_known_results_from_finals_uses_local_match_index_directly():
    parsed = live_draw._parse_bracket_wikitext(
        "=== Finals ===\n{{8TeamBracket-Tennis5\n"
        "| RD1-seed1=1\n| RD1-team1='''{{flagicon|ITA}} [[Jannik Sinner]]'''\n"
        "| RD1-seed2=2\n| RD1-team2={{flagicon|ESP}} [[Carlos Alcaraz]]\n"
        "}}\n"
    )
    known = live_draw._known_results_from_finals(parsed)
    assert known[("QF", 1)] == "Jannik Sinner"


def test_known_results_from_finals_empty_when_unplayed():
    parsed = live_draw._parse_bracket_wikitext(FINALS_UNPLAYED)
    assert live_draw._known_results_from_finals(parsed) == {}


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Nuno Borges (tennis)", "nuno borges"),
        ("Vít Kopřiva", "vit kopriva"),
        ("Jan-Lennard Struff", "jan-lennard struff"),
        ("", ""),
    ],
)
def test_normalize_name(raw, expected):
    assert live_draw.normalize_name(raw) == expected


def test_resolve_player_ids_prefers_wikidata_qid(monkeypatch):
    monkeypatch.setattr(live_draw, "_fetch_wikidata_qids", lambda titles: {"Alex de Minaur": "Q22958938"})
    monkeypatch.setattr(
        live_draw,
        "_load_players_index",
        lambda: live_draw._PlayersIndex(
            by_wikidata={"Q22958938": "200282"}, by_norm_name={"alex de minaur": "999999"}, name_by_id={"200282": "Alex De Minaur"}
        ),
    )
    resolved = live_draw.resolve_player_ids(["Alex de Minaur"])
    assert resolved["Alex de Minaur"] == "200282"  # wikidata gana sobre el nombre normalizado


def test_resolve_player_ids_falls_back_to_normalized_name(monkeypatch):
    monkeypatch.setattr(live_draw, "_fetch_wikidata_qids", lambda titles: {})
    monkeypatch.setattr(
        live_draw,
        "_load_players_index",
        lambda: live_draw._PlayersIndex(by_wikidata={}, by_norm_name={"rafael jodar": "212588"}, name_by_id={}),
    )
    resolved = live_draw.resolve_player_ids(["Rafael Jódar"])
    assert resolved["Rafael Jódar"] == "212588"


def test_resolve_player_ids_falls_back_to_manual_alias(monkeypatch):
    monkeypatch.setattr(live_draw, "_fetch_wikidata_qids", lambda titles: {})
    monkeypatch.setattr(
        live_draw, "_load_players_index", lambda: live_draw._PlayersIndex(by_wikidata={}, by_norm_name={}, name_by_id={})
    )
    monkeypatch.setattr(live_draw, "PLAYER_NAME_ALIASES", {"bu yunchaokete": "208029"})
    resolved = live_draw.resolve_player_ids(["Bu Yunchaokete"])
    assert resolved["Bu Yunchaokete"] == "208029"


def test_resolve_player_ids_raises_with_exact_unmatched_names(monkeypatch):
    monkeypatch.setattr(live_draw, "_fetch_wikidata_qids", lambda titles: {})
    monkeypatch.setattr(
        live_draw, "_load_players_index", lambda: live_draw._PlayersIndex(by_wikidata={}, by_norm_name={}, name_by_id={})
    )
    monkeypatch.setattr(live_draw, "PLAYER_NAME_ALIASES", {})
    with pytest.raises(live_draw.UnresolvedPlayersError) as exc_info:
        live_draw.resolve_player_ids(["Un Jugador Fantasma"])
    assert "Un Jugador Fantasma" in exc_info.value.titles


def test_fetch_live_bracket_state_falls_back_to_cache_on_network_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_RAW_DIR", tmp_path)
    cache_path = tmp_path / "live_draw_us_open_2026.json"
    cache_path.write_text(
        json.dumps({"draw": [{"slot_index": 1, "player_id": "100001", "full_name": "Cached Player",
                               "country": None, "seed": 1, "entry_type": None, "source": "wikipedia_live"}]}),
        encoding="utf-8",
    )

    def _boom(title):
        raise live_draw.FetchError("Wikipedia no respondió (simulado)")

    monkeypatch.setattr(live_draw, "_fetch_all_sections_wikitext", _boom)

    state = live_draw.fetch_live_bracket_state("Us Open", 2026)
    assert state.draw[0]["player_id"] == "100001"
    assert state.known_results == {}


def test_fetch_live_bracket_state_raises_without_cache_or_network(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_RAW_DIR", tmp_path)

    def _boom(title):
        raise live_draw.FetchError("Wikipedia no respondió (simulado)")

    monkeypatch.setattr(live_draw, "_fetch_all_sections_wikitext", _boom)

    with pytest.raises(live_draw.LiveDrawError):
        live_draw.fetch_live_bracket_state("Us Open", 2026)

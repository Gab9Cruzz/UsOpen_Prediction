"""Sorteo oficial en vivo (Fase 4 del plan de mejora), parseado de Wikipedia.

Cuando `ingest.build_draw` no encuentra R128 histórico para la edición
pedida -- porque el torneo todavía no se jugó -- `run_ingest` cae acá. En
cuanto se anuncia un sorteo de Grand Slam, los editores de Wikipedia arman el
bracket completo (128 jugadores, seeds, emparejamientos) usando plantillas
`{{16TeamBracket-Compact-Tennis5}}` (una por sección de 16, ronda de 128 a
ronda de 16) y `{{8TeamBracket-Tennis5}}` (cuartos/semis/final, combinando
las 8 secciones) -- y, a medida que el torneo avanza, esas MISMAS plantillas
se van completando con el ganador real de cada partido jugado (marcado en
negrita wikitexto, `'''...'''`). Este módulo no solo lee el sorteo inicial:
lee el estado actual del cuadro completo, en cualquier momento del torneo.

Diseño (ver conversación de /plan-eng-review, D1/D2/D3/D5/D8):
- D1: `ingest.run_ingest` decide solo (sin flag) cuándo usar esto -- intenta
  la reconstrucción histórica primero, cae acá si no hay R128 en Sackmann.
- D2/D3: el motor de simulación (`src/simulation/`) recibe los resultados ya
  conocidos (`known_results`, ver `fetch_live_bracket_state`) y los usa como
  hecho consumado en cada una de las N corridas Monte Carlo, en vez de
  tirar la moneda para un partido que ya se jugó de verdad.
- D3 (nombres): resolución en dos capas -- (1) Wikidata QID de la página de
  Wikipedia contra la columna `wikidata_id` de `atp_players.csv` (bien
  cuando existe: no importa acento, orden de nombre ni apodo); (2) nombre
  normalizado (`normalize_name`) como respaldo. Lo que no matchea por
  NINGUNA de las dos vías falla la ingesta con la lista exacta de nombres --
  se agregan a mano a `PLAYER_NAME_ALIASES` (nunca un player_id inventado en
  silencio, a pedido explícito).
- D8: el ESTADO del cuadro (quién ganó qué) se pide siempre fresco a
  Wikipedia, nunca de cache -- el sorteo ya resuelto se cachea en
  `data/raw/` solo como respaldo offline si Wikipedia no responde.
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

from src import config

logger = logging.getLogger(__name__)

_ENTRY_TYPES = {"Q", "WC", "LL", "PR", "SE", "ALT"}

# [ \t]* (no \s*) alrededor del "=" y al final: `\s` matchea saltos de línea,
# y con un valor vacío (p.ej. "RD1-seed02=" sin nada después) un `\s*`
# codicioso ahí se come el propio salto de línea antes de que `(.*?)$`
# entre a jugar -- el lazy `.*?` termina extendiéndose hasta el `$` de la
# LÍNEA SIGUIENTE (que sí puede alcanzar, `.` no cruza `\n` pero el primer
# `\s*` ya cruzó esa frontera él solo), fusionando dos campos en un único
# match. Confirmado con un caso mínimo antes de este fix -- ver
# tests/test_live_draw.py.
_FIELD_RE = re.compile(r"^\|[ \t]*RD(\d+)-(seed|team)(\d+)[ \t]*=[ \t]*(.*?)[ \t]*$", re.MULTILINE)
_FLAG_RE = re.compile(r"\{\{flagicon\|([A-Za-z]*)\}\}")
_LINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]")
_DISAMBIGUATION_RE = re.compile(r"\s*\([^)]*\)\s*$")

# Profundidad de ronda (RD1..RD4) dentro de una plantilla de sección -> ronda
# global, y cuántos partidos tiene esa ronda POR SECCIÓN (16 jugadores por
# sección: RD1=8 partidos, RD2=4, RD3=2, RD4=1 -- el campeón de la sección,
# que entra a cuartos). `Finals` usa su propia numeración (RD1=cuartos,
# ver `FINALS_DEPTH_ROUNDS`), sin offset de sección.
SECTION_DEPTH_ROUNDS = {1: "R128", 2: "R64", 3: "R32", 4: "R16"}
_MATCHES_PER_SECTION_AT_DEPTH = {1: 8, 2: 4, 3: 2, 4: 1}
FINALS_DEPTH_ROUNDS = {1: "QF", 2: "SF", 3: "F"}

# D3: alias curados a mano -- nombre de Wikipedia normalizado (`normalize_name`)
# -> player_id de Sackmann, para los casos donde ni el QID de Wikidata ni la
# normalización automática alcanzan (orden de nombre distinto, mononimos,
# transliteración distinta). Completar acá cuando `fetch_live_bracket_state`
# falle listando nombres sin resolver -- nunca generar un player_id inventado.
PLAYER_NAME_ALIASES: dict[str, str] = {
    # Wikipedia usa "Daniel Mérida" (forma corta habitual en medios); Sackmann
    # lo tiene con el segundo apellido completo ("Merida Aguilar") y sin
    # wikidata_id todavía (jugador nuevo) -- verificado corriendo la ingesta
    # real del sorteo 2026 (único nombre sin resolver de los 128).
    "daniel merida": "210017",
}


class LiveDrawError(RuntimeError):
    """Error genérico armando el sorteo/estado en vivo desde Wikipedia."""


class FetchError(LiveDrawError):
    """No se pudo obtener una página/sección desde la API de Wikipedia."""


class UnresolvedPlayersError(LiveDrawError):
    """Uno o más nombres del sorteo en vivo no matchearon ningún player_id."""

    def __init__(self, titles: list[str]):
        self.titles = titles
        joined = ", ".join(titles)
        super().__init__(
            "No se pudo identificar a estos jugadores del sorteo en vivo contra la base de "
            f"Sackmann: {joined}. Agregalos a live_draw.PLAYER_NAME_ALIASES "
            "(normalize_name(nombre_de_wikipedia) -> player_id) y reintentá."
        )


@dataclass
class BracketSlot:
    seed: int | None
    entry_type: str | None
    country: str | None
    wiki_title: str | None
    won: bool


@dataclass
class LiveBracketState:
    """`draw`: 128 filas listas para `cuadro_torneo` (slot_index/player_id/
    seed/entry_type/source), en el mismo orden 1..128 que usa
    `ingest.build_draw` para el cuadro histórico -- intercambiables.
    `known_results`: (round_name, match_index) -> player_id, solo para
    partidos que YA se jugaron de verdad; ver `src/simulation/monte_carlo.py`
    para cómo el motor los usa como hecho consumado en cada simulación."""

    draw: list[dict]
    known_results: dict[tuple[str, int], str]


# --- Wikipedia API -----------------------------------------------------------

_USER_AGENT = "Predecir-USOpen/1.0 (proyecto personal de predicción de torneos; sin contacto público)"


def _api_get(params: dict, _retried: bool = False) -> dict:
    query = {**params, "format": "json", "formatversion": "2"}
    try:
        resp = requests.get(
            config.WIKIPEDIA_API_URL, params=query, timeout=30, headers={"User-Agent": _USER_AGENT}
        )
        if resp.status_code == 429 and not _retried:
            # Rate limit -- un solo reintento respetando Retry-After si lo
            # manda (si no, un backoff fijo corto). Wikipedia lo tira de vez
            # en cuando bajo tráfico compartido; casi siempre transitorio.
            wait_s = float(resp.headers.get("Retry-After", 2))
            logger.warning("Wikipedia API devolvió 429 (rate limit) -- reintentando en %.0fs.", wait_s)
            time.sleep(wait_s)
            return _api_get(params, _retried=True)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise FetchError(f"Wikipedia API no respondió para {params}: {exc}") from exc
    data = resp.json()
    if "error" in data:
        raise FetchError(f"Wikipedia API devolvió error para {params}: {data['error'].get('info')}")
    return data


def _fetch_sections(title: str) -> list[dict]:
    data = _api_get({"action": "parse", "page": title, "prop": "sections"})
    return data["parse"]["sections"]


def _fetch_wikitext(title: str, section_idx) -> str:
    data = _api_get({"action": "parse", "page": title, "prop": "wikitext", "section": section_idx})
    return data["parse"]["wikitext"]


def _fetch_wikidata_qids(titles: list[str]) -> dict[str, str]:
    """título de Wikipedia -> QID de Wikidata, en lotes de 50 (límite de la
    API sin credenciales de bot). Sigue redirects (p.ej. un jugador cuyo
    título cambió de "X" a "X (tennis)" tras desambiguar).

    Es la capa de matching MÁS confiable (D3) pero no la única -- si la API
    falla (rate limit 429, timeout, lo que sea) esto NO debe tirar abajo
    toda la ingesta: se loggea y se sigue con lo que se pudo resolver hasta
    ese lote, dejando que `resolve_player_ids` caiga al nombre normalizado
    (segunda capa) para el resto. Solo si NINGUNA de las dos capas resuelve
    a alguien falla la ingesta (`UnresolvedPlayersError`, con la lista
    exacta) -- eso sí es una falla real, no una degradación aceptable."""
    qids: dict[str, str] = {}
    for i in range(0, len(titles), 50):
        batch = titles[i : i + 50]
        try:
            data = _api_get(
                {"action": "query", "prop": "pageprops", "titles": "|".join(batch), "redirects": 1}
            )
        except FetchError as exc:
            logger.warning(
                "No se pudo consultar Wikidata para %d jugador(es) (lote %d) -- se resuelven por "
                "nombre normalizado en su lugar: %s",
                len(batch), i // 50 + 1, exc,
            )
            continue
        query = data.get("query", {})
        for page in query.get("pages", []):
            title = page.get("title")
            qid = page.get("pageprops", {}).get("wikibase_item")
            if title and qid:
                qids[title] = qid
        for redirect in query.get("redirects", []):
            to_qid = qids.get(redirect.get("to"))
            if to_qid and redirect.get("from"):
                qids[redirect["from"]] = to_qid
    return qids


def _fetch_all_sections_wikitext(title: str) -> tuple[list[str], str]:
    """Devuelve (wikitext de las 8 "Section N" en orden 1..8, wikitext de
    "Finals"). Encuentra los índices de sección dinámicamente (no
    hardcodeados: cambian de edición a edición si alguien edita el artículo)."""
    sections = _fetch_sections(title)
    section_entries: list[tuple[int, object]] = []
    finals_idx = None
    for entry in sections:
        line = (entry.get("line") or "").strip()
        m = re.match(r"^Section\s+(\d+)$", line)
        if m:
            section_entries.append((int(m.group(1)), entry["index"]))
        elif line == "Finals":
            finals_idx = entry["index"]

    if len(section_entries) != 8 or finals_idx is None:
        raise LiveDrawError(
            f"Estructura de {title!r} inesperada para un cuadro de 128: se esperaban 8 "
            f"'Section N' + 'Finals', se encontraron {len(section_entries)} secciones "
            f"({'con' if finals_idx is not None else 'sin'} Finals). ¿Cambió el formato del "
            "artículo, o el draw todavía no tiene las 8 secciones publicadas?"
        )
    section_entries.sort(key=lambda t: t[0])
    section_wikitexts = [_fetch_wikitext(title, idx) for _, idx in section_entries]
    finals_wikitext = _fetch_wikitext(title, finals_idx)
    return section_wikitexts, finals_wikitext


# --- Parsing de la plantilla de bracket --------------------------------------


def _parse_seed(raw: str) -> tuple[int | None, str | None]:
    raw = raw.strip()
    if not raw:
        return None, None
    if raw.isdigit():
        return int(raw), None
    # Cualquier marca no numérica (Q/WC/LL/PR/SE/ALT, o algo más raro que
    # Wikipedia use en el futuro) se guarda como entry_type tal cual -- nunca
    # se descarta en silencio.
    return None, raw


def _parse_team(raw: str) -> tuple[str | None, str | None, bool]:
    won = "'''" in raw
    flag_match = _FLAG_RE.search(raw)
    country = (flag_match.group(1) or None) if flag_match else None
    link_match = _LINK_RE.search(raw)
    wiki_title = link_match.group(1).strip() if link_match else None
    return wiki_title, country, won


def _parse_bracket_wikitext(wikitext: str) -> dict[int, dict[int, BracketSlot]]:
    """Parsea UN template de bracket (`{{16TeamBracket-Compact-Tennis5}}` de
    una sección, o `{{8TeamBracket-Tennis5}}` de Finals) a
    `{profundidad: {slot: BracketSlot}}`. Profundidad 1..4 para una sección
    (R128..R16), 1..3 para Finals (QF..F). El slot es el número de equipo
    dentro de esa ronda tal como lo numera Wikipedia (con o sin cero a la
    izquierda -- el regex matchea ambos, se castea a int)."""
    seeds: dict[tuple[int, int], str] = {}
    teams: dict[tuple[int, int], str] = {}
    for depth_str, kind, slot_str, value in _FIELD_RE.findall(wikitext):
        key = (int(depth_str), int(slot_str))
        if kind == "seed":
            seeds[key] = value
        else:
            teams[key] = value

    result: dict[int, dict[int, BracketSlot]] = {}
    for (depth, slot), team_raw in teams.items():
        wiki_title, country, won = _parse_team(team_raw)
        seed, entry_type = _parse_seed(seeds.get((depth, slot), ""))
        result.setdefault(depth, {})[slot] = BracketSlot(seed, entry_type, country, wiki_title, won)
    return result


def _draw_skeleton_from_sections(sections_parsed: list[dict[int, dict[int, BracketSlot]]]) -> list[dict]:
    """RD1 (ronda de 128) de las 8 secciones, en orden -- el sorteo anunciado,
    128 slots. Sección `s` (0-based) aporta los slots globales
    `s*16+1 .. s*16+16`."""
    skeleton: list[dict] = []
    for s_idx, parsed in enumerate(sections_parsed):
        depth1 = parsed.get(1, {})
        for slot in range(1, 17):
            bslot = depth1.get(slot)
            if bslot is None or not bslot.wiki_title:
                raise LiveDrawError(
                    f"Sorteo incompleto en Wikipedia: falta el jugador de la sección {s_idx + 1}, "
                    f"posición {slot} (RD1-team{slot:02d})."
                )
            skeleton.append(
                {
                    "slot_index": s_idx * 16 + slot,
                    "seed": bslot.seed,
                    "entry_type": bslot.entry_type,
                    "country": bslot.country,
                    "wiki_title": bslot.wiki_title,
                }
            )
    return skeleton


def _known_results_from_sections(
    sections_parsed: list[dict[int, dict[int, BracketSlot]]],
) -> dict[tuple[str, int], str]:
    """Resultados reales ya decididos dentro de cada sección (R128..R16):
    para cada partido, el ganador es quien tenga `won=True` en su propio
    slot de esa profundidad -- no hace falta mirar la ronda siguiente."""
    known: dict[tuple[str, int], str] = {}
    for s_idx, parsed in enumerate(sections_parsed):
        for depth, round_name in SECTION_DEPTH_ROUNDS.items():
            matches_per_section = _MATCHES_PER_SECTION_AT_DEPTH[depth]
            for slot, bslot in parsed.get(depth, {}).items():
                if not bslot.won or not bslot.wiki_title:
                    continue
                local_match = (slot - 1) // 2 + 1
                global_match = s_idx * matches_per_section + local_match
                known[(round_name, global_match)] = bslot.wiki_title
    return known


def _known_results_from_finals(parsed: dict[int, dict[int, BracketSlot]]) -> dict[tuple[str, int], str]:
    known: dict[tuple[str, int], str] = {}
    for depth, round_name in FINALS_DEPTH_ROUNDS.items():
        for slot, bslot in parsed.get(depth, {}).items():
            if not bslot.won or not bslot.wiki_title:
                continue
            local_match = (slot - 1) // 2 + 1
            known[(round_name, local_match)] = bslot.wiki_title
    return known


# --- Resolución de nombres contra Sackmann -----------------------------------


def normalize_name(name: str) -> str:
    """Nombre de Wikipedia -> forma comparable contra Sackmann: saca el
    sufijo de desambiguación ("Nuno Borges (tennis)" -> "Nuno Borges"),
    saca acentos (NFKD + descarta combining marks) y normaliza mayúsculas/
    espacios. NO alcanza para casos de orden de nombre distinto o
    transliteración distinta -- eso va en `PLAYER_NAME_ALIASES`."""
    if not name:
        return ""
    name = _DISAMBIGUATION_RE.sub("", name)
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    ascii_name = re.sub(r"[^A-Za-z\s-]", "", ascii_name)
    return " ".join(ascii_name.lower().split())


@dataclass
class _PlayersIndex:
    by_wikidata: dict[str, str]
    by_norm_name: dict[str, str]
    name_by_id: dict[str, str]


def _load_players_index() -> _PlayersIndex:
    path = config.DATA_RAW_DIR / config.PLAYERS_FILE
    df = pd.read_csv(path, low_memory=False)
    df["player_id"] = df["player_id"].astype(str)

    by_wikidata: dict[str, str] = {}
    by_norm_name: dict[str, str] = {}
    name_by_id: dict[str, str] = {}
    for row in df.itertuples(index=False):
        pid = row.player_id
        full_name = f"{row.name_first or ''} {row.name_last or ''}".strip()
        name_by_id[pid] = full_name
        norm = normalize_name(full_name)
        # Primer player_id gana en caso de nombre duplicado -- raro (dos
        # jugadores homónimos), pero no debe pisar silenciosamente al que ya
        # estaba: el que llegue segundo termina resuelto por wikidata_id o
        # por alias manual en vez de por este índice.
        if norm and norm not in by_norm_name:
            by_norm_name[norm] = pid
        wikidata_id = getattr(row, "wikidata_id", None)
        if isinstance(wikidata_id, str) and wikidata_id:
            by_wikidata[wikidata_id] = pid
    return _PlayersIndex(by_wikidata, by_norm_name, name_by_id)


def resolve_player_ids(wiki_titles: list[str]) -> dict[str, str]:
    """título de Wikipedia -> player_id de Sackmann. Dos capas de matching
    (QID de Wikidata, nombre normalizado + alias manual); lo que no resuelve
    NINGUNA de las dos hace fallar la ingesta con la lista exacta (D3: nunca
    un player_id sintético en silencio)."""
    unique_titles = sorted({t for t in wiki_titles if t})
    qids = _fetch_wikidata_qids(unique_titles)
    idx = _load_players_index()

    resolved: dict[str, str] = {}
    unresolved: list[str] = []
    for title in unique_titles:
        pid = None
        qid = qids.get(title)
        if qid:
            pid = idx.by_wikidata.get(qid)
        if pid is None:
            norm = normalize_name(title)
            pid = idx.by_norm_name.get(norm) or PLAYER_NAME_ALIASES.get(norm)
        if pid is None:
            unresolved.append(title)
        else:
            resolved[title] = pid

    if unresolved:
        raise UnresolvedPlayersError(unresolved)
    return resolved


# --- Orquestación pública -----------------------------------------------------


def _wiki_title_for(tournament_name: str, draw_year: int) -> str:
    key = tournament_name.strip().lower()
    template = config.LIVE_DRAW_WIKI_TITLES.get(key)
    if template is None:
        raise LiveDrawError(f"Sorteo en vivo no soportado para {tournament_name!r} (solo US Open hoy).")
    return template.format(year=draw_year)


def _cache_path(tournament_name: str, draw_year: int) -> Path:
    fname = config.LIVE_DRAW_CACHE_TEMPLATE.format(
        tournament=tournament_name.strip().lower().replace(" ", "_"), year=draw_year
    )
    return config.DATA_RAW_DIR / fname


def fetch_live_bracket_state(tournament_name: str, draw_year: int, force: bool = False) -> LiveBracketState:
    """Sorteo oficial + estado actual del cuadro (quién ganó qué hasta
    ahora), parseado en vivo desde Wikipedia. `force` no cambia el
    comportamiento hoy (D8: el estado siempre se pide fresco); se mantiene
    en la firma por simetría con `fetchers.fetch_*` y como punto de
    extensión si se agrega un modo offline explícito más adelante.
    """
    title = _wiki_title_for(tournament_name, draw_year)
    cache_path = _cache_path(tournament_name, draw_year)

    try:
        section_wikitexts, finals_wikitext = _fetch_all_sections_wikitext(title)
    except FetchError as exc:
        if cache_path.exists():
            logger.warning(
                "No se pudo actualizar el sorteo en vivo desde Wikipedia (%s) -- usando el "
                "último sorteo cacheado en %s, SIN resultados en vivo (se simula como si el "
                "torneo no hubiera empezado todavía).",
                exc, cache_path,
            )
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            return LiveBracketState(draw=cached["draw"], known_results={})
        raise LiveDrawError(
            f"No se pudo obtener el sorteo en vivo de {title!r} y no hay cache local en {cache_path}: {exc}"
        ) from exc

    sections_parsed = [_parse_bracket_wikitext(wt) for wt in section_wikitexts]
    finals_parsed = _parse_bracket_wikitext(finals_wikitext)

    skeleton = _draw_skeleton_from_sections(sections_parsed)
    known_titles = _known_results_from_sections(sections_parsed)
    known_titles.update(_known_results_from_finals(finals_parsed))

    all_titles = [row["wiki_title"] for row in skeleton] + list(known_titles.values())
    id_by_title = resolve_player_ids(all_titles)
    idx = _load_players_index()

    draw = [
        {
            "slot_index": row["slot_index"],
            "player_id": id_by_title[row["wiki_title"]],
            # Nombre para mostrar: el de Sackmann (consistente con el resto
            # de la app, que siempre muestra full_name en esa forma), no el
            # título crudo de Wikipedia (que a veces trae desambiguación,
            # "Nuno Borges (tennis)").
            "full_name": idx.name_by_id.get(id_by_title[row["wiki_title"]], row["wiki_title"]),
            "country": row["country"],
            "seed": row["seed"],
            "entry_type": row["entry_type"],
            "source": config.LIVE_DRAW_SOURCE,
        }
        for row in skeleton
    ]
    known_results = {key: id_by_title[title] for key, title in known_titles.items()}

    config.DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"draw": draw}, ensure_ascii=False, indent=2), encoding="utf-8")

    return LiveBracketState(draw=draw, known_results=known_results)

"""Ingesta y normalización: CSV crudos -> métricas por jugador -> SQLite.

Responsabilidades (y solo estas, ver plan sección 12.1):
- cargar partidos de pista dura de los últimos N años
- calcular % de puntos ganados al saque y al resto por jugador
- reconstruir el cuadro real (R128) de la edición objetivo del US Open
- volcar todo a SQLite con `to_sql`

Regla de corte temporal (plan sección 7.6 / 14.2): las métricas de un jugador
para el cuadro del año Y solo usan partidos con tourney_date < fecha de inicio
del US Open del año Y. Nunca se usa el propio US Open objetivo (ni nada
posterior) para calcular sus métricas de entrada al torneo.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime

import pandas as pd

from src import config
from src.data import fetchers

logger = logging.getLogger(__name__)


def _load_matches(years: list[int]) -> pd.DataFrame:
    frames = []
    for year in years:
        path = config.DATA_RAW_DIR / config.MATCHES_FILE_TEMPLATE.format(year=year)
        if not path.exists():
            raise FileNotFoundError(
                f"Falta {path.name} — corré `python simular_usopen.py --update-data` "
                f"(o `fetchers.fetch_matches([{year}])`) para descargarlo."
            )
        df = pd.read_csv(path, low_memory=False)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def load_matches_for_years(years: list[int]) -> pd.DataFrame:
    """Wrapper público de `_load_matches` para reuso fuera de la ingesta

    (el backtest, `src/validation/backtest.py`, necesita el historial crudo
    de muchos años a la vez, no solo la ventana de una edición)."""
    return _load_matches(years)


def cutoff_date_for(tournament_name: str, draw_year: int, all_matches: pd.DataFrame) -> int:
    """Wrapper público de `_cutoff_date_for` — ver `load_matches_for_years`."""
    return _cutoff_date_for(tournament_name, draw_year, all_matches)


def latest_rank_before_cutoff(matches: pd.DataFrame, cutoff_date: int) -> pd.DataFrame:
    """Wrapper público de `_latest_rank_before_cutoff` — ver `load_matches_for_years`."""
    return _latest_rank_before_cutoff(matches, cutoff_date)


def _cutoff_date_for(tournament_name: str, draw_year: int, all_matches: pd.DataFrame) -> int:
    """Fecha (yyyymmdd int) de inicio del torneo objetivo, tomada del propio dataset."""
    mask = (
        all_matches["tourney_name"].str.contains(tournament_name, case=False, na=False)
        & (all_matches["tourney_date"] // 10000 == draw_year)
    )
    dates = all_matches.loc[mask, "tourney_date"].unique()
    if len(dates) == 0:
        raise ValueError(f"No se encontró {tournament_name} {draw_year} en los datos descargados")
    return int(dates.min())


def _decay_weight(match_date: int, cutoff_date: int, half_life_days: float) -> float:
    """B9: peso exponencial de un partido según su antigüedad respecto al
    corte -- un partido de hace `half_life_days` pesa la mitad que uno de
    ayer. Sin esto los 3 años de historial pesan igual, y la forma reciente
    predice mejor que un partido de hace 3 años."""
    d_match = datetime.strptime(str(int(match_date)), "%Y%m%d")
    d_cutoff = datetime.strptime(str(int(cutoff_date)), "%Y%m%d")
    days_ago = max((d_cutoff - d_match).days, 0)
    return 0.5 ** (days_ago / half_life_days)


def compute_surface_metrics(
    matches: pd.DataFrame,
    surface: str,
    cutoff_date: int,
    adjust_iterations: int = 5,
    half_life_days: float = config.DECAY_HALF_LIFE_DAYS,
) -> pd.DataFrame:
    """Agrega % de saque y % de resto por jugador, sobre partidos < cutoff_date.

    B9 del plan de mejora: cada partido pesa según su antigüedad (decaimiento
    exponencial, `half_life_days`), no todos por igual -- ver `_decay_weight`.
    `matches_played` queda SIN ponderar (es un conteo informativo); los
    puntos ganados/totales sí, porque son los que alimentan `serve_pct`.

    Además de las tasas crudas (`serve_pct`/`return_pct`), calcula B2 del plan
    de mejora: `serve_pct_adj`/`return_pct_adj`, ajustadas por la calidad de
    los rivales enfrentados (un jugador con calendario flojo infla su
    `serve_pct` cruda; uno que jugó solo contra los mejores la deshincha). La
    cruda se conserva sin tocar -- ver el docstring del ajuste más abajo.
    """
    df = matches[(matches["surface"] == surface) & (matches["tourney_date"] < cutoff_date)]

    stat_cols = ["svpt", "1stWon", "2ndWon"]
    for prefix in ("w_", "l_"):
        for col in stat_cols:
            df = df.dropna(subset=[f"{prefix}{col}"]) if f"{prefix}{col}" in df.columns else df

    records: dict[str, dict] = {}
    # Instancias de saque, una por lado de cada partido: (server_id,
    # returner_id, pts_ganados_sirviendo (ya ponderados por B9),
    # pts_totales_sirviendo (ídem)). Es la MISMA información que `records`
    # pero sin colapsar por rival — el ajuste por oponente (B2) necesita
    # saber CONTRA QUIÉN se ganó cada punto, no solo el total.
    serve_instances: list[tuple[str, str, float, float]] = []

    def _accumulate(player_id, name, serve_won, serve_total, return_won, return_total):
        row = records.setdefault(
            player_id,
            {
                "player_id": str(int(player_id)),
                "full_name": name,
                "matches_played": 0,
                "serve_pts_won": 0.0,
                "serve_pts_total": 0.0,
                "return_pts_won": 0.0,
                "return_pts_total": 0.0,
            },
        )
        row["matches_played"] += 1
        row["serve_pts_won"] += serve_won
        row["serve_pts_total"] += serve_total
        row["return_pts_won"] += return_won
        row["return_pts_total"] += return_total

    for _, m in df.iterrows():
        # Perspectiva del ganador: sirvió con stats w_*, restó contra stats l_*
        w_serve_total, w_serve_won = m["w_svpt"], m["w_1stWon"] + m["w_2ndWon"]
        l_serve_total, l_serve_won = m["l_svpt"], m["l_1stWon"] + m["l_2ndWon"]
        if pd.notna(w_serve_total) and pd.notna(l_serve_total):
            weight = _decay_weight(m["tourney_date"], cutoff_date, half_life_days)
            w_id, l_id = str(int(m["winner_id"])), str(int(m["loser_id"]))
            w_serve_total_wt, w_serve_won_wt = w_serve_total * weight, w_serve_won * weight
            l_serve_total_wt, l_serve_won_wt = l_serve_total * weight, l_serve_won * weight
            _accumulate(
                m["winner_id"], m["winner_name"],
                serve_won=w_serve_won_wt, serve_total=w_serve_total_wt,
                return_won=l_serve_total_wt - l_serve_won_wt, return_total=l_serve_total_wt,
            )
            _accumulate(
                m["loser_id"], m["loser_name"],
                serve_won=l_serve_won_wt, serve_total=l_serve_total_wt,
                return_won=w_serve_total_wt - w_serve_won_wt, return_total=w_serve_total_wt,
            )
            serve_instances.append((w_id, l_id, w_serve_won_wt, w_serve_total_wt))  # ganador sirvió contra perdedor
            serve_instances.append((l_id, w_id, l_serve_won_wt, l_serve_total_wt))  # perdedor sirvió contra ganador

    out = pd.DataFrame.from_records(list(records.values()))
    if out.empty:
        return out

    # Shrinkage bayesiano hacia el promedio del cohorte (plan sección 4.11:
    # "jugador con pocos partidos" -> priors + shrinkage para evitar overfit
    # espurio). Sin esto, un jugador con 1 solo partido puede terminar con
    # 100% de puntos ganados al resto y dominar la simulación. K_PRIOR_PTS es
    # el peso del prior expresado en "puntos virtuales" (~3 partidos).
    K_PRIOR_PTS = 300
    prior_serve = out["serve_pts_won"].sum() / out["serve_pts_total"].sum()
    prior_return = out["return_pts_won"].sum() / out["return_pts_total"].sum()
    out["serve_pct"] = (out["serve_pts_won"] + prior_serve * K_PRIOR_PTS) / (
        out["serve_pts_total"] + K_PRIOR_PTS
    )
    out["return_pct"] = (out["return_pts_won"] + prior_return * K_PRIOR_PTS) / (
        out["return_pts_total"] + K_PRIOR_PTS
    )
    out["surface"] = surface

    serve_adj, return_adj = _adjust_for_opponents(
        out.set_index("player_id")[["serve_pct", "return_pct"]],
        serve_instances, prior_serve, prior_return, adjust_iterations,
    )
    out["serve_pct_adj"] = out["player_id"].map(serve_adj)
    out["return_pct_adj"] = out["player_id"].map(return_adj)
    out.attrs["avg_serve_hard"] = prior_serve
    out.attrs["avg_return_hard"] = prior_return
    return out


def _adjust_for_opponents(
    raw: pd.DataFrame,
    serve_instances: list[tuple[str, str, float, float]],
    avg_serve: float,
    avg_return: float,
    iterations: int,
) -> tuple[dict[str, float], dict[str, float]]:
    """B2 — ajuste iterativo de punto fijo (estilo *opponent-adjusted rates* /
    Massey), plan sección 3, diagnóstico B2.

    Modelo aditivo: `serve_pct(i contra j) ≈ AVG_SERVE + (serve_adj[i] -
    AVG_SERVE) - (return_adj[j] - AVG_RETURN)`. Despejando y promediando
    sobre todos los rivales que enfrentó `i` (ponderado por puntos, para que
    un partido de 150 puntos pese más que uno de 60):

        serve_adj[i] = serve_pct_crudo[i] + (promedio ponderado de
                        return_adj[rivales de i] - AVG_RETURN)

    Intuición: si tus rivales devolvieron mejor que el promedio, tu
    `serve_pct` crudo está subestimado (te tocó un calendario duro) — se
    corrige hacia arriba, y viceversa. Simétrico para el resto. Se itera
    porque `return_adj[j]` depende a su vez de CONTRA QUIÉN sirvió `j`, así
    que hace falta punto fijo (3-5 iteraciones, plan sección 3) para que
    converja en vez de resolverlo en un solo paso.

    Re-centrado tras cada iteración (hallazgo propio, no estaba en el plan):
    sin esto, el sistema no tiene un punto fijo bien definido en general. La
    actualización es un promedio ponderado por rival (fila estocástica), y el
    producto de dos matrices estocásticas siempre tiene autovalor 1 en la
    dirección constante ("todos suben lo mismo") — la ecuación de punto fijo
    queda subdeterminada en esa dirección y, si el desbalance crudo
    saque+resto no es exactamente cero (el caso normal), la iteración deriva
    sin límite en vez de converger. Confirmado con un caso de 2 jugadores
    (`tests/test_opponent_adjustment.py`): sin re-centrar, 5 iteraciones
    llevan un serve_pct de 0.65 a 0.71 aunque el rival sea exactamente
    promedio. Restar el desvío medio de la población tras cada paso ancla el
    nivel global sin tocar las diferencias relativas entre jugadores, que es
    lo único que le importa a Barnett-Clarke (B1).
    """
    serve_adj = raw["serve_pct"].to_dict()
    return_adj = raw["return_pct"].to_dict()
    raw_serve = dict(serve_adj)
    raw_return = dict(return_adj)

    for _ in range(iterations):
        serve_num: dict[str, float] = {}
        serve_den: dict[str, float] = {}
        return_num: dict[str, float] = {}
        return_den: dict[str, float] = {}
        for server_id, returner_id, _won, total in serve_instances:
            if total <= 0:
                continue
            opp_return = return_adj.get(returner_id, avg_return)
            serve_num[server_id] = serve_num.get(server_id, 0.0) + total * (opp_return - avg_return)
            serve_den[server_id] = serve_den.get(server_id, 0.0) + total

            opp_serve = serve_adj.get(server_id, avg_serve)
            return_num[returner_id] = return_num.get(returner_id, 0.0) + total * (opp_serve - avg_serve)
            return_den[returner_id] = return_den.get(returner_id, 0.0) + total

        serve_adj = {
            pid: raw_serve[pid] + (serve_num.get(pid, 0.0) / serve_den[pid] if serve_den.get(pid) else 0.0)
            for pid in raw_serve
        }
        return_adj = {
            pid: raw_return[pid] + (return_num.get(pid, 0.0) / return_den[pid] if return_den.get(pid) else 0.0)
            for pid in raw_return
        }

        # Re-centrado (ver docstring): ancla el nivel global restando el
        # desvío medio de la población en cada dimensión, sin tocar las
        # diferencias relativas entre jugadores.
        mean_serve_shift = sum(serve_adj[pid] - raw_serve[pid] for pid in raw_serve) / len(raw_serve)
        mean_return_shift = sum(return_adj[pid] - raw_return[pid] for pid in raw_return) / len(raw_return)
        serve_adj = {pid: v - mean_serve_shift for pid, v in serve_adj.items()}
        return_adj = {pid: v - mean_return_shift for pid, v in return_adj.items()}

    return serve_adj, return_adj


def _latest_rank_before_cutoff(matches: pd.DataFrame, cutoff_date: int) -> pd.DataFrame:
    """Último ranking ATP conocido de cada jugador antes del corte (evita leakage)."""
    prior = matches[matches["tourney_date"] < cutoff_date]
    winner_ranks = prior[["winner_id", "tourney_date", "winner_rank"]].rename(
        columns={"winner_id": "player_id", "winner_rank": "rank"}
    )
    loser_ranks = prior[["loser_id", "tourney_date", "loser_rank"]].rename(
        columns={"loser_id": "player_id", "loser_rank": "rank"}
    )
    ranks = pd.concat([winner_ranks, loser_ranks], ignore_index=True).dropna(subset=["rank"])
    ranks = ranks.sort_values("tourney_date").drop_duplicates("player_id", keep="last")
    ranks["player_id"] = ranks["player_id"].astype(int).astype(str)
    return ranks.set_index("player_id")[["rank", "tourney_date"]]


def build_draw(all_matches: pd.DataFrame, tournament_name: str, draw_year: int) -> pd.DataFrame:
    """Reconstruye el cuadro real de R128 a partir de los emparejamientos oficiales.

    Sackmann numera match_num consecutivamente dentro de cada ronda siguiendo
    el orden real del cuadro (bracket order). Ordenando R128 por match_num se
    recupera la posición 1..128 real del sorteo oficial de esa edición.
    """
    mask = (
        all_matches["tourney_name"].str.contains(tournament_name, case=False, na=False)
        & (all_matches["tourney_date"] // 10000 == draw_year)
        & (all_matches["round"] == "R128")
    )
    r128 = all_matches.loc[mask].sort_values("match_num").reset_index(drop=True)
    if r128.empty:
        raise ValueError(f"No se encontró el cuadro R128 de {tournament_name} {draw_year}")

    rows = []
    for slot_pair, (_, m) in enumerate(r128.iterrows()):
        base = slot_pair * 2 + 1
        rows.append(
            {
                "tournament_name": tournament_name,
                "tournament_year": draw_year,
                "round_name": "R128",
                "slot_index": base,
                "player_id": str(int(m["winner_id"])),
                "seed": m["winner_seed"] if pd.notna(m["winner_seed"]) else None,
                "source": "sackmann_r128_reconstructed",
            }
        )
        rows.append(
            {
                "tournament_name": tournament_name,
                "tournament_year": draw_year,
                "round_name": "R128",
                "slot_index": base + 1,
                "player_id": str(int(m["loser_id"])),
                "seed": m["loser_seed"] if pd.notna(m["loser_seed"]) else None,
                "source": "sackmann_r128_reconstructed",
            }
        )
    return pd.DataFrame(rows)


def _draw_player_names(all_matches: pd.DataFrame, tournament_name: str, draw_year: int) -> dict[str, str]:
    """player_id -> nombre, tal como aparece en las filas R128 del propio cuadro."""
    mask = (
        all_matches["tourney_name"].str.contains(tournament_name, case=False, na=False)
        & (all_matches["tourney_date"] // 10000 == draw_year)
        & (all_matches["round"] == "R128")
    )
    r128 = all_matches.loc[mask]
    names: dict[str, str] = {}
    for _, m in r128.iterrows():
        names[str(int(m["winner_id"]))] = m["winner_name"]
        names[str(int(m["loser_id"]))] = m["loser_name"]
    return names


def _load_players_meta() -> pd.DataFrame:
    path = config.DATA_RAW_DIR / config.PLAYERS_FILE
    p = pd.read_csv(path, low_memory=False)
    p["player_id"] = p["player_id"].astype(str)
    p["full_name"] = (p["name_first"].fillna("") + " " + p["name_last"].fillna("")).str.strip()
    return p.set_index("player_id")[["full_name", "ioc", "hand", "height"]]


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Migra una base con un esquema más viejo que el de `schema.sql` actual
    (le falta `tournament_year` de B4, o `serve_pct_adj`/`return_pct_adj` de
    B2, o ambos).

    `schema.sql` usa `CREATE TABLE IF NOT EXISTS`, así que en una base vieja
    esas tablas ya existen con la forma anterior y el CREATE no las toca. Es
    una migración destructiva (dropea y recrea vacías), aceptable porque
    ambas tablas son 100% derivadas de los CSV crudos vía `--update-data`,
    nunca contienen datos que no se puedan recalcular.
    """
    jugadores_cols = {row[1] for row in conn.execute("PRAGMA table_info(jugadores)")}
    metricas_cols = {row[1] for row in conn.execute("PRAGMA table_info(metricas_superficie)")}
    needs_migration = (jugadores_cols and "tournament_year" not in jugadores_cols) or (
        metricas_cols and "serve_pct_adj" not in metricas_cols
    )
    if needs_migration:
        logger.warning(
            "Esquema viejo detectado (falta tournament_year y/o serve_pct_adj) — "
            "migrando. Se recalcula todo con --update-data en cada edición que se vuelva a simular."
        )
        conn.executescript("DROP TABLE IF EXISTS jugadores; DROP TABLE IF EXISTS metricas_superficie;")
        conn.executescript(config.SCHEMA_PATH.read_text(encoding="utf-8"))


def run_ingest(
    draw_year: int = config.DEFAULT_DRAW_YEAR,
    years_back: int = config.YEARS_BACK,
    surface: str = config.SURFACE,
    tournament_name: str = config.TOURNAMENT_NAME,
    db_path=config.DB_PATH,
    force_download: bool = False,
) -> None:
    fetched = fetchers.fetch_all(draw_year, years_back, force=force_download)
    logger.info("Años descargados: %s", fetched["years"])

    all_matches = _load_matches(fetched["years"])
    cutoff = _cutoff_date_for(tournament_name, draw_year, all_matches)

    metrics = compute_surface_metrics(all_matches, surface, cutoff)
    ranks = _latest_rank_before_cutoff(all_matches, cutoff)
    players_meta = _load_players_meta()

    metrics = metrics.set_index("player_id")
    metrics = metrics.join(ranks, how="left")
    metrics = metrics.join(players_meta, how="left", rsuffix="_meta")
    # full_name viene de los partidos (confiable); si falta, cae a atp_players.csv
    # y, en último caso, al player_id para no perder la fila.
    has_name = metrics["full_name"].notna() & (metrics["full_name"] != "")
    metrics["full_name"] = metrics["full_name"].where(has_name, metrics["full_name_meta"])
    has_name = metrics["full_name"].notna() & (metrics["full_name"] != "")
    metrics["full_name"] = metrics["full_name"].where(has_name, metrics.index.to_series())
    metrics = metrics.reset_index()

    now = datetime.utcnow().isoformat()

    jugadores = metrics[["player_id", "full_name", "ioc", "hand", "height", "rank", "tourney_date"]].copy()
    jugadores = jugadores.rename(
        columns={
            "ioc": "country",
            "height": "height_cm",
            "rank": "ranking_atp",
            "tourney_date": "ranking_fecha",
        }
    )
    jugadores["tournament_year"] = draw_year
    jugadores["updated_at"] = now
    jugadores = jugadores.drop_duplicates(subset=["player_id"])

    draw_df = build_draw(all_matches, tournament_name, draw_year)

    # Un jugador del cuadro puede no tener partidos en Hard antes del corte
    # (p.ej. viene de challengers en polvo de ladrillo, o es un qualifier sin
    # historial ATP) y por lo tanto no aparece en `metrics`. No puede faltar
    # en `jugadores` igual: rompería el emparejamiento de slots del cuadro.
    # Se completa con el nombre real tomado del propio partido del cuadro y,
    # si existe, sus metadatos de atp_players.csv.
    missing_ids = set(draw_df["player_id"]) - set(jugadores["player_id"])
    if missing_ids:
        draw_names = _draw_player_names(all_matches, tournament_name, draw_year)
        fallback_rows = []
        for pid in missing_ids:
            meta = players_meta.loc[pid] if pid in players_meta.index else None
            fallback_rows.append(
                {
                    "player_id": pid,
                    "full_name": draw_names.get(pid, pid),
                    "country": meta["ioc"] if meta is not None else None,
                    "hand": meta["hand"] if meta is not None else None,
                    "height_cm": meta["height"] if meta is not None else None,
                    "ranking_atp": None,
                    "ranking_fecha": None,
                    "tournament_year": draw_year,
                    "updated_at": now,
                }
            )
        jugadores = pd.concat([jugadores, pd.DataFrame(fallback_rows)], ignore_index=True)
        logger.warning(
            "%d jugador(es) del cuadro sin partidos en Hard antes del corte, completados con datos básicos: %s",
            len(missing_ids), sorted(missing_ids),
        )

    metricas_superficie = metrics[
        [
            "player_id", "surface", "matches_played",
            "serve_pts_won", "serve_pts_total", "serve_pct", "serve_pct_adj",
            "return_pts_won", "return_pts_total", "return_pct", "return_pct_adj",
        ]
    ].copy()
    metricas_superficie["tournament_year"] = draw_year
    metricas_superficie["years_included"] = ",".join(str(y) for y in fetched["years"])
    metricas_superficie["cutoff_date"] = str(cutoff)
    metricas_superficie["computed_at"] = now

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(config.SCHEMA_PATH.read_text(encoding="utf-8"))
        _migrate_schema(conn)
        # `jugadores`/`metricas_superficie` están particionadas por
        # tournament_year (B4 del plan de mejora): reingestar la edición Y
        # solo pisa las filas de Y, así 2010..2025 pueden convivir para el
        # backtest en vez de que cada ingesta borre todo lo anterior.
        conn.execute("DELETE FROM jugadores WHERE tournament_year = ?", (draw_year,))
        conn.execute("DELETE FROM metricas_superficie WHERE tournament_year = ?", (draw_year,))
        conn.execute(
            "DELETE FROM cuadro_torneo WHERE tournament_name = ? AND tournament_year = ?",
            (tournament_name, draw_year),
        )
        jugadores.to_sql("jugadores", conn, if_exists="append", index=False)
        metricas_superficie.to_sql("metricas_superficie", conn, if_exists="append", index=False)
        draw_df.to_sql("cuadro_torneo", conn, if_exists="append", index=False)
        conn.commit()

    logger.info(
        "Ingesta completa: %d jugadores, %d filas de métricas, %d slots de cuadro -> %s",
        len(jugadores), len(metricas_superficie), len(draw_df), db_path,
    )

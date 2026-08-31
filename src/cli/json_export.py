"""Exportador de la predicción a un JSON estático (PLAN_AUTOMATIZACION_WEB.md,
sección 3.1) -- el consumidor es `docs/app.js`, un frontend separado que lo
lee con `fetch()` sin necesitar ningún backend corriendo.

Reusa `run_prediction`/`build_predicted_bracket` tal cual (mismas piezas que
ya consume `html_report.py`, ningún dato nuevo que calcular) -- pero NO es un
passthrough de cero cómputo: hace tres conversiones reales, todas explícitas
acá abajo:

1. `counts`/`round_snapshots[i]["counts"]` son conteos ENTEROS crudos
   (`count`, no probabilidad) -- la normalización `count/n_simulations` vivía
   inline en `html_report._round_cell`; `_probabilities` la generaliza.
2. `build_predicted_bracket` devuelve objetos `Player`/`EloPlayer` como
   `favorite`/`underdog` -- se mapean a `.player_id` para el schema JSON.
3. `meta["known_results"]` es `dict[tuple[str, int], str]` -- las claves
   tupla NO son serializables a JSON (`json.dumps` tira `TypeError` si se
   intenta volcar `meta` entero tal cual). Por eso el output se arma campo
   por campo, nunca `json.dumps(meta)` directo.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.cli.formatting import DISPLAY_ROUNDS
from src.cli.pipeline import build_predicted_bracket, compute_match_predictions, compute_round_accuracy


def _probabilities(round_counts: dict[str, int], n_simulations: int) -> dict[str, float]:
    """Conteos enteros crudos -> probabilidad [0, 1], redondeada a 4
    decimales (suficiente precisión para un dashboard, JSON más liviano que
    el float completo)."""
    if not n_simulations:
        return {r: 0.0 for r in DISPLAY_ROUNDS}
    return {r: round(round_counts[r] / n_simulations, 4) for r in DISPLAY_ROUNDS}


def _players_payload(
    counts: dict[str, dict[str, int]], players_by_id: dict[str, object], n_simulations: int
) -> list[dict]:
    """Orden por probabilidad de Campeón descendente -- mismo criterio que
    `html_report._probability_table_html`, así la tabla del dashboard sale
    ya ordenada sin que `app.js` tenga que reordenar nada."""
    ranked = sorted(counts.items(), key=lambda kv: kv[1]["CAMPEON"], reverse=True)
    return [
        {
            "player_id": player_id,
            "full_name": players_by_id[player_id].full_name,
            "seed": players_by_id[player_id].seed,
            "probabilities": _probabilities(round_counts, n_simulations),
        }
        for player_id, round_counts in ranked
    ]


def _round_snapshots_payload(round_snapshots: list[dict]) -> list[dict]:
    """`players` referencia solo `player_id` (sin `full_name`) -- el
    diccionario `players` de arriba ya es la fuente de nombres; repetirlos en
    cada uno de los hasta 7 snapshots x 128 jugadores infla el JSON sin
    necesidad (nota de diseño del plan, sección 3.1)."""
    return [
        {
            "round_name": snap["round_name"],
            "frozen": snap["frozen"],
            "players": {
                player_id: _probabilities(round_counts, snap["n_simulations"])
                for player_id, round_counts in snap["counts"].items()
            },
        }
        for snap in round_snapshots
    ]


def _bracket_payload(
    players_by_id: dict[str, object],
    model: str,
    known_results,
    match_predictions: dict[tuple[str, int], str],
) -> list[dict]:
    """Cuadro proyectado, con el veredicto de cada cruce ya jugado.

    `status` por partido:
    - "hit"     -> el modelo tenía a este ganador (`predicted_id` == ganador real)
    - "miss"    -> el modelo tenía al otro; `predicted_id` dice a quién
    - "pending" -> todavía no se jugó; `favorite_id`/`prob` son la proyección

    `predicted_id` solo aparece en "miss" (en "hit" sería idéntico a
    `favorite_id`, y en "pending" el `favorite_id` YA es la predicción --
    repetirlo infla el JSON sin agregar información).

    Ojo con `prob` en un partido ya jugado: `build_predicted_bracket` le pone
    1.0 (es el resultado real inyectado, no una probabilidad del modelo), así
    que el frontend NO debe mostrarlo como "100% de confianza" -- ver
    `renderBracket` en docs/app.js."""
    rounds, _champion = build_predicted_bracket(players_by_id, model, known_results=known_results)
    payload: list[dict] = []
    for matches in rounds:
        round_name = matches[0]["round"] if matches else None
        round_payload: list[dict] = []
        for i, m in enumerate(matches, start=1):
            entry = {
                "favorite_id": m["favorite"].player_id,
                "underdog_id": m["underdog"].player_id,
                "prob": round(m["prob"], 4),
            }
            predicted_id = match_predictions.get((round_name, i))
            if predicted_id is None:
                entry["status"] = "pending"
            elif predicted_id == m["favorite"].player_id:
                entry["status"] = "hit"
            else:
                entry["status"] = "miss"
                entry["predicted_id"] = predicted_id
            round_payload.append(entry)
        payload.append({"round": round_name, "matches": round_payload})
    return payload


def build_export(
    counts: dict[str, dict[str, int]],
    players_by_id: dict[str, object],
    meta: dict,
    n_simulations: int,
) -> dict:
    """Arma el dict completo a exportar (sin escribir a disco -- separado de
    `export_json` para que los tests puedan verificar la estructura sin pasar
    por el filesystem)."""
    model = meta.get("model", "serve_return")
    known_results = meta.get("known_results") or {}
    # UNA sola vez: reconstruir el cuadro predicho por ronda (lo que hace
    # `compute_match_predictions`) no es gratis, y lo necesitan tanto el
    # veredicto por cruce del bracket como la tabla agregada de aciertos.
    match_predictions = compute_match_predictions(players_by_id, model, known_results)
    return {
        "meta": {
            "tournament_name": meta.get("tournament_name"),
            "tournament_year": meta.get("tournament_year"),
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "model": model,
            "n_simulations": n_simulations,
            "is_live": meta.get("is_live", False),
            "cutoff_date": meta.get("cutoff_date"),
            "note": meta.get("note"),
        },
        "players": _players_payload(counts, players_by_id, n_simulations),
        "round_snapshots": _round_snapshots_payload(meta.get("round_snapshots") or []),
        "bracket": _bracket_payload(players_by_id, model, known_results, match_predictions),
        "round_accuracy": compute_round_accuracy(
            players_by_id, model, known_results, match_predictions=match_predictions
        ),
    }


def export_json(
    counts: dict[str, dict[str, int]],
    players_by_id: dict[str, object],
    meta: dict,
    n_simulations: int,
    path: str | Path,
) -> Path:
    """Construye el JSON (`build_export`) y lo escribe en `path`, creando el
    directorio si hace falta. `ensure_ascii=False` -- nombres con tildes
    (Étcheverry, etc.) van legibles en el JSON, no como \\uXXXX escapes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_export(counts, players_by_id, meta, n_simulations)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path

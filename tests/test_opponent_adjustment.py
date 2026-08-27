"""B2 — ajuste por oponente (`ingest._adjust_for_opponents`): dos jugadores
con la MISMA tasa cruda de saque, pero uno enfrentó devolventes fuertes y el
otro devolventes flojos, deben terminar con tasas ajustadas DISTINTAS —
mayor para el que tuvo el calendario más difícil."""

from __future__ import annotations

import pandas as pd
import pytest

from src.data.ingest import _adjust_for_opponents

AVG_SERVE = 0.62
AVG_RETURN = 0.40


def _raw_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "serve_pct": {
                "hard_sched": 0.65, "easy_sched": 0.65,
                "elite_returner": AVG_SERVE, "weak_returner": AVG_SERVE,
            },
            "return_pct": {
                "hard_sched": AVG_RETURN, "easy_sched": AVG_RETURN,
                "elite_returner": 0.55, "weak_returner": 0.25,
            },
        }
    )


def test_harder_schedule_gets_adjusted_up_relative_to_easier_schedule():
    serve_instances = [
        ("hard_sched", "elite_returner", 65.0, 100.0),
        ("easy_sched", "weak_returner", 65.0, 100.0),
    ]
    serve_adj, _ = _adjust_for_opponents(_raw_df(), serve_instances, AVG_SERVE, AVG_RETURN, iterations=5)

    assert serve_adj["hard_sched"] > 0.65  # calendario duro: la cruda subestimaba
    assert serve_adj["easy_sched"] < 0.65  # calendario fácil: la cruda sobreestimaba
    assert serve_adj["hard_sched"] > serve_adj["easy_sched"]


def test_identical_schedule_converges_to_unchanged_rate():
    """Si ambos jugadores enfrentan devolventes exactamente promedio, el
    ajuste converge a ~0 corrección (geométricamente, vía el re-centrado —
    con población de 2 hacen falta más de las 5 iteraciones de producción
    para acercarse al límite; con cientos de jugadores converge mucho más
    rápido en términos relativos)."""
    raw = pd.DataFrame(
        {
            "serve_pct": {"p1": 0.65, "avg_returner": AVG_SERVE},
            "return_pct": {"p1": AVG_RETURN, "avg_returner": AVG_RETURN},
        }
    )
    serve_instances = [("p1", "avg_returner", 65.0, 100.0)]
    # Con una población de 2 el re-centrado reparte la corrección entre
    # ambos miembros (incluido el rival, que ni siquiera saca en este
    # dataset de juguete) -- converge a un residuo pequeño y estable, no a
    # cero exacto. Con cientos de jugadores reales ese residuo se diluye a
    # ~0. Lo que importa (y se verifica acá) es que converge y queda acotado.
    serve_adj, _ = _adjust_for_opponents(raw, serve_instances, AVG_SERVE, AVG_RETURN, iterations=60)
    assert serve_adj["p1"] == pytest.approx(0.65, abs=0.015)


def test_recentering_prevents_unbounded_drift_in_degenerate_two_node_graph():
    """Sin el re-centrado, este caso exacto (un jugador con serve_pct sobre
    el promedio jugando solo contra un rival return-promedio) diverge sin
    límite -- ver el docstring de `_adjust_for_opponents`. Con re-centrado
    debe quedarse cerca de la tasa cruda incluso con muchas iteraciones."""
    raw = _raw_df()[["serve_pct", "return_pct"]].loc[["hard_sched", "elite_returner"]]
    # variante degenerada: el rival es exactamente promedio, no "elite"
    raw.loc["elite_returner", "return_pct"] = AVG_RETURN
    serve_instances = [("hard_sched", "elite_returner", 65.0, 100.0)]

    serve_adj, _ = _adjust_for_opponents(raw, serve_instances, AVG_SERVE, AVG_RETURN, iterations=200)
    assert 0.0 <= serve_adj["hard_sched"] <= 1.0
    # Lo que importa: acotado y estable con 200 iteraciones, no explotando
    # sin límite como hacía la versión sin re-centrar (llegaba a 0.71 con
    # solo 5 iteraciones en el caso original de este mismo test).
    assert serve_adj["hard_sched"] == pytest.approx(0.65, abs=0.015)


def test_player_with_no_serve_instances_keeps_raw_rate():
    raw = pd.DataFrame({"serve_pct": {"ghost": 0.70}, "return_pct": {"ghost": 0.30}})
    serve_adj, return_adj = _adjust_for_opponents(raw, [], AVG_SERVE, AVG_RETURN, iterations=5)
    assert serve_adj["ghost"] == pytest.approx(0.70)
    assert return_adj["ghost"] == pytest.approx(0.30)

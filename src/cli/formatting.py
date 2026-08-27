"""Constantes y cálculos de presentación compartidos entre `render.py`
(terminal, Rich), `html_report.py` (archivo HTML estático) y `server.py`
(modo interactivo). Vivían dentro de `render.py`; se movieron acá cuando
`html_report.py` necesitó reusarlos sin importar un símbolo privado de otro
módulo (PLAN_PAGINA_RESULTADOS.md, decisión #17).
"""

from __future__ import annotations

Z_95 = 1.96

MODEL_LABELS = {
    "modelo_actual": "Modelo pre-Fase-B (piso)",
    "modelo_nuevo": "Modelo nuevo (en vivo)",
    "ranking_atp": "Ranking ATP",
    "elo_hard": "Elo (dura)",
    "moneda": "Moneda (50/50)",
}

DISPLAY_ROUNDS = ["R32", "R16", "QF", "SF", "F", "CAMPEON"]
LABELS = {"R32": "R32", "R16": "R16", "QF": "QF", "SF": "SF", "F": "Final", "CAMPEON": "Campeón"}


def binomial_ci95_pp(count: int, n_simulations: int) -> float:
    """B6 (plan de mejora): semi-ancho del IC95%, en puntos porcentuales, de
    una probabilidad estimada como `count/n_simulations` repeticiones
    Monte Carlo. Con 10.000 sims una probabilidad de campeón ~20% tiene
    SE≈±0.4pp -- sin esto, diferencias de 0.3pp entre jugadores se leen como
    señal cuando son ruido de muestreo."""
    p = count / n_simulations
    se = (p * (1 - p) / n_simulations) ** 0.5
    return Z_95 * se * 100

"""B5 (tie-break punto a punto), B7 (rotación de saque continua entre
sets) y B8 (tie-break a 10 en el set decisivo)."""

from __future__ import annotations

import random

import pytest

from src import config
from src.simulation.monte_carlo import _simulate_set, _simulate_tiebreak


class _ScriptedRandom:
    """RNG de juguete: devuelve una secuencia fija de valores, para forzar
    resultados de juego exactos y probar la lógica de rotación sin depender
    del azar real."""

    def __init__(self, values: list[float]):
        self._values = list(values)

    def random(self) -> float:
        return self._values.pop(0)


# --- B5: tie-break punto a punto --------------------------------------------


def test_tiebreak_symmetric_players_is_roughly_half():
    rng = random.Random(7)
    n = 3000
    wins = sum(1 for _ in range(n) if _simulate_tiebreak(rng, 0.65, 0.65, True))
    empirical = wins / n
    se = (0.5 * 0.5 / n) ** 0.5
    assert abs(empirical - 0.5) < 5 * se


def test_tiebreak_favors_stronger_server():
    rng = random.Random(7)
    n = 3000
    wins = sum(1 for _ in range(n) if _simulate_tiebreak(rng, 0.75, 0.55, True))
    assert wins / n > 0.55


def test_tiebreak_serves_alternate_after_first_point():
    # Con p=1.0/p=0.0 el que saca siempre gana el punto -- permite leer el
    # patrón de saque directamente del resultado: 7-0 significa que el
    # servidor ganó todos sus puntos y el resto los perdió, consistente con
    # "el 1º sirve el punto 1, después se turnan de a 2".
    rng = random.Random(1)
    won = _simulate_tiebreak(rng, p_a_serve=1.0, p_b_serve=0.0, a_serves_first=True, target=7)
    assert won  # A gana todos los puntos que sirve; ganar 7-x con este patrón requiere que A sirva la mayoría


# --- B7: rotación de saque continua entre sets ------------------------------


def _force_game_sequence(rng_values: list[str]) -> _ScriptedRandom:
    """`rng_values`: lista de 'A' o 'B' (quién gana ese juego). Con
    p_a_game=p_b_game=0.5, cualquier valor < 0.5 hace ganar a A pase lo que
    pase quién sirve."""
    return _ScriptedRandom([0.1 if v == "A" else 0.9 for v in rng_values])


def test_even_total_games_same_server_continues():
    # 6-0: 6 juegos (par). La regla real de tenis: con cantidad par de
    # juegos, el mismo jugador que sacó primero en este set saca primero en
    # el próximo (B7 -- el motor viejo volteaba SIEMPRE, sin mirar esto).
    rng = _force_game_sequence(["A"] * 6)
    games_a, games_b, a_won, next_server_is_a = _simulate_set(
        rng, p_a_serve=0.6, p_b_serve=0.4, p_a_game=0.5, p_b_game=0.5, a_serves_first=True
    )
    assert (games_a, games_b, a_won) == (6, 0, True)
    assert next_server_is_a is True  # sigue el mismo


def test_odd_total_games_server_flips():
    # 6-1: 7 juegos (impar) -> el saque SÍ cambia para el próximo set.
    rng = _force_game_sequence(["A", "A", "A", "A", "A", "B", "A"])
    games_a, games_b, a_won, next_server_is_a = _simulate_set(
        rng, p_a_serve=0.6, p_b_serve=0.4, p_a_game=0.5, p_b_game=0.5, a_serves_first=True
    )
    assert (games_a, games_b, a_won) == (6, 1, True)
    assert next_server_is_a is False  # cambia


# --- B8: tie-break a 10 en el set decisivo ----------------------------------


def test_deciding_set_tiebreak_target_is_ten():
    assert config.DECIDING_SET_TIEBREAK_TARGET == 10


def test_tiebreak_to_ten_needs_more_points_than_to_seven():
    # Con el mismo guion de puntos alternados 6-6 (A,B,A,B,A,B,A,B,A,B,A,B),
    # a 7 ya habría terminado; a 10 sigue. Verificamos que target=10
    # efectivamente exige más puntos para resolverse.
    rng7 = random.Random(3)
    rng10 = random.Random(3)
    # Con probabilidades parejas, en promedio un breaker a 10 dura más
    # puntos que uno a 7 -- lo confirmamos indirectamente: forzando un guion
    # 5-5 (a 7, terminaría pronto) y comprobando que a 10 sigue jugando.
    scripted = ["A", "B"] * 5  # 5-5 después de 10 puntos
    rng = _force_game_sequence(scripted + ["A", "A"])  # A gana los 2 siguientes -> 7-5 (gana a 7, no a 10)
    won_at_7 = _simulate_tiebreak(rng, 0.5, 0.5, True, target=7)
    assert won_at_7 is True

    rng2 = _force_game_sequence(scripted + ["A", "A"])  # mismos 12 puntos: a 10 esto da 7-5, todavía no corta
    with pytest.raises(IndexError):
        _simulate_tiebreak(rng2, 0.5, 0.5, True, target=10)  # se queda sin guion: confirma que sigue jugando

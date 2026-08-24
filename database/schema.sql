-- Esquema minimalista de Fase 1 (motor de datos + terminal).
--
-- Deliberadamente reducido: 3 tablas. El esquema completo del plan
-- (participantes_torneo, player_status_events, draw_slots, availability_state,
-- predictions, simulations...) llega en fases posteriores, cuando se resuelva
-- el sistema de disponibilidad/estado (Fase 3) y el modo live (Fase 4).
-- Ver PLAN_IMPLEMENTACION_USOPEN.md secciones 6 y 17.

CREATE TABLE IF NOT EXISTS jugadores (
    player_id       TEXT PRIMARY KEY,
    full_name       TEXT NOT NULL,
    country         TEXT,
    hand            TEXT,
    height_cm       REAL,
    ranking_atp     INTEGER,
    ranking_fecha   TEXT,      -- fecha del último ranking conocido antes del corte
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS metricas_superficie (
    player_id           TEXT NOT NULL,
    surface             TEXT NOT NULL,
    matches_played       INTEGER,
    serve_pts_won        INTEGER,
    serve_pts_total      INTEGER,
    serve_pct            REAL,   -- % de puntos ganados al saque
    return_pts_won       INTEGER,
    return_pts_total     INTEGER,
    return_pct           REAL,   -- % de puntos ganados al resto
    years_included       TEXT,   -- p.ej. "2023,2024,2025"
    cutoff_date          TEXT,   -- fecha límite usada (sin data leakage)
    computed_at           TEXT,
    PRIMARY KEY (player_id, surface),
    FOREIGN KEY (player_id) REFERENCES jugadores(player_id)
);

CREATE TABLE IF NOT EXISTS cuadro_torneo (
    tournament_name TEXT NOT NULL,
    tournament_year  INTEGER NOT NULL,
    round_name       TEXT NOT NULL,   -- R128 (única ronda cargada; el resto lo genera el simulador)
    slot_index       INTEGER NOT NULL, -- posición 1..128 dentro del cuadro
    player_id        TEXT,
    seed             INTEGER,
    source           TEXT,
    PRIMARY KEY (tournament_name, tournament_year, round_name, slot_index),
    FOREIGN KEY (player_id) REFERENCES jugadores(player_id)
);

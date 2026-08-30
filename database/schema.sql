-- Esquema minimalista de Fase 1 (motor de datos + terminal), extendido en el
-- plan de mejora (PLAN_MEJORA_SIMULACION.md, B4) para permitir backtest
-- multi-año: `jugadores` y `metricas_superficie` están particionadas por
-- `tournament_year`, así una ingesta de una edición no pisa las demás y el
-- backtest puede tener 2010..2025 conviviendo en la misma base.
--
-- El esquema completo del plan original (participantes_torneo,
-- player_status_events, draw_slots, availability_state, predictions,
-- simulations...) sigue diferido: ver PLAN_IMPLEMENTACION_USOPEN.md
-- secciones 6 y 17 (documento histórico, no existe en el repo).

CREATE TABLE IF NOT EXISTS jugadores (
    player_id       TEXT NOT NULL,
    tournament_year INTEGER NOT NULL,  -- edición para la que se calculó esta fila (corte temporal propio)
    full_name       TEXT NOT NULL,
    country         TEXT,
    hand            TEXT,
    height_cm       REAL,
    ranking_atp     INTEGER,
    ranking_fecha   TEXT,      -- fecha del último ranking conocido antes del corte
    updated_at      TEXT,
    PRIMARY KEY (player_id, tournament_year)
);

CREATE TABLE IF NOT EXISTS metricas_superficie (
    player_id           TEXT NOT NULL,
    tournament_year      INTEGER NOT NULL,  -- edición para la que se calculó esta fila
    surface             TEXT NOT NULL,
    matches_played       INTEGER,
    serve_pts_won        INTEGER,
    serve_pts_total      INTEGER,
    serve_pct            REAL,   -- % de puntos ganados al saque (crudo)
    serve_pct_adj        REAL,   -- B2: ajustado por fuerza del rival enfrentado
    return_pts_won       INTEGER,
    return_pts_total     INTEGER,
    return_pct           REAL,   -- % de puntos ganados al resto (crudo)
    return_pct_adj       REAL,   -- B2: ajustado por fuerza del rival enfrentado
    years_included       TEXT,   -- p.ej. "2023,2024,2025"
    cutoff_date          TEXT,   -- fecha límite usada (sin data leakage)
    computed_at           TEXT,
    PRIMARY KEY (player_id, tournament_year, surface),
    FOREIGN KEY (player_id, tournament_year) REFERENCES jugadores(player_id, tournament_year)
);

CREATE TABLE IF NOT EXISTS cuadro_torneo (
    tournament_name TEXT NOT NULL,
    tournament_year  INTEGER NOT NULL,
    round_name       TEXT NOT NULL,   -- R128 (única ronda cargada; el resto lo genera el simulador)
    slot_index       INTEGER NOT NULL, -- posición 1..128 dentro del cuadro
    player_id        TEXT,
    seed             INTEGER,
    -- Fase 4: tipo de entrada (Q=qualifier, WC=wildcard, LL=lucky loser,
    -- PR=protected ranking) cuando el jugador no tiene seed numérico --
    -- Sackmann lo trae en winner_entry/loser_entry, Wikipedia lo marca junto
    -- al seed en el draw en vivo (src/data/live_draw.py). Puramente
    -- informativo: ningún modelo de simulación lo lee.
    entry_type       TEXT,
    source           TEXT,
    PRIMARY KEY (tournament_name, tournament_year, round_name, slot_index),
    FOREIGN KEY (player_id) REFERENCES jugadores(player_id)
);

-- Fase 4: snapshot de predicción "entrando a la ronda X" -- condicionado en
-- los resultados reales ya conocidos de TODAS las rondas anteriores a X
-- (parcial o completo, ver src/data/live_draw.py), simulando el resto. Una
-- fila por (torneo, año, ronda, modelo); se pisa mientras la ronda anterior
-- todavía no está 100% jugada en la realidad, y se deja de recalcular (se
-- "congela") en cuanto lo está -- ver src/cli/pipeline.py::run_prediction.
-- Para una edición histórica (sin resultados en vivo que trackear) esta
-- tabla no se usa: solo aplica a ediciones ingeridas vía live_draw.
CREATE TABLE IF NOT EXISTS snapshots_prediccion (
    tournament_name TEXT NOT NULL,
    tournament_year INTEGER NOT NULL,
    round_name       TEXT NOT NULL,
    model            TEXT NOT NULL,
    n_simulations    INTEGER NOT NULL,
    counts_json      TEXT NOT NULL,   -- counts[player_id][ronda_alcanzada] = veces, serializado
    frozen           INTEGER NOT NULL DEFAULT 0,  -- 1 si todas las rondas anteriores ya están 100% jugadas en la realidad (no se vuelve a recalcular)
    generated_at     TEXT NOT NULL,
    PRIMARY KEY (tournament_name, tournament_year, round_name, model)
);

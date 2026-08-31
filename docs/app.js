// Dashboard estático (PLAN_AUTOMATIZACION_WEB.md, sección 3.3): fetch() del
// JSON exportado por `--export-json` (src/cli/json_export.py) + Chart.js,
// sin build step ni dependencias npm. Reusa el DOM fijo de docs/index.html
// (ids: content/loading-banner/error-banner/empty-banner y los contenedores
// de cada sección) -- este archivo solo llena esos contenedores.

const DATA_URL = "data/resultados_simulacion.json";
const DISPLAY_ROUNDS = ["R32", "R16", "QF", "SF", "F", "CAMPEON"];
const ROUND_LABELS = { R128: "R128", R64: "R64", R32: "R32", R16: "R16", QF: "QF", SF: "SF", F: "Final", CAMPEON: "Campeón" };
const MODEL_LABELS = {
  serve_return: "Saque/Resto (análisis juego a juego)",
  elo: "Elo de superficie",
  ensemble: "Ensamble (70% Saque/Resto + 30% Elo)",
};
const TOP_N_BAR_CHART = 12;
const TOP_N_FLUCTUATION = 6;
const MONTHS_ES = [
  "enero", "febrero", "marzo", "abril", "mayo", "junio",
  "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
];

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function fmtPct(p) {
  return `${(p * 100).toFixed(1)}%`;
}

function binomialCi95Pp(p, n) {
  if (!n) return 0;
  const se = Math.sqrt((p * (1 - p)) / n);
  return 1.96 * se * 100;
}

function formatCutoffDateEs(cutoff) {
  // meta.cutoff_date llega como "YYYYMMDD" (a veces con guiones) -- lo
  // pasamos a "31 de agosto de 2026" para el copy institucional del
  // masthead. Si el formato no matchea, se devuelve tal cual en vez de
  // reventar (nunca vimos otro formato, pero esto no es una validación de
  // negocio -- es puro texto de presentación).
  if (!cutoff) return "";
  const digits = String(cutoff).replace(/-/g, "");
  if (!/^\d{8}$/.test(digits)) return String(cutoff);
  const year = digits.slice(0, 4);
  const month = parseInt(digits.slice(4, 6), 10);
  const day = parseInt(digits.slice(6, 8), 10);
  const monthName = MONTHS_ES[month - 1];
  if (!monthName) return String(cutoff);
  return `${parseInt(day, 10)} de ${monthName} de ${year}`;
}

function relativeTimeEs(isoString) {
  const then = new Date(isoString).getTime();
  if (Number.isNaN(then)) return "";
  const diffMs = Date.now() - then;
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return "hace instantes";
  if (mins < 60) return `hace ${mins} min`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `hace ${hours} h`;
  const days = Math.round(hours / 24);
  return `hace ${days} d`;
}

function showState(name) {
  // "loading" | "error" | "empty" | "content" -- mutuamente excluyentes,
  // así un fetch fallido nunca deja la página en blanco sin explicación
  // (hallazgo de la revisión independiente, plan sección 3.3).
  for (const id of ["loading-banner", "error-banner", "empty-banner"]) {
    document.getElementById(id).style.display = name === id.replace("-banner", "") ? "" : "none";
  }
  document.getElementById("content").style.display = name === "content" ? "flex" : "none";
}

async function loadData() {
  showState("loading");
  let payload;
  try {
    const res = await fetch(DATA_URL, { cache: "no-store" });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    payload = await res.json();
  } catch (err) {
    console.error("No se pudo cargar la predicción:", err);
    document.getElementById("error-detail").textContent =
      `${err.message || err} -- probá recargar en un rato; si el archivo sigue sin cargar, avisale a quien mantiene el sitio.`;
    showState("error");
    return;
  }

  if (!payload || !Array.isArray(payload.players) || payload.players.length === 0) {
    showState("empty");
    return;
  }

  try {
    render(payload);
    showState("content");
  } catch (err) {
    console.error("Error renderizando la predicción:", err);
    document.getElementById("error-detail").textContent =
      "El JSON cargó pero tiene un formato inesperado -- esto es un bug, no falta de datos.";
    showState("error");
  }
}

function render(payload) {
  const { meta, players, round_snapshots: roundSnapshots, bracket, round_accuracy: roundAccuracy } = payload;
  const playersById = Object.fromEntries(players.map((p) => [p.player_id, p]));

  renderMasthead(meta);
  renderHero(players[0]);
  renderChampionChart(players, meta);
  renderFluctuationChart(roundSnapshots, playersById);
  renderAccuracyTable(roundAccuracy);
  renderBracket(bracket, playersById);
  renderTable(players, meta, computeEliminatedIds(bracket));
}

function computeEliminatedIds(bracket) {
  // Un jugador queda "eliminado" apenas pierde un cruce ya jugado. En un
  // match con status != "pending", `favorite_id` es el GANADOR real (no la
  // predicción -- ver el comentario en `_bracket_payload`, json_export.py) y
  // `underdog_id` es quien perdió esa ronda: por eso alcanza con juntar
  // todos los `underdog_id` de cruces jugados en cualquier ronda del cuadro,
  // sin tocar ningún cómputo de negocio (solo lee un campo que el export ya
  // expone).
  const eliminated = new Set();
  if (!Array.isArray(bracket)) return eliminated;
  for (const roundData of bracket) {
    for (const m of roundData.matches) {
      const status = m.status || "pending";
      if (status !== "pending") {
        eliminated.add(m.underdog_id);
      }
    }
  }
  return eliminated;
}

function renderMasthead(meta) {
  const tournamentLabel = `${meta.tournament_name} ${meta.tournament_year}`;
  document.getElementById("masthead-title").textContent = tournamentLabel;

  // Copy institucional (reemplaza el texto informal anterior) -- los
  // números (modelo, simulaciones, corte de datos) siguen viniendo de
  // `meta` para no quedar desactualizados de un torneo al siguiente; el
  // resto es texto fijo pedido para el masthead.
  const modelLabel = MODEL_LABELS[meta.model] || meta.model;
  const simsLabel = meta.n_simulations.toLocaleString("en-US");
  const cutoffLabel = formatCutoffDateEs(meta.cutoff_date);
  document.getElementById("masthead-meta").textContent =
    `Modelo Predictivo: ${modelLabel} | ${simsLabel} iteraciones de simulación | Corte de datos: ${cutoffLabel}.`;

  // "(En Vivo)" solo cuando `meta.is_live` es true -- mismo dato que ya
  // controla `live-badge`, así el copy no queda diciendo "En Vivo" a un
  // torneo terminado.
  const liveSuffix = meta.is_live ? " (En Vivo)" : "";
  document.getElementById("masthead-note").textContent =
    `Cuadro Oficial ${tournamentLabel} - Fase 4${liveSuffix}: Sorteo verificado vía Wikipedia, con actualización continua de resultados oficiales del torneo. Consulte el histórico por rondas en la sección inferior.`;

  const liveBadge = document.getElementById("live-badge");
  liveBadge.classList.toggle("hidden", !meta.is_live);

  const updatedBadge = document.getElementById("updated-badge");
  updatedBadge.textContent = meta.generated_at
    ? `última actualización: ${relativeTimeEs(meta.generated_at)}`
    : "";
}

function renderHero(topPlayer) {
  document.getElementById("hero-name").textContent = topPlayer.full_name;
  document.getElementById("hero-pct").textContent = fmtPct(topPlayer.probabilities.CAMPEON);
}

let championChart = null;
let fluctuationChart = null;

const barValueLabels = {
  id: "barValueLabels",
  afterDatasetsDraw(chart) {
    const { ctx } = chart;
    const dataset = chart.data.datasets[0];
    const meta = chart.getDatasetMeta(0);
    ctx.save();
    ctx.fillStyle = cssVar("--text-secondary");
    ctx.font = "600 11px system-ui, sans-serif";
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    meta.data.forEach((bar, i) => {
      ctx.fillText(`${dataset.data[i].toFixed(1)}%`, bar.x + 6, bar.y);
    });
    ctx.restore();
  },
};

function renderChampionChart(players, meta) {
  document.getElementById("chart-sims-label").textContent = meta.n_simulations.toLocaleString("es-AR");
  const top = players.slice(0, TOP_N_BAR_CHART);
  const labels = top.map((p) => p.full_name);
  const data = top.map((p) => p.probabilities.CAMPEON * 100);

  const grid = cssVar("--grid");
  const muted = cssVar("--text-muted");
  const primary = cssVar("--text-primary");
  const seriesColor = cssVar("--series-1");

  if (championChart) championChart.destroy();
  championChart = new Chart(document.getElementById("chart-champion"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Probabilidad de campeón",
          data,
          backgroundColor: seriesColor,
          borderRadius: 4,
          borderSkipped: false,
          barThickness: 18,
        },
      ],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: { right: 36 } },
      scales: {
        x: {
          min: 0,
          grid: { color: grid },
          border: { color: grid },
          ticks: { color: muted, callback: (v) => `${v}%` },
        },
        y: {
          grid: { display: false },
          border: { color: grid },
          ticks: { color: primary },
        },
      },
      plugins: {
        legend: { display: false }, // una sola serie -- el título ya dice qué se mide
        tooltip: {
          callbacks: { label: (ctx) => `${ctx.parsed.x.toFixed(2)}%` },
        },
      },
    },
    plugins: [barValueLabels],
  });
}

function renderFluctuationChart(roundSnapshots, playersById) {
  const section = document.getElementById("fluctuation-section");
  const empty = document.getElementById("fluctuation-empty");

  if (!roundSnapshots || roundSnapshots.length <= 1) {
    section.classList.add("hidden");
    empty.classList.remove("hidden");
    return;
  }
  section.classList.remove("hidden");
  empty.classList.add("hidden");

  const labels = roundSnapshots.map((s) => ROUND_LABELS[s.round_name] || s.round_name);
  // Top-N por probabilidad de campeón en el snapshot MÁS RECIENTE -- son los
  // jugadores que le importan a quien mira el gráfico hoy.
  const lastSnapshot = roundSnapshots[roundSnapshots.length - 1];
  const topIds = Object.entries(lastSnapshot.players)
    .sort((a, b) => b[1].CAMPEON - a[1].CAMPEON)
    .slice(0, TOP_N_FLUCTUATION)
    .map(([id]) => id);

  const seriesColors = [1, 2, 3, 4, 5, 6, 7, 8].map((i) => cssVar(`--series-${i}`));
  const grid = cssVar("--grid");
  const muted = cssVar("--text-muted");
  const primary = cssVar("--text-primary");

  const datasets = topIds.map((id, i) => ({
    label: playersById[id] ? playersById[id].full_name : id,
    data: roundSnapshots.map((s) => (s.players[id] ? s.players[id].CAMPEON * 100 : null)),
    borderColor: seriesColors[i % seriesColors.length],
    backgroundColor: seriesColors[i % seriesColors.length],
    borderWidth: 2,
    pointRadius: 4,
    pointBorderWidth: 2,
    pointBorderColor: cssVar("--surface-1"),
    tension: 0.15,
    spanGaps: true,
  }));

  if (fluctuationChart) fluctuationChart.destroy();
  fluctuationChart = new Chart(document.getElementById("chart-fluctuation"), {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { grid: { color: grid }, border: { color: grid }, ticks: { color: muted } },
        y: {
          min: 0,
          grid: { color: grid },
          border: { color: grid },
          ticks: { color: muted, callback: (v) => `${v}%` },
        },
      },
      plugins: {
        legend: {
          position: "bottom",
          labels: { color: primary, usePointStyle: true, boxWidth: 8, boxHeight: 8 },
        },
        tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)}%` } },
      },
    },
  });
}

function renderAccuracyTable(roundAccuracy) {
  const section = document.getElementById("accuracy-section");
  const empty = document.getElementById("accuracy-empty");
  // `round_accuracy` puede faltar en un JSON viejo cacheado (schema previo a
  // este campo) -- tratarlo igual que "sin datos todavía", no reventar.
  const hasAnyData = Array.isArray(roundAccuracy) && roundAccuracy.some((r) => r.total > 0);

  if (!hasAnyData) {
    section.classList.add("hidden");
    empty.classList.remove("hidden");
    return;
  }
  section.classList.remove("hidden");
  empty.classList.add("hidden");

  const body = document.getElementById("accuracy-table-body");
  body.textContent = "";
  for (const r of roundAccuracy) {
    const tr = document.createElement("tr");

    const roundTd = document.createElement("td");
    roundTd.className = "player-name";
    roundTd.textContent = ROUND_LABELS[r.round_name] || r.round_name;
    tr.appendChild(roundTd);

    if (r.total === 0) {
      // Ronda todavía no jugada -- "--", nunca "0%" (0% leería como "el
      // modelo falló todo", cuando en realidad no hay nada que medir aún).
      for (let i = 0; i < 3; i++) {
        const td = document.createElement("td");
        td.className = "accuracy-na";
        td.textContent = "--";
        tr.appendChild(td);
      }
      body.appendChild(tr);
      continue;
    }

    const incorrect = r.total - r.correct;
    const pct = r.correct / r.total;

    const correctTd = document.createElement("td");
    correctTd.textContent = String(r.correct);
    tr.appendChild(correctTd);

    const incorrectTd = document.createElement("td");
    incorrectTd.textContent = String(incorrect);
    tr.appendChild(incorrectTd);

    const pctTd = document.createElement("td");
    const cell = document.createElement("div");
    cell.className = "accuracy-bar-cell";
    const label = document.createElement("span");
    label.textContent = fmtPct(pct);
    const barTrack = document.createElement("div");
    barTrack.className = "accuracy-bar-track bar-row-track";
    const barFill = document.createElement("div");
    barFill.className = "accuracy-bar-fill bar-row-fill";
    barFill.style.width = `${(pct * 100).toFixed(1)}%`;
    barTrack.appendChild(barFill);
    cell.append(label, barTrack);
    pctTd.appendChild(cell);
    tr.appendChild(pctTd);

    body.appendChild(tr);
  }
}

const _BRACKET_ROW_PX = 50;

function renderBracket(bracket, playersById) {
  const root = document.getElementById("bracket-root");
  root.textContent = "";
  if (!bracket || bracket.length === 0) return;

  const name = (id) => (playersById[id] ? playersById[id].full_name : id);
  const unitHeight = Math.max(bracket[0].matches.length, 1) * _BRACKET_ROW_PX;

  for (const roundData of bracket) {
    const col = document.createElement("div");
    col.className = "bracket-round";

    const label = document.createElement("div");
    label.className = "bracket-round-label";
    label.textContent = ROUND_LABELS[roundData.round] || roundData.round;
    col.appendChild(label);

    const matchesWrap = document.createElement("div");
    matchesWrap.className = "bracket-round-matches";
    matchesWrap.style.height = `${unitHeight}px`;

    for (const m of roundData.matches) {
      const matchEl = document.createElement("div");
      // `status` puede faltar en un JSON viejo cacheado (schema previo a este
      // campo) -- se trata como "pending", el comportamiento de antes.
      const status = m.status || "pending";
      matchEl.className = `bracket-match${status === "pending" ? "" : ` ${status}`}`;

      const fav = document.createElement("div");
      fav.className = "fav";
      fav.textContent = name(m.favorite_id);

      const und = document.createElement("div");
      und.className = "und";
      und.textContent = name(m.underdog_id);

      const tooltip = document.createElement("div");
      tooltip.className = "bracket-tooltip";
      if (status === "hit") {
        tooltip.textContent = `✓ ${name(m.favorite_id)} venció a ${name(m.underdog_id)} — el modelo lo acertó`;
      } else if (status === "miss") {
        // Para un cruce ya jugado el favorito mostrado es el ganador REAL, no
        // la predicción -- por eso hace falta `predicted_id` para poder decir
        // a quién tenía el modelo.
        tooltip.textContent = `✗ ${name(m.favorite_id)} venció a ${name(m.underdog_id)} — el modelo tenía a ${name(m.predicted_id)}`;
      } else {
        // Solo acá el % significa algo: en un partido ya jugado `prob` es 1.0
        // (resultado real inyectado por build_predicted_bracket), no la
        // confianza del modelo -- mostrarlo diría "100%" y sería mentira.
        tooltip.textContent = `${name(m.favorite_id)} vence a ${name(m.underdog_id)} — ${(m.prob * 100).toFixed(0)}%`;
      }

      matchEl.append(fav, und, tooltip);
      if (status !== "pending") {
        const mark = document.createElement("span");
        mark.className = "bracket-mark";
        mark.textContent = status === "hit" ? "✓" : "✗";
        matchEl.appendChild(mark);
      }
      matchesWrap.appendChild(matchEl);
    }

    col.appendChild(matchesWrap);
    root.appendChild(col);
  }

  // Columna final: campeón proyectado (favorito de la última ronda).
  const lastRound = bracket[bracket.length - 1];
  const championId = lastRound.matches[0].favorite_id;
  const champCol = document.createElement("div");
  champCol.className = "bracket-round";
  const champLabel = document.createElement("div");
  champLabel.className = "bracket-round-label";
  champLabel.textContent = "Campeón";
  const champMatches = document.createElement("div");
  champMatches.className = "bracket-round-matches";
  champMatches.style.cssText = `height:${unitHeight}px; justify-content:center;`;
  const champCard = document.createElement("div");
  champCard.className = "champion-card";
  const champTrophy = document.createElement("img");
  champTrophy.src = "img/logo-trofeo.png";
  champTrophy.alt = "";
  champTrophy.className = "champ-trophy-icon";
  champCard.append(champTrophy, ` ${name(championId)}`);
  champMatches.appendChild(champCard);
  champCol.append(champLabel, champMatches);
  root.appendChild(champCol);
}

function renderTable(players, meta, eliminatedIds) {
  const eliminated = eliminatedIds || new Set();
  const head = document.getElementById("players-table-head");
  head.textContent = "";
  const headCells = ["#", "Jugador", "Seed", ...DISPLAY_ROUNDS.map((r) => (r === "CAMPEON" ? "Campeón (±IC95%)" : ROUND_LABELS[r]))];
  for (const text of headCells) {
    const th = document.createElement("th");
    th.textContent = text;
    head.appendChild(th);
  }

  const body = document.getElementById("players-table-body");
  body.textContent = "";

  // El "#" sigue siendo el ranking por probabilidad de campeón (orden que ya
  // trae `players`, sin recalcular nada) -- lo único que cambia es dónde
  // queda la FILA dentro del tbody: activos primero, eliminados al fondo
  // (cada grupo conserva su orden relativo original).
  const activeRows = [];
  const eliminatedRows = [];

  players.forEach((p, i) => {
    const isEliminated = eliminated.has(p.player_id);
    const tr = document.createElement("tr");
    if (isEliminated) tr.className = "eliminated-row";

    const rankTd = document.createElement("td");
    rankTd.className = "rank";
    rankTd.textContent = String(i + 1);
    tr.appendChild(rankTd);

    const nameTd = document.createElement("td");
    nameTd.className = "player-name";
    nameTd.textContent = p.full_name;
    if (isEliminated) {
      const tag = document.createElement("span");
      tag.className = "eliminated-tag";
      tag.textContent = "Eliminado";
      nameTd.appendChild(tag);
    }
    tr.appendChild(nameTd);

    const seedTd = document.createElement("td");
    seedTd.className = "secondary";
    seedTd.textContent = p.seed ? String(p.seed) : "-";
    tr.appendChild(seedTd);

    for (const r of DISPLAY_ROUNDS) {
      const td = document.createElement("td");
      const prob = p.probabilities[r];
      if (r === "CAMPEON") {
        const ci = binomialCi95Pp(prob, meta.n_simulations);
        td.innerHTML = "";
        const pctSpan = document.createElement("span");
        pctSpan.className = "champ-pct";
        pctSpan.textContent = fmtPct(prob);
        const ciSpan = document.createElement("span");
        ciSpan.className = "muted";
        ciSpan.style.fontSize = "0.72rem";
        ciSpan.textContent = ` ± ${ci.toFixed(1)}pp`;
        td.append(pctSpan, ciSpan);
      } else {
        td.textContent = fmtPct(prob);
      }
      tr.appendChild(td);
    }

    (isEliminated ? eliminatedRows : activeRows).push(tr);
  });

  for (const tr of activeRows) body.appendChild(tr);
  for (const tr of eliminatedRows) body.appendChild(tr);
}

loadData();

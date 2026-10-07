/* ScoringDiscrepNHL — renders the verified discrepancy database and the
 * monitor alert feed. Pure vanilla JS; data lives in /data. All dynamic
 * strings are HTML-escaped before insertion. */
"use strict";

const TYPE_LABELS = {
  goal_to_nogoal: "Goal → No Goal",
  nogoal_to_goal: "No Goal → Goal",
  scorer_change: "Scorer Changed",
  assist_change: "Assist Changed",
  video_review: "Video Review",
  double_review: "Double Review",
  acknowledged_error: "NHL-Acknowledged Error",
};

const CATEGORY_LABELS = {
  goal_total_changed: "Goal total changed",
  attribution_only: "Attribution only",
  acknowledged_error: "Acknowledged error",
};

const TIMING_LABELS = {
  in_game: "Corrected during game",
  intermission: "Corrected during intermission",
  postgame: "Corrected postgame",
};

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function periodLabel(p) {
  if (p === null || p === undefined || p === "") return "";
  if (p === "OT") return "Overtime";
  const n = Number(p);
  return n === 1 ? "1st period" : n === 2 ? "2nd period" : n === 3 ? "3rd period" : `${p} period`;
}

function oneLine(rec) {
  const t = rec.type || [];
  if (t.includes("nogoal_to_goal")) return "A goal taken away was restored after a second review.";
  if (t.includes("acknowledged_error") && t.includes("goal_to_nogoal"))
    return "A goal was waved off, then the NHL admitted it should have counted.";
  if (t.includes("goal_to_nogoal")) return "A goal called on the ice was taken off the board.";
  if (t.includes("scorer_change")) return "The goal was re-credited to a different player.";
  if (t.includes("assist_change")) return "Assist credit on the goal was corrected.";
  return "The official scoring record changed.";
}

function badge(cls, text) {
  return `<span class="badge ${cls}">${esc(text)}</span>`;
}

function recordBadges(rec) {
  const out = [];
  const cat = rec.category;
  if (cat === "goal_total_changed") out.push(badge("total", "Goal total changed"));
  if (cat === "attribution_only") out.push(badge("attrib", "Attribution only"));
  if (cat === "acknowledged_error") out.push(badge("error", "Acknowledged error"));
  (rec.type || []).forEach((t) => {
    if (TYPE_LABELS[t]) out.push(badge("plain", TYPE_LABELS[t]));
  });
  if (rec.correction_timing && TIMING_LABELS[rec.correction_timing])
    out.push(badge("plain", TIMING_LABELS[rec.correction_timing]));
  if (rec.market_impact === "high") out.push(badge("total", "High market impact"));
  else if (rec.market_impact === "potential") out.push(badge("flag", "Potential market impact"));
  if (rec.evidence_status === "verified_official") out.push(badge("ok", "Official source"));
  else out.push(badge("flag", "Evidence flagged"));
  return out.join(" ");
}

function recordCard(rec) {
  const clock = rec.game_clock ? ` · ${esc(rec.game_clock)}` : "";
  const period = rec.period !== null && rec.period !== undefined ? periodLabel(rec.period) : "period not stated";
  const sourcesHtml = (rec.sources || [])
    .map(
      (s) =>
        `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.label)}</a>${
          s.official ? '<span class="official-tag">OFFICIAL</span>' : ""
        }</li>`
    )
    .join("");
  const evidenceClass = rec.evidence_status === "verified_official" ? "ok" : "";
  return `
  <details class="record">
    <summary>
      <div class="rec-top">
        <span class="rec-date">${esc(rec.date)}</span>
        <span class="rec-teams">${esc(rec.away_team)} @ ${esc(rec.home_team)}</span>
        <span class="rec-clock">${esc(period)}${clock} · ${esc(rec.season)}</span>
      </div>
      <div class="badges">${recordBadges(rec)}</div>
      <div class="rec-summary-line">${esc(oneLine(rec))}</div>
    </summary>
    <div class="rec-body">
      <div class="state-grid">
        <div class="state-box before">
          <h4>Initial ruling / state</h4>
          <p>${esc(rec.initial_ruling)}</p>
        </div>
        <div class="state-box after">
          <h4>Corrected / final state</h4>
          <p>${esc(rec.corrected_ruling)}</p>
        </div>
      </div>
      <dl class="kv">
        <dt>Reason</dt><dd>${esc(rec.reason)}</dd>
        <dt>Changed goal total?</dt><dd>${rec.changed_goal_total ? "Yes" : "No"}</dd>
        <dt>Attribution changed?</dt><dd>${rec.attribution_changed ? "Yes" : "No"}</dd>
        <dt>Video review involved?</dt><dd>${rec.video_review ? "Yes" : "No"}</dd>
        <dt>Correction timing</dt><dd>${esc(TIMING_LABELS[rec.correction_timing] || rec.correction_timing || "")}</dd>
        <dt>Market/settlement impact</dt><dd>${esc(rec.market_impact || "none")}</dd>
      </dl>
      <div class="evidence ${evidenceClass}">
        <strong>Evidence (${esc(rec.evidence_status || "unknown")}):</strong> ${esc(rec.evidence_notes || "")}
      </div>
      <div>
        <strong>Sources for manual review:</strong>
        <ul class="sources">${sourcesHtml}</ul>
      </div>
    </div>
  </details>`;
}

function renderStats(records) {
  const seasons = new Set(records.map((r) => r.season));
  const totals = records.filter((r) => r.changed_goal_total).length;
  const attrib = records.filter((r) => r.category === "attribution_only").length;
  const postgame = records.filter((r) => r.correction_timing === "postgame").length;
  const official = records.filter((r) => r.evidence_status === "verified_official").length;
  const stats = [
    [records.length, "Verified records"],
    [seasons.size, "Seasons covered"],
    [totals, "Changed a goal total"],
    [attrib, "Attribution-only"],
    [postgame, "Postgame corrections"],
    [official, "Official-source verified"],
  ];
  document.getElementById("stats").innerHTML = stats
    .map(([n, l]) => `<div class="stat"><div class="num">${n}</div><div class="lbl">${esc(l)}</div></div>`)
    .join("");
}

function fillFilters(records) {
  const seasons = [...new Set(records.map((r) => r.season))].sort().reverse();
  const teams = [...new Set(records.flatMap((r) => [r.away_team, r.home_team]))].sort();
  const seasonSel = document.getElementById("f-season");
  seasons.forEach((s) => seasonSel.insertAdjacentHTML("beforeend", `<option>${esc(s)}</option>`));
  const teamSel = document.getElementById("f-team");
  teams.forEach((t) => teamSel.insertAdjacentHTML("beforeend", `<option>${esc(t)}</option>`));
}

function applyFilters(records) {
  const q = document.getElementById("f-search").value.trim().toLowerCase();
  const season = document.getElementById("f-season").value;
  const team = document.getElementById("f-team").value;
  const dateFrom = document.getElementById("f-from").value;
  const dateTo = document.getElementById("f-to").value;
  const category = document.getElementById("f-category").value;
  const type = document.getElementById("f-type").value;
  const timing = document.getElementById("f-timing").value;
  const period = document.getElementById("f-period").value;
  const marketOnly = document.getElementById("f-market").checked;
  const flaggedOnly = document.getElementById("f-flagged").checked;

  const filtered = records.filter((r) => {
    if (season && r.season !== season) return false;
    if (team && r.away_team !== team && r.home_team !== team) return false;
    if (dateFrom && r.date < dateFrom) return false;
    if (dateTo && r.date > dateTo) return false;
    if (category && r.category !== category) return false;
    if (type && !(r.type || []).includes(type)) return false;
    if (timing && r.correction_timing !== timing) return false;
    if (period && String(r.period) !== period) return false;
    if (marketOnly && !(r.market_impact === "high" || r.market_impact === "potential")) return false;
    if (flaggedOnly && r.evidence_status === "verified_official") return false;
    if (q) {
      const hay = JSON.stringify(r).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  filtered.sort((a, b) => (a.date < b.date ? 1 : -1));
  const container = document.getElementById("records");
  container.innerHTML = filtered.length
    ? filtered.map(recordCard).join("")
    : '<p class="empty">No records match the current filters.</p>';
}

async function loadDatabase() {
  let payload;
  try {
    const res = await fetch("data/discrepancies.json");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    payload = await res.json();
  } catch (err) {
    document.getElementById("records").innerHTML =
      '<p class="empty">Could not load data/discrepancies.json — see the repository.</p>';
    return;
  }
  const records = payload.records || [];
  renderStats(records);
  fillFilters(records);
  applyFilters(records);

  const controls = [
    "f-search", "f-season", "f-team", "f-category", "f-type", "f-timing", "f-period",
    "f-from", "f-to",
  ].map((id) => document.getElementById(id));
  controls.forEach((el) => el.addEventListener("input", () => applyFilters(records)));
  document.getElementById("f-market").addEventListener("change", () => applyFilters(records));
  document.getElementById("f-flagged").addEventListener("change", () => applyFilters(records));
  document.getElementById("f-reset").addEventListener("click", () => {
    document.getElementById("f-search").value = "";
    ["f-season", "f-team", "f-category", "f-type", "f-timing", "f-period", "f-from", "f-to"].forEach(
      (id) => (document.getElementById(id).value = "")
    );
    document.getElementById("f-market").checked = false;
    document.getElementById("f-flagged").checked = false;
    applyFilters(records);
  });
}

async function loadAlerts() {
  const container = document.getElementById("alerts-list");
  let alerts = [];
  try {
    const res = await fetch("data/alerts/feed.json");
    if (res.ok) alerts = await res.json();
  } catch (_) {
    /* feed not present yet */
  }
  if (!Array.isArray(alerts)) alerts = [];
  if (!alerts.length) {
    container.innerHTML = `
      <p class="empty">No automatic alerts recorded yet.</p>
      <p class="hint">The snapshot monitor starts collecting from the first time the GitHub Actions
      workflow runs, and it needs at least two snapshots per game before a change can be detected.
      Alerts that survive review are promoted into the database above with full sources.</p>`;
    return;
  }
  alerts.sort((a, b) => ((a.detected_at || "") < (b.detected_at || "") ? 1 : -1));
  container.innerHTML = alerts
    .map(
      (a) => `
    <div class="record alert ${esc(a.severity || "")}">
      <div class="rec-top">
        <span class="alert-type">${esc(a.alert_type || "alert")}</span>
        <span class="rec-teams">${esc(a.away_team || "?")} @ ${esc(a.home_team || "?")}</span>
        <span class="rec-clock">game ${esc(a.game_id || "")} · ${esc((a.game_date || "").slice(0, 10))}</span>
      </div>
      <div class="badges">
        ${badge(a.severity === "high" ? "total" : a.severity === "low" ? "attrib" : "flag", `${a.severity || "medium"} severity`)}
        ${a.period ? badge("plain", `${periodLabel(a.period)}${a.time ? " " + esc(a.time) : ""}`) : ""}
        ${badge("plain", "requires human review")}
      </div>
      <p style="margin:10px 0 0; font-size:0.92rem;">${esc(a.explanation || "")}</p>
      <p class="hint" style="margin:6px 0 0;">Detected ${esc((a.detected_at || "").replace("T", " "))}</p>
    </div>`
    )
    .join("");
}

loadDatabase();
loadAlerts();

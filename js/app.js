/* ScoringDiscrepNHL — site logic. Vanilla JS, no frameworks, no tracking. */
"use strict";

const state = {
  records: [],
  alerts: [],
  coverage: null,
  generatedAt: null,
  queues: [],   // {file, status, why, records[]}
};

const QUEUE_FILES = [
  "data/inbox/pr3_database_review.json",
  "data/inbox/prior_session_leads.json",
];

/* ---------------- data loading ---------------- */

async function fetchJson(path) {
  const resp = await fetch(path, { cache: "no-store" });
  if (!resp.ok) throw new Error(`${path} -> HTTP ${resp.status}`);
  return resp.json();
}

async function loadAll() {
  const banner = document.getElementById("status-banner");
  try {
    const db = await fetchJson("data/discrepancies.json");
    state.records = Array.isArray(db.records) ? db.records : [];
    state.generatedAt = db.generated_at || null;
  } catch (err) {
    banner.textContent = `Could not load the discrepancy database (${err.message}). ` +
      "If the site was just deployed, data files arrive with the first monitor run.";
    banner.classList.remove("hidden");
    banner.classList.add("error");
  }
  try {
    const alerts = await fetchJson("data/alerts.json");
    state.alerts = Array.isArray(alerts.alerts) ? alerts.alerts : [];
  } catch { /* alerts are optional */ }
  try {
    state.coverage = await fetchJson("data/coverage_report.json");
  } catch { /* coverage is optional */ }
  for (const file of QUEUE_FILES) {
    try {
      const q = await fetchJson(file);
      if (q && Array.isArray(q.records)) {
        state.queues.push({ file, status: q.status, why: q.why, records: q.records });
      }
    } catch { /* queue files are optional */ }
  }
}

/* ---------------- helpers ---------------- */

const TYPE_LABELS = {
  goal_to_no_goal: "goal → no-goal",
  no_goal_to_goal: "no-goal → goal",
  video_review_overturn: "video review overturn",
  coach_challenge: "coach's challenge",
  scorer_change: "scorer correction",
  assist_change: "assist correction",
  strength_change: "strength / empty-net",
  official_report_changed: "official report edited",
  other: "other",
};

const TIMING_LABELS = {
  in_game: "during game",
  intermission: "intermission",
  postgame: "postgame",
  unknown: "unknown timing",
};

function esc(value) {
  const div = document.createElement("div");
  div.textContent = value === null || value === undefined ? "" : String(value);
  return div.innerHTML;
}

function dash(value) {
  return (value === null || value === undefined || value === "") ? "—" : esc(value);
}

function teamLabel(team) {
  if (!team) return "?";
  return team.tri ? `${esc(team.tri)}` : esc(team.name || "?");
}

function fmtDate(dateStr) {
  return dateStr ? esc(dateStr) : "—";
}

function recordFamily(rec) {
  const cls = rec.classification || {};
  if ((cls.types || []).includes("official_report_changed")) return "report";
  return cls.changes_game_total ? "total" : "attrib";
}

/* ---------------- filtering ---------------- */

function matchesFilters(rec) {
  const fam = document.getElementById("f-family").value;
  const season = document.getElementById("f-season").value;
  const team = document.getElementById("f-team").value;
  const period = document.getElementById("f-period").value;
  const type = document.getElementById("f-type").value;
  const timing = document.getElementById("f-timing").value;
  const from = document.getElementById("f-date-from").value;
  const to = document.getElementById("f-date-to").value;
  const settlementOnly = document.getElementById("f-settlement").checked;
  const flaggedOnly = document.getElementById("f-flagged-only").checked;
  const search = document.getElementById("f-search").value.trim().toLowerCase();

  const cls = rec.classification || {};
  const game = rec.game || {};
  const ev = rec.event || {};

  if (fam !== "all" && recordFamily(rec) !== fam) return false;
  if (season !== "all" && game.season !== season) return false;
  if (team !== "all") {
    const tris = [(game.away || {}).tri, (game.home || {}).tri, ev.team]
      .filter(Boolean).map((t) => t.toUpperCase());
    if (!tris.includes(team)) return false;
  }
  if (period !== "all") {
    const p = ev.period;
    if (period === "5+") { if (!(p >= 5)) return false; }
    else if (String(p) !== period) return false;
  }
  if (type !== "all" && !(cls.types || []).includes(type)) return false;
  if (timing !== "all" && cls.timing !== timing) return false;
  if (from && (game.date || "") < from) return false;
  if (to && (game.date || "") > to) return false;
  if (settlementOnly && !cls.settlement_risk) return false;
  if (flaggedOnly && !(rec.flags || []).includes("needs_human_review")) return false;

  if (search) {
    const hay = JSON.stringify(rec).toLowerCase();
    if (!hay.includes(search)) return false;
  }
  return true;
}

function applyFilters() {
  return state.records.filter(matchesFilters)
    .sort((a, b) => (b.game && b.game.date || "").localeCompare(a.game && a.game.date || ""));
}

/* ---------------- rendering ---------------- */

function stateBox(title, goalState, changed) {
  const gs = goalState || {};
  return `
    <div class="state-box ${changed ? "changed-state" : ""}">
      <h4>${esc(title)}</h4>
      <dl>
        <dt>Ruling</dt><dd>${dash(gs.ruling)}</dd>
        <dt>Scorer</dt><dd>${dash(gs.scorer)}</dd>
        <dt>Assists</dt><dd>${dash((gs.assists || []).join(", "))}</dd>
        <dt>Strength</dt><dd>${dash(gs.strength)}</dd>
        <dt>Clock</dt><dd>${dash(gs.clock)}</dd>
      </dl>
    </div>`;
}

function evidenceBlock(rec) {
  const items = (rec.evidence || []).map((ev) => `
    <li>
      <a href="${esc(ev.url)}" rel="noopener">${esc(ev.label)}</a>
      <span class="badge badge-${ev.status === "verified" ? "ok" : ev.status === "incomplete" ? "warn" : ev.status === "conflicting" ? "bad" : "mut"}">${esc(ev.status)}</span>
      ${ev.captured_at ? `<span class="muted">captured ${esc(ev.captured_at)}</span>` : ""}
      ${ev.archive_url ? ` · <a href="${esc(ev.archive_url)}" rel="noopener">archive copy</a>` : ""}
      ${ev.note ? `<div class="muted">${esc(ev.note)}</div>` : ""}
    </li>`).join("");
  return `<div class="evidence"><h4>Evidence — official sources</h4><ul>${items}</ul></div>`;
}

function recordCard(rec) {
  const cls = rec.classification || {};
  const game = rec.game || {};
  const ev = rec.event || {};
  const family = recordFamily(rec);

  const typeBadges = (cls.types || []).map((t) =>
    `<span class="badge">${esc(TYPE_LABELS[t] || t)}</span>`).join("");
  const timingBadge = `<span class="badge">${esc(TIMING_LABELS[cls.timing] || cls.timing)}${cls.timing_confidence === "heuristic" ? " (heuristic)" : ""}</span>`;
  const familyBadge = family === "total"
    ? '<span class="badge badge-total">CHANGED GOAL TOTAL</span>'
    : family === "attrib"
      ? '<span class="badge badge-attrib">ATTRIBUTION ONLY</span>'
      : '<span class="badge badge-warn">REPORT EDITED</span>';
  const riskBadge = cls.settlement_risk ? '<span class="badge badge-risk">settlement risk</span>' : "";
  const flagBadges = (rec.flags || []).map((f) =>
    `<span class="badge badge-flag">${esc(f.replaceAll("_", " "))}</span>`).join("");

  const teams = `${teamLabel(game.away)} @ ${teamLabel(game.home)}`;
  const periodTxt = ev.period ? `P${esc(ev.period)}` : "";
  const clockTxt = (rec.corrected && rec.corrected.clock) || (rec.original && rec.original.clock) || "";

  return `
  <article class="record-card family-${family}">
    <div class="record-top">
      <div class="record-title">${fmtDate(game.date)} — ${teams} ${periodTxt} ${esc(clockTxt)}</div>
      <span class="muted">${esc(rec.id)}</span>
    </div>
    <div class="badges">${familyBadge}${riskBadge}${typeBadges}${timingBadge}${flagBadges}</div>
    <div class="state-pair">
      ${stateBox("Original ruling", rec.original, false)}
      ${stateBox("Corrected ruling", rec.corrected, true)}
    </div>
    ${cls.reason ? `<div class="record-meta"><strong>Reason (official):</strong> ${esc(cls.reason)}</div>` : ""}
    ${ev.description ? `<div class="record-meta"><strong>Official description:</strong> ${esc(ev.description)}</div>` : ""}
    ${evidenceBlock(rec)}
    <div class="record-meta">
      Status: <strong>${esc(rec.status)}</strong> ·
      Detected ${esc((rec.detection || {}).first_detected_at || "?")} via ${esc((rec.detection || {}).method || "?")} ·
      ${game.links && game.links.live_feed ? `<a href="${esc(game.links.live_feed)}" rel="noopener">live feed</a> · ` : ""}
      <a href="https://www.nhl.com/gamecenter/${esc(game.game_pk)}" rel="noopener">NHL game page</a>
    </div>
  </article>`;
}

function renderDatabase() {
  // summary stats (unfiltered)
  const total = state.records.length;
  const totalChanging = state.records.filter((r) => (r.classification || {}).changes_game_total).length;
  const attrib = state.records.filter((r) => recordFamily(r) === "attrib").length;
  const review = state.records.filter((r) =>
    ((r.classification || {}).types || []).some((t) => t === "video_review_overturn" || t === "coach_challenge")).length;
  const flagged = state.records.filter((r) => (r.flags || []).includes("needs_human_review")).length;
  document.getElementById("stat-total").textContent = total;
  document.getElementById("stat-total-changing").textContent = totalChanging;
  document.getElementById("stat-attribution").textContent = attrib;
  document.getElementById("stat-review").textContent = review;
  document.getElementById("stat-flagged").textContent = flagged;

  // populate season/team selects from data
  const seasons = [...new Set(state.records.map((r) => (r.game || {}).season).filter(Boolean))].sort().reverse();
  const seasonSel = document.getElementById("f-season");
  seasonSel.length = 1;
  seasons.forEach((s) => seasonSel.add(new Option(`${s.slice(0, 4)}–${s.slice(4)}`, s)));

  const tris = new Set();
  state.records.forEach((r) => {
    const g = r.game || {};
    [(g.away || {}).tri, (g.home || {}).tri, (r.event || {}).team].forEach((t) => t && tris.add(t.toUpperCase()));
  });
  const teamSel = document.getElementById("f-team");
  teamSel.length = 1;
  [...tris].sort().forEach((t) => teamSel.add(new Option(t, t)));

  renderFiltered();
}

function renderFiltered() {
  const list = document.getElementById("record-list");
  const filtered = applyFilters();
  document.getElementById("results-count").textContent =
    `${filtered.length} of ${state.records.length} records`;

  if (state.records.length === 0) {
    list.innerHTML = `
      <div class="empty-state">
        <h3>Monitoring is live — first records appear after the first detected change.</h3>
        <p>This database is populated <em>only</em> with entries backed by captured official NHL
        sources. Nothing is hand-invented, so day zero is intentionally empty.</p>
        <p>The monitor snapshots every recently completed game every 30 minutes; the first
        discrepancy or correction it catches will appear here with full before/after detail
        and official-source links. Check the <strong>Coverage &amp; Limits</strong> tab for what
        can and cannot be detected.</p>
        ${state.generatedAt ? `<p class="muted">Database last updated: ${esc(state.generatedAt)}</p>` : ""}
      </div>`;
    return;
  }
  if (filtered.length === 0) {
    list.innerHTML = '<div class="empty-state"><h3>No records match these filters.</h3><p>Try clearing a filter or two.</p></div>';
    return;
  }
  list.innerHTML = filtered.map(recordCard).join("");
}

/* ---------------- alerts ---------------- */

function renderAlerts() {
  const countPill = document.getElementById("alert-count");
  if (state.alerts.length > 0) {
    countPill.textContent = state.alerts.length;
    countPill.classList.remove("hidden");
  }
  const list = document.getElementById("alert-list");
  if (!state.alerts.length) {
    list.innerHTML = '<div class="empty-state"><h3>No alerts yet.</h3><p>Alerts are emitted automatically when the monitor detects a new or updated discrepancy.</p></div>';
    return;
  }
  list.innerHTML = state.alerts.map((a) => `
    <article class="record-card alert-card">
      <div class="record-top">
        <div class="record-title">${esc(a.title)}</div>
        <span class="muted">${esc(a.created_at || "")}</span>
      </div>
      <div class="badges">
        <span class="badge">${esc(a.type)}</span>
        ${a.severity === "warn" ? '<span class="badge badge-warn">warning</span>' : ""}
        ${a.record_id ? `<span class="badge badge-mut">${esc(a.record_id)}</span>` : ""}
      </div>
      <pre>${esc(a.body || "")}</pre>
      ${(a.links || []).length ? `<div class="evidence"><h4>Links</h4><ul>${a.links.map((l) => `<li><a href="${esc(l)}" rel="noopener">${esc(l)}</a></li>`).join("")}</ul></div>` : ""}
    </article>`).join("");
}

/* ---------------- verification queue ---------------- */

function leadCard(lead, file) {
  const sources = (lead.sources || []).map((s) => `
    <li>
      <a href="${esc(s.url)}" rel="noopener">${esc(s.label || s.url)}</a>
      ${s.official ? '<span class="badge badge-ok">official</span>' : '<span class="badge badge-mut">secondary</span>'}
      ${s.accessed ? `<span class="muted">accessed ${esc(s.accessed)}</span>` : ""}
    </li>`).join("");
  const flags = [...(lead.flags || []), ...(lead.integrity_flags || [])];
  const flagBadges = flags.map((f) => `<span class="badge badge-flag">${esc(f)}</span>`).join("");
  const evStatus = lead.evidence_status || lead.verification_status || "";
  const row = (label, value) => value === null || value === undefined || value === ""
    ? `<dt>${label}</dt><dd><span class="muted">unknown (never guessed)</span></dd>`
    : `<dt>${label}</dt><dd>${esc(value)}</dd>`;
  return `
  <article class="record-card family-report">
    <div class="record-top">
      <div class="record-title">${dash(lead.date || lead.game_date)} — ${dash(lead.away_team)} @ ${dash(lead.home_team)} · ${esc(lead.id)}</div>
      ${evStatus ? `<span class="badge badge-warn">${esc(evStatus)}</span>` : ""}
    </div>
    <div class="badges">
      ${lead.changed_goal_total ? '<span class="badge badge-total">CHANGED GOAL TOTAL</span>' : ""}
      ${lead.attribution_changed || lead.changed_attribution_only ? '<span class="badge badge-attrib">ATTRIBUTION</span>' : ""}
      ${lead.video_review ? '<span class="badge">video review</span>' : ""}
      ${flagBadges}
    </div>
    <div class="state-pair">
      <div class="state-box"><h4>Initial ruling (as claimed)</h4>
        <dl>${row("Ruling", lead.initial_ruling)}${row("Confidence", lead.initial_ruling_confidence)}</dl>
      </div>
      <div class="state-box changed-state"><h4>Corrected ruling (as claimed)</h4>
        <dl>${row("Ruling", lead.corrected_ruling)}${row("Reason", lead.reason)}</dl>
      </div>
    </div>
    <div class="record-meta">
      Period ${dash(lead.period)} · clock ${dash(lead.clock || lead.game_clock)} ·
      timing ${dash(lead.correction_timing)} · season ${dash(lead.season)} ·
      market impact ${lead.market_impact === true || lead.potential_total_market_impact === true ? "possible" : "none stated"}
      ${lead.evidence_notes ? `<div><strong>Evidence notes:</strong> ${esc(lead.evidence_notes)}</div>` : ""}
    </div>
    <div class="evidence"><h4>Cited sources — click to verify</h4><ul>${sources}</ul></div>
    <div class="record-meta muted">From ${esc(file)} — not yet independently re-verified in this environment.</div>
  </article>`;
}

function renderQueue() {
  const list = document.getElementById("queue-list");
  const all = state.queues.flatMap((q) => q.records.map((r) => ({ ...r, _file: q.file })));
  const pill = document.getElementById("queue-count");
  if (all.length) {
    pill.textContent = all.length;
    pill.classList.remove("hidden");
  }
  if (!all.length) {
    list.innerHTML = '<div class="empty-state"><h3>Verification queue is empty.</h3><p>All known leads have been verified and promoted, or discarded.</p></div>';
    return;
  }
  const banners = state.queues.map((q) => `
    <div class="banner" role="note" style="margin:0 0 14px;">
      <strong>${esc(q.file)}</strong>: ${esc(q.status || "quarantined")}.
      ${esc(q.why || "")}
    </div>`).join("");
  list.innerHTML = banners + all.map((r) => leadCard(r, r._file)).join("");
}

/* ---------------- coverage ---------------- */

const CAPABILITIES = [
  ["Detect goal ↔ no-goal flips", "yes", "Snapshot diffing of the official live feed — any added/removed goal is caught within one monitor cycle (~30 min)."],
  ["Detect video-review overturns", "yes", "Review/challenge events in the official play-by-play are captured and linked to the goal they affected."],
  ["Detect scorer/assist changes", "yes", "Per-goal attribution fields are diffed between snapshots; the goal total is untouched in these records."],
  ["Detect silent edits to official reports", "partial", "SHA-256 hashes of Game/Event Summary PDFs flag that a report changed; explaining WHAT changed still needs a human (content diff is planned)."],
  ["Classify correction timing", "partial", "in-game / intermission / postgame from snapshot timestamps + feed state; low-confidence cases are marked heuristic."],
  ["Explain WHY a correction happened", "partial", "Official Situation Room text and review descriptions are attached as evidence; interpretation is human-verified."],
  ["Changes before monitoring started", "no", "No baseline snapshot exists for games that finished before the monitor first saw them; those need archival research, flagged for review."],
  ["Pre-1997/98 era history", "no", "No machine-readable official play-by-play exists online for that era; requires manual archival verification."],
];

function renderCoverage() {
  const grid = document.getElementById("capability-grid");
  grid.innerHTML = CAPABILITIES.map(([title, level, desc]) => `
    <div class="cap-card">
      <h4><span class="cap-${level === "yes" ? "yes" : level === "no" ? "no" : "part"}">${level === "yes" ? "✓ Automated" : level === "no" ? "✗ Not automated" : "◐ Partial"}</span> — ${esc(title)}</h4>
      <p>${esc(desc)}</p>
    </div>`).join("");

  const cov = state.coverage;
  const tbody = document.querySelector("#probe-table tbody");
  const summary = document.getElementById("probe-summary");
  if (!cov || !Array.isArray(cov.results) || !cov.results.length) {
    summary.innerHTML = cov && cov.note
      ? `No probe has run yet. ${esc(cov.note)}`
      : "No probe has run yet — the first GitHub Actions probe run will publish results here.";
    tbody.innerHTML = '<tr><td colspan="5" class="muted">No probe results yet.</td></tr>';
    return;
  }
  summary.innerHTML = `Probed at <strong>${esc(cov.probed_at || "?")}</strong> · ` +
    `earliest OK historical feed probe: <strong>${esc((cov.summary || {}).earliest_ok_historical_feed_probe || "none")}</strong> · ` +
    `earliest OK report season: <strong>${esc((cov.summary || {}).earliest_ok_report_season || "none")}</strong>`;
  tbody.innerHTML = cov.results.map((r) => `
    <tr>
      <td>${esc(r.label)}</td>
      <td>${esc(r.kind)}</td>
      <td class="status-${esc(r.status)}">${esc(r.status)}</td>
      <td>${dash(r.http_code)}</td>
      <td>${r.url ? `<a href="${esc(r.url)}" rel="noopener">${esc(r.url)}</a>` : ""}${r.note ? ` <span class="muted">${esc(r.note)}</span>` : ""}</td>
    </tr>`).join("");
}

/* ---------------- CSV export ---------------- */

function csvEscape(value) {
  const s = value === null || value === undefined ? "" : String(value);
  return /[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
}

function exportCsv() {
  const rows = [["id", "date", "season", "away", "home", "period", "team",
    "family", "changes_game_total", "attribution_only", "types", "timing",
    "settlement_risk", "status", "original_ruling", "original_scorer",
    "original_assists", "corrected_ruling", "corrected_scorer",
    "corrected_assists", "reason", "evidence_urls"]];
  applyFilters().forEach((r) => {
    const g = r.game || {}, c = r.classification || {}, o = r.original || {}, x = r.corrected || {};
    rows.push([r.id, g.date, g.season, (g.away || {}).tri, (g.home || {}).tri,
      (r.event || {}).period, (r.event || {}).team, recordFamily(r),
      c.changes_game_total, c.attribution_only, (c.types || []).join("|"),
      c.timing, c.settlement_risk, r.status, o.ruling, o.scorer,
      (o.assists || []).join("|"), x.ruling, x.scorer, (x.assists || []).join("|"),
      c.reason || "", (r.evidence || []).map((e) => e.url).join("|")]);
  });
  const csv = rows.map((row) => row.map(csvEscape).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "scoringdiscrepnhl-export.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ---------------- tabs & wiring ---------------- */

function switchView(view) {
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  document.getElementById(`view-${view}`).classList.remove("hidden");
  document.querySelectorAll(".tab").forEach((t) => {
    const active = t.dataset.view === view;
    t.classList.toggle("active", active);
    t.setAttribute("aria-selected", active ? "true" : "false");
  });
}

function wire() {
  document.querySelectorAll(".tab").forEach((t) =>
    t.addEventListener("click", () => switchView(t.dataset.view)));

  ["f-family", "f-season", "f-team", "f-period", "f-type", "f-timing",
   "f-date-from", "f-date-to", "f-search"].forEach((id) => {
    const el = document.getElementById(id);
    el.addEventListener(id === "f-search" ? "input" : "change", renderFiltered);
  });
  ["f-settlement", "f-flagged-only"].forEach((id) =>
    document.getElementById(id).addEventListener("change", renderFiltered));

  document.getElementById("f-clear").addEventListener("click", () => {
    document.getElementById("f-search").value = "";
    document.getElementById("f-family").value = "all";
    document.getElementById("f-season").value = "all";
    document.getElementById("f-team").value = "all";
    document.getElementById("f-period").value = "all";
    document.getElementById("f-type").value = "all";
    document.getElementById("f-timing").value = "all";
    document.getElementById("f-date-from").value = "";
    document.getElementById("f-date-to").value = "";
    document.getElementById("f-settlement").checked = false;
    document.getElementById("f-flagged-only").checked = false;
    renderFiltered();
  });
  document.getElementById("f-csv").addEventListener("click", exportCsv);
}

(async function init() {
  wire();
  await loadAll();
  renderDatabase();
  renderAlerts();
  renderQueue();
  renderCoverage();
})();

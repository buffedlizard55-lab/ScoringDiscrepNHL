/* ScoringDiscrepNHL — site logic. Vanilla JS, no frameworks, no tracking.
 *
 * Record and alert shapes are normalised in js/normalize.js; this file only loads,
 * filters and renders. Nothing here invents a value: an absent field renders as an
 * em dash, and a record whose evidence is thin says so on the card.
 */
"use strict";

const state = {
  records: [],
  alerts: [],
  coverage: null,        // data/reference/coverage_report.json  (measured per season)
  probe: null,           // data/reference/probe_report.json     (source reachability)
  vocabulary: null,      // data/schema/observed_vocabulary.json (what the feed can say)
  sourceCatalog: null,   // data/reference/sources.json          (what was fetched, and when)
  legacyCoverage: null,  // data/coverage_report.json            (engine probe, may be empty)
  generatedAt: null,
  provenance: {},        // which file each store came from + counts, shown on the page
  queues: [],            // {file, status, why, records[]}
};

const QUEUE_FILES = [
  "data/inbox/pr3_database_review.json",
  "data/inbox/prior_session_leads.json",
];

const ENGINE_DB = "data/discrepancies.json";
const MONITOR_DB = "data/records/discrepancies.json";
const MONITOR_ALERT_INDEX = "data/alerts/index.json";
const LEGACY_ALERTS = "data/alerts.json";

/* ---------------- data loading ---------------- */

async function fetchJson(path) {
  const resp = await fetch(path, { cache: "no-store" });
  if (!resp.ok) throw new Error(`${path} -> HTTP ${resp.status}`);
  return resp.json();
}

async function tryJson(path) {
  try { return await fetchJson(path); } catch { return null; }
}

async function loadAll() {
  const banner = document.getElementById("status-banner");
  const notes = [];

  const engine = await tryJson(ENGINE_DB);
  const monitor = await tryJson(MONITOR_DB);
  const engineRecords = engine && Array.isArray(engine.records) ? engine.records : [];
  const monitorRecords = monitor && Array.isArray(monitor.records) ? monitor.records : [];

  if (!engine && !monitor) {
    banner.textContent = "Could not load either discrepancy database. If the site was just " +
      "deployed, the data files arrive with the first monitor run.";
    banner.classList.remove("hidden");
    banner.classList.add("error");
  }

  state.records = mergeRecords(
    engineRecords.map((r) => normalizeRecord(r, ENGINE_DB)).filter(Boolean),
    monitorRecords.map((r) => normalizeRecord(r, MONITOR_DB)).filter(Boolean),
  );
  state.provenance = {
    engine: { file: ENGINE_DB, count: engineRecords.length, ok: !!engine },
    monitor: { file: MONITOR_DB, count: monitorRecords.length, ok: !!monitor },
    merged: state.records.length,
  };
  state.generatedAt = (engine && (engine.generated_at || engine.updated_at_utc))
    || (monitor && monitor.updated_at_utc) || null;

  // Alerts: three artifacts, three writers. Merge so the feed the user sees does
  // not depend on which detection route ran last. Record ids differ between the
  // two stores, so an alias map keeps one correction from alerting twice.
  const aliases = new Map();
  state.records.forEach((r) => (r.also_in || []).forEach((alt) => aliases.set(alt, r.id)));
  const monitorIndex = await tryJson(MONITOR_ALERT_INDEX);
  const legacy = await tryJson(LEGACY_ALERTS);
  let digest = null;
  for (const path of digestCandidatePaths(monitorIndex)) {
    digest = await tryJson(path);
    if (digest) { digest._origin = path; break; }
  }
  state.alerts = mergeAlerts(monitorIndex, legacy, digest, aliases);

  state.coverage = await tryJson("data/reference/coverage_report.json");
  state.probe = await tryJson("data/reference/probe_report.json");
  state.vocabulary = await tryJson("data/schema/observed_vocabulary.json");
  state.sourceCatalog = await tryJson("data/reference/sources.json");
  state.legacyCoverage = await tryJson("data/coverage_report.json");

  for (const file of QUEUE_FILES) {
    const q = await tryJson(file);
    if (q && Array.isArray(q.records)) {
      state.queues.push({ file, status: q.status, why: q.why, records: q.records });
    }
  }

  if (!state.records.length && (engineRecords.length || monitorRecords.length)) {
    notes.push("The databases loaded but no record could be normalised — treat this as a bug, not an empty database.");
  }
  if (notes.length) {
    banner.textContent = notes.join(" ");
    banner.classList.remove("hidden");
    banner.classList.add("error");
  }
}

/* ---------------- helpers ---------------- */

const TYPE_LABELS = {
  goal_to_no_goal: "goal → no-goal",
  no_goal_to_goal: "no-goal → goal",
  scorer_change: "scorer correction",
  assist_change: "assist correction",
  strength_change: "strength / empty-net",
  own_goal_flag_change: "own-goal annotation",
  clock_conflict: "goal-clock conflict",
  official_report_changed: "official report edited",
  official_announcement: "league scoring-change announcement",
  video_review_cited: "video review cited by source",
};

const TIMING_LABELS = {
  in_game: "during game",
  intermission: "during intermission",
  postgame: "postgame",
  not_applicable: "timing not applicable",
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

function fmtDate(dateStr) {
  return dateStr ? esc(dateStr) : "—";
}

function seasonLabel(season) {
  if (!season || season.length !== 8) return dash(season);
  return `${season.slice(0, 4)}–${season.slice(4)}`;
}

/* total / attrib / unknown / report — "unknown" is its own family because a
 * secondary source claiming a goal-count change is not the same thing as a
 * measured one, and the site must not present it as either. */
function recordFamily(rec) {
  if ((rec.types || []).includes("official_report_changed")) return "report";
  if (rec.changes_game_total) return "total";
  if (rec.attribution_only) return "attrib";
  return "unknown";
}

function needsHumanReview(rec) {
  return rec.status === "pending_review"
    || rec.status === "disputed"
    || (rec.flags || []).some((f) => /human|verify|secondary|unresolved|undetermined|not_established|conflict/.test(f))
    || rec.needs_human_read === true;
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
  const verifiedOnly = document.getElementById("f-verified-only").checked;
  const search = document.getElementById("f-search").value.trim().toLowerCase();

  if (fam !== "all" && recordFamily(rec) !== fam) return false;
  if (season !== "all" && rec.season !== season) return false;
  if (team !== "all") {
    const tris = [rec.away, rec.home, rec.team].filter(Boolean).map((t) => t.toUpperCase());
    if (!tris.includes(team)) return false;
  }
  if (period !== "all") {
    const p = rec.period;
    if (period === "5+") { if (!(p >= 5)) return false; }
    else if (String(p) !== period) return false;
  }
  if (type !== "all" && !(rec.types || []).includes(type)) return false;
  if (timing !== "all" && rec.timing !== timing) return false;
  if (from && (rec.date || "") < from) return false;
  if (to && (rec.date || "") > to) return false;
  if (settlementOnly && !rec.settlement_risk) return false;
  if (flaggedOnly && !needsHumanReview(rec)) return false;
  if (verifiedOnly && rec.status !== "verified") return false;

  if (search) {
    const hay = JSON.stringify(rec).toLowerCase();
    if (!hay.includes(search)) return false;
  }
  return true;
}

function applyFilters() {
  return state.records.filter(matchesFilters)
    .sort((a, b) => String(b.date || "").localeCompare(String(a.date || ""))
      || String(b.id).localeCompare(String(a.id)));
}

/* ---------------- rendering ---------------- */

function stateBox(title, s, changed) {
  const st = s || {};
  const assists = st.assists_known
    ? (st.assists && st.assists.length ? st.assists.join(", ") : "unassisted")
    : null;
  return `
    <div class="state-box ${changed ? "changed-state" : ""}">
      <h4>${esc(title)}</h4>
      <dl>
        <dt>Ruling</dt><dd>${dash(st.ruling)}</dd>
        <dt>Scorer</dt><dd>${dash(st.scorer)}</dd>
        <dt>Assists</dt><dd>${dash(assists)}</dd>
        <dt>Strength</dt><dd>${dash(st.strength)}</dd>
        <dt>Clock</dt><dd>${dash(st.clock)}</dd>
      </dl>
      ${st.evidence_status ? `<div class="muted">state evidence: ${esc(st.evidence_status)}</div>` : ""}
      ${st.evidence_note ? `<div class="muted">${esc(st.evidence_note)}</div>` : ""}
    </div>`;
}

function evidenceBlock(rec) {
  const items = (rec.evidence || []).map((ev) => `
    <li>
      <a href="${esc(ev.url)}" rel="noopener">${esc(ev.label)}</a>
      ${ev.status ? `<span class="badge badge-${/primary|verified|official/.test(ev.status) ? "ok" : /secondary/.test(ev.status) ? "warn" : "mut"}">${esc(ev.status)}</span>` : ""}
      ${ev.http_status ? `<span class="muted">HTTP ${esc(ev.http_status)}</span>` : ""}
      ${ev.retrieved_at ? `<span class="muted">retrieved ${esc(ev.retrieved_at)}</span>` : ""}
      ${ev.quote ? `<div class="quote"><code>${esc(ev.quote)}</code></div>` : ""}
      ${ev.note ? `<div class="muted">${esc(ev.note)}</div>` : ""}
    </li>`).join("");
  return `<div class="evidence"><h4>Evidence — official sources</h4><ul>${items || "<li class=\"muted\">No source links are stored on this record.</li>"}</ul></div>`;
}

function recordCard(rec) {
  const family = recordFamily(rec);
  const typeBadges = (rec.types || []).map((t) =>
    `<span class="badge">${esc(TYPE_LABELS[t] || t)}</span>`).join("");
  const timingBadge = `<span class="badge">${esc(TIMING_LABELS[rec.timing] || rec.timing || "timing unknown")}${rec.timing_uncertain ? " (uncertain)" : ""}</span>`;
  const familyBadge = {
    total: '<span class="badge badge-total">CHANGED GOAL TOTAL</span>',
    attrib: '<span class="badge badge-attrib">ATTRIBUTION ONLY</span>',
    report: '<span class="badge badge-warn">REPORT EDITED</span>',
    unknown: '<span class="badge badge-warn">GOAL-TOTAL IMPACT NOT ESTABLISHED</span>',
  }[family];
  const riskBadge = rec.settlement_risk ? `<span class="badge badge-risk">settlement risk${rec.market_risk ? `: ${esc(rec.market_risk)}` : ""}</span>` : "";
  const flagBadges = (rec.flags || []).map((f) =>
    `<span class="badge badge-flag">${esc(f.replaceAll("_", " "))}</span>`).join("");
  const statusBadge = `<span class="badge ${rec.status === "verified" ? "badge-ok" : "badge-warn"}">${esc(rec.status || "status unknown")}</span>`;

  // A record whose teams were never captured says so, rather than printing a
  // placeholder that reads like data. The game id is the way to look it up.
  const teams = (rec.away && rec.home)
    ? `${esc(rec.away)} @ ${esc(rec.home)}`
    : `<span class="muted">teams not recorded${rec.game_id ? ` (game ${esc(rec.game_id)})` : ""}</span>`;
  const periodTxt = rec.period ? `P${esc(rec.period)}` : "";
  const clockTxt = rec.clock || "";
  const gameLink = rec.game_id
    ? `<a href="${esc(rec.gamecenter_url || `https://www.nhl.com/gamecenter/${rec.game_id}`)}" rel="noopener">NHL game ${esc(rec.game_id)}</a>`
    : '<span class="muted">game id not resolved</span>';
  const reportLinks = Object.entries(rec.report_urls || {}).map(([k, url]) =>
    `<a href="${esc(url)}" rel="noopener">${esc(k)}</a>`).join(" · ");
  const latency = rec.latency_seconds
    ? `${Math.round(rec.latency_seconds / 60)} min after the final buzzer`
    : null;

  return `
  <article class="record-card family-${family}" data-id="${esc(rec.id)}">
    <div class="record-top">
      <div class="record-title">${fmtDate(rec.date)} — ${teams} ${periodTxt} ${esc(clockTxt)}</div>
      <span class="muted">${esc(rec.id)}</span>
    </div>
    <div class="badges">${familyBadge}${statusBadge}${riskBadge}${typeBadges}${timingBadge}${flagBadges}</div>
    <div class="state-pair">
      ${stateBox("Original ruling (as first published)", rec.original, false)}
      ${stateBox("Corrected / final ruling", rec.corrected, true)}
    </div>
    ${rec.summary ? `<div class="record-meta"><strong>What changed:</strong> ${esc(rec.summary)}</div>` : ""}
    ${rec.reason_text ? `<div class="record-meta"><strong>Reason (official statement):</strong> ${esc(rec.reason_text)}${rec.reason_channel ? ` <span class="muted">— ${esc(rec.reason_channel)}</span>` : ""}</div>`
      : `<div class="record-meta"><strong>Reason:</strong> <span class="muted">no official statement of the reason is stored for this record</span></div>`}
    ${rec.machine_diff ? `<div class="record-meta"><strong>Checked from the two states:</strong> ${esc(Object.entries(rec.machine_diff).map(([k, v]) => `${k} ${v}`).join(" · "))}</div>` : ""}
    ${evidenceBlock(rec)}
    <div class="record-meta">
      ${gameLink}${reportLinks ? ` · ${reportLinks}` : ""}<br>
      Detected ${dash(rec.detected_at)} via ${dash(rec.detected_by)}
      ${rec.announced_at_utc ? ` · league announcement ${esc(rec.announced_at_utc)}` : ""}
      ${latency ? ` · ${esc(latency)}` : ""}
      ${rec.source_db ? `<span class="muted"> · store: ${esc(rec.source_db === "both" ? "both databases (deduplicated)" : rec.source_db)}</span>` : ""}
    </div>
  </article>`;
}

function renderDatabase() {
  const total = state.records.length;
  const totalChanging = state.records.filter((r) => r.changes_game_total).length;
  const attrib = state.records.filter((r) => recordFamily(r) === "attrib").length;
  const unestablished = state.records.filter((r) => recordFamily(r) === "unknown").length;
  const review = state.records.filter(needsHumanReview).length;
  const verified = state.records.filter((r) => r.status === "verified").length;

  document.getElementById("stat-total").textContent = total;
  document.getElementById("stat-total-changing").textContent = totalChanging;
  document.getElementById("stat-attribution").textContent = attrib;
  document.getElementById("stat-unestablished").textContent = unestablished;
  document.getElementById("stat-flagged").textContent = review;
  document.getElementById("stat-verified").textContent = verified;

  const prov = document.getElementById("provenance-note");
  if (prov) {
    const p = state.provenance;
    prov.innerHTML = `Merged from <code>${esc(p.engine.file)}</code> (${p.engine.count} record${p.engine.count === 1 ? "" : "s"})`
      + ` and <code>${esc(p.monitor.file)}</code> (${p.monitor.count} record${p.monitor.count === 1 ? "" : "s"})`
      + ` → <strong>${p.merged}</strong> distinct correction${p.merged === 1 ? "" : "s"}.`
      + (state.generatedAt ? ` Last database write: ${esc(state.generatedAt)}.` : "")
      + ` Every card names the store it came from.`;
  }

  const seasons = [...new Set(state.records.map((r) => r.season).filter(Boolean))].sort().reverse();
  const seasonSel = document.getElementById("f-season");
  seasonSel.length = 1;
  seasons.forEach((s) => seasonSel.add(new Option(seasonLabel(s), s)));

  const tris = new Set();
  state.records.forEach((r) => [r.away, r.home, r.team].forEach((t) => t && tris.add(t.toUpperCase())));
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
        <h3>No records have been written to the database yet.</h3>
        <p>This database is populated <em>only</em> with entries backed by captured official NHL
        sources. Nothing is hand-invented, so an empty database is a statement about coverage,
        not about the league.</p>
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
    list.innerHTML = '<div class="empty-state"><h3>No alerts yet.</h3><p>Alerts are emitted automatically when a detection route writes a new or updated discrepancy record.</p></div>';
    return;
  }
  list.innerHTML = state.alerts.map((a) => `
    <article class="record-card alert-card severity-${esc(a.severity || "low")}" data-alert-id="${esc(a.id)}">
      <div class="record-top">
        <div class="record-title">${esc(a.title)}</div>
        <span class="muted">${esc(a.created_at || "")}</span>
      </div>
      <div class="badges">
        <span class="badge badge-${a.severity === "critical" || a.severity === "high" ? "risk" : a.severity === "medium" ? "warn" : "mut"}">${esc(a.severity || "info")}</span>
        ${a.type ? `<span class="badge">${esc(TYPE_LABELS[a.type] || a.type)}</span>` : ""}
        ${a.affects_goal_total ? '<span class="badge badge-total">changed goal total</span>' : '<span class="badge badge-attrib">attribution</span>'}
        ${a.record_id ? `<span class="badge badge-mut">${esc(a.record_id)}</span>` : ""}
      </div>
      <pre>${esc(a.body || "")}</pre>
      ${(a.links || []).length ? `<div class="evidence"><h4>Official source links</h4><ul>${a.links.map((l) => `<li><a href="${esc(l)}" rel="noopener">${esc(l)}</a></li>`).join("")}</ul></div>` : ""}
      <div class="record-meta muted">alert artifact: ${esc(a.origin)}</div>
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
    <div class="record-meta muted">From ${esc(file)} — not yet independently re-verified.</div>
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

/* ---------------- coverage & capability ---------------- */

/* Every claim in this table is backed by a committed measurement. The previous
 * version of this table asserted automated video-review detection; the measured
 * event vocabulary contains no review event type at all, so the claim was false
 * and is now stated the other way round. See docs/LIMITATIONS.md §2.1. */
function capabilities(vocab) {
  const reviewTypes = (vocab && vocab.review_event_types_found) || [];
  const noReview = reviewTypes.length === 0;
  return [
    ["A goal appears or disappears in the official record after we captured it",
      "yes",
      "Two captured official states are diffed. This is the only formulation that is fully defensible: the NHL publishes no correction flag and no revision history."],
    ["Scorer / assist / strength attribution changes",
      "yes",
      "Per-goal attribution fields are diffed between captures, and the league's own scoring-change announcements are parsed when one exists."],
    ["A correction announced by the league after the game",
      "yes",
      "The league publishes 'OFFICIAL SCORING CHANGE: Game n … now reads X from Y and Z'. Parsed into a record with the post URL stored; measured latency 2h49m–3h25m after the final buzzer on the three verified records."],
    ["Video review as the *reason* for a change",
      noReview ? "no" : "partial",
      noReview
        ? `Measured: no review or challenge event type exists in the official play-by-play (0 of ${((vocab && vocab.observed_type_desc_keys) || []).length} observed event types). An overturned call is detectable as a goal added/removed; the cause stays unknown unless an official artifact states it in words.`
        : `${reviewTypes.length} review event type(s) observed: ${reviewTypes.join(", ")}.`],
    ["Why the league changed a ruling",
      "partial",
      "Only when an official artifact says so in words. There is no machine-readable Situation Room feed; no public endpoint exposes correction or version history."],
    ["When a correction happened, relative to the game",
      "partial",
      "Bounded by our poll times. The report footer stamp says when a document was generated, not when a value in it changed, so a stamp alone never earns better than 'timing uncertain'."],
    ["Which of two disagreeing official artifacts is the corrected one",
      "no",
      "The HTML sheet and the GameCenter JSON are the same data rendered twice, not two witnesses. A disagreement is reported as conflicting and flagged, never auto-resolved."],
    ["Changes that happened between two polls with no prior capture",
      "no",
      "If every capture post-dates the correction, the original state is unrecoverable from any source we have. This is the structural false negative."],
    ["Games before the 2000-01 season",
      "no",
      "Measured: 19992000/GS020001.HTM returns 404; the earliest season served by the official report family is 2000-01. Nothing older has a machine-readable official source in this family."],
    ["Whether a bookmaker regraded a settled market",
      "no",
      "House rules are private. The system flags 'a settled market may have been graded on a superseded number' and stops there."],
  ];
}

function renderCoverage() {
  const grid = document.getElementById("capability-grid");
  grid.innerHTML = capabilities(state.vocabulary).map(([title, level, desc]) => `
    <div class="cap-card">
      <h4><span class="cap-${level === "yes" ? "yes" : level === "no" ? "no" : "part"}">${level === "yes" ? "✓ Detectable" : level === "no" ? "✗ Not detectable" : "◐ Partial"}</span> — ${esc(title)}</h4>
      <p>${esc(desc)}</p>
    </div>`).join("");

  const tbody = document.querySelector("#probe-table tbody");
  const summary = document.getElementById("probe-summary");
  const probe = state.probe;
  const cov = state.coverage;

  const parts = [];
  if (cov && cov.earliest_season_with_report) {
    parts.push(`earliest season with an official report: <strong>${esc(seasonLabel(cov.earliest_season_with_report))}</strong>`);
    parts.push(`seasons measured: <strong>${(cov.seasons || []).length}</strong>`);
    parts.push(`still frozen at game time: <strong>${(cov.frozen_seasons || []).length}</strong>`);
    parts.push(`regenerated in place: <strong>${(cov.regenerated_seasons || []).length}</strong>`);
    parts.push(`era undetermined: <strong>${(cov.undetermined_seasons || []).length}</strong>`);
  }
  if (probe && Array.isArray(probe.results) && probe.results.length) {
    const ok = probe.results.filter((r) => r.ok).length;
    parts.push(`source probe ${esc(probe.probed_at_utc || "")}: <strong>${ok}/${probe.results.length}</strong> reachable from the environment that ran it`);
  }
  summary.innerHTML = parts.length ? parts.join(" · ")
    : "No measured coverage report is committed yet. Run the coverage job from an environment with access to NHL endpoints.";

  if (cov && Array.isArray(cov.seasons) && cov.seasons.length) {
    tbody.innerHTML = cov.seasons.map((r) => `
      <tr>
        <td>${esc(seasonLabel(r.season))}</td>
        <td>${esc(r.report_is_frozen_original ? "frozen at game time (original record)" : r.available === false ? "no report" : r.report_generated_at ? "regenerated in place" : "available, era undetermined")}</td>
        <td class="status-${r.available === false ? "fail" : r.http_status === 200 ? "ok" : "warn"}">${dash(r.http_status)}</td>
        <td>${dash(r.report_generated_at)}</td>
        <td>${r.url ? `<a href="${esc(r.url)}" rel="noopener">${esc(r.url)}</a>` : ""}${(r.parse_warnings || []).length ? ` <span class="muted">${esc(r.parse_warnings.join("; "))}</span>` : ""}</td>
      </tr>`).join("");
    return;
  }
  const legacy = state.legacyCoverage;
  if (legacy && Array.isArray(legacy.results) && legacy.results.length) {
    tbody.innerHTML = legacy.results.map((r) => `
      <tr><td>${esc(r.label)}</td><td>${esc(r.kind)}</td><td class="status-${esc(r.status)}">${esc(r.status)}</td><td>${dash(r.http_code)}</td><td>${r.url ? `<a href="${esc(r.url)}" rel="noopener">${esc(r.url)}</a>` : ""}</td></tr>`).join("");
    return;
  }
  tbody.innerHTML = '<tr><td colspan="5" class="muted">No per-season measurement is committed. The table stays empty rather than showing planned probes as results.</td></tr>';
}

/* ---------------- sources ---------------- */

/* The Sources tab used to hard-code a list of endpoints, two of which
 * (statsapi.web.nhl.com and the GS/ES "PDF" reports) are not what this project
 * actually reads. It now renders data/reference/sources.json, which records what
 * was fetched, when, and what the response proved. */
function renderSources() {
  const wrap = document.getElementById("source-table-wrap");
  const gaps = document.getElementById("source-gaps");
  if (!wrap) return;
  const cat = state.sourceCatalog;
  if (!cat || !cat.sources) {
    wrap.innerHTML = '<p class="muted">No source catalogue is committed. Nothing is listed rather than guessed.</p>';
    if (gaps) gaps.innerHTML = "";
    return;
  }
  const rows = Object.values(cat.sources).map((s) => `
    <tr>
      <td><strong>${esc(s.name)}</strong><br><span class="muted">${esc(s.key)}</span></td>
      <td><code>${esc(s.url_template)}</code></td>
      <td><span class="badge ${s.status === "verified" ? "badge-ok" : "badge-mut"}">${esc(s.status)}</span>${s.verified_on ? `<br><span class="muted">${esc(s.verified_on)}</span>` : ""}</td>
      <td>${esc(s.evidence || "")}${s.notes ? `<div class="muted">${esc(s.notes)}</div>` : ""}${(s.authoritative_for || []).length ? `<div class="muted">authoritative for: ${esc((s.authoritative_for || []).join(", "))}</div>` : ""}</td>
    </tr>`).join("");
  wrap.innerHTML = `<table class="probe-table"><thead><tr><th>Source</th><th>URL pattern</th><th>Status</th><th>What was actually verified</th></tr></thead><tbody>${rows}</tbody></table>`;

  if (gaps) {
    const notUsed = cat.unverified_and_deliberately_not_used || {};
    gaps.innerHTML = `<ul>${Object.entries(notUsed).map(([k, v]) =>
      `<li><strong>${esc(k)}</strong> — ${esc(v)}</li>`).join("")}</ul>`;
  }
}

/* ---------------- CSV export ---------------- */

function csvEscape(value) {
  const s = value === null || value === undefined ? "" : String(value);
  return /[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
}

function exportCsv() {
  const rows = [["id", "store", "date", "season", "away", "home", "game_id", "period", "clock", "team",
    "status", "family", "changes_game_total", "attribution_only", "goal_total_impact_established",
    "types", "timing", "timing_uncertain", "settlement_risk",
    "original_ruling", "original_scorer", "original_assists",
    "corrected_ruling", "corrected_scorer", "corrected_assists",
    "reason_stated_by_league", "reason", "needs_human_review", "flags", "evidence_urls"]];
  applyFilters().forEach((r) => {
    const o = r.original || {}, x = r.corrected || {};
    rows.push([r.id, r.source_db, r.date, r.season, r.away, r.home, r.game_id, r.period, r.clock, r.team,
      r.status, recordFamily(r), r.changes_game_total, r.attribution_only, !r.total_change_unknown,
      (r.types || []).join("|"), r.timing, r.timing_uncertain, r.market_risk,
      o.ruling, o.scorer, (o.assists || []).join("|"),
      x.ruling, x.scorer, (x.assists || []).join("|"),
      r.reason_stated_by_league, r.reason_text || "", needsHumanReview(r),
      (r.flags || []).join("|"), (r.evidence || []).map((e) => e.url).join("|")]);
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

const FILTER_IDS = ["f-family", "f-season", "f-team", "f-period", "f-type", "f-timing",
  "f-date-from", "f-date-to", "f-search"];
const CHECK_IDS = ["f-settlement", "f-flagged-only", "f-verified-only"];

function wire() {
  document.querySelectorAll(".tab").forEach((t) =>
    t.addEventListener("click", () => switchView(t.dataset.view)));

  FILTER_IDS.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener(id === "f-search" ? "input" : "change", renderFiltered);
  });
  CHECK_IDS.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", renderFiltered);
  });

  const clear = document.getElementById("f-clear");
  if (clear) clear.addEventListener("click", () => {
    FILTER_IDS.forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      if (el.tagName === "SELECT") el.value = "all"; else el.value = "";
    });
    CHECK_IDS.forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.checked = false;
    });
    renderFiltered();
  });
  const csv = document.getElementById("f-csv");
  if (csv) csv.addEventListener("click", exportCsv);
}

/* Exposed for tools/check_root_site.mjs, which runs this file in a stub DOM and
 * asserts on the rendered output. Without a handle like this the published page
 * has no automated check at all — which is how a broken renderer reached main. */
if (typeof window !== "undefined") {
  window.__sdn = {
    state,
    recordFamily,
    needsHumanReview,
    applyFilters,
    matchesFilters,
    renderDatabase,
    renderAlerts,
    renderQueue,
    renderCoverage,
    renderSources,
    capabilities,
    recordCard,
  };
}

(async function init() {
  wire();
  await loadAll();
  renderDatabase();
  renderAlerts();
  renderQueue();
  renderCoverage();
  renderSources();
})();

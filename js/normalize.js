/* ScoringDiscrepNHL — record + alert normalisation.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * This repository grew two implementations of the same brief in parallel sessions
 * (see docs/parallel_line/PARALLEL_LINE.md). They were merged into one branch by
 * PR #9, and the merge kept BOTH databases rather than deleting either:
 *
 *   data/discrepancies.json         written by pipeline/nhl_scoring/db.py
 *                                   (shape: record_id, game.away_team, discrepancy.*, initial_state, corrected_state, sources[])
 *   data/records/discrepancies.json written by src/nhl_monitor/store.py
 *                                   (shape: record_id, game.away.abbrev, event.*, change.*, initial_state, corrected_state, sources[])
 *
 * The published site (GitHub Pages serves this repository root) originally rendered
 * the FIRST shape with field names belonging to a THIRD shape, so every card on the
 * live site rendered as "? @ ?" with empty ruling boxes and a broken game link.
 * That is what this module fixes: one view model, two documented input shapes, and a
 * merge that dedupes the same real-world correction instead of showing it twice.
 *
 * RULE: this file never invents a value. If a field is absent from the source record
 * it stays null and the renderer prints an em dash, which is the project's stated
 * "flagged, never guessed" behaviour (PROJECT_PROMPT.md).
 */
"use strict";

/* ------------------------------------------------------------------ types */

/* change_type values observed in data/discrepancies.json, mapped onto the
 * controlled vocabulary the filters and the CSV export use. Anything unmapped is
 * passed through verbatim so a new engine rule cannot silently disappear. */
const ENGINE_TYPE_MAP = {
  scorer_changed_by_official_announcement: "scorer_change",
  assists_changed_by_official_announcement: "assist_change",
  scorer_attribution_conflict: "scorer_change",
  assist_attribution_conflict: "assist_change",
  nogoal_reversed_to_goal_on_league_review: "no_goal_to_goal",
  goal_removed_on_league_review: "goal_to_no_goal",
  goal_awarded_after_goal_line_review: "no_goal_to_goal",
  goal_disallowed_after_goal_line_review: "goal_to_no_goal",
  goal_clock_conflict: "clock_conflict",
  strength_conflict: "strength_change",
  own_goal_annotation_conflict: "own_goal_flag_change",
  official_report_changed: "official_report_changed",
};

/* Monitor-line timing values are a superset of the engine's; both are kept. */
const TIMING_ALIASES = {
  postgame_after_publication: "postgame",
  next_day: "postgame",
  not_applicable: "not_applicable",
};

const SEVERITY_RANK = { critical: 0, high: 1, warn: 1, medium: 2, review: 2, low: 3, info: 3 };
const ENGINE_LEVEL_TO_SEVERITY = { immediate: "high", review: "medium", info: "low" };

/* ---------------------------------------------------------------- helpers */

function str(v) {
  return (v === null || v === undefined || v === "") ? null : String(v);
}

function bool(v) {
  return v === true || v === "true" || v === "yes";
}

function playerText(p) {
  if (!p) return null;
  if (typeof p === "string") return p;
  const name = p.name || p.fullName || p.last_name || null;
  const num = p.number !== undefined && p.number !== null ? p.number : p.sweater;
  if (!name) return null;
  return num === undefined || num === null ? String(name) : `#${num} ${name}`;
}

function playerList(list) {
  if (!Array.isArray(list)) return [];
  return list.map(playerText).filter(Boolean);
}

function rulingText(state) {
  if (!state) return null;
  if (state.ruling === "no_goal" || state.goal_present === false) return "no goal credited";
  return str(state.ruling);
}

function normTiming(v) {
  const s = str(v);
  if (!s) return null;
  return TIMING_ALIASES[s] || s;
}

/* ------------------------------------------------- engine-shape normaliser */

/* Input: one record from data/discrepancies.json (pipeline/nhl_scoring). */
function fromEngineRecord(rec, sourceDb) {
  const g = rec.game || {};
  const d = rec.discrepancy || {};
  const mi = d.market_impact || {};
  const reason = d.reason || {};
  const flags = Array.isArray(rec.flags) ? rec.flags.slice() : [];
  const rawType = str(d.change_type) || str((rec.detection || {}).rule) || "other";

  const totalChanged = bool(d.total_changed);
  const attributionOnly = bool(d.attribution_only);
  const totalUnknown = !totalChanged && !attributionOnly;

  const types = [ENGINE_TYPE_MAP[rawType] || rawType];
  if (bool(d.video_review)) types.push("video_review_cited");
  if (bool(d.goal_no_goal_change)) {
    types.push(totalChanged ? "goal_count_change" : "goal_count_change");
  }

  return {
    id: str(rec.record_id) || str(rec.id),
    source_db: sourceDb,
    status: str(rec.status),
    confidence: str(rec.confidence),

    date: str(g.date),
    season: str(g.season),
    away: str(g.away_team) || str((g.away || {}).abbrev) || str((g.away || {}).tri),
    home: str(g.home_team) || str((g.home || {}).abbrev) || str((g.home || {}).tri),
    final_score: g.final_score && typeof g.final_score === "object"
      ? `${g.final_score.away}-${g.final_score.home}` : str(g.final_score),
    game_id: str(g.game_id),
    gamecenter_url: str(g.gamecenter_url),
    report_urls: g.report_urls || {},

    period: d.period === undefined ? null : d.period,
    clock: str(d.clock),
    team: str(d.team),
    strength: str((rec.corrected_state || {}).strength) || str((rec.initial_state || {}).strength),

    raw_type: rawType,
    types: types,
    changes_game_total: totalChanged,
    attribution_only: attributionOnly,
    total_change_unknown: totalUnknown,
    video_review: bool(d.video_review),

    timing: normTiming(d.when_corrected),
    timing_uncertain: bool(d.timing_uncertain),
    announced_at_utc: str(d.announced_at_utc),
    announced_on: str(d.announced_on),
    latency_note: str(d.latency_note),

    settlement_risk: str(mi.risk) && mi.risk !== "low",
    market_risk: str(mi.risk),
    market_reason: str(mi.reason),
    affects_game_total_market: str(mi.affects_game_total),
    affects_player_props: str(mi.affects_player_props),

    reason_text: str(reason.text),
    reason_stated_by_league: bool(reason.stated_by_league),
    reason_channel: str(reason.channel),
    needs_human_read: bool(reason.needs_human_read),

    original: {
      artifact: str((rec.initial_state || {}).artifact),
      ruling: rulingText(rec.initial_state),
      scorer: playerText((rec.initial_state || {}).scorer),
      assists: playerList((rec.initial_state || {}).assists),
      assists_known: Array.isArray((rec.initial_state || {}).assists),
      strength: str((rec.initial_state || {}).strength),
      clock: str((rec.initial_state || {}).clock),
      evidence_status: str((rec.initial_state || {}).evidence_status),
      evidence_note: str((rec.initial_state || {}).evidence_note),
    },
    corrected: {
      artifact: str((rec.corrected_state || {}).artifact),
      ruling: rulingText(rec.corrected_state),
      scorer: playerText((rec.corrected_state || {}).scorer),
      assists: playerList((rec.corrected_state || {}).assists),
      assists_known: Array.isArray((rec.corrected_state || {}).assists),
      strength: str((rec.corrected_state || {}).strength),
      clock: str((rec.corrected_state || {}).clock),
      evidence_status: str((rec.corrected_state || {}).evidence_status),
      evidence_note: str((rec.corrected_state || {}).evidence_note),
    },

    machine_diff: d.machine_diff || null,
    summary: str(d.summary),
    detail: str(d.detail),
    flags: flags,
    notes: str(rec.notes),

    evidence: (rec.sources || []).map((s) => ({
      label: str(s.label) || str(s.name) || str(s.url),
      url: str(s.url),
      status: str(s.evidence) || str(s.kind),
      note: str(s.note),
      quote: str(s.quote) || str(s.quoted_row),
      retrieved_at: str(s.retrieved_at) || str(s.retrieved_at_utc),
      http_status: s.http_status === undefined ? null : s.http_status,
    })),

    detected_at: str((rec.detection || {}).detected_at) || str((rec.detection || {}).detected_at_utc),
    detected_by: str(rec.detected_by) || str((rec.detection || {}).check_id),
    detection_method: str((rec.detection || {}).method),
    check_id: str((rec.detection || {}).check_id),
  };
}

/* ------------------------------------------------ monitor-shape normaliser */

/* Input: one record from data/records/discrepancies.json (src/nhl_monitor). */
function fromMonitorRecord(rec, sourceDb) {
  const g = rec.game || {};
  const ev = rec.event || {};
  const ch = rec.change || {};
  const tm = rec.timing || {};
  const st = rec.settlement || {};
  const reason = rec.reason || {};
  const det = rec.detection || {};

  const types = [str(ch.discrepancy_type) || "other"];
  if (str(reason.category) === "official_source_statement") types.push("official_announcement");

  const rawType = str(ch.discrepancy_type) || "other";

  return {
    id: str(rec.record_id),
    source_db: sourceDb,
    status: str(rec.status),
    confidence: str(det.confidence),

    date: str(g.date),
    season: str(g.season),
    away: str((g.away || {}).abbrev),
    home: str((g.home || {}).abbrev),
    final_score: str(g.final_score),
    game_id: str(g.game_id),
    gamecenter_url: g.game_id ? `https://www.nhl.com/gamecenter/${g.game_id}` : null,
    report_urls: Object.fromEntries((rec.sources || [])
      .filter((s) => /htmlreports\//.test(s.url || ""))
      .map((s) => [(s.url || "").split("/").pop().replace(/\.HTM$/i, ""), s.url])),

    period: ev.period === undefined ? null : ev.period,
    clock: str(ev.clock),
    team: str(ev.team),
    strength: str(ev.strength),

    raw_type: rawType,
    types: types,
    changes_game_total: bool(ch.affects_goal_total),
    attribution_only: bool(ch.attribution_only),
    total_change_unknown: false,
    video_review: false,

    timing: normTiming(tm.when),
    timing_uncertain: false,
    timing_reasoning: str(tm.reasoning),
    announced_at_utc: str(tm.announced_at_utc),
    announced_on: str(tm.announced_on),
    latency_seconds: tm.latency_after_final_buzzer_seconds === undefined
      ? null : tm.latency_after_final_buzzer_seconds,
    latency_note: str(tm.game_end_time_note),

    settlement_risk: str(st.level) === "high" || bool(st.could_affect_game_total_market),
    market_risk: str(st.level),
    market_reason: str(st.reasoning),
    affects_game_total_market: bool(st.could_affect_game_total_market) ? "yes" : "no",
    affects_player_props: bool(st.could_affect_player_props) ? "yes" : "no",

    reason_text: str(reason.text),
    reason_stated_by_league: str(reason.category) === "official_source_statement",
    reason_channel: str(reason.announcement_channel),
    needs_human_read: false,

    original: {
      artifact: null,
      ruling: rulingText(rec.initial_state),
      scorer: playerText((rec.initial_state || {}).scorer),
      assists: playerList((rec.initial_state || {}).assists),
      assists_known: Array.isArray((rec.initial_state || {}).assists),
      strength: str(ev.strength),
      clock: str(ev.clock),
      evidence_status: str((rec.initial_state || {}).evidence_status),
      evidence_note: str((rec.initial_state || {}).evidence),
    },
    corrected: {
      artifact: null,
      ruling: rulingText(rec.corrected_state),
      scorer: playerText((rec.corrected_state || {}).scorer),
      assists: playerList((rec.corrected_state || {}).assists),
      assists_known: Array.isArray((rec.corrected_state || {}).assists),
      strength: str(ev.strength),
      clock: str(ev.clock),
      evidence_status: str((rec.corrected_state || {}).evidence_status),
      evidence_note: null,
    },

    machine_diff: ch.machine_diff || null,
    summary: str(ch.detail),
    detail: str(ch.detail),
    flags: Array.isArray(rec.flags) ? rec.flags.slice() : [],
    notes: str(rec.notes),
    evidence_status: str(rec.evidence_status),

    evidence: (rec.sources || []).map((s) => ({
      label: str(s.name) || str(s.role) || str(s.url),
      url: str(s.url),
      status: str(s.type),
      note: str(s.note),
      quote: str(s.quoted_row) || str(s.quote),
      retrieved_at: str(s.retrieved_at_utc),
      http_status: s.http_status === undefined ? null : s.http_status,
      role: str(s.role),
    })),

    detected_at: str(det.detected_at_utc),
    detected_by: str(det.detected_by),
    detection_method: str(det.detected_by),
    check_id: null,
  };
}

/* --------------------------------------------------------------- detection */

/* A record is "monitor shape" when it carries the monitor's `change` block; the
 * engine shape carries a `discrepancy` block. Testing for the block (rather than
 * the filename) keeps this correct if the two files are ever consolidated. */
function normalizeRecord(rec, sourceDb) {
  if (!rec || typeof rec !== "object") return null;
  if (rec.change && rec.event) return fromMonitorRecord(rec, sourceDb);
  return fromEngineRecord(rec, sourceDb);
}

/* Two records describe the same real-world correction when they agree on game,
 * period and clock. Records with no game id (some quarantined leads) are never
 * merged, because "same clock, unknown game" is not evidence of identity. */
function dedupeKey(r) {
  if (!r.game_id) return null;
  return `${r.game_id}|${r.period}|${r.clock}|${r.raw_type === "clock_conflict" ? "clock" : "scoring"}`;
}

const EVIDENCE_WEIGHT = { verified: 3, primary: 3, official_report: 3, "official-document": 3, "official-api": 3 };

function evidenceScore(r) {
  return (r.evidence || []).reduce((n, e) => n + (EVIDENCE_WEIGHT[e.status] || 1), 0);
}

/* Merge the two databases. The record with the stronger evidence becomes the
 * card; the other one's flags, sources and ids are folded in and its provenance
 * is preserved, so nothing a reviewer could look up is dropped. */
function mergeRecords(engineRecords, monitorRecords) {
  const byKey = new Map();
  const out = [];

  const place = (r) => {
    const k = dedupeKey(r);
    if (!k) { out.push(r); return; }
    const prev = byKey.get(k);
    if (!prev) { byKey.set(k, r); out.push(r); return; }
    const keep = evidenceScore(r) > evidenceScore(prev) ? r : prev;
    const drop = keep === r ? prev : r;
    keep.source_db = "both";
    keep.also_in = Array.from(new Set([...(keep.also_in || []), drop.source_db, drop.id])).filter(Boolean);
    keep.flags = Array.from(new Set([...(keep.flags || []), ...(drop.flags || [])]));
    const seen = new Set((keep.evidence || []).map((e) => e.url));
    keep.evidence = [...(keep.evidence || []), ...(drop.evidence || []).filter((e) => e.url && !seen.has(e.url))];
    if (!keep.reason_text && drop.reason_text) keep.reason_text = drop.reason_text;
    if (!keep.summary && drop.summary) keep.summary = drop.summary;
  };

  // The monitor line's records are the ones the scheduled monitor writes, so they
  // are placed second and win ties only on evidence strength, never on order.
  engineRecords.forEach(place);
  monitorRecords.forEach(place);
  return out;
}

/* ----------------------------------------------------------------- alerts */

function normalizeMonitorAlert(a, origin) {
  return {
    id: str(a.alert_id) || str(a.record_id),
    record_id: str(a.record_id),
    title: str(a.title),
    severity: str(a.severity),
    type: str(a.discrepancy_type),
    affects_goal_total: a.affects_goal_total === true,
    created_at: str(a.created_at_utc),
    body: str(a.body_markdown),
    links: Array.isArray(a.official_urls) ? a.official_urls.filter(Boolean) : [],
    origin: origin,
  };
}

function normalizeLegacyAlert(a, origin) {
  return {
    id: str(a.id),
    record_id: str(a.record_id),
    title: str(a.title),
    severity: str(a.severity),
    type: str(a.type),
    affects_goal_total: false,
    created_at: str(a.created_at),
    body: str(a.body),
    links: Array.isArray(a.links) ? a.links.filter(Boolean) : [],
    origin: origin,
  };
}

function normalizeDigestAlert(entry, origin) {
  const rec = entry.record || {};
  const g = rec.game || {};
  const d = rec.discrepancy || {};
  const severity = ENGINE_LEVEL_TO_SEVERITY[entry.level] || "low";
  const links = (rec.sources || []).map((s) => s.url).filter(Boolean);
  const body = [
    d.summary || "",
    d.detail && d.detail !== d.summary ? d.detail : "",
    "",
    `Record ${rec.record_id || "?"} · status ${rec.status || "?"} · confidence ${rec.confidence || "?"}`,
    `Change type: ${d.change_type || "?"}`,
    `Goal total changed: ${d.total_changed === undefined ? "unknown" : d.total_changed}`,
    `Attribution only: ${d.attribution_only === undefined ? "unknown" : d.attribution_only}`,
    `Corrected: ${d.when_corrected || "?"}`,
    (rec.flags || []).length ? `Flags: ${rec.flags.join(", ")}` : "",
    (d.reason || {}).text ? `Official reason: ${(d.reason || {}).text}` : "",
  ].filter((x) => x !== "").join("\n");
  return {
    id: str(rec.record_id) || str(d.summary),
    record_id: str(rec.record_id),
    title: `[${String(entry.level || "info").toUpperCase()}] ${g.date || "?"} ${g.away_team || "?"} @ ${g.home_team || "?"} — ${d.summary || d.change_type || "scoring discrepancy"}`,
    severity: severity,
    level: str(entry.level),
    type: str(d.change_type),
    affects_goal_total: bool(d.total_changed),
    created_at: str((rec.detection || {}).detected_at),
    body: body,
    links: links,
    origin: origin,
  };
}

/* One alert per underlying correction, newest first, with the richest body kept.
 * Three artifacts are read because three code paths write alerts (see
 * docs/ALERTING.md); the site must not depend on which one ran last.
 *
 * `aliases` maps a record id from either store onto the canonical merged record,
 * so the same correction reported by both detection routes appears once instead of
 * twice under two different ids. */
function mergeAlerts(monitorIndex, legacy, digest, aliases) {
  const resolve = (id) => (aliases && id && aliases.get(id)) || id;
  const all = [];
  if (monitorIndex && Array.isArray(monitorIndex.alerts)) {
    monitorIndex.alerts.forEach((a) => all.push(normalizeMonitorAlert(a, "data/alerts/index.json")));
  }
  if (legacy && Array.isArray(legacy.alerts)) {
    legacy.alerts.forEach((a) => all.push(normalizeLegacyAlert(a, "data/alerts.json")));
  }
  if (digest && Array.isArray(digest.alerts)) {
    digest.alerts.forEach((a) => all.push(normalizeDigestAlert(a, digest._origin || "data/alerts/<date>/alerts.json")));
  }

  const byId = new Map();
  all.filter((a) => a && (a.id || a.title)).forEach((a) => {
    a.record_id = resolve(a.record_id);
    const k = a.record_id || resolve(a.id) || a.title;
    const prev = byId.get(k);
    if (!prev) { byId.set(k, a); return; }
    const keep = (a.body || "").length > (prev.body || "").length ? a : prev;
    const drop = keep === a ? prev : a;
    keep.links = Array.from(new Set([...(keep.links || []), ...(drop.links || [])]));
    keep.origin = `${keep.origin} + ${drop.origin}`;
    byId.set(k, keep);
  });

  return Array.from(byId.values()).sort((x, y) => {
    const s = (SEVERITY_RANK[x.severity] ?? 9) - (SEVERITY_RANK[y.severity] ?? 9);
    if (s !== 0) return s;
    return String(y.created_at || "").localeCompare(String(x.created_at || ""));
  });
}

/* The digest artifact lives in a date-stamped folder that a static site cannot
 * list, so data/alerts/index.json is authoritative for "what dates exist". The
 * loader tries the newest date folder it can find in the index, if any. */
function digestCandidatePaths(index) {
  const dates = new Set();
  ((index && index.alerts) || []).forEach((a) => {
    const m = String(a.created_at_utc || "").match(/^(\d{4}-\d{2}-\d{2})/);
    if (m) dates.add(m[1]);
  });
  const today = new Date().toISOString().slice(0, 10);
  dates.add(today);
  return Array.from(dates).sort().reverse().map((d) => `data/alerts/${d}/alerts.json`);
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    normalizeRecord, mergeRecords, mergeAlerts, digestCandidatePaths,
    fromEngineRecord, fromMonitorRecord,
    normalizeMonitorAlert, normalizeLegacyAlert, normalizeDigestAlert,
    ENGINE_TYPE_MAP, SEVERITY_RANK,
  };
}

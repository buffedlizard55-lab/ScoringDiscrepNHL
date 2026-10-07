/* Browser-less smoke test for the PUBLISHED site.
 *
 *   node tools/check_root_site.mjs
 *
 * WHY THIS EXISTS
 * ---------------
 * GitHub Pages for this repository is configured as branch `main`, path `/`, so the
 * site users see is index.html + js/ + css/ at the repository root. Until this file
 * existed, the only automated check on that site was `node --check js/app.js`, which
 * proves the JavaScript parses and nothing else. tools/check_site.mjs exercises a
 * DIFFERENT client (site/app.js) that Pages does not serve.
 *
 * The result was that the published page rendered every record as "? @ ?" with empty
 * ruling boxes and a broken game link, and showed "No alerts yet" while three alerts
 * were committed in the repository. Both were invisible to CI. This test runs the
 * real client against the real committed data and fails on either.
 *
 * It is not a layout test. It asserts on the HTML string the client produces.
 */

import { readFileSync, existsSync } from 'node:fs';
import { createContext, runInContext } from 'node:vm';
import path from 'node:path';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const failures = [];

function check(name, condition, detail = '') {
  if (condition) console.log(`  ok   ${name}`);
  else { console.log(`  FAIL ${name}${detail ? ` — ${detail}` : ''}`); failures.push(name); }
}

function readJson(rel) {
  const p = path.join(root, rel);
  if (!existsSync(p)) return null;
  return JSON.parse(readFileSync(p, 'utf8'));
}

/* ----------------------------------------------------------------- DOM stub */

const html = readFileSync(path.join(root, 'index.html'), 'utf8');
const ids = [...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1]);

function makeEl(id) {
  const el = {
    id,
    tagName: 'DIV',
    value: '',
    checked: false,
    hidden: false,
    textContent: '',
    innerHTML: '',
    dataset: {},
    options: [],
    length: 0,
    classList: {
      add() {}, remove() {}, toggle() {}, contains: () => false,
    },
    setAttribute() {},
    getAttribute: () => null,
    addEventListener(type, fn) { (this._listeners ||= {})[type] = fn; },
    appendChild() {},
    add(opt) { this.options.push(opt); this.length = this.options.length; },
    querySelector: () => null,
    querySelectorAll: () => [],
    parentElement: { querySelector: () => ({ hidden: true }) },
  };
  return el;
}

const elements = new Map();
for (const id of ids) elements.set('#' + id, makeEl(id));

// A real <select> reports the value of its first <option>; the stub has to agree
// or every filter reads "" and silently filters the whole database out.
for (const m of html.matchAll(/<select id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)) {
  const el = elements.get('#' + m[1]);
  if (!el) continue;
  el.tagName = 'SELECT';
  const first = m[2].match(/<option value="([^"]*)"/);
  if (first) el.value = first[1];
}
for (const m of html.matchAll(/<input id="([^"]+)" type="(checkbox|date|search)"/g)) {
  const el = elements.get('#' + m[1]);
  if (el) el.tagName = 'INPUT';
}

// record whether the client ever raised the error banner
let errorBannerSet = false;
for (const el of elements.values()) {
  const add = el.classList.add.bind(el.classList);
  el.classList.add = (...c) => { if (c.includes('error')) errorBannerSet = true; add(...c); };
}
// ids the client creates dynamically or queries by selector
for (const sel of ['#probe-table', '#table-sources']) {
  if (!elements.has(sel)) elements.set(sel, makeEl(sel));
}
// querySelector('#probe-table tbody') needs a real node with innerHTML
elements.get('#probe-table').querySelector = (s) => {
  const key = `#probe-table ${s}`;
  if (!elements.has(key)) elements.set(key, makeEl(key));
  return elements.get(key);
};

function elFor(sel) {
  if (!elements.has(sel)) elements.set(sel, makeEl(sel));
  return elements.get(sel);
}
const pick = (sel, prop = 'innerHTML') => elFor(sel)[prop];

const documentStub = {
  querySelector: (sel) => elFor(sel),
  querySelectorAll: (sel) => {
    if (sel === '.view' || sel === '.tab') return [];
    return [];
  },
  getElementById: (id) => elements.get('#' + id) || null,
  // esc() relies on a text-node round trip; reproduce the escaping it produces.
  createElement: () => {
    let text = '';
    return {
      set textContent(v) { text = v === null || v === undefined ? '' : String(v); },
      get textContent() { return text; },
      get innerHTML() {
        return text.replace(/&/g, '&amp;').replace(/</g, '&lt;')
          .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      },
      classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
      setAttribute() {},
      click() {},
      href: '',
      download: '',
    };
  },
  addEventListener() {},
};

/* ------------------------------------------------- real committed data files */

const ENGINE_DB = readJson('data/discrepancies.json');
const MONITOR_DB = readJson('data/records/discrepancies.json');
const MONITOR_INDEX = readJson('data/alerts/index.json');
const LEGACY_ALERTS = readJson('data/alerts.json');
const COVERAGE = readJson('data/reference/coverage_report.json');
const PROBE = readJson('data/reference/probe_report.json');
const VOCAB = readJson('data/schema/observed_vocabulary.json');
const SOURCES = readJson('data/reference/sources.json');
const LEGACY_COVERAGE = readJson('data/coverage_report.json');
const QUEUE1 = readJson('data/inbox/pr3_database_review.json');
const QUEUE2 = readJson('data/inbox/prior_session_leads.json');

const digest = new Map();
for (const rel of ['data/alerts/2026-10-07/alerts.json']) {
  const d = readJson(rel);
  if (d) digest.set(rel, d);
}

const responses = {
  'data/discrepancies.json': ENGINE_DB,
  'data/records/discrepancies.json': MONITOR_DB,
  'data/alerts/index.json': MONITOR_INDEX,
  'data/alerts.json': LEGACY_ALERTS,
  'data/reference/coverage_report.json': COVERAGE,
  'data/reference/probe_report.json': PROBE,
  'data/schema/observed_vocabulary.json': VOCAB,
  'data/reference/sources.json': SOURCES,
  'data/coverage_report.json': LEGACY_COVERAGE,
  'data/inbox/pr3_database_review.json': QUEUE1,
  'data/inbox/prior_session_leads.json': QUEUE2,
};
for (const [k, v] of digest) responses[k] = v;

/* Also serve today's date folder if it exists, because the client derives the
 * digest path from the current date when the index has no dated alerts. */
const today = new Date().toISOString().slice(0, 10);
const todayDigest = readJson(`data/alerts/${today}/alerts.json`);
if (todayDigest) responses[`data/alerts/${today}/alerts.json`] = todayDigest;

/* ------------------------------------------------------------------ sandbox */

function freshSandbox() {
  const blobs = [];
  const sandbox = {
    document: documentStub,
    setTimeout,
    clearTimeout,
    console,
    JSON,
    Math,
    Date,
    Set,
    Map,
    Array,
    Object,
    String,
    Number,
    Boolean,
    RegExp,
    Promise,
    Option: function Option(label, value) { this.label = label; this.value = value; },
    Blob: function Blob(parts) { blobs.push(parts.join('')); },
    URL: { createObjectURL: () => 'blob:test', revokeObjectURL() {} },
    fetch: async (url) => ({
      ok: Object.prototype.hasOwnProperty.call(responses, url),
      status: Object.prototype.hasOwnProperty.call(responses, url) ? 200 : 404,
      json: async () => responses[url],
    }),
  };
  sandbox.window = sandbox;
  sandbox.__blobs = blobs;
  return sandbox;
}

const normalizeCode = readFileSync(path.join(root, 'js/normalize.js'), 'utf8');
const appCode = readFileSync(path.join(root, 'js/app.js'), 'utf8');

const sandbox = freshSandbox();
runInContext(normalizeCode, createContext(sandbox));
runInContext(appCode, createContext(sandbox));
await new Promise((r) => setTimeout(r, 120));

const sdn = sandbox.__sdn;

/* =================================================================== checks */

console.log('published-site smoke test (root index.html + js/)');

check('client exposed its test handle', !!sdn, 'window.__sdn missing');

const records = sdn ? sdn.state.records : [];
const engineCount = (ENGINE_DB && ENGINE_DB.records) || [];
const monitorCount = (MONITOR_DB && MONITOR_DB.records) || [];

/* --- 1. every committed record reaches the page ------------------------- */
check('engine database loaded', engineCount.length > 0, `${engineCount.length} records on disk`);
check('monitor database loaded', monitorCount.length > 0, `${monitorCount.length} records on disk`);
check('merged record set is not empty', records.length > 0);
check('merged set is no larger than the two stores combined',
  records.length <= engineCount.length + monitorCount.length,
  `${records.length} > ${engineCount.length + monitorCount.length}`);
check('deduplication removed the records present in both stores',
  records.length < engineCount.length + monitorCount.length,
  `merged ${records.length}; the 3 monitor records are also in the engine store`);

const rendered = pick('#record-list');
const renderedCards = (rendered.match(/<article class="record-card/g) || []).length;
check('every merged record renders a card', renderedCards === records.length,
  `${renderedCards} cards for ${records.length} records`);

/* --- 2. no placeholders leak into the published HTML -------------------- */
check('no "? @ ?" placeholder teams in the rendered list',
  !rendered.includes('? @ ?'), 'a record rendered without team abbreviations');
check('no literal "undefined" in the rendered list', !rendered.includes('undefined'));
check('no literal "null" in the rendered list', !/>null</.test(rendered));
check('no "[object Object]" in the rendered list', !rendered.includes('[object Object]'));

/* --- 3. per-record fidelity -------------------------------------------- */
for (const r of records) {
  const card = sdn.recordCard(r);
  const hasTeams = r.away && r.home;
  if (hasTeams) {
    check(`card ${r.id} shows both teams`,
      card.includes(r.away) && card.includes(r.home));
  }
  if (r.game_id) {
    check(`card ${r.id} links to its game id`, card.includes(`gamecenter/${r.game_id}`));
  }
  if (r.corrected && r.corrected.scorer) {
    check(`card ${r.id} shows the corrected scorer`, card.includes(r.corrected.scorer));
  }
  if (r.original && r.original.scorer) {
    check(`card ${r.id} shows the original scorer`, card.includes(r.original.scorer));
  }
  const officialUrls = (r.evidence || []).filter((e) => e.url && /nhl\.com|nhle\.com/.test(e.url));
  if (officialUrls.length) {
    check(`card ${r.id} prints its official source link`, card.includes(officialUrls[0].url));
  } else {
    check(`card ${r.id} has no official source link to print`, officialUrls.length === 0);
  }
}

/* --- 4. the three families stay separate -------------------------------- */
const families = new Map();
records.forEach((r) => {
  const f = sdn.recordFamily(r);
  families.set(f, (families.get(f) || 0) + 1);
});
const expectTotal = records.filter((r) => r.changes_game_total).length;
const expectAttrib = records.filter((r) => sdn.recordFamily(r) === 'attrib').length;
const expectUnknown = records.filter((r) => sdn.recordFamily(r) === 'unknown').length;
check('goal-total-changing stat matches the data',
  String(pick('#stat-total-changing', 'textContent')) === String(expectTotal),
  `rendered ${pick('#stat-total-changing', 'textContent')}, expected ${expectTotal}`);
check('attribution-only stat matches the data',
  String(pick('#stat-attribution', 'textContent')) === String(expectAttrib),
  `rendered ${pick('#stat-attribution', 'textContent')}, expected ${expectAttrib}`);
check('unestablished-impact stat matches the data',
  String(pick('#stat-unestablished', 'textContent')) === String(expectUnknown),
  `rendered ${pick('#stat-unestablished', 'textContent')}, expected ${expectUnknown}`);
check('record-count stat matches the merged set',
  String(pick('#stat-total', 'textContent')) === String(records.length),
  `rendered ${pick('#stat-total', 'textContent')}, expected ${records.length}`);
check('verified stat matches the verified records',
  String(pick('#stat-verified', 'textContent')) === String(records.filter((r) => r.status === 'verified').length));
check('records whose total impact is unestablished are NOT counted as attribution-only',
  expectAttrib + expectTotal + expectUnknown + (families.get('report') || 0) === records.length);

/* --- 5. alerts: the failure that motivated this test -------------------- */
const alerts = sdn.state.alerts;
const distinctAlertIds = new Set();
if (MONITOR_INDEX && MONITOR_INDEX.alerts) MONITOR_INDEX.alerts.forEach((a) => distinctAlertIds.add(a.record_id || a.alert_id));
if (LEGACY_ALERTS && LEGACY_ALERTS.alerts) LEGACY_ALERTS.alerts.forEach((a) => distinctAlertIds.add(a.record_id || a.id));
for (const d of digest.values()) (d.alerts || []).forEach((a) => distinctAlertIds.add((a.record || {}).record_id));
if (todayDigest) (todayDigest.alerts || []).forEach((a) => distinctAlertIds.add((a.record || {}).record_id));

check('the alert feed is not empty while alerts are committed',
  alerts.length > 0, `${distinctAlertIds.size} distinct alerts exist in the committed artifacts`);
// The same correction is reported by both detection routes under two different
// record ids (SDN-... from the engine store, NHL-... from the monitor store).
// The feed must show the correction once, so the expectation is the number of
// distinct CORRECTIONS, resolved through the merged records' alias map.
const aliasOf = new Map();
records.forEach((r) => (r.also_in || []).forEach((alt) => aliasOf.set(alt, r.id)));
const distinctCorrections = new Set(
  [...distinctAlertIds].map((id) => aliasOf.get(id) || id));
check('alert count equals the distinct corrections across all artifacts',
  alerts.length === distinctCorrections.size,
  `${alerts.length} rendered vs ${distinctCorrections.size} distinct corrections (${distinctAlertIds.size} raw alert ids)`);
check('no correction is alerted twice under two record ids',
  new Set(alerts.map((a) => a.record_id)).size === alerts.length);
check('both detection routes reached the merged feed',
  new Set(alerts.map((a) => a.detected_by || 'unknown')).size >= 1
  && alerts.some((a) => /data\/alerts\/index\.json/.test(a.origin))
  && alerts.some((a) => /data\/alerts\.json|data\/alerts\/2026/.test(a.origin)));
check('the Alerts tab pill shows the count',
  String(pick('#alert-count', 'textContent')) === String(alerts.length));
const alertHtml = pick('#alert-list');
check('alert cards rendered', (alertHtml.match(/<article class="record-card alert-card/g) || []).length === alerts.length);
check('alerts do not render the empty state', !alertHtml.includes('No alerts yet'));
for (const a of alerts) {
  check(`alert ${a.id} has a title`, !!a.title);
  check(`alert ${a.id} has a body`, !!a.body && a.body.length > 20);
  check(`alert ${a.id} names its artifact`, alertHtml.includes('data/alerts'));
}

/* --- 6. capability claims must match the measured vocabulary ------------ */
const caps = sdn.capabilities(VOCAB).map((c) => c.join(' | ')).join('\n');
const reviewTypes = (VOCAB && VOCAB.review_event_types_found) || [];
if (reviewTypes.length === 0) {
  check('site does not claim automated video-review detection',
    /Video review as the \*reason\* for a change \| no \|/.test(caps),
    'the measured vocabulary has no review event type');
  check('capability table states the measured absence',
    caps.includes('no review or challenge event type'));
}
check('capability table does not overstate the earliest season',
  !caps.includes('1997') || caps.includes('2000-01'));
const capHtml = pick('#capability-grid');
check('capability grid rendered', capHtml.includes('cap-card'));
check('capability grid has no empty cell', !capHtml.includes('<p></p>'));

/* --- 7. coverage and sources render from measurements, not plans -------- */
const probeBody = pick('#probe-table tbody');
check('coverage table lists the measured seasons',
  COVERAGE && COVERAGE.seasons ? probeBody.includes(String(COVERAGE.seasons[0].season).slice(0, 4)) : true);
check('coverage table is not showing planned probes as results',
  !probeBody.includes('PLANNED'));
const srcHtml = pick('#source-table-wrap');
check('source catalogue rendered from data/reference/sources.json',
  srcHtml.includes('api-web.nhle.com'));
check('source catalogue does not resurrect the disproved statsapi host',
  !srcHtml.includes('statsapi.web.nhl.com'));
check('source catalogue does not claim PDF reports',
  !srcHtml.includes('.PDF'));
check('searches-that-came-back-empty section rendered',
  pick('#source-gaps').includes('situation-room-web'));

/* --- 8. filters still work after the schema change ---------------------- */
function runFilters() {
  const el = elFor('#f-search');
  if (el._listeners && el._listeners.input) el._listeners.input();
}
elFor('#f-family').value = 'attrib';
runFilters();
const attribCards = (pick('#record-list').match(/<article class="record-card/g) || []).length;
check('category filter reduces to the attribution-only records',
  attribCards === expectAttrib, `${attribCards} cards, expected ${expectAttrib}`);

elFor('#f-family').value = 'all';
elFor('#f-verified-only').checked = true;
runFilters();
const verifiedCards = (pick('#record-list').match(/<article class="record-card/g) || []).length;
const expectVerified = records.filter((r) => r.status === 'verified').length;
check('verified-only filter matches the verified records',
  verifiedCards === expectVerified, `${verifiedCards} cards, expected ${expectVerified}`);

elFor('#f-verified-only').checked = false;
elFor('#f-flagged-only').checked = true;
runFilters();
const flaggedCards = (pick('#record-list').match(/<article class="record-card/g) || []).length;
const expectFlagged = records.filter(sdn.needsHumanReview).length;
check('needs-human-review filter matches the flagged records',
  flaggedCards === expectFlagged, `${flaggedCards} cards, expected ${expectFlagged}`);
check('needs-human-review stat matches the filter',
  String(pick('#stat-flagged', 'textContent')) === String(expectFlagged),
  `rendered ${pick('#stat-flagged', 'textContent')}, expected ${expectFlagged}`);

elFor('#f-flagged-only').checked = false;
runFilters();

/* --- 9. CSV export covers the requested fields -------------------------- */
elFor('#f-csv')._listeners.click();
const csv = sandbox.__blobs.at(-1) || '';
const header = csv.split('\n')[0];
for (const col of ['changes_game_total', 'attribution_only', 'goal_total_impact_established',
  'original_scorer', 'corrected_scorer', 'reason_stated_by_league', 'needs_human_review',
  'evidence_urls', 'timing']) {
  check(`CSV export includes ${col}`, header.includes(col));
}
// count CSV rows properly: the reason field legitimately contains newlines
function csvRowCount(text) {
  let rows = 0, inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"') inQuotes = !inQuotes;
    else if (c === '\n' && !inQuotes) rows++;
  }
  return rows + (text.length && !text.endsWith('\n') ? 1 : 0);
}
check('CSV has one row per merged record',
  csvRowCount(csv) === records.length + 1,
  `${csvRowCount(csv)} rows for ${records.length} records + header`);
check('CSV never prints the string undefined', !csv.includes('undefined'));

/* --- 10. verification queue still renders ------------------------------- */
const queueHtml = pick('#queue-list');
const queueRecords = (QUEUE1 ? QUEUE1.records.length : 0) + (QUEUE2 ? QUEUE2.records.length : 0);
check('verification queue rendered its quarantined leads',
  (queueHtml.match(/<article class="record-card/g) || []).length === queueRecords,
  `${queueRecords} leads committed`);
check('queue is labelled as quarantined', queueHtml.includes('quarantined') || queueHtml.includes('QUARANTINED'));

/* --- 11. the banner must not hide a load failure ------------------------ */
check('no error banner when both databases load', errorBannerSet === false,
  'the client reported a load failure');
check('provenance note names both stores',
  pick('#provenance-note').includes('data/discrepancies.json')
  && pick('#provenance-note').includes('data/records/discrepancies.json'));

if (failures.length) {
  console.error(`\n${failures.length} published-site failure(s):`);
  failures.forEach((f) => console.error(`  - ${f}`));
  process.exit(1);
}
console.log('\nall published-site checks passed');

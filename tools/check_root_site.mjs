/* Browser-less smoke test for the DEPLOYED site (repository root).
 *
 *   node tools/check_root_site.mjs
 *
 * Why this file exists
 * --------------------
 * GitHub Pages for this repository serves the main-branch root (source: branch
 * `main`, path `/`), so `index.html` + `js/app.js` + `css/style.css` *is* the
 * published site. It reads the canonical database at `data/discrepancies.json`
 * and the alert feed at `data/alerts.json` over `fetch()`.
 *
 * `tools/check_site.mjs` covers the other client (`site/app.js`, monitor line)
 * against synthetic records. This one runs the deployed client against the
 * REAL committed data files, which is the only way to catch the failure mode
 * that actually happened on 2026-10-07: the canonical database was switched to
 * the engine record schema while the deployed client still spoke the pipeline
 * schema, so every record rendered as "?" teams and empty states while CI was
 * green (see docs/REPO_REVIEW.md, finding R1).
 *
 * It stubs just enough DOM to run js/app.js unmodified, then asserts that
 *   - every record in the canonical database renders, with teams and both states
 *   - the goal-total / attribution-only split is correct
 *   - the alert feed renders and its severity counts are shown
 *   - the monitor heartbeat renders, including the "stale monitor" warning
 *   - no capability claim is published without an evidence basis
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

function readJson(rel, fallback) {
  const p = path.join(root, rel);
  if (!existsSync(p)) return fallback;
  return JSON.parse(readFileSync(p, 'utf8'));
}

/* ------------------------------- DOM shim ------------------------------- */

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

class El {
  constructor(id = '') {
    this.id = id;
    this.value = '';
    this.checked = false;
    this.hidden = false;
    this.dataset = {};
    this.children = [];
    this._text = '';
    this._html = '';
    this._listeners = {};
    this.options = [];
    this.classList = {
      _set: new Set(),
      add: (...c) => c.forEach((x) => this.classList._set.add(x)),
      remove: (...c) => c.forEach((x) => this.classList._set.delete(x)),
      contains: (c) => this.classList._set.has(c),
      toggle: (c, on) => (on ? this.classList.add(c) : this.classList.remove(c)),
    };
  }
  get textContent() { return this._text; }
  set textContent(v) { this._text = v === null || v === undefined ? '' : String(v); }
  get innerHTML() {
    // esc() in app.js writes textContent and reads innerHTML back
    return this._html || this._text.replace(/[&<>"']/g, (c) => ESCAPES[c]);
  }
  set innerHTML(v) { this._html = v === null || v === undefined ? '' : String(v); this._text = ''; }
  setAttribute() {}
  getAttribute() { return null; }
  addEventListener(type, fn) { this._listeners[type] = fn; }
  appendChild(child) { this.children.push(child); }
  add(option) { this.options.push(option); this.length = this.options.length; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
}

/* A <select> in a browser starts at its first <option>; the shim must agree, or
 * every filter would read "" and matchesFilters() would reject every record. */
function selectDefaults(markup) {
  const out = {};
  for (const m of markup.matchAll(/<select[^>]*id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)) {
    const first = /<option[^>]*value="([^"]*)"/.exec(m[2]);
    out[m[1]] = first ? first[1] : '';
  }
  return out;
}

function makeDoc(htmlIds, defaults = {}) {
  const byId = new Map();
  for (const id of htmlIds) {
    const el = new El(id);
    if (id in defaults) el.value = defaults[id];
    byId.set(id, el);
  }
  const bySelector = new Map();
  const elFor = (key) => {
    if (!bySelector.has(key)) bySelector.set(key, new El(key));
    return bySelector.get(key);
  };
  return {
    _byId: byId,
    _elFor: elFor,
    getElementById: (id) => byId.get(id) || null,
    // js/app.js only ever queries '#probe-table tbody', '.view' and '.tab'
    querySelector: (sel) => elFor(sel),
    querySelectorAll: (sel) => {
      if (sel === '.view' || sel === '.tab') return [elFor(sel + ':0'), elFor(sel + ':1')];
      return [];
    },
    createElement: () => new El('created'),
    addEventListener() {},
  };
}

/* ------------------------------ data under test ------------------------------ */

const html = readFileSync(path.join(root, 'index.html'), 'utf8');
const htmlIds = [...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1]);

const DB = readJson('data/discrepancies.json', { records: [] });
const ALERTS = readJson('data/alerts.json', { alerts: [] });
const COVERAGE = readJson('data/coverage_report.json', null);
const CAPABILITIES = readJson('data/reference/capabilities.json', null);
const HEARTBEAT = readJson('data/alerts/heartbeat.json', null);
const QUEUE_A = readJson('data/inbox/pr3_database_review.json', null);
const QUEUE_B = readJson('data/inbox/prior_session_leads.json', null);

const responses = {
  'data/discrepancies.json': DB,
  'data/alerts.json': ALERTS,
  'data/reference/capabilities.json': CAPABILITIES,
  'data/alerts/heartbeat.json': HEARTBEAT,
  'data/inbox/pr3_database_review.json': QUEUE_A,
  'data/inbox/prior_session_leads.json': QUEUE_B,
};
if (COVERAGE) responses['data/coverage_report.json'] = COVERAGE;

async function runClient() {
  const doc = makeDoc(htmlIds, selectDefaults(html));
  const sandbox = {
    document: doc,
    console,
    JSON,
    Promise,
    Math,
    Date,
    Set,
    Array,
    Object,
    String,
    Number,
    Boolean,
    encodeURIComponent,
    setTimeout,
    Option: class Option { constructor(text, value) { this.text = text; this.value = value; } },
    fetch: async (url) => ({
      ok: url in responses && responses[url] !== null && responses[url] !== undefined,
      status: url in responses ? 200 : 404,
      json: async () => responses[url],
    }),
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  const code = readFileSync(path.join(root, 'js/app.js'), 'utf8');
  runInContext(code, createContext(sandbox));
  await new Promise((r) => setTimeout(r, 120));
  return doc;
}

/* --------------------------------- assertions --------------------------------- */

console.log('deployed root site: client vs the committed canonical data');

const records = Array.isArray(DB.records) ? DB.records : [];
const doc = await runClient();
const get = (id, prop = 'innerHTML') => {
  const el = doc.getElementById(id);
  if (!el) return `<<missing element #${id}>>`;
  return String(el[prop] ?? '');
};

const recordList = get('record-list');
const rendered = (recordList.match(/class="record-card/g) || []).length;

check('the canonical database is not empty', records.length > 0, `${records.length} records`);
check('every canonical record renders as a card', rendered === records.length,
  `rendered ${rendered} of ${records.length}`);

// Team names must survive the schema adapter: the engine schema stores
// game.away_team / game.home_team, the pipeline schema stored game.away.tri.
const teamish = records
  .map((r) => [r?.game?.away_team, r?.game?.away?.tri, r?.game?.home_team, r?.game?.home?.tri]
    .filter(Boolean))
  .flat();
const missingTeams = teamish.filter((t) => !recordList.includes(t));
check('team abbreviations are rendered for every record', missingTeams.length === 0,
  `missing: ${missingTeams.join(', ')}`);
check('no record renders an unresolved team placeholder', !recordList.includes('? @ ?'),
  'a card shows "? @ ?"');

// Both states must be visible — the brief requires the original AND the corrected.
const hasStates = records.filter((r) => {
  const before = r.initial_state || r.original || {};
  const after = r.corrected_state || r.corrected || {};
  return Object.keys(before).length > 0 && Object.keys(after).length > 0;
}).length;
check('records carrying both states render both state boxes',
  (recordList.match(/state-box/g) || []).length >= hasStates * 2,
  `${(recordList.match(/state-box/g) || []).length} state boxes for ${hasStates} two-state records`);

// Every official source link on the record must reach the page.
const urls = records.flatMap((r) => (r.sources || r.evidence || [])
  .map((s) => s.url)
  .filter((u) => typeof u === 'string' && u.startsWith('http')));
const uniqueUrls = [...new Set(urls)];
const missingUrls = uniqueUrls.filter((u) => !recordList.includes(u));
check('official source URLs are rendered as links', missingUrls.length === 0,
  `${missingUrls.length} of ${uniqueUrls.length} missing, e.g. ${missingUrls.slice(0, 2).join(' ')}`);

// Summary statistics must be computed, not left at zero, when the data says otherwise.
const expectTotalChanging = records.filter((r) => {
  const cls = r.classification || {};
  const disc = r.discrepancy || {};
  const change = r.change || {};
  return cls.changes_game_total || disc.total_changed || change.affects_goal_total;
}).length;
check('goal-total statistic matches the database',
  Number(get('stat-total-changing', 'textContent')) === expectTotalChanging,
  `site says ${get('stat-total-changing', 'textContent')}, database says ${expectTotalChanging}`);
check('record count statistic matches the database',
  Number(get('stat-total', 'textContent')) === records.length,
  `site says ${get('stat-total', 'textContent')}, database says ${records.length}`);

// Season and team filters must be populated from the data.
const seasonSel = doc.getElementById('f-season');
const teamSel = doc.getElementById('f-team');
check('season filter is populated from the database',
  seasonSel && seasonSel.options.length > 1, `${seasonSel ? seasonSel.options.length : 0} options`);
check('team filter is populated from the database',
  teamSel && teamSel.options.length > 1, `${teamSel ? teamSel.options.length : 0} options`);

/* ------------------------------- alert feed ------------------------------- */

console.log('\ndeployed root site: alert feed');
const alertList = get('alert-list');
const alerts = Array.isArray(ALERTS.alerts) ? ALERTS.alerts : [];
check('the alert feed file exists and parses', Array.isArray(ALERTS.alerts), 'data/alerts.json');
if (alerts.length) {
  const renderedAlerts = (alertList.match(/alert-card/g) || []).length;
  check('every alert in the feed renders', renderedAlerts === alerts.length,
    `rendered ${renderedAlerts} of ${alerts.length}`);
  check('alert severity is shown', /badge-(critical|immediate|high|warn|medium|review|info)/
    .test(alertList), 'no severity badge rendered');
  check('alerts carry at least one official link', alerts.every((a) => (a.links || []).length > 0
    || (a.official_urls || []).length > 0), 'an alert has no source link');
  check('alert pill count is set', String(get('alert-count', 'textContent')) === String(alerts.length),
    `pill says ${get('alert-count', 'textContent')}`);
} else {
  check('an empty feed says so explicitly rather than rendering nothing',
    alertList.length > 20, 'alert list is blank');
}

/* ------------------------- heartbeat / staleness banner ------------------------- */

console.log('\ndeployed root site: monitor heartbeat');
if (HEARTBEAT) {
  const banner = get('monitor-heartbeat');
  check('the heartbeat renders on the page', banner.length > 0, 'no #monitor-heartbeat content');
  check('the heartbeat names the last detection run',
    banner.includes(String(HEARTBEAT.last_run_utc || '')), 'last_run_utc not shown');
  const stale = HEARTBEAT.stale === true;
  check(stale ? 'a stale monitor is reported as stale' : 'a fresh monitor is not reported stale',
    banner.toLowerCase().includes(stale ? 'stale' : 'last'),
    `stale=${stale}, banner="${banner.slice(0, 120)}"`);
} else {
  console.log('  --   data/alerts/heartbeat.json not present yet (skipped)');
}

/* --------------------------- published capability claims --------------------------- */

console.log('\ndeployed root site: capability claims');
if (CAPABILITIES && Array.isArray(CAPABILITIES.capabilities)) {
  const grid = get('capability-grid');
  check('the capability grid renders from data', grid.length > 100, 'grid is empty');
  const unjustified = CAPABILITIES.capabilities.filter((c) => !c.basis || !c.evidence_status);
  check('every published capability claim carries a basis and an evidence status',
    unjustified.length === 0, unjustified.map((c) => c.title).join('; '));
  const review = CAPABILITIES.capabilities.find((c) => /video review|review/i.test(c.title));
  check('the video-review claim does not overclaim automatic detection',
    !review || review.verdict !== 'yes' || /announc|statement|text/i.test(String(review.basis)),
    review ? `${review.verdict}: ${review.basis}` : 'no review row');
} else {
  console.log('  --   data/reference/capabilities.json not present yet (skipped)');
}

/* ----------------------------------- result ----------------------------------- */

if (failures.length) {
  console.error(`\n${failures.length} check(s) failed: ${failures.join(' | ')}`);
  process.exit(1);
}
console.log('\nroot site client OK against the committed data');

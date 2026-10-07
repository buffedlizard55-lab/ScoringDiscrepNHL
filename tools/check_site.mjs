/* Browser-less smoke test for the static site client.
 *
 *   node tools/check_site.mjs
 *
 * It stubs just enough DOM to run site/app.js against synthetic records, then asserts
 * that the tables render, that the impact filter separates goal-count changes from
 * attribution-only corrections, and that no exception escapes. This is NOT a layout
 * test - it exists so a typo in the client cannot reach the published site unnoticed,
 * and so CI can check the client without a browser.
 */

import { readFileSync } from 'node:fs';
import { createContext, runInContext } from 'node:vm';
import path from 'node:path';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');

const html = readFileSync(path.join(root, 'site/index.html'), 'utf8');
const ids = [...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1]);

const elements = new Map();
function makeEl(id) {
  return {
    id,
    value: '',
    checked: false,
    hidden: false,
    textContent: '',
    innerHTML: '',
    dataset: {},
    classList: { add() {}, remove() {}, contains: () => false },
    setAttribute() {},
    getAttribute: () => null,
    addEventListener(type, fn) { (this._listeners ||= {})[type] = fn; },
    appendChild() {},
    querySelector: () => null,
    querySelectorAll: () => [],
    parentElement: { querySelector: () => ({ hidden: true }) },
  };
}
for (const id of ids) elements.set('#' + id, makeEl(id));

const RECORDS = {
  schema_version: '1.0',
  updated_at_utc: '2026-10-07T00:00:00Z',
  count: 2,
  status_note: ['why the database is empty'],
  coverage: { season_coverage_measured: { '20052006': 'frozen at game time', '20232024': 'regenerated' },
              official_sources_verified: ['api-web play-by-play'], sources_not_available_as_machine_readable: ['Situation Room feed'] },
  records: [
    {
      record_id: 'NHL-20232024-020001-01', status: 'auto_detected',
      game: { game_id: 2023020001, season: '20232024', date: '2023-10-10',
              away: { abbrev: 'NSH', score: 3 }, home: { abbrev: 'TBL', score: 5 }, final_score: '3-5' },
      event: { period: 1, period_type: 'REG', clock: '9:48', strength: 'EV', team: 'TBL' },
      initial_state: { ruling: 'goal', scorer: { name: 'N.KUCHEROV', sweater: 86 }, assists: [] },
      corrected_state: { ruling: 'goal', scorer: { name: 'B.HAGEL', sweater: 38 }, assists: [] },
      change: { discrepancy_type: 'scorer_change', affects_goal_total: false, affects_team_assignment: false,
                attribution_only: true, counts: {}, detail: 'scorer changed' },
      reason: { category: 'unknown', text: null },
      timing: { when: 'postgame_after_publication', reasoning: 'was final' },
      sources: [{ role: 'corrected_state', type: 'official-api', name: 'NHL GameCenter play-by-play',
                  url: 'https://api-web.nhle.com/v1/gamecenter/2023020001/play-by-play',
                  http_status: 200, retrieved_at_utc: '2026-10-07T00:00:00Z' }],
      evidence_status: 'verified_two_official_states',
      settlement: { level: 'attribution', could_affect_game_total_market: false, could_affect_team_markets: false,
                    could_affect_player_props: true, requires_book_specific_review: true, reasoning: 'attribution only' },
      detection: { detected_by: 'auto_poll', detected_at_utc: '2026-10-07T00:00:00Z', confidence: 'high' },
      flags: [], notes: '', completeness: { missing_requested_fields: [], fields_present: 16, fields_requested: 16, percent_complete: 100 },
    },
    {
      record_id: 'NHL-20052006-020001-02', status: 'auto_detected',
      game: { game_id: 2005020001, season: '20052006', date: '2005-10-05',
              away: { abbrev: 'MTL', score: 2 }, home: { abbrev: 'BOS', score: 1 }, final_score: '2-1' },
      event: { period: 3, period_type: 'REG', clock: '19:48', strength: 'PP', team: 'MTL' },
      initial_state: { ruling: 'no_goal', team: 'MTL', scorer: null, assists: [] },
      corrected_state: { ruling: 'goal', scorer: { name: 'M. RYDER', sweater: 73 }, assists: [] },
      change: { discrepancy_type: 'no_goal_to_goal', affects_goal_total: true, affects_team_assignment: false,
                attribution_only: false, counts: { goals_added: 1 }, detail: 'goal added' },
      reason: { category: 'official_source_statement', text: 'a scoring change was announced after review' },
      timing: { when: 'postgame_after_publication', reasoning: 'frozen document vs current database' },
      sources: [{ role: 'initial_state', type: 'official-document', name: 'Official Game Summary (HTML)',
                  url: 'https://www.nhl.com/scores/htmlreports/20052006/GS020001.HTM',
                  http_status: 200, retrieved_at_utc: '2026-10-07T00:00:00Z' }],
      evidence_status: 'verified_two_official_states',
      settlement: { level: 'high', could_affect_game_total_market: true, could_affect_team_markets: true,
                    could_affect_player_props: false, requires_book_specific_review: true, reasoning: 'total changed' },
      detection: { detected_by: 'backfill', detected_at_utc: '2026-10-07T00:00:00Z', confidence: 'high' },
      flags: [], notes: '', completeness: { missing_requested_fields: [], fields_present: 16, fields_requested: 16, percent_complete: 100 },
    },
  ],
};

const TAXONOMY = JSON.parse(readFileSync(path.join(root, 'data/taxonomy.json'), 'utf8'));
const FACTS = JSON.parse(readFileSync(path.join(root, 'data/reference/verified_facts.json'), 'utf8'));
const VOCAB = JSON.parse(readFileSync(path.join(root, 'data/schema/observed_vocabulary.json'), 'utf8'));
const SOURCES = JSON.parse(readFileSync(path.join(root, 'data/reference/sources.json'), 'utf8'));

const responses = {
  'data/records/discrepancies.json': RECORDS,
  'data/taxonomy.json': TAXONOMY,
  'data/reference/verified_facts.json': FACTS,
  'data/schema/observed_vocabulary.json': VOCAB,
  'data/reference/sources.json': SOURCES,
  'data/alerts/index.json': { count: 1, alerts: [{ alert_id: 'ALERT-1', severity: 'high', created_at_utc: '2026-10-07T00:00:00Z' }] },
};

function elFor(sel) {
  if (!elements.has(sel)) elements.set(sel, makeEl(sel));
  return elements.get(sel);
}
const pick = (sel, prop = 'innerHTML') => elFor(sel)[prop];

const documentStub = {
  querySelector: (sel) => elFor(sel),
  querySelectorAll: () => [],
  getElementById: (id) => elements.get('#' + id) || null,
  createElement: () => makeEl('option'),
  addEventListener() {},
};
let sandboxRef = null;

// A FRESH sandbox per run: re-using one sandbox would make the second run throw
// "Identifier has already been declared", since app.js declares top-level consts.
function freshSandbox() {
  const sandbox = {
    document: documentStub,
    setTimeout,
    console,
    JSON,
    Promise,
    fetch: async (url) => ({
      ok: url in responses,
      json: async () => responses[url],
    }),
  };
  sandbox.window = sandbox;
  return sandbox;
}

const code = readFileSync(path.join(root, 'site/app.js'), 'utf8');
runInContext(code, createContext(freshSandbox()));

await new Promise((r) => setTimeout(r, 60));

const failures = [];
function check(name, condition, detail = '') {
  if (condition) console.log(`  ok   ${name}`);
  else { console.log(`  FAIL ${name} ${detail}`); failures.push(name); }
}

console.log('site client smoke test');
const all = pick('#table-all tbody');
const totalTable = pick('#table-total tbody');
const attrTable = pick('#table-attr tbody');

check('renders both records in the full table', (all.match(/<tr data-id=/g) || []).length === 2);
check('goal-count table holds exactly the total-affecting record',
  totalTable.includes('NHL-20052006-020001-02') && !totalTable.includes('NHL-20232024-020001-01'));
check('attribution table holds exactly the attribution-only record',
  attrTable.includes('NHL-20232024-020001-01') && !attrTable.includes('NHL-20052006-020001-02'));
check('record count is reported', pick('#stat-count', 'textContent') === 2);
check('goal-count statistic is reported', pick('#stat-total', 'textContent') === 1);
check('alert count is reported', pick('#stat-alerts', 'textContent') === 1);
check('sources table rendered', pick('#table-sources tbody').includes('api-web.nhle.com'));
check('verification ledger rendered', pick('#facts').includes('F01'));
check('secondary leads are labelled as not evidence', pick('#leads').includes('NOT VERIFIED'));
check('coverage section rendered', pick('#coverage').includes('20052006'));
check('limits section rendered', pick('#limits-grid').length > 200);

// impact filter: attribution only
elements.get('#f-impact').value = 'attribution';
runFilterHook();
check('attribution filter reduces the full table to one row',
  (pick('#table-all tbody').match(/<tr data-id=/g) || []).length === 1);

// cause filter: video review can only match a stated official quote
elements.get('#f-impact').value = '';
elements.get('#f-cause').value = 'video_review';
runFilterHook();
check('video-review filter matches only the record whose official quote mentions review',
  pick('#table-all tbody').includes('NHL-20052006-020001-02') &&
  !pick('#table-all tbody').includes('NHL-20232024-020001-01'));

// post-final market risk
elements.get('#f-cause').value = '';
elements.get('#f-postfinal').checked = true;
runFilterHook();
check('post-final risk filter keeps only total-affecting changes after publication',
  pick('#table-all tbody').includes('NHL-20052006-020001-02') &&
  !pick('#table-all tbody').includes('NHL-20232024-020001-01'));

function runFilterHook() {
  // applyFilters is wired to every filter control via addEventListener('input'|'change');
  // calling the recorded handler is exactly what a keystroke would do
  const filterEl = elFor('#f-q');
  if (filterEl._listeners && filterEl._listeners.input) filterEl._listeners.input();
}

// --------------------------------------------------------------------------
// Second pass: the SHIPPED database, which is written by the ingest path.
// This is the integration check: it fails if a record shape produced by
// src/nhl_monitor/ingest.py cannot be rendered by the site.
// --------------------------------------------------------------------------
const shipped = JSON.parse(readFileSync(path.join(root, 'data/records/discrepancies.json'), 'utf8'));
if (shipped.count > 0) {
  console.log(`\nsite client against the shipped database (${shipped.count} records)`);
  responses['data/records/discrepancies.json'] = shipped;
  elements.clear();
  for (const id of ids) elements.set('#' + id, makeEl(id));
  sandboxRef = freshSandbox();
  runInContext(code, createContext(sandboxRef));
  await new Promise((r) => setTimeout(r, 60));

  const rows = (pick('#table-all tbody').match(/<tr data-id=/g) || []).length;
  check('every shipped record renders', rows === shipped.count, `rendered ${rows} of ${shipped.count}`);
  const attrRows = (pick('#table-attr tbody').match(/<tr data-id=/g) || []).length;
  const totalRows = (pick('#table-total tbody').match(/<tr data-id=/g) || []).length;
  const expectTotal = shipped.records.filter((r) => r.change && r.change.affects_goal_total).length;
  check('goal-count view shows only goal-count changes', totalRows === expectTotal,
    `goal-count rows ${totalRows}, expected ${expectTotal}`);
  check('attribution view accounts for the rest',
    attrRows === shipped.records.filter((r) => r.change && r.change.attribution_only).length);
  check('shipped record count statistic matches', pick('#stat-count', 'textContent') === shipped.count);
  // the detail drawer is where flags, source URLs and the tri-state check are shown
  const flagged = shipped.records.find((r) => (r.flags || []).length);
  sandboxRef.openRecord(flagged.record_id);
  const drawer = pick('#drawer-body');
  check('drawer renders every flag of the record',
    flagged.flags.every((f) => drawer.includes(f)), 'drawer is missing a flag');
  check('drawer shows the league announcement timestamp and latency',
    drawer.includes(flagged.timing.announced_at_utc) ||
    !flagged.timing.announced_at_utc);
  check('drawer lists the official sources with their URLs',
    flagged.sources.every((src) => !src.url || drawer.includes(src.url)));
  check('drawer links the official report and the statement',
    drawer.includes('x.com/NHLPR/status/') && drawer.includes('scores/htmlreports/'));
  check('drawer shows the tri-state check on the two states',
    drawer.includes('Checked from the two states'));
}

if (failures.length) {
  console.error(`\n${failures.length} site smoke test failure(s): ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nall site smoke checks passed');

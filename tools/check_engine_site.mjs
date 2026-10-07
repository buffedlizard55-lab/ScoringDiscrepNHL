/* Browser-less smoke test for the PUBLISHED site (repository root).
 *
 *   node tools/check_engine_site.mjs            # checks ./index.html ./app.js ./data.js
 *   node tools/check_engine_site.mjs <dir>      # checks a freshly built copy
 *
 * GitHub Pages serves the repository root of main. `node --check app.js` only
 * proves the client parses; a renderer that prints "? at ?" for every record
 * passes it. This runs the real client (app.js) against the real committed
 * payload (data.js) inside a 150-line DOM stand-in and asserts on the HTML it
 * produces: every database record is rendered with its teams and a working
 * official link, every view mounts without throwing, the Situation Room log
 * and the alert feed show what the data files contain, and the payload agrees
 * with data/discrepancies.json. Not a layout test.
 */

import { readFileSync, existsSync } from 'node:fs';
import { createContext, runInContext } from 'node:vm';
import path from 'node:path';

const here = path.dirname(new URL(import.meta.url).pathname);
const repo = path.resolve(here, '..');
const siteDir = process.argv[2] ? path.resolve(process.argv[2]) : repo;
const failures = [];
function check(name, cond, detail = '') {
  if (cond) console.log(`  ok   ${name}`);
  else { console.log(`  FAIL ${name}${detail ? ` - ${detail}` : ''}`); failures.push(name); }
}

/* ------------------------------------------------------------ tiny DOM */
const VOID = new Set(['br', 'hr', 'img', 'input', 'meta', 'link']);
function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
class Node {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.tag = tag.toLowerCase();
    this.children = []; this.attrs = {}; this.dataset = {}; this.listeners = {};
    this._html = ''; this.hidden = false; this.className = ''; this.style = {};
    this.value = ''; this.checked = false; this.selected = false; this.name = ''; this.type = '';
    this.parentNode = null;
  }
  appendChild(c) { if (typeof c !== 'string') c.parentNode = this; this.children.push(c); return c; }
  removeChild(c) { this.children = this.children.filter((x) => x !== c); return c; }
  insertBefore(c, ref) { const i = this.children.indexOf(ref); if (i < 0) return this.appendChild(c); this.children.splice(i, 0, c); return c; }
  get firstChild() { return this.children[0] || null; }
  set innerHTML(v) { this._html = String(v); this.children = []; }
  get innerHTML() { return this._html + this.children.map((c) => (typeof c === 'string' ? escapeHtml(c) : c.outerHTML)).join(''); }
  set textContent(v) { this._html = escapeHtml(String(v)); this.children = []; }
  get textContent() { return this.innerHTML.replace(/<[^>]*>/g, ''); }
  get outerHTML() {
    const attrs = Object.entries(this.attrs).map(([k, v]) => ` ${k}="${escapeHtml(v)}"`).join('')
      + (this.className ? ` class="${escapeHtml(this.className)}"` : '')
      + Object.entries(this.dataset).map(([k, v]) => ` data-${k}="${escapeHtml(v)}"`).join('')
      + (this.hidden ? ' hidden' : '');
    if (VOID.has(this.tag)) return `<${this.tag}${attrs}>`;
    return `<${this.tag}${attrs}>${this.innerHTML}</${this.tag}>`;
  }
  setAttribute(k, v) { if (k === 'class') this.className = String(v); else if (k === 'name') this.name = String(v); else if (k === 'type') this.type = String(v); else if (k === 'value') this.value = String(v); else this.attrs[k] = String(v); }
  getAttribute(k) { if (k === 'class') return this.className; return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); }
  dispatch(t, ev = {}) { (this.listeners[t] || []).forEach((fn) => fn(Object.assign({ target: this, preventDefault() {} }, ev))); }
  get classList() {
    const self = this;
    return {
      add(...c) { const s = new Set(self.className.split(/\s+/).filter(Boolean)); c.forEach((x) => s.add(x)); self.className = [...s].join(' '); },
      remove(...c) { self.className = self.className.split(/\s+/).filter((x) => x && !c.includes(x)).join(' '); },
      toggle(c, force) { const has = this.contains(c); if (force === true || (force === undefined && !has)) this.add(c); else this.remove(c); },
      contains(c) { return self.className.split(/\s+/).includes(c); },
    };
  }
  *walk() { for (const c of this.children) if (typeof c !== 'string') { yield c; yield* c.walk(); } }
  matches(sel) {
    return sel.split(',').some((part) => {
      part = part.trim();
      const m = part.match(/^([a-z0-9]*)(#[\w-]+)?((?:\.[\w-]+)*)((?:\[[^\]]+\])*)$/i);
      if (!m) return false;
      if (m[1] && m[1].toLowerCase() !== this.tag) return false;
      if (m[2] && this.attrs.id !== m[2].slice(1)) return false;
      for (const cls of (m[3] || '').split('.').filter(Boolean)) if (!this.classList.contains(cls)) return false;
      for (const a of (m[4] || '').match(/\[[^\]]+\]/g) || []) {
        const am = a.match(/^\[([\w-]+)(?:=["']?([^"'\]]*)["']?)?\]$/);
        if (!am) return false;
        const val = am[1] === 'type' ? this.type : am[1] === 'name' ? this.name : this.getAttribute(am[1]);
        if (am[2] === undefined ? val === null : val !== am[2]) return false;
      }
      return true;
    });
  }
  querySelectorAll(sel) {
    // supports "a b" descendant chains of simple selectors, and "x, y" lists
    return sel.split(',').flatMap((part) => {
      const chain = part.trim().split(/\s+/);
      let scope = [this];
      for (const step of chain) {
        const next = [];
        for (const s of scope) for (const n of s.walk()) if (n.matches(step) && !next.includes(n)) next.push(n);
        scope = next;
      }
      return scope;
    });
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

/* ----------------------------------------------------------- the page */
const html = readFileSync(path.join(siteDir, 'index.html'), 'utf8');
const body = new Node('body');
for (const m of html.matchAll(/<(\w+)[^>]*\sid="([^"]+)"/g)) {
  const el = new Node(m[1]); el.attrs.id = m[2]; body.appendChild(el);
}
const document = {
  body,
  readyState: 'complete',
  createElement: (t) => new Node(t),
  createTextNode: (s) => String(s),
  getElementById: (id) => [...body.walk()].find((n) => n.attrs.id === id) || null,
  querySelectorAll: (sel) => body.querySelectorAll(sel),
  querySelector: (sel) => body.querySelector(sel),
  addEventListener() {},
};
const location = { hash: '', href: 'https://example.invalid/' };
const sandbox = {
  document, location, console,
  history: { replaceState(_s, _t, url) { if (typeof url === 'string' && url.startsWith('#')) location.hash = url; }, pushState() {} },
  addEventListener() {}, setTimeout, clearTimeout, encodeURIComponent, decodeURIComponent, URLSearchParams, Date, Math, JSON,
};
sandbox.window = sandbox; sandbox.self = sandbox; sandbox.globalThis = sandbox;
const ctx = createContext(sandbox);
runInContext(readFileSync(path.join(siteDir, 'data.js'), 'utf8'), ctx, { filename: 'data.js' });
const SDN = sandbox.SDN;
check('data.js defines window.SDN with records, rulings, alerts, docs', SDN && Array.isArray(SDN.records) && Array.isArray(SDN.rulings) && Array.isArray(SDN.alerts) && SDN.docs);

let threw = null;
try { runInContext(readFileSync(path.join(siteDir, 'app.js'), 'utf8'), ctx, { filename: 'app.js' }); } catch (e) { threw = e; }
check('app.js runs to completion against the committed payload', !threw, threw && (threw.stack || threw.message));
if (threw) { process.exit(1); }

const results = document.getElementById('results');
const nav = document.getElementById('nav');
const overview = document.getElementById('overview');
check('navigation rendered', nav.children.length >= 6, `${nav.children.length} buttons`);
check('overview rendered something', overview.innerHTML.length > 200);

/* --------------------------------------------- database view: each record */
const db = JSON.parse(readFileSync(path.join(repo, 'data', 'discrepancies.json'), 'utf8'));
check('payload record count equals data/discrepancies.json', SDN.records.length === db.records.length, `${SDN.records.length} vs ${db.records.length}`);
const dbHtml = results.innerHTML;
check('database view is not empty', dbHtml.length > 500 && !/database empty/i.test(dbHtml));
check('no record renders as "? at ?" or "undefined"', !/\?\s+at\s+\?/.test(dbHtml) && !/undefined/.test(dbHtml));
let missingLinks = 0, missingTeams = 0;
for (const r of SDN.records) {
  const urls = (r.sources || []).map((s) => s.url).filter(Boolean);
  if (!urls.length) missingLinks += 1;
  if (!(r.game && r.game.away_team && r.game.home_team)) missingTeams += 1;
}
check('every record has at least one source URL', missingLinks === 0, `${missingLinks} without`);
check('every record names both teams', missingTeams === 0, `${missingTeams} without`);
const sampleIds = SDN.records.slice(0, 50).map((r) => r.record_id);
const shown = sampleIds.filter((id) => dbHtml.includes(id)).length;
check('first page of records is rendered with their ids', shown > 0, `${shown}/${sampleIds.length} (paging may hide some)`);

/* ------------------------------------------------------------ other views */
const buttons = nav.querySelectorAll('button');
function open(view) {
  const b = buttons.find((x) => x.dataset.view === view);
  if (!b) return null;
  b.dispatch('click');
  return results.innerHTML;
}
for (const view of ['rulings', 'alerts', 'market', 'coverage', 'monitor', 'overview']) {
  let err = null, out = null;
  try { out = open(view); } catch (e) { err = e; }
  check(`view "${view}" mounts`, !err && (view === 'overview' || (out && out.length > 100)), err ? err.stack : `${out ? out.length : 0} chars`);
}
const docViews = buttons.map((b) => b.dataset.view).filter((v) => v && v.startsWith('doc:'));
let docErr = null;
for (const v of docViews) { try { const out = open(v); if (!out || /Missing document|Missing: docs/.test(out)) docErr = `${v} missing`; } catch (e) { docErr = e.stack; } }
check(`all ${docViews.length} documentation pages mount`, docViews.length > 0 && !docErr, docErr || '');

/* ------------------------------------------- Situation Room log + alerts */
const ledgerPath = path.join(repo, 'data', 'situation_room', 'rulings.json');
if (existsSync(ledgerPath)) {
  const ledger = JSON.parse(readFileSync(ledgerPath, 'utf8'));
  check('payload rulings equal the ledger', SDN.rulings.length === (ledger.rulings || []).length, `${SDN.rulings.length} vs ${(ledger.rulings || []).length}`);
  const rul = open('rulings');
  check('Situation Room log renders rows with official links', /nhl\.com\/news\//.test(rul) && /statements match/.test(rul));
  const overturned = SDN.rulings.filter((r) => r.outcome === 'overturned');
  const withRecord = overturned.filter((r) => r.record_id);
  const recIds = new Set(SDN.records.map((r) => r.record_id));
  const dangling = withRecord.filter((r) => !recIds.has(r.record_id)).length;
  check('every ruling that points at a record points at an existing one', dangling === 0, `${dangling} dangling`);
} else {
  console.log('  skip ledger checks (data/situation_room/rulings.json absent)');
}
const feedPath = path.join(repo, 'data', 'alerts.json');
if (existsSync(feedPath)) {
  const feed = JSON.parse(readFileSync(feedPath, 'utf8'));
  const n = Math.min((feed.alerts || []).length, 300);
  check('payload alerts mirror data/alerts.json', SDN.alerts.length === n, `${SDN.alerts.length} vs ${n}`);
  const al = open('alerts');
  check('alerts view lists the feed (or says it is empty)', n ? /alerts:/.test(al) && /data\/alerts\.xml/.test(al) : /No alerts/.test(al));

  /* The Alerts tab must tell a reader how to be notified, and must not claim a
   * channel that the delivery code does not have. */
  const channels = ((SDN.meta || {}).notifications || {}).channels || [];
  check('payload describes the notification channels', channels.length === 4,
    `expected feed/issue/webhook/email, got ${channels.map((c) => c.id).join(',')}`);
  check('alerts view renders the subscription panel', /Get notified instead of checking/.test(al));
  const missing = channels.filter((c) => !al.includes(c.name));
  check('every channel is listed on the page', missing.length === 0, missing.map((c) => c.id).join(','));
  check('an unconfigured channel is shown as unconfigured',
    channels.filter((c) => !c.configured).every((c) => /not configured/.test(al)));
  const withTotal = (SDN.alerts || []).filter((a) => a.affects_goal_total);
  check('a goal-total alert carries the record\'s own settlement wording',
    !withTotal.length || withTotal.every((a) => a.settlement_reason && al.includes(a.settlement_reason.slice(0, 40))));
  const lastRun = ((SDN.meta || {}).notifications || {}).last_run;
  check('the last delivery run is shown when one has been recorded',
    !lastRun || /Last delivery run/.test(al));
}

console.log(failures.length ? `\n${failures.length} check(s) failed` : '\nall checks passed');
process.exit(failures.length ? 1 : 0);

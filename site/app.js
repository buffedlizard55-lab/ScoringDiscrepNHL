/* NHL Scoring Discrepancies - static client.
 *
 * Reads the JSON that the collector commits to the repository. There is no server
 * side logic and no third-party dependency: what you see is exactly what is in
 * data/, which is also what is in git history.
 */

const FILES = {
  records: 'data/records/discrepancies.json',
  taxonomy: 'data/taxonomy.json',
  facts: 'data/reference/verified_facts.json',
  vocab: 'data/schema/observed_vocabulary.json',
  alerts: 'data/alerts/index.json',
  sources: 'data/reference/sources.json',
};

const state = { records: [], taxonomy: null, facts: null, vocab: null, alerts: [] };

/* ----------------------------- helpers ----------------------------- */
const $ = (sel) => document.querySelector(sel);

function esc(value) {
  return String(value === null || value === undefined ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

async function loadJSON(url) {
  try {
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    return null;
  }
}

function playerLabel(p) {
  if (!p) return '—';
  const sweater = p.sweater ? `#${p.sweater} ` : '';
  return `${sweater}${p.name || (p.id ? 'id:' + p.id : 'unknown')}`;
}

function rulingText(blob) {
  if (!blob) return '—';
  if (blob.ruling === 'no_goal') return 'no goal credited';
  if (blob.ruling !== 'goal') return blob.ruling || '—';
  const assists = (blob.assists || []).map(playerLabel).filter(Boolean);
  const who = playerLabel(blob.scorer);
  return `${who}${assists.length ? ' (assists: ' + assists.join(', ') + ')' : ' (unassisted)'}` +
         (blob.strength ? ` · ${blob.strength}` : '');
}

function termLabel(rec) {
  const ev = rec.event || {};
  return `${ev.period_type || 'REG'} P${ev.period ?? '?'} · ${ev.clock || '?'}`;
}

function typeLabel(value) {
  const t = (state.taxonomy?.discrepancy_types || []).find((x) => x.value === value);
  return t ? t.label : (value || '—');
}

function badge(text, cls) {
  return `<span class="badge ${cls || ''}">${esc(text)}</span>`;
}

function evidenceBadge(status) {
  const cls = status === 'verified_two_official_states' ? 'ok'
    : status === 'verified_corrected_state' ? 'ok-soft'
    : status === 'conflicting' ? 'bad' : 'warn';
  return badge(String(status || 'unknown').replace(/_/g, ' '), cls);
}

function settlementBadge(level) {
  const map = { critical: 'bad', high: 'bad', medium: 'warn', attribution: 'info', low: '' };
  return badge(level || '—', map[level] ?? '');
}

function impactCell(rec) {
  const ch = rec.change || {};
  if (ch.affects_goal_total) return badge('goal count changed', 'bad');
  if (ch.attribution_only) return badge('attribution only', 'info');
  return badge('other', 'warn');
}

function sourcesCell(rec) {
  const links = (rec.sources || []).filter((s) => s.url).slice(0, 3);
  if (!links.length) return badge('no source', 'bad');
  return links.map((s) => {
    const short = s.name ? s.name.replace(/ \(.*\)/, '').replace('NHL GameCenter ', '') : 'source';
    return `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(short)}</a>`;
  }).join('<br>');
}

/* ----------------------------- rendering ----------------------------- */
function rowFor(rec) {
  const g = rec.game || {};
  const away = (g.away || {}).abbrev || '?';
  const home = (g.home || {}).abbrev || '?';
  const score = g.final_score ? ` (${g.final_score})` : '';
  return `<tr data-id="${esc(rec.record_id)}">
    <td>${esc(g.date || '—')}</td>
    <td>${esc(away)} @ ${esc(home)}${esc(score)}</td>
    <td>${esc(termLabel(rec))}</td>
    <td>${esc(typeLabel((rec.change || {}).discrepancy_type))}</td>
    <td>${esc(rulingText(rec.initial_state))}</td>
    <td>${esc(rulingText(rec.corrected_state))}</td>
    <td>${impactCell(rec)}</td>
    <td>${esc((rec.timing || {}).when || '—')}</td>
    <td>${evidenceBadge(rec.evidence_status)}</td>
    <td>${sourcesCell(rec)}</td>
  </tr>`;
}

function shortRow(rec, kind) {
  const g = rec.game || {};
  const away = (g.away || {}).abbrev || '?';
  const home = (g.home || {}).abbrev || '?';
  const tail = kind === 'total'
    ? settlementBadge((rec.settlement || {}).level)
    : badge('player props', 'info');
  return `<tr data-id="${esc(rec.record_id)}">
    <td>${esc(g.date || '—')}</td>
    <td>${esc(away)} @ ${esc(home)}</td>
    <td>${esc(termLabel(rec))}</td>
    <td>${esc(typeLabel((rec.change || {}).discrepancy_type))}</td>
    <td>${esc((rec.timing || {}).when || '—')}</td>
    <td>${tail}</td>
    <td>${evidenceBadge(rec.evidence_status)}</td>
  </tr>`;
}

function applyFilters() {
  const q = $('#f-q').value.trim().toLowerCase();
  const f = {
    season: $('#f-season').value,
    team: $('#f-team').value,
    from: $('#f-from').value,
    to: $('#f-to').value,
    period: $('#f-period').value,
    type: $('#f-type').value,
    impact: $('#f-impact').value,
    timing: $('#f-timing').value,
    settlement: $('#f-settlement').value,
    evidence: $('#f-evidence').value,
  };
  const rows = state.records.filter((rec) => {
    const g = rec.game || {};
    const ev = rec.event || {};
    const ch = rec.change || {};
    if (f.season && String(g.season) !== f.season) return false;
    if (f.team && (g.away || {}).abbrev !== f.team && (g.home || {}).abbrev !== f.team) return false;
    if (f.from && (g.date || '') < f.from) return false;
    if (f.to && (g.date || '') > f.to) return false;
    if (f.period && String(ev.period) !== f.period) return false;
    if (f.type && ch.discrepancy_type !== f.type) return false;
    if (f.impact === 'total' && !ch.affects_goal_total) return false;
    if (f.impact === 'attribution' && !ch.attribution_only) return false;
    if (f.timing && (rec.timing || {}).when !== f.timing) return false;
    if (f.settlement && (rec.settlement || {}).level !== f.settlement) return false;
    if (f.evidence && rec.evidence_status !== f.evidence) return false;
    if (q) {
      const hay = JSON.stringify(rec).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  const total = rows.filter((r) => (r.change || {}).affects_goal_total);
  const attr = rows.filter((r) => (r.change || {}).attribution_only);
  $('#table-total tbody').innerHTML = total.map((r) => shortRow(r, 'total')).join('');
  $('#table-attr tbody').innerHTML = attr.map((r) => shortRow(r, 'attr')).join('');
  $('#table-all tbody').innerHTML = rows.map(rowFor).join('');
  toggleEmpty('#table-total', total.length);
  toggleEmpty('#table-attr', attr.length);
  toggleEmpty('#table-all', rows.length);
  wireRows();
}

function toggleEmpty(selector, count) {
  const table = $(selector);
  const msg = table.parentElement.querySelector('.empty-row');
  table.hidden = count === 0;
  if (msg) msg.hidden = count !== 0;
}

function fillSelect(id, values, labels) {
  const sel = $(id);
  const current = sel.value;
  values.forEach((v, i) => {
    const opt = document.createElement('option');
    opt.value = v;
    opt.textContent = labels ? labels[i] : v;
    sel.appendChild(opt);
  });
  sel.value = current;
}

function populateFilters() {
  const seasons = new Set(); const teams = new Set(); const periods = new Set();
  const timings = new Set(); const levels = new Set(); const statuses = new Set();
  state.records.forEach((r) => {
    const g = r.game || {};
    if (g.season) seasons.add(String(g.season));
    if ((g.away || {}).abbrev) teams.add(g.away.abbrev);
    if ((g.home || {}).abbrev) teams.add(g.home.abbrev);
    if ((r.event || {}).period !== undefined) periods.add(String(r.event.period));
    if ((r.timing || {}).when) timings.add(r.timing.when);
    if ((r.settlement || {}).level) levels.add(r.settlement.level);
    if (r.evidence_status) statuses.add(r.evidence_status);
  });
  const types = (state.taxonomy?.discrepancy_types || [])
    .filter((t) => t.value !== 'no_change')
    .map((t) => t.value);
  const timingLabels = (state.taxonomy?.timing || []).reduce((acc, t) => { acc[t.value] = t.label; return acc; }, {});
  fillSelect('#f-season', [...seasons].sort());
  fillSelect('#f-team', [...teams].sort());
  fillSelect('#f-period', [...periods].sort((a, b) => a - b));
  fillSelect('#f-type', types, types.map(typeLabel));
  fillSelect('#f-timing', [...timings].sort(), [...timings].sort().map((t) => timingLabels[t] || t));
  fillSelect('#f-settlement', [...levels].sort());
  fillSelect('#f-evidence', [...statuses].sort());
}

function renderStatus() {
  const recs = state.records;
  $('#stat-count').textContent = recs.length;
  $('#stat-total').textContent = recs.filter((r) => (r.change || {}).affects_goal_total).length;
  $('#stat-attr').textContent = recs.filter((r) => (r.change || {}).attribution_only).length;
  $('#stat-alerts').textContent = state.alerts.length;
  const updated = (state.recordsMeta || {}).updated_at_utc || '—';
  $('#stat-updated').textContent = updated.replace('T', ' ').replace('Z', '');

  if (!recs.length) {
    $('#empty-notice').hidden = false;
    const coverage = (state.recordsMeta || {}).coverage || {};
    const lines = [];
    if (state.recordsMeta && state.recordsMeta.status_note) {
      lines.push(state.recordsMeta.status_note[0]);
      lines.push(state.recordsMeta.status_note[1]);
      lines.push(state.recordsMeta.status_note[2]);
    }
    if (coverage.known_evidence_gaps) {
      lines.push('<strong>Known evidence gaps right now:</strong> ' + coverage.known_evidence_gaps.map(esc).join(' '));
    }
    $('#empty-explain').innerHTML = lines.join('<br>');
  }
}

function renderSourcesTable() {
  const rows = state.sources?.sources ? Object.values(state.sources.sources) : [];
  $('#table-sources tbody').innerHTML = rows.map((s) => `<tr>
      <td><strong>${esc(s.name)}</strong><div class="muted small">${esc(s.authoritative_for ? s.authoritative_for.join(', ') : '')}</div></td>
      <td>${esc(s.kind)}</td>
      <td>${badge(s.status.replace(/_/g, ' '), s.status === 'verified' ? 'ok' : s.status === 'reachable_at_runtime' ? 'ok-soft' : 'warn')}</td>
      <td>${esc(s.verified_on || '—')}</td>
      <td><a href="${esc(s.url_template.replace('{game_id}', '2023020001'))}" target="_blank" rel="noopener">open</a></td>
      <td class="small">${esc(s.evidence || '')}</td>
    </tr>`).join('');
}

function renderFacts() {
  const facts = state.facts?.verified_facts || [];
  $('#facts').innerHTML = facts.map((f) => `
    <details class="fact">
      <summary><code>${esc(f.id)}</code> ${esc(f.claim)}</summary>
      <p class="muted small">How it was established: ${esc(f.method || 'direct retrieval')}</p>
      ${f.observations ? `<ul>${f.observations.map((o) => `<li>${esc(o)}</li>`).join('')}</ul>` : ''}
      ${f.conclusion ? `<p><strong>Conclusion:</strong> ${esc(f.conclusion)}</p>` : ''}
      ${f.consequence ? `<p><strong>Consequence for this project:</strong> ${esc(f.consequence)}</p>` : ''}
      ${urlsList(f.urls)}
    </details>`).join('') || '<p class="muted">Ledger not loaded.</p>';

  const leads = state.facts?.secondary_leads_not_evidence || [];
  $('#leads').innerHTML = leads.map((l) => `
    <div class="card warn-card">
      <p><strong>${esc(l.lead)}</strong></p>
      <p class="small muted">${esc(l.status)}</p>
      ${l.source ? `<p class="small"><a href="${esc(l.source)}" target="_blank" rel="noopener">${esc(l.source)}</a></p>` : ''}
    </div>`).join('') || '<p class="muted">None.</p>';
}

function urlsList(urls) {
  if (!urls) return '';
  const list = Array.isArray(urls) ? urls : Object.values(urls);
  return `<p class="small">Official/normal sources: ${list
    .map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(u.replace(/^https?:\/\//, ''))}</a>`)
    .join(' · ')}</p>`;
}

function renderVocab() {
  $('#vocab').textContent = JSON.stringify(state.vocab || {}, null, 2);
}

function renderLimits() {
  const vocab = state.vocab || {};
  const blocks = [
    ['Not detectable automatically', vocab.consequence ||
      'Review-driven changes are detected as goal state changes, but the reason stays unknown unless an official artifact states it.'],
    ['Source & feed latency', 'The public GameCenter feed updates during and after games, but the timing between an on-ice ruling and the feed reflecting it is not published by the league. A correction that is published and then superseded inside one polling interval is only detectable from an archived snapshot.'],
    ['Historical coverage', 'Official report paths are absent for 1999-2000 and present from 2005-06 (measured). Reports were generated on game night in 2005-06 and 2016-17 (frozen = original state preserved) but are regenerated in place by 2023-24 (original bytes lost). The exact transition season is not yet bracketed tighter than 2016-17 .. 2023-24.'],
    ['Archive density', 'Most games have zero or one archived snapshot of their official report. A snapshot taken after a correction looks identical to the corrected live document, so absence of a detected change is not proof that none happened.'],
    ['Reason attribution', 'No machine-readable Situation Room / video-review feed was located. Reasons are quoted verbatim from official artifacts when present, otherwise left null.'],
    ['Settlement', 'Whether a sportsbook regrades a market after a post-publication correction depends on private house rules. Records can only flag that a settled market was graded on a superseded number.'],
    ['Scale', 'A complete census requires fetching official documents for every game of every season (thousands of games). That is a pipeline job (see backfill workflows), not something this page can do.'],
  ];
  $('#limits-grid').innerHTML = blocks.map(([title, body]) =>
    `<div class="card"><h4>${esc(title)}</h4><p>${esc(body)}</p></div>`).join('');
}

function renderCoverage() {
  const cov = (state.recordsMeta || {}).coverage;
  if (!cov) { $('#coverage').innerHTML = '<p class="muted">Coverage block not present.</p>'; return; }
  const seasons = cov.season_coverage_measured || {};
  const rows = Object.entries(seasons).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join('');
  $('#coverage').innerHTML = `
    <div class="table-wrap"><table>
      <thead><tr><th>Season / source path</th><th>Measured status</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <p class="small muted">Verified sources: ${(cov.official_sources_verified || []).map(esc).join(', ')}.</p>
    <p class="small muted">Not available as a machine-readable feed: ${(cov.sources_not_available_as_machine_readable || []).map(esc).join(', ')}.</p>`;
}

/* ----------------------------- details drawer ----------------------------- */
function openRecord(recordId) {
  const rec = state.records.find((r) => r.record_id === recordId);
  if (!rec) return;
  const ch = rec.change || {};
  const body = `
    <h2>${esc(rec.game.away.abbrev)} @ ${esc(rec.game.home.abbrev)} — ${esc(rec.game.date)}</h2>
    <p class="muted">Game id ${esc(rec.game.game_id)} · season ${esc(rec.game.season)} · record
      <code>${esc(rec.record_id)}</code> · status ${badge(rec.status, 'info')} ${evidenceBadge(rec.evidence_status)}</p>
    <p>${esc(termLabel(rec))} · team ${esc(rec.event.team || '—')} · strength ${esc(rec.event.strength || '—')}</p>
    <div class="two-col">
      <div class="card"><h4>Initial ruling (as previously published)</h4><p>${esc(rulingText(rec.initial_state))}</p>
        <p class="small muted">captured ${esc((rec.timing || {}).previous_state_captured_at_utc || '—')}</p></div>
      <div class="card"><h4>Corrected ruling</h4><p>${esc(rulingText(rec.corrected_state))}</p>
        <p class="small muted">captured ${esc((rec.timing || {}).new_state_captured_at_utc || '—')}</p></div>
    </div>
    <p><strong>Type:</strong> ${esc(typeLabel(ch.discrepancy_type))} —
      ${ch.affects_goal_total ? 'the goal count changed' : 'the goal count did not change'}${ch.attribution_only ? ' (attribution only)' : ''}</p>
    <p><strong>What changed:</strong> ${esc(ch.detail || '—')}</p>
    <p><strong>Reason (official statements only):</strong> ${esc((rec.reason || {}).text || 'not stated in any retrieved official artifact')}</p>
    <p><strong>Timing:</strong> ${esc((rec.timing || {}).when || '—')} — ${esc((rec.timing || {}).reasoning || '')}</p>
    <p><strong>Settlement relevance:</strong> ${settlementBadge((rec.settlement || {}).level)}
      ${esc((rec.settlement || {}).reasoning || '')}</p>
    <h4>Official sources</h4>
    <ul>${(rec.sources || []).map((s) => `<li><strong>${esc(s.role)}</strong> — ${esc(s.name || '')}
      <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a>
      <span class="muted small">(HTTP ${esc(s.http_status ?? '?')}, retrieved ${esc(s.retrieved_at_utc || '?')})</span></li>`).join('')}</ul>
    ${rec.flags && rec.flags.length ? `<p><strong>Flags:</strong> ${rec.flags.map((f) => badge(f, 'warn')).join(' ')}</p>` : ''}
    ${rec.completeness ? `<p class="small muted">Record completeness: ${rec.completeness.fields_present}/${rec.completeness.fields_requested}
      (${rec.completeness.percent_complete}%). Missing: ${(rec.completeness.missing_requested_fields || []).map(esc).join(', ') || 'none'}.</p>` : ''}
  `;
  $('#drawer-body').innerHTML = body;
  $('#drawer').hidden = false;
}

function wireRows() {
  document.querySelectorAll('tbody tr[data-id]').forEach((tr) => {
    tr.onclick = () => openRecord(tr.getAttribute('data-id'));
  });
}

/* ----------------------------- tabs ----------------------------- */
function wireTabs() {
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.onclick = () => {
      document.querySelectorAll('.tab').forEach((t) => { t.classList.remove('active'); t.setAttribute('aria-selected', 'false'); });
      tab.classList.add('active');
      tab.setAttribute('aria-selected', 'true');
      document.querySelectorAll('.view').forEach((v) => v.classList.remove('active'));
      document.getElementById('view-' + tab.dataset.view).classList.add('active');
    };
  });
}

/* ----------------------------- boot ----------------------------- */
async function boot() {
  const [recordsFile, taxonomy, facts, vocab, alerts, sources] = await Promise.all([
    loadJSON(FILES.records), loadJSON(FILES.taxonomy), loadJSON(FILES.facts),
    loadJSON(FILES.vocab), loadJSON(FILES.alerts), loadJSON(FILES.sources),
  ]);
  state.taxonomy = taxonomy;
  state.facts = facts;
  state.vocab = vocab;
  state.records = (recordsFile && recordsFile.records) || [];
  state.recordsMeta = recordsFile || {};
  state.alerts = (alerts && alerts.alerts) || [];
  state.sources = sources;

  populateFilters();
  renderStatus();
  renderSourcesTable();
  renderFacts();
  renderVocab();
  renderLimits();
  renderCoverage();
  applyFilters();

  ['#f-season', '#f-team', '#f-from', '#f-to', '#f-period', '#f-type', '#f-impact',
   '#f-timing', '#f-settlement', '#f-evidence', '#f-q'].forEach((sel) => {
    $(sel).addEventListener('input', applyFilters);
    $(sel).addEventListener('change', applyFilters);
  });
  $('#f-reset').onclick = () => {
    document.querySelectorAll('#filters input, #filters select').forEach((el) => { el.value = ''; });
    applyFilters();
  };
  $('#drawer-close').onclick = () => { $('#drawer').hidden = true; };
  $('#drawer').onclick = (ev) => { if (ev.target.id === 'drawer') $('#drawer').hidden = true; };
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') $('#drawer').hidden = true; });
  wireTabs();
}

boot();

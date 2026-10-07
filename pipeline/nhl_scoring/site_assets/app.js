
(function () {
  'use strict';
  var SDN = window.SDN || {records: [], summary: {}, meta: {}, docs: {}};
  var R = SDN.records || [];
  var VIEWS = [['database', 'Database'], ['market', 'Settlement exposure'], ['coverage', 'Detection coverage'], ['monitor', 'Live monitor']]
    .concat(Object.keys(SDN.docs || {}).map(function (f) { return ['doc:' + f, SDN.docs[f].label]; }));
  var state = {view: 'database', doc: null, sort: 'date-desc', page: 0, per: 60};
  var els = {};

  function h(tag, attrs, kids) {
    var n = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === 'dataset') { Object.keys(attrs[k]).forEach(function (d) { n.dataset[d] = attrs[k][d]; }); }
      else if (k === 'class') n.className = attrs[k];
      else if (k === 'html') n.innerHTML = attrs[k];
      else if (k === 'text') n.textContent = attrs[k];
      else if (k.indexOf('on') === 0) n.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] !== null && attrs[k] !== undefined) n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  function esc(s) { return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
    return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); }
  function uniq(vals) { var seen = {}, out = []; vals.forEach(function (v) { if (v !== null && v !== undefined && v !== '' && !seen[v]) { seen[v] = 1; out.push(v); } }); return out; }
  function naturalDesc(a, b) { return String(b).localeCompare(String(a)); }

  // ---- filter model -------------------------------------------------------
  var FILTERS = [
    {key: 'q', label: 'Search players, teams, notes', type: 'search', placeholder: 'e.g. Pacioretty, OT, 2023020451'},
    {key: 'season', label: 'Season', type: 'select', options: uniq(R.map(function (r) { return r.game && r.game.season; })).sort(naturalDesc)},
    {key: 'team', label: 'Team', type: 'select', options: (SDN.summary.teams || []).slice().sort()},
    {key: 'rule', label: 'Discrepancy type', type: 'select', options: Object.keys(SDN.summary.rules || {}).sort()},
    {key: 'status', label: 'Record status', type: 'select', options: ['verified', 'flagged', 'pending_review', 'disputed', 'retired']},
    {key: 'period', label: 'Period', type: 'select', options: uniq(R.map(function (r) { return r.discrepancy && r.discrepancy.period; })).sort(function (a, b) { return a - b; })},
    {key: 'date_from', label: 'Date from', type: 'date'},
    {key: 'date_to', label: 'Date to', type: 'date'},
    {key: 'game_type', label: 'Game type', type: 'select', options: uniq(R.map(function (r) { return r.game && r.game.game_type; })).sort()}
  ];
  var TOGGLES = [
    {key: 'goal_total_changed', label: 'Changed the goal total'},
    {key: 'goal_no_goal_change', label: 'Goal <-> no-goal change'},
    {key: 'attribution_only', label: 'Attribution only (scorer/assist)'},
    {key: 'scorer_change', label: 'Scorer changed'},
    {key: 'assist_change', label: 'Assist changed'},
    {key: 'video_review', label: 'Video review / challenge'},
    {key: 'in_game', label: 'Corrected during game'},
    {key: 'intermission', label: 'Corrected at intermission'},
    {key: 'postgame', label: 'Corrected after game'},
    {key: 'cross_source', label: 'Official records disagree'},
    {key: 'affects_settlement', label: 'Could affect game-total settlement'},
    {key: 'flagged_incomplete', label: 'Evidence incomplete / needs human'}
  ];
  var active = {};
  FILTERS.forEach(function (f) { if (f.type !== 'date') active[f.key] = ''; });
  TOGGLES.forEach(function (t) { active[t.key] = false; });

  function scorerOf(r, which) { var s = (r[which] && r[which].scorer) || {}; return s.name || ''; }
  function assistNames(st) { return ((st && st.assists) || []).map(function (a) { return typeof a === 'string' ? a : (a && a.name) || ''; }).filter(Boolean); }

  function matches(r) {
    var g = r.game || {}, d = r.discrepancy || {}, mi = d.market_impact || {}, ini = r.initial_state || {}, cor = r.corrected_state || {};
    if (active.season && String(g.season) !== active.season) return false;
    if (active.team && g.away_team !== active.team && g.home_team !== active.team) return false;
    if (active.rule && d.change_type !== active.rule) return false;
    if (active.status && r.status !== active.status) return false;
    if (active.period && String(d.period) !== String(active.period)) return false;
    if (active.game_type && g.game_type !== active.game_type) return false;
    if (active.date_from && (g.date || '') < active.date_from) return false;
    if (active.date_to && (g.date || '') > active.date_to) return false;
    if (active.goal_total_changed && d.total_changed !== true) return false;
    if (active.attribution_only && d.attribution_only !== true) return false;
    if (active.goal_no_goal_change && d.goal_no_goal_change !== true) return false;
    if (active.video_review && d.video_review !== true) return false;
    if (active.in_game && d.when_corrected !== 'in_game') return false;
    if (active.intermission && d.when_corrected !== 'intermission') return false;
    if (active.postgame && !/postgame|next_day/.test(d.when_corrected || '')) return false;
    if (active.cross_source && r.detected_by !== 'cross_source') return false;
    if (active.affects_settlement && mi.affects_game_total === 'no') return false;
    if (active.flagged_incomplete && !((r.flags || []).length || r.status === 'pending_review' || r.status === 'flagged' || r.status === 'disputed')) return false;
    if (active.scorer_change && scorerOf(r, 'initial_state') === scorerOf(r, 'corrected_state')) return false;
    if (active.assist_change && assistNames(ini).sort().join('|') === assistNames(cor).sort().join('|')) return false;
    if (active.q) {
      var hay = [g.game_id, g.date, g.away_team, g.home_team, d.summary, d.detail, scorerOf(r, 'initial_state'),
                 scorerOf(r, 'corrected_state'), assistNames(ini).join(' '), assistNames(cor).join(' '),
                 (r.notes || ''), (r.flags || []).join(' ')].join(' ').toLowerCase();
      if (hay.indexOf(active.q.toLowerCase()) === -1) return false;
    }
    return true;
  }

  function sortRows(rows) {
    var key = state.sort;
    return rows.slice().sort(function (a, b) {
      var ga = a.game || {}, gb = b.game || {}, da = ga.date || '', db = gb.date || '';
      switch (key) {
        case 'date-asc': return da < db ? -1 : da > db ? 1 : 0;
        case 'risk': return (rank(b.discrepancy && b.discrepancy.market_impact ? b.discrepancy.market_impact.risk : 'none') - rank(a.discrepancy && a.discrepancy.market_impact ? a.discrepancy.market_impact.risk : 'none')) || (da < db ? 1 : -1);
        case 'team': return String(ga.home_team || '').localeCompare(String(gb.home_team || '')) || (da < db ? 1 : -1);
        default: return da > db ? -1 : da < db ? 1 : 0;
      }
    });
  }
  function rank(r) { return r === 'high' ? 3 : r === 'medium' ? 2 : r === 'low' ? 1 : 0; }

  // ---- views --------------------------------------------------------------
  function overview() {
    var s = SDN.summary || {}, m = SDN.meta || {}, cov = m.coverage || {};
    var el = h('div');
    el.appendChild(h('h2', {text: 'What this is'}));
    el.appendChild(h('p', {class: 'note', html:
      'A database of NHL scoring records that do not match themselves: goals credited differently by two official ' +
      'artifacts, goals that appear in one official record and not the other, and scoring changes caught live. ' +
      'Every row carries the official links needed to check it by hand.'}));
    var stats = h('div', {class: 'stats'});
    [['Records', s.record_count || 0], ['Verified', s.verified || 0], ['Flagged for review', s.flagged || 0],
     ['Changed the goal total', s.totals_changed || 0], ['Attribution only', s.attribution_only || 0],
     ['Total change unresolved', s.total_change_unknown || 0]]
      .forEach(function (pair) { stats.appendChild(h('div', {class: 'stat'}, [h('b', {text: String(pair[1])}), h('span', {text: pair[0]})])); });
    el.appendChild(stats);
    el.appendChild(h('div', {class: 'callout', html:
      '<strong>Read the limits before you use it.</strong> The NHL does not publish a correction feed, and its public ' +
      'game data is edited in place with no version history. That means <em>retroactive</em> detection is limited to ' +
      'disagreements that survive between two official artifacts, and <em>new</em> corrections are only catchable while ' +
      'we are actively polling. Details in ' +
      '<a href="#feasibility" data-jump="doc:FEASIBILITY.md">Can we detect it?</a>.'}));
    if (cov && cov.games_scanned !== undefined) {
      var c = h('div', {class: 'callout info'});
      c.appendChild(h('strong', {text: 'Latest automated scan'}));
      c.appendChild(h('div', {class: 'note', html:
        esc(cov.games_scanned) + ' games scanned, ' + esc(cov.games_parsed) + ' parsed by both official sources, ' +
        esc(cov.games_unreadable) + ' unreadable (parser or source gap - <em>not</em> cleared). ' +
        'Findings: ' + esc(cov.finding_count) + '. Run ' + esc(cov.run_id || cov.generated_at || 'local') + '.'}));
      el.appendChild(c);
    }
    if (m.snapshots && m.snapshots.polls) {
      el.appendChild(h('p', {class: 'note', html: 'Live monitor so far: ' + esc(m.snapshots.polls) +
        ' polls across ' + esc(m.snapshots.games) + ' games, ' + esc(m.snapshots.games_with_changes) +
        ' games where the official data changed while we watched.'}));
    }
    return el;
  }

  function filterPanel() {
    var wrap = h('div');
    var grid = h('div', {class: 'fgrid'});
    FILTERS.forEach(function (f) {
      var lab = h('label', {class: 'f'});
      lab.appendChild(h('span', {text: f.label}));
      var input;
      if (f.type === 'select') {
        input = h('select', {name: f.key});
        input.appendChild(h('option', {value: '', text: 'All'}));
        (f.options || []).forEach(function (o) { input.appendChild(h('option', {value: String(o), text: String(o)})); });
      } else {
        input = h('input', {type: f.type === 'search' ? 'search' : f.type, name: f.key, placeholder: f.placeholder || ''});
      }
      var apply = function () { active[f.key] = input.value; state.page = 0; render(); };
      // 'input' covers text fields; a <select> is only guaranteed to fire 'change',
      // so both are wired or the dropdown silently does nothing in some browsers.
      input.addEventListener('input', apply);
      input.addEventListener('change', apply);
      lab.appendChild(input);
      grid.appendChild(lab);
    });
    wrap.appendChild(grid);
    var checks = h('div', {class: 'checks'});
    TOGGLES.forEach(function (t) {
      var lab = h('label');
      var box = h('input', {type: 'checkbox', name: t.key});
      box.checked = active[t.key];
      box.addEventListener('change', function () { active[t.key] = box.checked; state.page = 0; render(); });
      lab.appendChild(box); lab.appendChild(document.createTextNode(' ' + t.label));
      checks.appendChild(lab);
    });
    wrap.appendChild(checks);
    var bar = h('div', {class: 'fbar'});
    bar.appendChild(h('span', {class: 'note', id: 'count', text: ''}));
    var sortSel = h('select', {name: 'sort', style: 'width:auto'});
    [['date-desc', 'Newest first'], ['date-asc', 'Oldest first'], ['risk', 'Market risk'], ['team', 'Team']]
      .forEach(function (o) { var opt = h('option', {value: o[0], text: o[1]}); if (state.sort === o[0]) opt.selected = true; sortSel.appendChild(opt); });
    sortSel.addEventListener('change', function () { state.sort = sortSel.value; render(); });
    bar.appendChild(h('div', {class: 'sortbar'}, [document.createTextNode('Sort '), sortSel]));
    bar.appendChild(h('button', {class: 'btn', text: 'Reset filters', onclick: function () {
      FILTERS.forEach(function (f) { active[f.key] = ''; });
      TOGGLES.forEach(function (t) { active[t.key] = false; });
      state.page = 0;
      syncToggles();
      render();
    }}));
    bar.appendChild(h('button', {class: 'btn', text: 'Copy shareable link', onclick: function (e) {
      var url = location.href.split('#')[0] + '#' + encodeState();
      if (navigator.clipboard) navigator.clipboard.writeText(url);
      e.target.textContent = 'Link copied';
      setTimeout(function () { e.target.textContent = 'Copy shareable link'; }, 1600);
    }}));
    wrap.appendChild(bar);
    return wrap;
  }
  function syncHash() {
    var encoded = encodeState();
    var target = '#' + (encoded ? encoded + '&' : '') + 'view=' + state.view;
    if (target === '#' + 'view=' + state.view && !(location.hash || '')) return;
    if ((location.hash || '') === target) return;
    if (history && history.replaceState) history.replaceState(null, '', target);
    else location.hash = target.slice(1);
  }
  function encodeState() {
    var parts = [];
    Object.keys(active).forEach(function (k) { if (active[k] === true) parts.push('!'+k); else if (active[k]) parts.push(k+'='+encodeURIComponent(active[k])); });
    if (state.sort !== 'date-desc') parts.push('sort=' + state.sort);
    return parts.join('&');
  }
  function resetFilters() {
    FILTERS.forEach(function (f) { active[f.key] = ''; });
    TOGGLES.forEach(function (t) { active[t.key] = false; });
  }
  function decodeState(str) {
    // The hash is the whole state: a link a reader opens must show them exactly what
    // the sharer saw, so filters absent from the hash are cleared rather than kept
    // from whatever the previous view had set.
    resetFilters();
    (str || '').split('&').forEach(function (p) {
      if (!p) return;
      if (p[0] === '!') { if (TOGGLES.some(function (t) { return t.key === p.slice(1); })) active[p.slice(1)] = true; return; }
      var kv = p.split('=');
      if (kv[0] === 'sort') { state.sort = decodeURIComponent(kv[1] || 'date-desc'); return; }
      if (kv[0] === 'view') {
        var want = decodeURIComponent(kv[1] || '');
        var known = ['overview'].concat(VIEWS.map(function (v) { return v[0]; }));
        if (known.indexOf(want) !== -1) state.view = want;
        return;
      }
      if (FILTERS.some(function (f) { return f.key === kv[0]; })) active[kv[0]] = decodeURIComponent(kv[1] || '');
    });
  }

  function stateBlock(cls, title, st) {
    var box = h('div', {class: 'state ' + cls});
    box.appendChild(h('h4', {text: title}));
    var rows = [
      ['Ruling', st.goal_present === false ? (st.ruling || 'absent from this artifact') : (st.ruling || 'goal')],
      ['Scorer', (st.scorer && st.scorer.name) || null],
      ['Assists', assistNames(st).join(', ') || (st.goal_present === false ? null : 'none')],
      ['Period / clock', (st.period === null || st.period === undefined) ? null : ('P' + st.period + ' ' + (st.clock || '?'))],
      ['Strength', st.strength_raw || st.strength || null],
      ['Own goal', st.own_goal === true ? 'yes' : st.own_goal === false ? 'no' : null],
      ['Score after', st.score_after ? (st.score_after.away + '-' + st.score_after.home) : null],
      ['Artifact', st.artifact || null]
    ];
    rows.forEach(function (r) {
      var row = h('div', {class: 'row'});
      row.appendChild(h('span', {text: r[0]}));
      row.appendChild(h('span', {html: r[1] === null || r[1] === undefined ? '<span class="miss">not recorded</span>' : esc(r[1])}));
      box.appendChild(row);
    });
    return box;
  }

  function recordCard(r, openByDefault) {
    var g = r.game || {}, d = r.discrepancy || {}, mi = d.market_impact || {}, det = r.detection || {};
    var ini = r.initial_state || {}, cor = r.corrected_state || {};
    var card = h('details', {class: 'card', open: openByDefault || undefined});
    var sum = h('summary');
    var badges = h('div', {class: 'badges'});
    badges.appendChild(h('span', {class: 'badge ' + esc(r.status || ''), text: r.status || '?'}));
    badges.appendChild(h('span', {class: 'badge risk-' + esc(mi.risk || 'none'), text: 'risk: ' + (mi.risk || 'none')}));
    badges.appendChild(h('span', {class: 'badge' + (d.total_changed ? ' total-yes' : ''),
      text: d.total_changed === true ? 'goal total changed' : d.total_changed === false ? 'attribution only' : 'total change unresolved'}));
    if (d.goal_no_goal_change) badges.appendChild(h('span', {class: 'badge', text: 'goal <-> no-goal'}));
    if (d.video_review) badges.appendChild(h('span', {class: 'badge', text: 'video review'}));
    var title = h('div', {class: 'title', text: (d.summary || det.rule_label || d.change_type || 'discrepancy')});
    var meta = h('div', {class: 'meta', html:
      esc(g.date || '?') + ' · ' + esc(g.away_team || '?') + ' at ' + esc(g.home_team || '?') +
      (g.final_score ? ' · final ' + esc(g.final_score.away) + '-' + esc(g.final_score.home) : '') +
      ' · P' + esc(d.period === undefined || d.period === null ? '?' : d.period) + ' ' + esc(d.clock || '?') +
      ' · ' + esc(g.season || '') + ' ' + esc(g.game_type || '') + ' · <code>' + esc(g.game_id || '') + '</code>'});
    sum.appendChild(badges); sum.appendChild(h('div', {}, [title, meta]));
    sum.appendChild(h('span', {class: 'badge', text: det.check_id || r.record_id || ''}));
    card.appendChild(sum);

    var body = h('div', {class: 'body'});
    body.appendChild(h('div', {class: 'diff', html: '<strong>What the records say:</strong> ' + esc(d.detail || d.summary || '')}));
    var cmp = h('div', {class: 'compare'});
    cmp.appendChild(stateBlock('initial', 'Initial / conflicting state', ini));
    cmp.appendChild(stateBlock('corrected', 'Corrected / other official state', cor));
    body.appendChild(cmp);
    body.appendChild(h('div', {class: 'row'}, [h('span', {text: 'When corrected'}), h('span', {html:
      esc(d.when_corrected || 'unknown') + (d.timing_uncertain ? ' <span class="badge">timing uncertain</span>' : '')})]));
    body.appendChild(h('div', {class: 'row'}, [h('span', {text: 'Attribution only'}), h('span', {text: d.attribution_only ? 'yes - number of goals identical' : 'no / unclear'})]));
    body.appendChild(h('div', {class: 'row'}, [h('span', {text: 'Game-total market'}), h('span', {text: mi.affects_game_total || 'unknown'})]));
    body.appendChild(h('div', {class: 'row'}, [h('span', {text: 'Player props'}), h('span', {text: mi.affects_player_props || 'unknown'})]));
    body.appendChild(h('p', {class: 'note', html: '<strong>Settlement note:</strong> ' + esc(mi.reason || '')}));
    if (d.reason && d.reason.text) {
      body.appendChild(h('p', {class: 'note', html: '<strong>League explanation:</strong> ' + esc(d.reason.text) +
        (d.reason.rule_citation ? ' (rule ' + esc(d.reason.rule_citation) + ')' : '')}));
    }
    body.appendChild(h('h4', {text: 'Official sources'}));
    var ul = h('ul', {class: 'srcs'});
    (r.sources || []).forEach(function (s) {
      var li = h('li');
      li.appendChild(h('a', {href: s.url, target: '_blank', rel: 'noopener noreferrer', text: s.label || s.url}));
      li.appendChild(h('span', {html: ' · ' + esc(s.kind || '') + ' · evidence: ' + esc(s.evidence || '?') +
        (s.retrieved_at ? ' · retrieved ' + esc(s.retrieved_at) : '')}));
      if (s.sha256) li.appendChild(h('span', {html: ' · sha256 <code>' + esc(String(s.sha256).slice(0, 12)) + '</code>'}));
      if (s.http_status !== undefined && s.http_status !== null) li.appendChild(h('span', {html: ' · HTTP ' + esc(s.http_status)}));
      if (s.quote) li.appendChild(h('code', {class: 'q', text: s.quote}));
      if (s.note) li.appendChild(h('span', {class: 'badge', text: s.note}));
      ul.appendChild(li);
    });
    body.appendChild(ul);
    if ((r.flags || []).length) {
      var fl = h('div', {class: 'flags'});
      r.flags.forEach(function (f) { fl.appendChild(h('span', {class: 'badge flagged', text: f})); });
      body.appendChild(fl);
    }
    body.appendChild(h('p', {class: 'note', html: 'Detected by <code>' + esc(r.detected_by) + '</code> check <code>' +
      esc(det.check_id) + '</code> (' + esc(det.rule_label) + ', ' + esc(det.severity) + ') on ' + esc(det.detected_at || '?') +
      ' · record <code>' + esc(r.record_id) + '</code>' + (r.notes ? ' · ' + esc(r.notes) : '')}));
    card.appendChild(body);
    return card;
  }

  function databaseView() {
    var rows = sortRows(R.filter(matches));
    var wrap = h('div');
    var head = h('header', {class: 'rh'});
    head.appendChild(h('div', {}, [
      h('h2', {text: 'Database', style: 'margin:0 0 4px'}),
      h('div', {class: 'note', text: rows.length + ' of ' + R.length + ' records match the filters. Click any row to open the comparison, evidence and source links.'})
    ]));
    head.appendChild(h('div', {class: 'badges'}, [
      h('button', {class: 'btn', text: 'Expand all', onclick: function () {
        wrap.querySelectorAll('details').forEach(function (d) { d.open = true; }); }}),
      h('button', {class: 'btn', text: 'Collapse all', onclick: function () {
        wrap.querySelectorAll('details').forEach(function (d) { d.open = false; }); }})
    ]));
    wrap.appendChild(head);
    var groups = [
      ['total', 'Changed the number of goals in the game', rows.filter(function (r) { return r.discrepancy && r.discrepancy.total_changed === true; })],
      ['attribution', 'Attribution only - same goal count, different credit', rows.filter(function (r) { return r.discrepancy && r.discrepancy.total_changed === false; })],
      ['unresolved', 'Total change not established from the evidence', rows.filter(function (r) { return r.discrepancy && r.discrepancy.total_changed === null && r.discrepancy.total_changed !== false; })]
    ];
    if (!rows.length) { wrap.appendChild(h('p', {class: 'empty', text: 'No records match. Try clearing a filter or two.'})); return wrap; }
    groups.forEach(function (grp) {
      var list = grp[2];
      if (!list.length) return;
      var gh = h('div', {class: 'grouphead'});
      gh.appendChild(h('h3', {text: grp[1]}));
      gh.appendChild(h('span', {class: 'count', text: list.length + ' record' + (list.length === 1 ? '' : 's')}));
      wrap.appendChild(gh);
      list.slice(state.page * state.per, (state.page + 1) * state.per).forEach(function (r) { wrap.appendChild(recordCard(r)); });
      if (list.length > state.per) {
        wrap.appendChild(h('button', {class: 'btn', text: 'Show ' + Math.min(state.per, list.length - (state.page + 1) * state.per) + ' more',
          onclick: function () { state.page += 1; render(); }}));
      }
    });
    return wrap;
  }

  function marketView() {
    var rows = R.filter(matches).filter(function (r) {
      var mi = (r.discrepancy || {}).market_impact || {};
      return mi.affects_game_total !== 'no' || mi.affects_player_props === 'yes';
    }).sort(function (a, b) { return rank((b.discrepancy || {}).market_impact ? b.discrepancy.market_impact.risk : 'none') -
      rank((a.discrepancy || {}).market_impact ? a.discrepancy.market_impact.risk : 'none'); });
    var wrap = h('div');
    wrap.appendChild(h('h2', {text: 'Settlement exposure'}));
    wrap.appendChild(h('p', {class: 'note', html:
      'Records where a goal total, a period total, or a player credit is in doubt - i.e. the subset that could move a ' +
      'market <em>if</em> a book were settling off the NHL box score. Sportsbooks settle off their own source of record, ' +
      'so this is a review queue, not a claim that anything was mis-settled.'}));
    var hi = rows.filter(function (r) { return ((r.discrepancy || {}).market_impact || {}).affects_game_total === 'yes'; });
    var pos = rows.filter(function (r) { return ((r.discrepancy || {}).market_impact || {}).affects_game_total === 'possible'; });
    var prop = rows.filter(function (r) { return ((r.discrepancy || {}).market_impact || {}).affects_player_props === 'yes'; });
    var stats = h('div', {class: 'stats'});
    [['Game total affected', hi.length], ['Game total possibly affected', pos.length],
     ['Player props affected', prop.length], ['This view', rows.length]]
      .forEach(function (p) { stats.appendChild(h('div', {class: 'stat'}, [h('b', {text: String(p[1])}), h('span', {text: p[0]})])); });
    wrap.appendChild(stats);
    if (!rows.length) { wrap.appendChild(h('p', {class: 'empty', text: 'Nothing market-relevant matches the current filters.'})); return wrap; }
    rows.forEach(function (r) { wrap.appendChild(recordCard(r)); });
    return wrap;
  }

  function coverageView() {
    var cov = (SDN.meta || {}).coverage || {};
    var wrap = h('div');
    wrap.appendChild(h('h2', {text: 'Detection coverage of the last automated scan'}));
    wrap.appendChild(h('p', {class: 'note', html:
      'Games the detector actually read. A game that could not be parsed is listed as unreadable and is explicitly ' +
      '<strong>not</strong> treated as clean - that distinction is the difference between a coverage report and a lie.'}));
    var t = h('table', {class: 'grid'});
    t.appendChild(h('thead', {html: '<tr><th>Game</th><th>Both sources parsed</th><th>Goals (API)</th><th>Goals (GS report)</th><th>Findings</th><th>Notes</th></tr>'}));
    var tb = h('tbody');
    (cov.games || []).forEach(function (g) {
      tb.appendChild(h('tr', {html: '<td><code>' + esc(g.game_id) + '</code></td><td>' + (g.ok ? 'yes' : 'no') + '</td>' +
        '<td>' + esc((g.goal_counts || {}).nhl_api_landing) + '</td><td>' + esc((g.goal_counts || {}).nhl_gs_report) + '</td>' +
        '<td>' + esc(g.findings === undefined ? '-' : g.findings) + '</td><td>' + esc((g.notes || []).join('; ') || '-') + '</td>'}));
    });
    t.appendChild(tb);
    wrap.appendChild(t);
    if (!(cov.games || []).length) wrap.appendChild(h('p', {class: 'empty', text: 'No scan payload committed yet. Run: python -m nhl_scoring.cli scan --games ...'}));
    var polls = (SDN.meta || {}).snapshots || {};
    if (polls.polls) {
      var st = h('div', {class: 'stats'});
      [['Games polled', polls.games], ['Polls', polls.polls], ['Distinct states', polls.states], ['Games that changed under watch', polls.games_with_changes]]
        .forEach(function (p) { st.appendChild(h('div', {class: 'stat'}, [h('b', {text: String(p[1])}), h('span', {text: p[0]})])); });
      wrap.appendChild(h('h3', {text: 'Live monitor'}));
      wrap.appendChild(st);
    }
    return wrap;
  }

  function monitorView() {
    var wrap = h('div');
    wrap.appendChild(h('h2', {text: 'Live monitor and alerting'}));
    wrap.appendChild(h('p', {html:
      'The monitor is a scheduled job, not a service. In this repository it runs as a GitHub Action: poll the ' +
      'official Game Center endpoints for today’s games, write a digest only when the league’s data actually changed, ' +
      'diff consecutive digests, merge findings into the database, rebuild this site, and open an issue when ' +
      'something needs a human. See <a href="https://github.com/buffedlizard55-lab/ScoringDiscrepNHL/actions">' +
      'workflows</a> and docs/FEASIBILITY.md for the honest latency picture.'}));
    var how = h('table', {class: 'grid'});
    how.appendChild(h('thead', {html: '<tr><th>Change type</th><th>Detected automatically?</th><th>Latency</th><th>How</th></tr>'}));
    var rows = [
      ['Goal added/removed during a game', 'yes', 'seconds-minutes while polling', 'snapshot diff of live endpoints (C21)'],
      ['Goal credited to another player during a game', 'yes', 'same poll interval', 'snapshot diff (C20)'],
      ['Correction during intermission', 'yes', 'same poll interval', 'polling continues through intermission'],
      ['Correction after last poll but before report generation', 'partial', '12-36 h', 'cross-source diff, GS report vs API'],
      ['Silent post-game edit, no prior poll', 'no', 'never', 'no version history in official data'],
      ["League's stated reason for a change", 'no', 'manual', 'Situation Room text is not published in any machine-readable feed'],
      ['Historical corrections (pre-2000-01)', 'no', 'n/a', 'no official artifact to diff against'],
      ['Box score vs official scorer ruling mismatch', 'yes', 'per scan', 'C10-C17 cross-source checks']
    ];
    var tb = h('tbody');
    rows.forEach(function (r) { tb.appendChild(h('tr', {html: '<td>' + esc(r[0]) + '</td><td>' + esc(r[1]) + '</td><td>' + esc(r[2]) + '</td><td>' + esc(r[3]) + '</td>'})); });
    how.appendChild(tb);
    wrap.appendChild(how);
    return wrap;
  }

  function docView(name) {
    var wrap = h('div', {class: 'docs'});
    var doc = (SDN.docs || {})[name];
    if (!doc) { wrap.appendChild(h('p', {text: 'Missing document'})); return wrap; }
    wrap.appendChild(h('h2', {text: doc.title || doc.label}));
    wrap.appendChild(h('div', {html: doc.html || ''}));
    return wrap;
  }

  // ---- render -------------------------------------------------------------
  // The overview panel and the filter widgets are built once. Re-rendering the
  // filter bar on every keystroke would blow away focus mid-typing, which is
  // exactly the kind of thing that makes a review tool unusable.
  function render() {
    Array.prototype.forEach.call(document.querySelectorAll('#nav button'), function (b) {
      b.setAttribute('aria-current', b.dataset.view === state.view ? 'true' : 'false');
    });
    els.filters.hidden = !(state.view === 'database' || state.view === 'market');
    var out = null;
    if (state.view === 'database') out = databaseView();
    else if (state.view === 'market') out = marketView();
    else if (state.view === 'coverage') out = coverageView();
    else if (state.view === 'monitor') out = monitorView();
    else if (state.view.indexOf('doc:') === 0) out = docView(state.view.slice(4));
    els.results.hidden = out === null;
    els.results.innerHTML = '';
    if (out) els.results.appendChild(out);
    var cnt = document.getElementById('count');
    if (cnt) {
      var n = R.filter(matches).length;
      cnt.textContent = n + ' / ' + R.length + ' records' + (R.length ? '' : ' (database empty - run the scan)');
    }
    syncHash();
  }

  function route() {
    var raw = (location.hash || '').replace(/^#/, '');
    var known = ['overview'].concat(VIEWS.map(function (v) { return v[0]; }));
    if (known.indexOf(raw) !== -1) { state.view = raw; return; }
    if (raw.indexOf('doc:') === 0) { state.view = raw; return; }
    state.view = 'database';
    decodeState(raw);
  }

  function syncToggles() {
    Array.prototype.forEach.call(els.filters.querySelectorAll('input[type=checkbox]'), function (box) {
      box.checked = !!active[box.name];
    });
    Array.prototype.forEach.call(els.filters.querySelectorAll('select,input'), function (input) {
      if (input.type === 'checkbox') return;
      if (input.name && active.hasOwnProperty(input.name)) input.value = active[input.name];
    });
  }

  function init() {
    els = {
      overview: document.getElementById('overview'),
      filters: document.getElementById('filters'),
      results: document.getElementById('results'),
      nav: document.getElementById('nav')
    };
    els.nav.appendChild(h('button', {text: 'Overview', dataset: {view: 'overview'}, onclick: function () { state.view = 'overview'; render(); }}));
    VIEWS.forEach(function (v) {
      els.nav.appendChild(h('button', {text: v[1], dataset: {view: v[0]}, onclick: function () { state.view = v[0]; render(); }}));
    });
    els.overview.appendChild(overview());
    els.filters.appendChild(filterPanel());
    els.overview.addEventListener('click', function (e) {
      var jump = e.target && e.target.getAttribute && e.target.getAttribute('data-jump');
      if (jump) { e.preventDefault(); state.view = jump; render(); }
    });
    route();
    syncToggles();
    render();
    window.addEventListener('hashchange', function () { route(); syncToggles(); render(); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();

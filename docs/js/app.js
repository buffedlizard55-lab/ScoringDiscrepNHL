/* NHL Scoring Discrepancies — database browser (vanilla JS, no dependencies) */
(function () {
  "use strict";

  var DATA_URL = "data/discrepancies.json";
  var allRecords = [];
  var meta = {};
  var view = "all"; // all | total | attribution

  var els = {};
  ["loading", "error", "stats", "results", "resultsMeta",
   "fSeason", "fTeam", "fPeriod", "fType", "fTiming", "fReview", "fTotal",
   "fVerify", "fSearch", "fSort", "coverageNote", "lastUpdated"
  ].forEach(function (id) { els[id] = document.getElementById(id); });

  var TYPE_LABELS = {
    "goal-added": "Goal added (no-goal → goal)",
    "goal-removed": "Goal removed (goal → no-goal)",
    "scorer-change": "Scorer change",
    "assist-change": "Assist change",
    "scorer-assist-change": "Scorer + assist change",
    "other": "Other"
  };
  var VERIFY_LABELS = {
    "official-direct": "Official · direct",
    "official-direct-partial": "Official · partial",
    "official-quoted": "Official · quoted",
    "secondary": "Secondary",
    "unverified": "Unverified"
  };

  function esc(s) {
    if (s === null || s === undefined) return "";
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function fmtDate(d) { return d ? d : "Unknown — flagged"; }
  function fmtPeriod(p) {
    if (p === null || p === undefined) return "Unknown";
    if (p === "OT") return "OT";
    if (p === "SO") return "Shootout";
    return "Period " + p;
  }

  function uniqueSorted(values) {
    return Array.from(new Set(values.filter(function (v) { return v !== null && v !== undefined && v !== ""; }))).sort();
  }

  function fillSelect(sel, values, allLabel) {
    sel.innerHTML = "";
    var opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = allLabel;
    sel.appendChild(opt0);
    values.forEach(function (v) {
      var o = document.createElement("option");
      o.value = v;
      o.textContent = v;
      sel.appendChild(o);
    });
  }

  function recordMatches(r, q) {
    q = q.toLowerCase();
    var hay = [r.id, r.season, r.game_date, r.away_team, r.home_team,
      r.initial_ruling, r.corrected_ruling, r.reason].filter(Boolean).join(" ").toLowerCase();
    return hay.indexOf(q) !== -1;
  }

  function applyFilters() {
    var season = els.fSeason.value;
    var team = els.fTeam.value;
    var period = els.fPeriod.value;
    var type = els.fType.value;
    var timing = els.fTiming.value;
    var review = els.fReview.value;   // "", "yes", "no"
    var total = els.fTotal.value;     // "", "yes", "no"
    var verify = els.fVerify.value;
    var q = els.fSearch.value.trim();
    var sort = els.fSort.value;
    var from = els.fFrom.value;
    var to = els.fTo.value;

    var out = allRecords.filter(function (r) {
      if (view === "total" && !r.changed_game_total) return false;
      if (view === "attribution" && !r.changed_attribution_only) return false;
      if (season && r.season !== season) return false;
      if (team && r.away_team !== team && r.home_team !== team) return false;
      if (period && String(r.period) !== period) return false;
      if (type && r.discrepancy_type !== type) return false;
      if (timing && r.correction_timing !== timing) return false;
      if (review === "yes" && !r.video_review) return false;
      if (review === "no" && r.video_review) return false;
      if (total === "yes" && !r.changed_game_total) return false;
      if (total === "no" && r.changed_game_total) return false;
      if (verify && r.verification_status !== verify) return false;
      if (q && !recordMatches(r, q)) return false;
      return true;
    });

    out.sort(function (a, b) {
      var da = a.game_date || "9999";
      var db = b.game_date || "9999";
      if (da === db) return a.id < b.id ? -1 : 1;
      return sort === "oldest" ? (da < db ? -1 : 1) : (da > db ? -1 : 1);
    });

    render(out);
  }

  function badge(text, cls) {
    return '<span class="badge ' + cls + '">' + esc(text) + "</span>";
  }

  function verifyBadge(status) {
    var cls = {
      "official-direct": "b-green",
      "official-direct-partial": "b-blue",
      "official-quoted": "b-amber",
      "secondary": "b-gray",
      "unverified": "b-red"
    }[status] || "b-gray";
    return badge(VERIFY_LABELS[status] || status, cls);
  }

  function render(list) {
    els.resultsMeta.textContent = "Showing " + list.length + " of " + allRecords.length + " records";
    if (!list.length) {
      els.results.innerHTML = '<div class="notice blue">No records match these filters. ' +
        "<a href=\"methodology.html\">Read the methodology</a> for coverage notes.</div>";
      return;
    }
    els.results.innerHTML = list.map(function (r) {
      var cardCls = r.changed_game_total ? "total-changer" : "attribution-only";
      var flags = (r.flags && r.flags.length)
        ? '<div class="flags"><strong>⚠ Flags — needs review (' + r.flags.length + "):</strong><ul>" +
          r.flags.map(function (f) { return "<li>" + esc(f) + "</li>"; }).join("") + "</ul></div>"
        : "";
      var sources = (r.sources || []).map(function (s) {
        return '<li><a href="' + esc(s.url) + '" target="_blank" rel="noopener">' +
          esc(s.label) + "</a> <span class=\"src-type\">[" + esc(s.type) + "]</span></li>";
      }).join("");
      var gameLine = esc(r.away_team) + " at " + esc(r.home_team);
      if (r.game_number) gameLine += " · Game " + esc(r.game_number);
      return (
        '<article class="card ' + cardCls + '">' +
          '<div class="card-head">' +
            '<span class="rid">' + esc(r.id) + "</span>" +
            badge(TYPE_LABELS[r.discrepancy_type] || r.discrepancy_type, r.changed_game_total ? "b-red" : "b-blue") +
            (r.changed_game_total ? badge("Changed goal total", "b-red") : badge("Attribution only", "b-blue")) +
            (r.video_review ? badge("Video review", "b-amber") : "") +
            (r.potential_total_market_impact ? badge("Possible total-market impact", "b-red") : "") +
            verifyBadge(r.verification_status) +
          "</div>" +
          '<div class="matchup">' + gameLine + " — " + esc(r.season) + "</div>" +
          '<div class="vs">' +
            '<div class="vs-box before"><h4>Original ruling</h4><div>' +
              (r.initial_ruling ? esc(r.initial_ruling) : "<em>Unknown — flagged, not assumed.</em>") +
            "</div></div>" +
            '<div class="vs-box after"><h4>Corrected / final ruling</h4><div>' + esc(r.corrected_ruling) + "</div></div>" +
          "</div>" +
          '<dl class="meta">' +
            "<div><dt>Game date</dt><dd>" + esc(fmtDate(r.game_date)) +
              (r.date_confidence !== "verified" ? " (" + esc(r.date_confidence) + ")" : "") + "</dd></div>" +
            "<div><dt>Period / clock</dt><dd>" + esc(fmtPeriod(r.period)) +
              (r.clock ? " · " + esc(r.clock) : " · clock unknown") + "</dd></div>" +
            "<div><dt>Correction timing</dt><dd>" + esc(r.correction_timing) + "</dd></div>" +
            "<div><dt>Reason</dt><dd>" + (r.reason ? esc(r.reason) : "<em>Not stated</em>") + "</dd></div>" +
            (r.total_market_note ? "<div><dt>Total-market note</dt><dd>" + esc(r.total_market_note) + "</dd></div>" : "") +
          "</dl>" +
          flags +
          '<div class="sources"><strong>Sources (' + (r.sources || []).length + "):</strong><ul>" + sources + "</ul></div>" +
        "</article>"
      );
    }).join("");
  }

  function renderStats() {
    var total = allRecords.length;
    var changers = allRecords.filter(function (r) { return r.changed_game_total; }).length;
    var attrib = allRecords.filter(function (r) { return r.changed_attribution_only; }).length;
    var reviews = allRecords.filter(function (r) { return r.video_review; }).length;
    var official = allRecords.filter(function (r) { return r.verification_status === "official-direct"; }).length;
    var flagged = allRecords.filter(function (r) { return r.flags && r.flags.length; }).length;
    els.stats.innerHTML =
      stat(total, "Records") +
      stat(changers, "Changed goal total") +
      stat(attrib, "Attribution only") +
      stat(reviews, "Video reviews") +
      stat(official, "Official-direct") +
      stat(flagged, "Flagged for review");
    function stat(n, label) {
      return '<div class="stat"><div class="num">' + n + '</div><div class="lbl">' + label + "</div></div>";
    }
  }

  function initFilters() {
    fillSelect(els.fSeason, uniqueSorted(allRecords.map(function (r) { return r.season; })), "All seasons");
    fillSelect(els.fTeam, uniqueSorted(allRecords.reduce(function (a, r) {
      return a.concat([r.away_team, r.home_team]);
    }, [])), "All teams");
    fillSelect(els.fPeriod, uniqueSorted(allRecords.map(function (r) { return String(r.period); })), "All periods");

    ["fSeason", "fTeam", "fPeriod", "fType", "fTiming", "fReview", "fTotal", "fVerify", "fSort"]
      .forEach(function (id) { els[id].addEventListener("change", applyFilters); });
    els.fSearch.addEventListener("input", applyFilters);

    document.querySelectorAll(".view-toggle button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        document.querySelectorAll(".view-toggle button").forEach(function (b) { b.classList.remove("active"); });
        btn.classList.add("active");
        view = btn.getAttribute("data-view");
        applyFilters();
      });
    });
  }

  fetch(DATA_URL, { cache: "no-store" })
    .then(function (resp) {
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      return resp.json();
    })
    .then(function (data) {
      meta = data;
      allRecords = data.records || [];
      els.loading.style.display = "none";
      els.coverageNote.textContent = data.coverage_note || "";
      els.lastUpdated.textContent = "Database version " + (data.version || "?") +
        " · last updated " + (data.last_updated || "?");
      renderStats();
      initFilters();
      applyFilters();
    })
    .catch(function (err) {
      els.loading.style.display = "none";
      els.error.style.display = "block";
      els.error.textContent = "Could not load data/discrepancies.json (" + err.message + "). " +
        "If you opened this file directly, serve the docs/ folder over HTTP or use GitHub Pages.";
    });
})();

"""Static site builder for GitHub Pages.

No bundler, no framework, no runtime dependencies: the whole point of the site
is to be a review surface that still loads five years from now. Output is plain
files in ``docs/`` (``.nojekyll`` included so Pages does not try to build it),
and the data is shipped as ``data.js`` rather than fetched, so the page works
from ``file://`` and from any subpath the Pages config happens to use.

Docs are rendered here from the markdown in ``docs/`` with a deliberately small
converter so that the methodology, source inventory and limitation write-ups
live in one place (the repo) and appear on the site without duplication.
"""

from __future__ import annotations

import html
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

SITE_FILES = ("index.html", "styles.css", "app.js", "data.js", ".nojekyll")

DOC_PAGES: List[Tuple[str, str, str]] = [
    # (path under docs/, nav label, page title). Both implementations' docs are
    # published: the repository carries a parallel monitor line (see README
    # "Consolidation"), and hiding one line's analysis would misrepresent what the
    # project knows. Paths prefixed engine/ are this package's own documents.
    ("FEASIBILITY.md", "Can we detect it?", "Detection feasibility and limits"),
    ("STATUS.md", "Status & backlog", "Project status, consolidation, and open work"),
    ("engine/METHODOLOGY.md", "Methodology (engine)", "How a record gets made, validated, and promoted"),
    ("engine/SOURCES.md", "Sources (engine)", "Official endpoints, response status, what each proves"),
    ("engine/DATA_MODEL.md", "Data model (engine)", "Record schema, field by field"),
    ("LIMITATIONS.md", "Limitations (monitor line)", "What the monitor line says it cannot do"),
    ("DETECTION.md", "Detection (monitor line)", "The monitor line's detection design"),
    ("COVERAGE_AND_LIMITATIONS.md", "Coverage (monitor line)", "Measured coverage and its holes"),
    ("OPERATIONS.md", "Operations", "Running the monitor and the backfill"),
    ("VERIFICATION_LOG.md", "Verification log", "Line-by-line checks performed, with links"),
    ("ROADMAP.md", "Roadmap", "What is left, in order"),
]


# --------------------------------------------------------------------------
# tiny markdown renderer (headings, lists, tables, links, emphasis, code)
# --------------------------------------------------------------------------
def _inline(text: str) -> str:
    out = html.escape(text)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", out)
    out = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                 r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', out)
    out = re.sub(r"\[([^\]]+)\]\((?!http)([^)\s]+)\)", r'<a href="\2">\1</a>', out)
    return out


def md_to_html(markup: str) -> str:
    lines = (markup or "").splitlines()
    out: List[str] = []
    para: List[str] = []
    in_code = False
    i = 0

    def flush() -> None:
        if para:
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            out.append("</code></pre>" if in_code else "<pre><code>")
            in_code = not in_code
            i += 1
            continue
        if in_code:
            out.append(html.escape(line))
            i += 1
            continue
        if not stripped:
            flush()
            i += 1
            continue
        if re.fullmatch(r"(?:-\s*){3,}", stripped) or set(stripped) == {"*"}:
            flush()
            out.append("<hr>")
            i += 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            flush()
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            flush()
            header = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            table = ["<table class='md'><thead><tr>"]
            table += [f"<th>{_inline(c)}</th>" for c in header]
            table.append("</tr></thead><tbody>")
            for row in rows:
                table.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>")
            table.append("</tbody></table>")
            out.append("".join(table))
            continue
        if re.match(r"^[-*]\s+", stripped):
            flush()
            items = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*]\s+", "", lines[i].strip()))
                i += 1
            out.append("<ul>" + "".join(f"<li>{_inline(it)}</li>" for it in items) + "</ul>")
            continue
        if re.match(r"^\d+[.)]\s+", stripped):
            flush()
            items = []
            while i < len(lines) and re.match(r"^\s*\d+[.)]\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+[.)]\s+", "", lines[i].strip()))
                i += 1
            out.append("<ol>" + "".join(f"<li>{_inline(it)}</li>" for it in items) + "</ol>")
            continue
        if stripped.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append("<blockquote>" + _inline(" ".join(quote)) + "</blockquote>")
            continue
        para.append(stripped)
        i += 1
    flush()
    if in_code:
        out.append("</code></pre>")
    return "\n".join(out)


# --------------------------------------------------------------------------
# data payload
# --------------------------------------------------------------------------
def summarize(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    seasons: Dict[str, int] = {}
    teams: set = set()
    rules: Dict[str, int] = {}
    total_changed = attribution = unknown = 0
    verified = flagged = pending = disputed = 0
    risk_counts: Dict[str, int] = {}
    dates: List[str] = []
    for rec in records:
        game = rec.get("game") or {}
        disc = rec.get("discrepancy") or {}
        seasons[str(game.get("season"))] = seasons.get(str(game.get("season")), 0) + 1
        for key in ("away_team", "home_team"):
            if game.get(key):
                teams.add(game[key])
        rule = disc.get("change_type") or "unknown"
        rules[rule] = rules.get(rule, 0) + 1
        if disc.get("total_changed") is True:
            total_changed += 1
        elif disc.get("total_changed") is False:
            attribution += 1
        else:
            unknown += 1
        status = rec.get("status")
        verified += status == "verified"
        flagged += status == "flagged"
        pending += status == "pending_review"
        disputed += status == "disputed"
        risk = ((disc.get("market_impact") or {}).get("risk")) or "none"
        risk_counts[risk] = risk_counts.get(risk, 0) + 1
        if game.get("date"):
            dates.append(game["date"])
    return {
        "record_count": len(records),
        "seasons": dict(sorted(seasons.items())),
        "teams": sorted(teams),
        "rules": dict(sorted(rules.items(), key=lambda kv: -kv[1])),
        "totals_changed": total_changed,
        "attribution_only": attribution,
        "total_change_unknown": unknown,
        "verified": verified,
        "flagged": flagged,
        "pending_review": pending,
        "disputed": disputed,
        "market_risk": risk_counts,
        "date_min": min(dates) if dates else None,
        "date_max": max(dates) if dates else None,
    }


def build(out_dir: str, *, db_path: str, repo_root: str,
           coverage_path: Optional[str] = None) -> List[str]:
    os.makedirs(out_dir, exist_ok=True)
    db_payload: Dict[str, Any] = {"records": []}
    if os.path.exists(db_path):
        with open(db_path, "r", encoding="utf-8") as fh:
            db_payload = json.load(fh)
    records = db_payload.get("records") or []
    coverage: Dict[str, Any] = {}
    if coverage_path and os.path.exists(coverage_path):
        with open(coverage_path, "r", encoding="utf-8") as fh:
            scan = json.load(fh)
        coverage = {k: scan.get(k) for k in
                    ("generated_at", "games_requested", "games_scanned", "games_parsed",
                     "games_unreadable", "finding_count", "tool_version", "run_id")}
        coverage["games"] = scan.get("coverage") or []
    snapshot_summary: Dict[str, Any] = {}
    polls_path = os.path.join(repo_root, "data", "snapshots", "polls.json")
    if os.path.exists(polls_path):
        with open(polls_path, "r", encoding="utf-8") as fh:
            polls = json.load(fh)
        snapshot_summary = {
            "games": len(polls),
            "polls": sum(int(v.get("polls") or 0) for v in polls.values()),
            "states": sum(int(v.get("states") or 0) for v in polls.values()),
            "games_with_changes": sum(1 for v in polls.values() if int(v.get("states") or 0) > 1),
        }
    docs: Dict[str, str] = {}
    for filename, label, title in DOC_PAGES:
        path = os.path.join(repo_root, "docs", filename)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                docs[filename] = {"label": label, "title": title, "html": md_to_html(fh.read())}
        else:
            docs[filename] = {"label": label, "title": title,
                              "html": "<p><em>Missing: docs/" + filename + "</em></p>"}
    payload = {
        "meta": {
            "generated_at": db_payload.get("generated_at") or "",
            "schema_version": db_payload.get("schema_version", "1.0"),
            "site_build": "nhl_scoring.site",
            "repo": "https://github.com/buffedlizard55-lab/ScoringDiscrepNHL",
            "coverage": coverage,
            "snapshots": snapshot_summary,
        },
        "summary": summarize(records),
        "records": records,
        "docs": docs,
    }
    written: List[str] = []
    def write(name: str, content: str) -> None:
        path = os.path.join(out_dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        written.append(path)

    write("data.js", "window.SDN = " + json.dumps(payload, ensure_ascii=False,
          separators=(",", ":")).replace("</", "<\\/") + ";\n")
    for name in ("styles.css", "app.js", "index.html"):
        write(name, read_asset(name))
    write(".nojekyll", "")
    return written


# --------------------------------------------------------------------------
# static assets (kept as real files so they can be linted/tested on their own)
# --------------------------------------------------------------------------
ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site_assets")
ASSET_NAMES = ("index.html", "styles.css", "app.js")


def read_asset(name: str) -> str:
    path = os.path.join(ASSET_DIR, name)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"missing site asset {path}; the site cannot be built without it"
        )
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()

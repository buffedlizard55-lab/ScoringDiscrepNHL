"""Official NHL Situation Room feed -> goal / no-goal discrepancy records.

What this is
------------
The NHL publishes a short official statement for every Coach's Challenge and
every Situation Room video review ("Coach's Challenge: NSH @ TOR - 11:49 of the
Third Period", "Video Review: EDM @ VAN - 4:43 of the Third Period", ...). The
statements are stories on nhl.com tagged ``situation-room`` and are served,
newest first, by the league's public content API::

    https://forge-dapi.d3.nhle.com/v2/content/en-us/stories?tags.slug=situation-room&$limit=100&$skip=N

Measured on 2026-10-07: about 4,400 statements, continuous from the start of
the Coach's Challenge era (2016-02) to the current night's games, most tagged
``gameid-<10-digit id>``. Each statement carries the on-ice call, the result,
the rule applied and the league's explanation, i.e. exactly the "original
ruling / corrected ruling / reason / source link" the project brief asks for.

Two formats exist in the feed and both are parsed here:

* **structured** (roughly 2019 onwards): a markdown part with
  ``**Challenge Initiated By:**`` / ``**Type of Challenge**:`` or
  ``**Type of Review:**`` / ``**Result:**`` / ``**Explanation:**`` lines, e.g.
  ``Result: Call on the ice is overturned - No Goal Toronto``.
* **prose** (2016 - 2018): a single paragraph ("At 14:53 of the second period
  in the Islanders/Panthers game, the original call ... was 'no goal' but ...
  the call on the ice was changed to 'good goal' ... Therefore the 'good call'
  call is overturned - no goal Florida Panthers") plus a one-line verdict in
  ``fields.description`` ("Review overturns call of no goaltender
  interference, no goal Panthers").

What is and is not inferred
---------------------------
Only an *explicit* statement that the on-ice call was changed produces a
database record. "Call on the ice is overturned" is explicit. "Video review
determined that the puck did cross the goal line" with no mention of the
on-ice call is **not** - the on-ice call could have been a goal that was merely
confirmed - and such statements are kept in the ruling ledger as
``on_ice_call_not_stated`` instead of being guessed at. Rule quotations inside
the explanation routinely contain the word "overturned" ("the original call on
the ice will be overturned if, and only if ..."), so verdict words are never
read from quoted text.

Every record is then cross-checked against the official play-by-play for the
game (``api-web.nhle.com/v1/gamecenter/<id>/play-by-play``): a goal awarded on
review must exist at the stated period and clock, and a goal disallowed on
review must be *absent* from the final record while a ``chlg-*`` /
``video-review`` stoppage sits at or near the clock. Two independent official
artifacts agreeing is the bar for ``verified``; anything less stays ``flagged``
with the reason spelled out.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import SCHEMA_VERSION, __version__
from . import db as db_mod
from .fetch import Fetcher, FetchResult, utcnow
from .sources import GAME_TYPE_NAMES, GameRef

FEED_BASE = "https://forge-dapi.d3.nhle.com/v2/content/en-us/stories"
FEED_TAG = "situation-room"
PUBLIC_NEWS_BASE = "https://www.nhl.com/news/"
API_BASE = "https://api-web.nhle.com/v1"
CHECK_ID = "SR1"
DEFAULT_PAGE_SIZE = 100

#: PBP stoppage reasons that mark a review. Observed live: ``video-review``
#: (2026020033, 2026020015), ``chlg-vis-off-side`` (2026020044),
#: ``chlg-vis-goal-interference`` (2016020214). ``chlg-hm-*`` and
#: ``chlg-league-*`` are the symmetric forms the NHL uses for home-bench and
#: league-initiated challenges; matching on the ``chlg-`` prefix covers them
#: without pretending to know the full list.
REVIEW_STOPPAGE_PREFIXES = ("chlg-",)
REVIEW_STOPPAGE_EXACT = {"video-review"}

#: Team abbreviations as they appear in Situation Room headlines, mapped to the
#: three-letter codes api-web uses. Everything not listed passes through.
ABBREV_ALIASES = {
    "NJ": "NJD", "TB": "TBL", "LA": "LAK", "SJ": "SJS", "MON": "MTL", "WAS": "WSH",
    "CLB": "CBJ", "NAS": "NSH", "PHX": "ARI", "FLO": "FLA", "CAL": "CGY", "WIN": "WPG",
    "VGS": "VGK", "LV": "VGK",
}

#: Words the "Result" line uses for the team, mapped to abbreviations. Both the
#: city and the nickname are listed because the league uses either ("No Goal
#: Toronto", "good goal Devils", "no goal Florida Panthers").
TEAM_WORDS: Dict[str, Tuple[str, ...]] = {
    "ANA": ("anaheim", "ducks"), "ARI": ("arizona", "coyotes", "phoenix"), "BOS": ("boston", "bruins"),
    "BUF": ("buffalo", "sabres"), "CGY": ("calgary", "flames"), "CAR": ("carolina", "hurricanes"),
    "CHI": ("chicago", "blackhawks"), "COL": ("colorado", "avalanche"), "CBJ": ("columbus", "blue jackets"),
    "DAL": ("dallas", "stars"), "DET": ("detroit", "red wings"), "EDM": ("edmonton", "oilers"),
    "FLA": ("florida", "panthers"), "LAK": ("los angeles", "kings"), "MIN": ("minnesota", "wild"),
    "MTL": ("montreal", "montréal", "canadiens"), "NSH": ("nashville", "predators"),
    "NJD": ("new jersey", "devils"), "NYI": ("islanders",), "NYR": ("rangers",),
    "OTT": ("ottawa", "senators"), "PHI": ("philadelphia", "flyers"), "PIT": ("pittsburgh", "penguins"),
    "SJS": ("san jose", "sharks"), "SEA": ("seattle", "kraken"), "STL": ("st. louis", "st louis", "blues"),
    "TBL": ("tampa bay", "tampa", "lightning"), "TOR": ("toronto", "maple leafs"),
    "UTA": ("utah", "mammoth", "hockey club"), "VAN": ("vancouver", "canucks"),
    "VGK": ("vegas", "golden knights"), "WSH": ("washington", "capitals"), "WPG": ("winnipeg", "jets"),
}

PERIOD_ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,
                   "fourth": 4, "4th": 4, "fifth": 5, "5th": 5, "sixth": 6, "6th": 6}

HEADLINE_KIND_RE = re.compile(r"^\s*(?P<kind>[^:]{3,60}?)\s*:", re.I)
HEADLINE_TEAMS_RE = re.compile(r"\b(?P<away>[A-Z]{2,3})\s*@\s*(?P<home>[A-Z]{2,3})\b")
HEADLINE_CLOCK_RE = re.compile(r"(?P<clock>\d{1,2}:\d{2})\s+(?:of|in)\s+(?:the\s+)?(?P<period>[A-Za-z0-9 ]+?)\s*$", re.I)
FIELD_RE = re.compile(
    r"\*{0,2}\s*(?P<name>Challenge Initiated By|Type of Challenge|Type of Review|Result|Explanation)\s*\*{0,2}\s*:\s*\*{0,2}\s*",
    re.I,
)
RULE_RE = re.compile(r"\bRule\s+(\d{1,3}(?:\.\d{1,2})?)", re.I)
CLOCK_RESET_RE = re.compile(r"clock\s+is\s+reset\s+to\s+show\s+(\d{1,2}:\d{2})\s*\((\d{1,2}:\d{2})\s+elapsed", re.I)
GAME_TAG_TITLE_RE = re.compile(r"^(?P<away>[A-Z]{2,3})@(?P<home>[A-Z]{2,3})\s+(?P<m>\d{2})/(?P<d>\d{2})/(?P<y>\d{4})")

#: Wordings the league uses for an on-ice ruling that was *not* a goal.
INFRACTION_WORDS = re.compile(
    r"batted|kicked|kicking|hand pass|high[- ]stick|glove|goaltender interference|interfere|"
    r"off[- ]side|offside|did not (?:completely )?cross|no goal|net was (?:off|dislodged)|"
    r"distinct kicking|whistle|intent to blow|puck was (?:frozen|covered)|disallowed|waved off|"
    r"deliberately|illegal",
    re.I,
)
LEGAL_GOAL_WORDS = re.compile(r"good goal|\bgoal\b|crossed the goal line|legal fashion|legal(?:ly)?\b", re.I)


# --------------------------------------------------------------------------
# text helpers
# --------------------------------------------------------------------------
def _norm(text: str) -> str:
    """Lower-case, straighten quotes/dashes, collapse whitespace."""
    out = (text or "")
    for src, dst in (("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"'),
                     ("\u2013", "-"), ("\u2014", "-"), ("\u00a0", " ")):
        out = out.replace(src, dst)
    out = re.sub(r"<br\s*/?>", "\n", out, flags=re.I)
    out = re.sub(r"[ \t]+", " ", out)
    return out.strip().lower()


def _strip_markdown(text: str) -> str:
    out = re.sub(r"\*{1,3}", "", text or "")
    out = re.sub(r"<[^>]+>", "", out)
    return out.strip()


def _strip_quotations(text: str, min_len: int = 60) -> str:
    """Remove long quoted passages (rulebook citations) so verdict words are only
    read from the league's own sentence, never from the rule it quotes.

    Quotes are paired left to right, so short quoted calls such as ``"no goal"``
    and ``"good goal"`` survive and the text *between* two short quotes is never
    mistaken for a quotation.
    """
    out = text or ""
    out = re.sub(r"\u201c([^\u201d]{%d,})\u201d" % min_len, " ", out)
    positions = [m.start() for m in re.finditer(r'"', out)]
    spans = []
    for i in range(0, len(positions) - 1, 2):
        start, end = positions[i], positions[i + 1]
        if end - start - 1 >= min_len:
            spans.append((start, end + 1))
    for start, end in reversed(spans):
        out = out[:start] + " " + out[end:]
    return out


def normalize_abbrev(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    code = code.strip().upper()
    return ABBREV_ALIASES.get(code, code)


def pad_clock(clock: Optional[str]) -> Optional[str]:
    if not clock:
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", clock.strip())
    if not m:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def clock_seconds(clock: Optional[str]) -> Optional[int]:
    padded = pad_clock(clock)
    if not padded:
        return None
    mm, ss = padded.split(":")
    return int(mm) * 60 + int(ss)


def period_from_label(label: Optional[str]) -> Tuple[Optional[int], Optional[str]]:
    """'Third Period' -> (3, 'REG'); 'Overtime' -> (4, 'OT'); 'Second Overtime' -> (5, 'OT')."""
    if not label:
        return None, None
    text = _norm(label)
    m = re.search(r"(?:(?P<ord>first|second|third|fourth|fifth|sixth|1st|2nd|3rd|4th|5th|6th)\s+)?"
                  r"(?P<unit>period|overtime|ot|shootout|so)\b", text)
    if not m:
        return None, None
    unit = m.group("unit")
    ordinal = PERIOD_ORDINALS.get(m.group("ord") or "", None)
    if unit == "period":
        return ordinal, "REG" if ordinal else None
    if unit in ("overtime", "ot"):
        return 3 + (ordinal or 1), "OT"
    return None, "SO"


def team_from_words(text: str, candidates: Iterable[Optional[str]]) -> Optional[str]:
    """Pick which of the two teams a 'No Goal Toronto' style phrase names.

    The words right after the verdict ("no goal Montreal", "good goal Devils")
    are tried first; only if that is inconclusive is the whole text searched,
    and an ambiguous mention of both teams yields ``None`` rather than a guess.
    """
    low = _norm(text)
    cands = [c for c in candidates if c]

    def hits_in(fragment: str) -> List[str]:
        found = []
        for abbrev in cands:
            for word in TEAM_WORDS.get(abbrev, ()) + (abbrev.lower(),):
                if re.search(r"\b" + re.escape(word) + r"\b", fragment):
                    found.append(abbrev)
                    break
        return found

    verdicts = list(re.finditer(r"\b(?:no[- ]goal|good goal|goal)\s+([a-z.' ]{3,32})", low))
    for m in reversed(verdicts):
        hits = hits_in(m.group(1))
        if len(set(hits)) == 1:
            return hits[0]
    hits = hits_in(low)
    if len(set(hits)) == 1:
        return hits[0]
    return None


# --------------------------------------------------------------------------
# parsing one feed item
# --------------------------------------------------------------------------
def parse_headline(headline: str) -> Dict[str, Any]:
    text = (headline or "").replace("\u2019", "'").strip()
    out: Dict[str, Any] = {"kind": "other", "away": None, "home": None, "clock": None,
                           "period": None, "period_type": None, "period_label": None}
    km = HEADLINE_KIND_RE.match(text)
    kind_text = _norm(km.group("kind")) if km else _norm(text)
    if "officials update" in kind_text or "officiating update" in kind_text:
        out["kind"] = "officials_update"
    elif "challenge" in kind_text:
        out["kind"] = "coach_challenge"
    elif "video review" in kind_text or "review" in kind_text:
        out["kind"] = "video_review"
    tm = HEADLINE_TEAMS_RE.search(text)
    if tm:
        out["away"] = normalize_abbrev(tm.group("away"))
        out["home"] = normalize_abbrev(tm.group("home"))
    cm = HEADLINE_CLOCK_RE.search(text)
    if cm:
        out["clock"] = pad_clock(cm.group("clock"))
        out["period_label"] = cm.group("period").strip()
        out["period"], out["period_type"] = period_from_label(out["period_label"])
    return out


def markdown_of(item: Dict[str, Any]) -> str:
    parts = item.get("parts") or []
    chunks = [p.get("content") or "" for p in parts if (p or {}).get("type") == "markdown"]
    if chunks:
        return "\n\n".join(chunks)
    return item.get("summary") or ""


def extract_fields(text: str) -> Dict[str, str]:
    """Pull the structured lines out of a modern statement. Returns {} for prose."""
    text = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.I)
    matches = list(FIELD_RE.finditer(text))
    fields: Dict[str, str] = {}
    for idx, m in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        value = text[m.end():end].strip()
        value = re.sub(r"\*+\s*$", "", value).strip()
        key = m.group("name").lower().replace(" ", "_")
        if key not in fields:
            fields[key] = value
    return fields


def _final_call(text: str) -> Optional[str]:
    low = _norm(text)
    # 2016-17 prose verdicts name the call that was REVERSED, not the final one:
    #   "Goal overturned as Stars deemed offsides"                -> no goal
    #   "Review overturns ... decision that resulted in a 'no goal' call" -> goal
    if re.search(r"\b(?:good )?goal (?:is |was |has been )?(?:overturned|disallowed|reversed|nullified|negated|waved off|taken off the board|wiped out)\b", low):
        return "no_goal"
    if re.search(r"\boverturn(?:s|ed)\b.{0,100}\bno[- ]goal\b[\"']? (?:call|ruling|decision)", low) or \
            re.search(r"\bno[- ]goal\b[\"']? (?:call|ruling|decision) (?:is |was |has been )?(?:overturned|reversed)", low):
        return "goal"
    if re.search(r"\bno[- ]goal\b", low):
        return "no_goal"
    if re.search(r"\b(good goal|goal)\b", low):
        return "goal"
    return None


def _on_ice_call_from_prose(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (call, basis) for the LAST on-ice ruling the statement describes."""
    low = _norm(_strip_quotations(_strip_markdown(text)))
    found: List[Tuple[int, str, str]] = []
    direct = [
        (r"(?:call|ruling) on the ice (?:was|is|of)(?: changed to| a| an)?\s*[\"']?(no[- ]goal|good goal|goal)\b", "call_on_the_ice"),
        (r"original call(?: by the referee[^.]{0,60}?)? was\s*[\"']?(no[- ]goal|good goal|goal)\b", "original_call"),
        (r"(?:initially|originally) (?:ruled|called|signaled|signalled)(?: it| the play| this)?(?: a| as| an)?\s*[\"']?(no[- ]goal|good goal|goal)\b", "initial_ruling"),
        (r"referee(?:'s)? (?:initial )?(?:call|ruling) (?:was|of)\s*[\"']?(no[- ]goal|good goal|goal)\b", "referee_call"),
        (r"(?:ruled|called|signaled|signalled|waved off)(?: it)? (?:a |as )?[\"']?(no[- ]goal|good goal)\b on the ice", "ruled_on_ice"),
    ]
    for pattern, basis in direct:
        for m in re.finditer(pattern, low):
            word = m.group(1)
            found.append((m.start(), "no_goal" if word.startswith("no") else "goal", basis))
    # "The Referee's initially ruled that Rossi batted the puck into the net with
    # his glove" names the infraction rather than the words "no goal".
    for m in re.finditer(r"(?:initially|originally) (?:ruled|called|determined|signaled|signalled) that ([^.]{3,200})", low):
        clause = m.group(1)
        if re.search(r"\bno[- ]goal\b", clause):
            found.append((m.start(), "no_goal", "initial_ruling_sentence"))
        elif INFRACTION_WORDS.search(clause):
            found.append((m.start(), "no_goal", "initial_ruling_sentence_infraction"))
        elif LEGAL_GOAL_WORDS.search(clause):
            found.append((m.start(), "goal", "initial_ruling_sentence"))
    if not found:
        return None, None
    found.sort(key=lambda t: t[0])
    return found[-1][1], found[-1][2]


def classify_outcome(kind: str, fields: Dict[str, str], description: str, body: str) -> Dict[str, Any]:
    """Decide whether the on-ice call changed, and what the final call was.

    Returns a dict with ``changed`` (True/False/None), ``final_call``,
    ``on_ice_call``, ``outcome`` (overturned|upheld|on_ice_call_not_stated|
    unclassified), ``confidence`` (high|medium|low) and ``basis`` (free text
    naming the sentence the decision rests on).
    """
    result_line = fields.get("result") or ""
    verdict_source = result_line or description or ""
    body_plain = _strip_markdown(body)
    body_unquoted = _norm(_strip_quotations(body_plain))
    out: Dict[str, Any] = {"changed": None, "final_call": None, "on_ice_call": None,
                           "outcome": "unclassified", "confidence": "low", "basis": ""}

    # Statements that are not goal reviews at all. They stay in the ledger
    # (the feed is captured whole) but never become discrepancy records.
    if kind == "officials_update":
        out.update(outcome="not_a_review", confidence="high",
                   basis="Officials Update: officiating-crew change, not a review")
        return out
    verdict_norm = _norm(verdict_source)
    if verdict_norm and re.search(r"\bnot (?:a )?reviewable\b", verdict_norm):
        out.update(changed=False, outcome="not_reviewable", confidence="high",
                   basis=f"result line: {_strip_markdown(verdict_source)[:160]}")
        return out
    if verdict_norm and re.search(r"\bpenalty\b", verdict_norm) and not re.search(r"\bgoal\b", verdict_norm):
        # 2025-26 coach's challenges of delay-of-game penalties, major-penalty
        # reviews, "penalty call rescinded": a penalty changed, no goal did.
        changed = bool(re.search(r"\boverturn|\brescind|\breduced|\breversed", verdict_norm))
        out.update(changed=changed, outcome="penalty_review", confidence="high",
                   basis=f"result line names a penalty and no goal: {_strip_markdown(verdict_source)[:160]}")
        return out

    final = _final_call(verdict_source)
    if final is None and fields.get("explanation"):
        final = _final_call(fields["explanation"][-160:])
    if final is None and not fields:
        # prose era: the verdict is the last "- no goal X" / "good goal X" phrase
        tail = body_unquoted[-260:]
        m = list(re.finditer(r"\b(no[- ]goal|good goal)\b", tail))
        if m:
            final = "no_goal" if m[-1].group(1).startswith("no") else "goal"
    out["final_call"] = final

    verdict = _norm(verdict_source)
    if re.search(r"\boverturn(?:ed|s)?\b|\breversed\b", verdict):
        out.update(changed=True, outcome="overturned", confidence="high",
                   basis=f"result line: {_strip_markdown(verdict_source)[:160]}")
    elif re.search(r"\bupheld\b|\bstands\b|\bconfirmed\b|\bsupported\b|\bremains\b|\bnot overturned\b", verdict):
        out.update(changed=False, outcome="upheld", confidence="high",
                   basis=f"result line: {_strip_markdown(verdict_source)[:160]}")

    on_ice, on_ice_basis = _on_ice_call_from_prose(body_plain)
    out["on_ice_call"] = on_ice
    if out["changed"] is None:
        if on_ice and final:
            out.update(changed=(on_ice != final),
                       outcome="overturned" if on_ice != final else "upheld",
                       confidence="high" if on_ice_basis in ("call_on_the_ice", "original_call", "initial_ruling", "referee_call", "ruled_on_ice") else "medium",
                       basis=f"on-ice call {on_ice} ({on_ice_basis}) vs final {final}")
        else:
            # prose verdict sentence, read only outside quotations, last one wins
            over = [m.start() for m in re.finditer(r"\b(?:is|was|been) overturned\b|\boverturns\b|\boverturned\b.{0,40}\bno goal\b|\breversed\b", body_unquoted)]
            kept = [m.start() for m in re.finditer(r"\bcall stands\b|\boriginal call stands\b|\bcall (?:on the ice )?(?:is|was) (?:confirmed|upheld|correct)\b|\bconfirmed (?:the )?(?:referee|call|no goal|good goal)|\bsupported the referee|\bupheld\b", body_unquoted)]
            if over or kept:
                last_over = max(over) if over else -1
                last_kept = max(kept) if kept else -1
                if last_over > last_kept:
                    out.update(changed=True, outcome="overturned", confidence="high", basis="verdict sentence: overturned")
                else:
                    out.update(changed=False, outcome="upheld", confidence="high", basis="verdict sentence: call stands / confirmed")
    if out["changed"] is None:
        out["outcome"] = "on_ice_call_not_stated" if final else "unclassified"
        out["basis"] = "statement gives the result but not the on-ice call" if final else "no result phrase recognised"
    if out["on_ice_call"] is None and out["changed"] is not None and final:
        out["on_ice_call"] = ("goal" if final == "no_goal" else "no_goal") if out["changed"] else final
    return out


def infer_review_type(fields: Dict[str, str], body: str, kind: str) -> Tuple[Optional[str], bool]:
    explicit = fields.get("type_of_challenge") or fields.get("type_of_review")
    if explicit:
        return _strip_markdown(explicit).strip().rstrip("."), False
    low = _norm(_strip_markdown(body))
    table = [
        (r"goaltender interference|interfer", "Goaltender Interference"),
        (r"off[- ]side|offside", "Off-Side"),
        (r"missed (?:game )?stoppage|should have been stopped", "Missed Game Stoppage"),
        (r"cross(?:ed)? the goal line|goal line", "Puck Over Goal Line"),
        (r"high[- ]stick", "High Stick"),
        (r"kick|skate", "Distinct Kicking Motion"),
        (r"hand pass|batted|glove", "Hand Pass / Batted Puck"),
        (r"net (?:was )?(?:off|dislodged)|net off its moorings", "Net Dislodged"),
        (r"before the (?:period|game) ended|expiration of time|clock", "Time Expired"),
    ]
    for pattern, label in table:
        if re.search(pattern, low):
            return label, True
    return None, kind == "other"


REVIEW_TYPE_GROUPS: List[Tuple[str, str]] = [
    (r"situation room initiated", "League-initiated challenge"),
    (r"missed (?:game )?stoppage", "Missed Game Stoppage Event"),
    (r"goal(?:tender|ie|keeper) interference|interference on the goal", "Goaltender Interference"),
    (r"off[- ]?side", "Off-Side"),
    (r"puck (?:over|crossed|crossing|across) (?:the )?goal line|goal line|entering net|legal goal|legal fashion", "Puck Over Goal Line"),
    (r"kick", "Distinct Kicking Motion"),
    (r"high[- ]?stick", "High-Sticking the Puck"),
    (r"hand pass|batted|bats|batting|directed puck|directs puck", "Hand Pass / Batted Puck"),
    (r"net off|net dislodged|displaced net|net displaced|moorings|awarded goal", "Net Off / Awarded Goal"),
    (r"out of play|out of bounds", "Puck Out of Play"),
    (r"time expired|time on clock|expir", "Time Expired"),
    (r"continuous play|culmination", "Culmination of a Continuous Play"),
    (r"penalty|penalties|major|match", "Penalty"),
    (r"deflected directly off official|off official", "Puck Off Official"),
]


def normalize_review_type(label: Optional[str]) -> str:
    """Collapse the ~70 spellings the league has used for a dozen review types
    into stable filter buckets. The verbatim label is always kept alongside;
    this only drives filtering and counting."""
    if not label:
        return "unstated"
    low = _norm(label).replace("\u2013", "-").replace("--", "-")
    hits = []
    for pattern, group in REVIEW_TYPE_GROUPS:
        if re.search(pattern, low):
            hits.append(group)
    if not hits:
        return "Other"
    if hits[0] in ("Missed Game Stoppage Event", "League-initiated challenge"):
        return hits[0]
    if "Penalty" in hits and not re.search(r"\bgoal\b", low):
        return "Penalty"
    return hits[0] if len(hits) == 1 else "Combined: " + " + ".join(dict.fromkeys(hits))


def all_tags(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Story tags plus the tags of embedded parts: in the 2019-2023 era the
    ``gameid-`` tag often sits on the embedded video, not on the story."""
    tags = list(item.get("tags") or [])
    for part in item.get("parts") or []:
        tags.extend((part or {}).get("tags") or [])
    return tags


def game_from_tags(tags: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"game_id": None, "game_tag_title": None, "tag_date": None,
                           "tag_away": None, "tag_home": None, "season_tag": None, "team_tags": []}
    for tag in tags or []:
        slug = str(tag.get("slug") or "")
        if slug.startswith("gameid-"):
            gid = slug[len("gameid-"):]
            if re.fullmatch(r"\d{10}", gid):
                out["game_id"] = gid
            out["game_tag_title"] = tag.get("title")
            m = GAME_TAG_TITLE_RE.match(str(tag.get("title") or ""))
            if m:
                out["tag_date"] = f"{m.group('y')}-{m.group('m')}-{m.group('d')}"
                out["tag_away"] = normalize_abbrev(m.group("away"))
                out["tag_home"] = normalize_abbrev(m.group("home"))
        elif slug.startswith("teamid-"):
            abbrev = ((tag.get("extraData") or {}).get("abbreviation"))
            if abbrev:
                out["team_tags"].append(normalize_abbrev(abbrev))
        elif re.fullmatch(r"\d{4}-\d{2}", slug):
            out["season_tag"] = slug
    return out


def season_from_game_id(game_id: Optional[str]) -> Optional[str]:
    if not game_id or not re.fullmatch(r"\d{10}", game_id):
        return None
    start = int(game_id[:4])
    return f"{start}{start + 1}"


def et_date_candidates(content_date: Optional[str]) -> List[str]:
    """Game dates a statement time-stamped in UTC could belong to (ET calendar)."""
    if not content_date:
        return []
    try:
        ts = datetime.strptime(content_date[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return []
    et = ts - timedelta(hours=4)      # EDT; the extra day below covers EST
    return sorted({(et - timedelta(days=1)).strftime("%Y-%m-%d"), et.strftime("%Y-%m-%d")}, reverse=True)


@dataclasses.dataclass
class Ruling:
    slug: str
    headline: str
    kind: str
    away: Optional[str]
    home: Optional[str]
    period: Optional[int]
    period_type: Optional[str]
    period_label: Optional[str]
    clock: Optional[str]
    game_id: Optional[str]
    game_id_source: Optional[str]
    game_date: Optional[str]
    season: Optional[str]
    content_date: Optional[str]
    last_updated: Optional[str]
    initiated_by: Optional[str]
    review_type: Optional[str]
    review_type_inferred: bool
    result_text: Optional[str]
    explanation: str
    description: Optional[str]
    on_ice_call: Optional[str]
    final_call: Optional[str]
    changed: Optional[bool]
    outcome: str
    confidence: str
    basis: str
    final_team: Optional[str]
    rule_citations: List[str]
    clock_reset: Optional[Dict[str, str]]
    public_url: str
    api_url: str
    format: str
    flags: List[str] = dataclasses.field(default_factory=list)
    crosscheck: Optional[Dict[str, Any]] = None
    ingested_at: str = dataclasses.field(default_factory=utcnow)
    human_read: Optional[Dict[str, Any]] = None
    parser_reading: Optional[Dict[str, Any]] = None
    review_type_group: str = "unstated"

    def to_dict(self) -> Dict[str, Any]:
        d = dataclasses.asdict(self)
        d["review_type_group"] = normalize_review_type(self.review_type)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Ruling":
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def ruling_from_item(item: Dict[str, Any]) -> Ruling:
    """Parse one feed/story payload. Pure function; safe on fixtures."""
    headline = item.get("headline") or ""
    head = parse_headline(headline)
    body = markdown_of(item)
    fields = extract_fields(body)
    description = ((item.get("fields") or {}).get("description")) or None
    tags = game_from_tags(all_tags(item))
    verdict = classify_outcome(head["kind"], fields, description or "", body)
    review_type, inferred = infer_review_type(fields, body, head["kind"])
    plain = _strip_markdown(body)
    explanation = _strip_markdown(fields.get("explanation") or "") if fields else plain
    rules = []
    for m in RULE_RE.finditer(plain):
        if m.group(1) not in rules:
            rules.append(m.group(1))
    reset = None
    rm = CLOCK_RESET_RE.search(plain)
    if rm:
        reset = {"shows": pad_clock(rm.group(1)), "elapsed": pad_clock(rm.group(2))}
    away = head["away"] or tags["tag_away"]
    home = head["home"] or tags["tag_home"]
    final_team = team_from_words(fields.get("result") or description or plain[-200:], (away, home))
    initiated = fields.get("challenge_initiated_by")
    if not initiated and not fields:
        im = re.search(r"([A-Z][A-Za-z.\s]{2,30}?) (?:then )?requested a coach's challenge", plain.replace("\u2019", "'"), re.I)
        if im:
            initiated = im.group(1).strip()
        elif re.search(r"situation room initiated|league[- ]initiated", plain, re.I):
            initiated = "NHL Situation Room"
    if not initiated and head["kind"] == "video_review" and re.search(r"situation room (?:then )?initiated", plain, re.I):
        initiated = "NHL Situation Room"
    flags: List[str] = []
    if not tags["game_id"]:
        flags.append("game_id_not_tagged")
    if head["period"] is None:
        flags.append("period_unparsed")
    if head["clock"] is None:
        flags.append("clock_unparsed")
    if verdict["outcome"] == "on_ice_call_not_stated":
        flags.append("on_ice_call_not_stated")
    elif verdict["outcome"] == "unclassified":
        flags.append("outcome_unclassified")
    if verdict["confidence"] == "medium":
        flags.append("on_ice_call_inferred_from_wording")
    if inferred and review_type:
        flags.append("review_type_inferred")
    if final_team is None and verdict["final_call"]:
        flags.append("final_team_unresolved")
    return Ruling(
        slug=item.get("slug") or "",
        headline=headline.strip(),
        kind=head["kind"], away=away, home=home,
        period=head["period"], period_type=head["period_type"], period_label=head["period_label"],
        clock=head["clock"],
        game_id=tags["game_id"], game_id_source="tag" if tags["game_id"] else None,
        game_date=tags["tag_date"],
        season=season_from_game_id(tags["game_id"]),
        content_date=item.get("contentDate"), last_updated=item.get("lastUpdatedDate"),
        initiated_by=_strip_markdown(initiated).strip() if initiated else None,
        review_type=review_type, review_type_inferred=inferred,
        result_text=_strip_markdown(fields.get("result") or "") or description,
        explanation=explanation, description=description,
        on_ice_call=verdict["on_ice_call"], final_call=verdict["final_call"],
        changed=verdict["changed"], outcome=verdict["outcome"], confidence=verdict["confidence"],
        basis=verdict["basis"], final_team=final_team, rule_citations=rules, clock_reset=reset,
        public_url=PUBLIC_NEWS_BASE + (item.get("slug") or ""),
        api_url=item.get("selfUrl") or (FEED_BASE + "/" + (item.get("slug") or "")),
        format="structured" if fields else "prose",
        flags=flags,
    )


# --------------------------------------------------------------------------
# network: feed pages, stories, play-by-play, schedule
# --------------------------------------------------------------------------
def feed_url(skip: int, limit: int = DEFAULT_PAGE_SIZE) -> str:
    return f"{FEED_BASE}?tags.slug={FEED_TAG}&$limit={limit}&$skip={skip}"


def fetch_feed_page(fetcher: Fetcher, skip: int, limit: int = DEFAULT_PAGE_SIZE) -> Tuple[List[Dict[str, Any]], FetchResult]:
    payload, res = fetcher.get_json(feed_url(skip, limit))
    if not res.ok or not isinstance(payload, dict):
        return [], res
    return list(payload.get("items") or []), res


def fetch_story(fetcher: Fetcher, slug: str) -> Tuple[Optional[Dict[str, Any]], FetchResult]:
    payload, res = fetcher.get_json(f"{FEED_BASE}/{slug}")
    if not res.ok or not isinstance(payload, dict):
        return None, res
    return payload, res


def resolve_game_id(fetcher: Fetcher, ruling: Ruling) -> Tuple[Optional[str], Optional[str], List[str]]:
    """Find the game id for an untagged statement from the daily scoreboard."""
    tried: List[str] = []
    if not ruling.away or not ruling.home:
        return None, None, tried
    for date in et_date_candidates(ruling.content_date):
        url = f"{API_BASE}/score/{date}"
        tried.append(url)
        payload, res = fetcher.get_json(url)
        if not res.ok or not isinstance(payload, dict):
            continue
        for game in payload.get("games") or []:
            away = normalize_abbrev(((game.get("awayTeam") or {}).get("abbrev")))
            home = normalize_abbrev(((game.get("homeTeam") or {}).get("abbrev")))
            if away == ruling.away and home == ruling.home:
                return str(game.get("id")), game.get("gameDate") or date, tried
    return None, None, tried


def _roster_names(pbp: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for spot in pbp.get("rosterSpots") or []:
        pid = spot.get("playerId")
        if pid is None:
            continue
        first = (spot.get("firstName") or {}).get("default") or ""
        last = (spot.get("lastName") or {}).get("default") or ""
        out[int(pid)] = {
            "name": (f"{first[:1]}. {last}" if first else last).strip(),
            "surname": last, "initial": first[:1] or None, "player_id": int(pid),
            "sweater_number": spot.get("sweaterNumber"), "team_id": spot.get("teamId"),
        }
    return out


def _is_review_stoppage(play: Dict[str, Any]) -> bool:
    if play.get("typeDescKey") != "stoppage":
        return False
    details = play.get("details") or {}
    for key in ("reason", "secondaryReason"):
        reason = str(details.get(key) or "")
        if reason in REVIEW_STOPPAGE_EXACT or reason.startswith(REVIEW_STOPPAGE_PREFIXES):
            return True
    return False


def crosscheck_with_pbp(pbp: Dict[str, Any], ruling: Ruling, *, fetch: Optional[FetchResult] = None) -> Dict[str, Any]:
    """Compare the statement with the official final play-by-play.

    ``status`` is ``agree`` when the final record matches the ruling (goal
    present for an awarded goal; goal absent plus a review stoppage for a
    disallowed one), ``conflict`` when it contradicts it, ``inconclusive`` when
    the clock/period could not be matched.
    """
    out: Dict[str, Any] = {
        "status": "inconclusive", "checked_at": utcnow(), "pbp_url": f"{API_BASE}/gamecenter/{ruling.game_id}/play-by-play",
        "pbp_sha256": fetch.sha256 if fetch else None, "game_state": pbp.get("gameState"),
        "game_date": pbp.get("gameDate"), "away": None, "home": None, "final_score": None,
        "goal_event": None, "review_stoppages": [], "notes": [],
    }
    away_t = pbp.get("awayTeam") or {}
    home_t = pbp.get("homeTeam") or {}
    out["away"] = normalize_abbrev(away_t.get("abbrev"))
    out["home"] = normalize_abbrev(home_t.get("abbrev"))
    out["final_score"] = {"away": away_t.get("score"), "home": home_t.get("score")}
    out["venue"] = (pbp.get("venue") or {}).get("default")
    team_by_id = {away_t.get("id"): out["away"], home_t.get("id"): out["home"]}
    if ruling.period is None or ruling.clock is None:
        out["notes"].append("period/clock not parsed from headline")
        return out
    want_sec = clock_seconds(ruling.clock)
    plays = [p for p in pbp.get("plays") or [] if ((p.get("periodDescriptor") or {}).get("number")) == ruling.period]
    if not plays:
        out["notes"].append(f"no plays for period {ruling.period} in play-by-play")
        return out
    names = _roster_names(pbp)
    goals_near: List[Tuple[int, Dict[str, Any]]] = []
    for p in plays:
        sec = clock_seconds(p.get("timeInPeriod"))
        if sec is None:
            continue
        delta = abs(sec - want_sec)
        if p.get("typeDescKey") == "goal" and delta <= 2:
            goals_near.append((delta, p))
        if _is_review_stoppage(p) and delta <= 150:
            d = p.get("details") or {}
            out["review_stoppages"].append({"event_id": p.get("eventId"), "time": p.get("timeInPeriod"),
                                            "reason": d.get("reason"), "secondary_reason": d.get("secondaryReason"),
                                            "delta_seconds": sec - want_sec})
    goals_near.sort(key=lambda t: t[0])
    team_goals = []
    for delta, p in goals_near:
        d = p.get("details") or {}
        scorer_team = team_by_id.get(d.get("eventOwnerTeamId"))
        if ruling.final_team and scorer_team and scorer_team != ruling.final_team:
            continue
        team_goals.append((delta, p, scorer_team))

    def goal_dict(p: Dict[str, Any], scorer_team: Optional[str]) -> Dict[str, Any]:
        d = p.get("details") or {}
        assists = []
        for key in ("assist1PlayerId", "assist2PlayerId"):
            pid = d.get(key)
            if pid:
                a = dict(names.get(int(pid), {"name": str(pid), "player_id": int(pid)}))
                a["season_counter"] = d.get(key.replace("PlayerId", "PlayerTotal"))
                assists.append(a)
        scorer = dict(names.get(int(d.get("scoringPlayerId") or 0), {"name": None, "player_id": d.get("scoringPlayerId")}))
        scorer["season_counter"] = d.get("scoringPlayerTotal")
        return {
            "event_id": p.get("eventId"), "period": (p.get("periodDescriptor") or {}).get("number"),
            "clock": pad_clock(p.get("timeInPeriod")), "team": scorer_team, "scorer": scorer, "assists": assists,
            "away_score": d.get("awayScore"), "home_score": d.get("homeScore"), "shot_type": d.get("shotType"),
            "goal_modifier": d.get("goalModifier"), "situation_code": p.get("situationCode"),
            "goalie_in_net_id": d.get("goalieInNetId"),
        }

    if ruling.final_call == "goal":
        if team_goals:
            delta, p, scorer_team = team_goals[0]
            out["goal_event"] = goal_dict(p, scorer_team)
            out["status"] = "agree"
            if delta:
                out["notes"].append(f"goal event is {delta}s from the stated clock")
            if not out["review_stoppages"]:
                out["notes"].append("no review stoppage recorded near the clock (goal present as ruled)")
        else:
            # Same team, same period, further away: the statement clock and the
            # play-by-play clock disagree (clock resets after a review are
            # common). Not a contradiction, but not a confirmation either.
            same_period = []
            for p in plays:
                if p.get("typeDescKey") != "goal" or (p.get("periodDescriptor") or {}).get("number") != ruling.period:
                    continue
                d = p.get("details") or {}
                scorer_team = team_by_id.get(d.get("eventOwnerTeamId"))
                if ruling.final_team and scorer_team and scorer_team != ruling.final_team:
                    continue
                sec = clock_seconds(p.get("timeInPeriod"))
                if sec is None:
                    continue
                same_period.append((abs(sec - want_sec), sec - want_sec, p, scorer_team))
            same_period.sort(key=lambda t: t[0])
            if same_period and same_period[0][0] <= 180:
                _, signed, p, scorer_team = same_period[0]
                out["goal_event"] = goal_dict(p, scorer_team)
                out["status"] = "inconclusive"
                out["notes"].append(
                    f"no goal within 2s of the stated clock; nearest {scorer_team or 'same-team'} goal in the period is at "
                    f"{pad_clock(p.get('timeInPeriod'))} ({signed:+d}s) - statement clock and play-by-play clock disagree; human check")
            else:
                out["status"] = "conflict"
                out["notes"].append("ruling awards a goal but the final play-by-play has no goal at that period/clock")
    elif ruling.final_call == "no_goal":
        if team_goals:
            delta, p, scorer_team = team_goals[0]
            out["goal_event"] = goal_dict(p, scorer_team)
            out["status"] = "conflict"
            out["notes"].append("ruling disallows a goal but the final play-by-play still carries a goal at that clock")
        elif out["review_stoppages"]:
            out["status"] = "agree"
            out["notes"].append("no goal in the final record at the clock; review stoppage present")
        else:
            out["status"] = "inconclusive"
            out["notes"].append("no goal at the clock (as ruled) but no review stoppage found within 150s either")
    else:
        out["notes"].append("final call unknown; nothing to compare")
    return out


# --------------------------------------------------------------------------
# record construction
# --------------------------------------------------------------------------
def _gs_url(game_id: str) -> Optional[str]:
    try:
        return GameRef(game_id).report_url("GS")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Human reads: documented, source-backed supplements for statements the parser
# cannot classify on its own (typically "on_ice_call_not_stated").  They live in
# data/curation/situation_room_human_reads.json, keyed by statement slug, and
# every entry must carry the official source that states the on-ice call.  The
# ingest applies them on every run, so the resulting record is reproducible
# machine output with a visible audit trail - not a hand-typed row.
# ---------------------------------------------------------------------------
HUMAN_READS_RELPATH = os.path.join("data", "curation", "situation_room_human_reads.json")
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HUMAN_READS_PATH = os.path.join(_REPO_ROOT, HUMAN_READS_RELPATH)
HUMAN_READ_FLAG = "on_ice_call_from_documented_human_read"


_PARSER_READING_KEYS = ("on_ice_call", "changed", "outcome", "confidence", "basis", "flags")


def ruling_from_item_dict(row: Dict[str, Any]) -> Ruling:
    """Rebuild a Ruling from a ledger row with any earlier human overlay removed,
    so a changed or withdrawn read can be re-applied cleanly: the parser's own
    reading is restored from ``parser_reading`` when an overlay was applied."""
    data = dict(row)
    parser = data.get("parser_reading")
    if parser:
        data.update({k: parser.get(k) for k in _PARSER_READING_KEYS if k in parser})
    data["human_read"] = None
    data["parser_reading"] = None
    return Ruling.from_dict(data)


def load_human_reads(path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Return ``{slug: read}`` from the curation file (empty when absent)."""
    path = path or HUMAN_READS_PATH
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    out: Dict[str, Dict[str, Any]] = {}
    for read in data.get("reads") or []:
        slug = read.get("slug")
        if slug and read.get("on_ice_call") in ("goal", "no_goal"):
            out[slug] = read
    return out


def apply_human_read(ruling: Ruling, read: Optional[Dict[str, Any]]) -> Ruling:
    """Overlay a documented on-ice call onto a ruling the parser could not settle.

    The read only ever *adds* the on-ice call; the final call always stays the
    one printed in the official statement.  A read that contradicts an on-ice
    call the statement states explicitly (confidence ``high``) is ignored and
    flagged, because the statement outranks any later reading of it.
    """
    if not read:
        return ruling
    call = read.get("on_ice_call")
    if call not in ("goal", "no_goal") or not ruling.final_call:
        return ruling
    if ruling.confidence == "high" and ruling.on_ice_call and ruling.on_ice_call != call:
        ruling.flags = sorted(set(ruling.flags) | {"human_read_contradicts_statement_ignored"})
        return ruling
    if ruling.parser_reading is None:
        ruling.parser_reading = {k: getattr(ruling, k) for k in _PARSER_READING_KEYS}
    ruling.on_ice_call = call
    ruling.changed = call != ruling.final_call
    ruling.outcome = "overturned" if ruling.changed else "upheld"
    ruling.confidence = "high"
    ruling.basis = (f"{ruling.basis}; on-ice call {call} from documented human read "
                    f"({read.get('read_at') or 'undated'}): {read.get('basis') or ''}").strip()
    ruling.human_read = {k: read.get(k) for k in ("on_ice_call", "basis", "read_at", "read_by", "sources", "quote")}
    ruling.flags = sorted((set(ruling.flags) | {HUMAN_READ_FLAG}) - {"needs_human_read_of_on_ice_call"})
    return ruling


def ruling_to_record(ruling: Ruling, *, run_id: str, now: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Build a database record for a ruling whose on-ice call was changed.

    Returns ``None`` for upheld / not-stated rulings and for anything without
    a game id, period and clock (those stay in the ledger with their flags).
    """
    if ruling.changed is not True or ruling.outcome != "overturned" or not ruling.game_id or ruling.period is None or not ruling.clock:
        return None
    if ruling.final_call not in ("goal", "no_goal") or ruling.on_ice_call not in ("goal", "no_goal") or ruling.final_call == ruling.on_ice_call:
        return None
    now = now or utcnow()
    final = ruling.final_call
    field = "goal_added" if final == "goal" else "goal_removed"
    goal_key = f"P{ruling.period}@{ruling.clock}"
    rid = db_mod.compute_record_id(ruling.game_id, CHECK_ID, field, goal_key)
    xc = ruling.crosscheck or {}
    agree = xc.get("status") == "agree"
    conflict = xc.get("status") == "conflict"
    away = xc.get("away") or ruling.away
    home = xc.get("home") or ruling.home
    team = ruling.final_team
    kind_label = "Coach's Challenge" if ruling.kind == "coach_challenge" else "Video review"
    label_type = ruling.review_type or "review"
    if final == "goal":
        change_type = "no_goal_overturned_to_goal"
        rule = "situation_room_no_goal_overturned_to_goal"
        summary = (f"{kind_label} ({label_type}): on-ice no-goal overturned, goal awarded to {team or 'the attacking team'} "
                   f"at {ruling.clock} of period {ruling.period}")
    else:
        change_type = "goal_overturned_to_no_goal"
        rule = "situation_room_goal_overturned_to_no_goal"
        summary = (f"{kind_label} ({label_type}): on-ice goal overturned, no goal {team or ''} "
                   f"at {ruling.clock} of period {ruling.period}").replace("  ", " ")
    goal_ev = xc.get("goal_event") or {}
    score_after = ({"away": goal_ev.get("away_score"), "home": goal_ev.get("home_score")}
                   if goal_ev else None)
    scorer = goal_ev.get("scorer") if goal_ev else None
    assists = goal_ev.get("assists") if goal_ev else []
    on_ice_state = {
        "artifact": "on-ice call, as described in the NHL Situation Room statement",
        "goal_present": ruling.on_ice_call == "goal",
        "ruling": ruling.on_ice_call or ("goal" if final == "no_goal" else "no_goal"),
        "scorer": (scorer if (final == "no_goal" and scorer) else None),
        "assists": (assists if final == "no_goal" else []),
        "period": ruling.period, "clock": ruling.clock, "team": team,
        "score_after": None,
        "note": ("the disallowed goal is removed from the official record, so the on-ice scorer is not recoverable "
                 "from the final play-by-play" if final == "no_goal" else None),
    }
    final_state = {
        "artifact": ("official play-by-play after review" if agree and final == "goal"
                     else "NHL Situation Room result" + (" (confirmed against play-by-play)" if agree else "")),
        "goal_present": final == "goal",
        "ruling": final,
        "scorer": scorer if final == "goal" else None,
        "assists": assists if final == "goal" else [],
        "period": ruling.period, "clock": ruling.clock, "team": team,
        "score_after": score_after if final == "goal" else None,
        "event_id": goal_ev.get("event_id") if final == "goal" else None,
        "shot_type": goal_ev.get("shot_type") if final == "goal" else None,
    }
    market = {
        "total_changed": True,
        "affects_game_total": "yes",
        "affects_period_total": "yes",
        "affects_player_props": "yes",
        "affects_result_markets": "yes",
        "risk": "high" if ruling.period >= 3 else "medium",
        "settlement_window": "in_game",
        "reason": ("The number of goals in the game changed between the on-ice announcement and the official ruling, "
                   "inside the same game. Live game-total, period-total and anytime-scorer markets that reacted to the "
                   "on-ice call were exposed; the post-game box score already reflects the corrected state, so a "
                   "settlement made from the final official record is not affected. NHL records are not a sportsbook "
                   "source of record; this is an exposure flag, not a claim that any market was mis-settled."),
        "rule_class": "total",
    }
    flags = sorted(set(ruling.flags) - {"game_id_not_tagged"})
    status = "flagged"
    if agree and ruling.confidence == "high":
        status = "verified"
    if conflict:
        flags.append("pbp_conflicts_with_situation_room_statement")
    elif not xc:
        flags.append("awaiting_pbp_crosscheck")
    elif xc.get("status") == "inconclusive":
        flags.append("pbp_crosscheck_inconclusive")
    if ruling.confidence == "medium":
        flags.append("needs_human_read_of_on_ice_call")
    if ruling.game_id_source == "schedule":
        flags.append("game_id_resolved_from_schedule")
    flags = sorted(set(flags))
    sources: List[Dict[str, Any]] = [
        {"label": f"NHL Situation Room statement - {ruling.headline}", "url": ruling.public_url,
         "kind": "official_statement", "evidence": "primary", "retrieved_at": ruling.ingested_at,
         "quote": ruling.result_text or ruling.explanation[:200]},
        {"label": "Same statement, league content API record (machine-readable, with tags and timestamps)",
         "url": ruling.api_url, "kind": "official_api", "evidence": "primary", "retrieved_at": ruling.ingested_at,
         "note": f"contentDate {ruling.content_date}"},
    ]
    if xc:
        sources.append({
            "label": "Official play-by-play (api-web) - final record checked for the goal and the review stoppage",
            "url": xc.get("pbp_url"), "kind": "official_api", "evidence": "primary",
            "retrieved_at": xc.get("checked_at"), "sha256": xc.get("pbp_sha256"),
            "note": f"cross-check: {xc.get('status')}; " + "; ".join(xc.get("notes") or [])[:300],
        })
    for extra in (ruling.human_read or {}).get("sources") or []:
        if extra.get("url") and extra["url"] not in {src.get("url") for src in sources}:
            sources.append({"label": extra.get("label") or "Source for the on-ice call (documented human read)",
                            "url": extra["url"], "kind": extra.get("kind") or "official_page",
                            "evidence": extra.get("evidence") if extra.get("evidence") in db_mod.VALID_EVIDENCE else "secondary",
                            "retrieved_at": extra.get("retrieved_at") or (ruling.human_read or {}).get("read_at") or "",
                            "quote": extra.get("quote"), "note": extra.get("note")})
    gs = _gs_url(ruling.game_id)
    if gs:
        sources.append({"label": "Official Game Summary (GS) report - frozen post-game scoring summary",
                        "url": gs, "kind": "official_report", "evidence": "reference", "retrieved_at": "",
                        "note": "linked for manual re-verification; not fetched by the Situation Room ingest"})
    verification = {
        "status": status,
        "evidence_grade": "primary",
        "independently_checkable": True,
        "method": "league_statement" + ("+pbp_crosscheck" if xc else ""),
        "check_instructions": (
            f"Open the Situation Room statement and confirm the Result line. Then open "
            f"{API_BASE}/gamecenter/{ruling.game_id}/play-by-play and look at period {ruling.period} around "
            f"{ruling.clock}: {'a goal event for ' + (team or 'the awarded team') + ' must be present' if final == 'goal' else 'there must be no goal for ' + (team or 'the team') + ' at that clock, and a chlg-*/video-review stoppage nearby'}. "
            f"The GS report should show the same scoring summary."),
        "verified_by": ("nhl_scoring.situation_room - official statement and official play-by-play agree"
                        + (f"; on-ice call from documented human read by {(ruling.human_read or {}).get('read_by')}"
                           if ruling.human_read else "")
                        if status == "verified" else ""),
        "verified_at": now if status == "verified" else "",
    }
    if ruling.human_read:
        verification["human_read"] = ruling.human_read
    gtype = GAME_TYPE_NAMES.get(ruling.game_id[4:6], ruling.game_id[4:6])
    record = {
        "record_id": rid,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "confidence": "high" if (agree and ruling.confidence == "high") else "medium",
        "detected_by": "league_statement",
        "detection": {
            "check_id": CHECK_ID,
            "rule": rule,
            "rule_label": "Situation Room statement: on-ice call overturned",
            "severity": "high",
            "detected_at": now,
            "run_id": run_id,
            "tool_version": __version__,
            "source_feed": feed_url(0),
            "statement_published_at": ruling.content_date,
        },
        "game": {
            "game_id": ruling.game_id,
            "season": ruling.season,
            "game_type": gtype,
            "date": xc.get("game_date") or ruling.game_date,
            "away_team": away,
            "home_team": home,
            "venue": xc.get("venue"),
            "final_score": xc.get("final_score") or {"away": None, "home": None},
            "game_state": xc.get("game_state"),
            "gamecenter_url": f"https://www.nhl.com/gamecenter/{ruling.game_id}",
            "report_urls": {"GS": gs} if gs else {},
        },
        "discrepancy": {
            "period": ruling.period,
            "period_type": ruling.period_type,
            "clock": ruling.clock,
            "team": team,
            "field": field,
            "goal_key": goal_key,
            "change_type": change_type,
            "summary": summary,
            "detail": ruling.explanation,
            "total_changed": True,
            "attribution_only": False,
            "goal_no_goal_change": True,
            "video_review": True,
            "when_corrected": "in_game",
            "timing_uncertain": False,
            "market_impact": market,
            "review": {
                "kind": ruling.kind,
                "initiated_by": ruling.initiated_by,
                "type": ruling.review_type,
                "type_inferred": ruling.review_type_inferred,
                "result": ruling.result_text,
                "on_ice_call": ruling.on_ice_call,
                "final_call": final,
                "outcome": ruling.outcome,
                "classification_confidence": ruling.confidence,
                "classification_basis": ruling.basis,
                "clock_reset": ruling.clock_reset,
                "statement_format": ruling.format,
            },
            "reason": {
                "stated_by_league": True,
                "text": ruling.explanation,
                "rule_citation": ", ".join(ruling.rule_citations),
                "needs_human_read": ruling.confidence != "high",
            },
        },
        "initial_state": on_ice_state,
        "corrected_state": final_state,
        "totals": {
            "initial_game_goals": None,
            "corrected_game_goals": ((xc.get("final_score") or {}).get("away") or 0) + ((xc.get("final_score") or {}).get("home") or 0)
            if xc.get("final_score") and (xc.get("final_score") or {}).get("away") is not None else None,
            "goal_delta": 1 if final == "goal" else -1,
            "basis": "on-ice call versus the official ruling; game total from the final play-by-play when available",
        },
        "sources": sources,
        "verification": verification,
        "flags": flags,
        "notes": (f"Ingested from the official NHL Situation Room feed ({ruling.format} format). "
                  f"Classification basis: {ruling.basis}."),
    }
    return record


# --------------------------------------------------------------------------
# ledger + ingest orchestration
# --------------------------------------------------------------------------
def load_ledger(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"schema_version": SCHEMA_VERSION, "feed": feed_url(0), "rulings": [], "meta": {}}
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    payload.setdefault("rulings", [])
    payload.setdefault("meta", {})
    return payload


def summarize_rulings(rulings: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(rulings)
    by_outcome: Dict[str, int] = {}
    by_season: Dict[str, Dict[str, int]] = {}
    by_kind: Dict[str, int] = {}
    by_type: Dict[str, int] = {}
    by_group: Dict[str, int] = {}
    xc: Dict[str, int] = {}
    dates = [r.get("content_date") for r in rows if r.get("content_date")]
    for r in rows:
        by_outcome[r.get("outcome") or "?"] = by_outcome.get(r.get("outcome") or "?", 0) + 1
        by_kind[r.get("kind") or "?"] = by_kind.get(r.get("kind") or "?", 0) + 1
        t = r.get("review_type") or "unstated"
        by_type[t] = by_type.get(t, 0) + 1
        g = r.get("review_type_group") or normalize_review_type(r.get("review_type"))
        by_group[g] = by_group.get(g, 0) + 1
        season = r.get("season") or ((r.get("content_date") or "")[:4] + "?")
        bucket = by_season.setdefault(season, {"total": 0, "overturned": 0, "upheld": 0, "not_stated": 0, "non_goal": 0, "unclassified": 0})
        bucket["total"] += 1
        key = {"overturned": "overturned", "upheld": "upheld", "on_ice_call_not_stated": "not_stated",
               "penalty_review": "non_goal", "not_a_review": "non_goal", "not_reviewable": "non_goal"}.get(r.get("outcome"), "unclassified")
        bucket[key] += 1
        status = ((r.get("crosscheck") or {}).get("status")) or "not_checked"
        if r.get("outcome") == "overturned":
            xc[status] = xc.get(status, 0) + 1
    return {
        "rulings": len(rows),
        "by_outcome": by_outcome,
        "by_kind": by_kind,
        "by_review_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
        "by_review_type_group": dict(sorted(by_group.items(), key=lambda kv: -kv[1])),
        "by_season": dict(sorted(by_season.items())),
        "overturned_crosscheck": xc,
        "earliest_statement": min(dates) if dates else None,
        "latest_statement": max(dates) if dates else None,
        "missing_game_id": sum(1 for r in rows if not r.get("game_id")),
    }


def save_ledger(payload: Dict[str, Any], path: str) -> None:
    rulings = sorted(payload.get("rulings", []), key=lambda r: (r.get("content_date") or "", r.get("slug") or ""), reverse=True)
    out = {
        "schema_version": payload.get("schema_version", SCHEMA_VERSION),
        "generated_by": "pipeline/nhl_scoring (situation_room.py)",
        "generated_at": utcnow(),
        "feed": feed_url(0),
        "public_index": "https://www.nhl.com/news/topic/situation-room",
        "meta": payload.get("meta") or {},
        "summary": summarize_rulings(rulings),
        "rulings": rulings,
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Raw capture: the ledger keeps the verbatim statement body and the tags that
# matter, so the corpus can be re-parsed offline (``mode="reparse"``) after a
# parser change without re-fetching ~4,400 stories, and so every classification
# can be audited against the exact text it was made from.
# ---------------------------------------------------------------------------
def raw_of(item: Dict[str, Any]) -> Dict[str, Any]:
    tags = []
    for tag in all_tags(item):
        slug = str((tag or {}).get("slug") or "")
        if slug.startswith(("gameid-", "teamid-")) or re.fullmatch(r"\d{4}-\d{2}", slug):
            tags.append({"slug": slug, "title": tag.get("title"),
                         "extraData": {k: v for k, v in (tag.get("extraData") or {}).items()
                                       if k in ("abbreviation", "gameId", "teamId")}})
    return {"headline": item.get("headline") or "", "body": markdown_of(item),
            "description": ((item.get("fields") or {}).get("description")) or None,
            "summary": item.get("summary") or None, "tags": tags}


def item_from_raw(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Rebuild a feed item from a ledger row's raw capture (None if not captured)."""
    raw = row.get("raw") or {}
    if not raw or not (raw.get("body") or raw.get("summary") or raw.get("description")):
        return None
    return {"slug": row.get("slug"), "headline": raw.get("headline") or row.get("headline") or "",
            "parts": [{"type": "markdown", "content": raw.get("body") or ""}] if raw.get("body") else [],
            "summary": raw.get("summary"),
            "fields": {"description": raw["description"]} if raw.get("description") else {},
            "tags": raw.get("tags") or [], "contentDate": row.get("content_date"),
            "lastUpdatedDate": row.get("last_updated"), "selfUrl": row.get("api_url")}


def _carry_over(new_row: Dict[str, Any], old_row: Dict[str, Any]) -> Dict[str, Any]:
    """Keep what a re-parse cannot reproduce: resolved ids, cross-checks, record ids."""
    if old_row.get("game_id") and not new_row.get("game_id"):
        new_row["game_id"], new_row["game_id_source"] = old_row["game_id"], old_row.get("game_id_source")
        new_row["game_date"] = new_row.get("game_date") or old_row.get("game_date")
        new_row["season"] = season_from_game_id(new_row["game_id"])
        if old_row.get("game_id_source") == "schedule":
            new_row["flags"] = sorted(set(new_row.get("flags") or []) | {"game_id_resolved_from_schedule"})
    if old_row.get("game_id_lookup_failed"):
        new_row["game_id_lookup_failed"] = old_row["game_id_lookup_failed"]
    same_claim = (old_row.get("outcome") == new_row.get("outcome") and old_row.get("final_call") == new_row.get("final_call")
                  and old_row.get("period") == new_row.get("period") and old_row.get("clock") == new_row.get("clock"))
    if same_claim and old_row.get("crosscheck"):
        new_row["crosscheck"] = old_row["crosscheck"]
    if old_row.get("record_id"):
        new_row["record_id"] = old_row["record_id"]
    if old_row.get("raw") and not new_row.get("raw"):
        new_row["raw"] = old_row["raw"]
    return new_row


def ingest(fetcher: Fetcher, *, ledger_path: str, mode: str = "incremental", max_pages: int = 2,
           page_size: int = DEFAULT_PAGE_SIZE, start_skip: int = 0, crosscheck: bool = True,
           max_crosscheck: int = 150, run_id: str = "", verbose: bool = False,
           resolve_ids: bool = True,
           pages: Optional[Iterable[List[Dict[str, Any]]]] = None,
           pbp_loader=None, human_reads: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Walk the feed, update the ledger, return records for changed rulings.

    ``mode='incremental'`` stops at the first page that contains nothing new
    (slug unseen or ``lastUpdatedDate`` moved); ``mode='full'`` walks
    ``max_pages`` pages from ``start_skip`` and remembers where it stopped so a
    later run can continue; ``mode='reparse'`` touches no feed page and re-runs
    the parser over the raw statements already in the ledger (a parser fix can
    then be applied to the whole corpus offline). ``pages`` / ``pbp_loader`` let
    tests feed fixtures without a network.
    """
    ledger = load_ledger(ledger_path)
    by_slug: Dict[str, Dict[str, Any]] = {r["slug"]: r for r in ledger["rulings"] if r.get("slug")}
    stats = {"pages": 0, "items": 0, "new": 0, "updated": 0, "unchanged": 0, "stories_fetched": 0,
             "game_ids_resolved": 0, "crosschecked": 0, "records": 0, "fetch_errors": 0, "human_reads_applied": 0}
    if human_reads is None:
        human_reads = load_human_reads()
    run_id = run_id or utcnow().replace(":", "").replace("-", "")

    def page_iter():
        if mode == "reparse":
            return
        if pages is not None:
            for p in pages:
                yield p
            return
        skip = start_skip
        for _ in range(max_pages):
            items, res = fetch_feed_page(fetcher, skip, page_size)
            if not res.ok:
                stats["fetch_errors"] += 1
                if verbose:
                    print(f"  feed page skip={skip} failed: {res.error}")
                return
            yield items
            if len(items) < page_size:
                return
            skip += page_size
        ledger["meta"]["next_skip"] = skip

    for items in page_iter():
        stats["pages"] += 1
        page_new = 0
        for item in items:
            stats["items"] += 1
            slug = item.get("slug") or ""
            if not slug:
                continue
            prior = by_slug.get(slug)
            if prior and prior.get("last_updated") == item.get("lastUpdatedDate") and prior.get("parser_version") == __version__:
                stats["unchanged"] += 1
                continue
            if not any((p or {}).get("type") == "markdown" for p in item.get("parts") or []):
                cached = item_from_raw(prior) if (prior and prior.get("last_updated") == item.get("lastUpdatedDate")) else None
                if cached:
                    item = cached          # same version already captured: no fetch needed
                    stats["raw_reused"] = stats.get("raw_reused", 0) + 1
                else:
                    story, res = fetch_story(fetcher, slug)
                    stats["stories_fetched"] += 1
                    if story:
                        item = story
                    elif not res.ok:
                        stats["fetch_errors"] += 1
            ruling = apply_human_read(ruling_from_item(item), human_reads.get(slug))
            row = ruling.to_dict()
            row["parser_version"] = __version__
            row["raw"] = raw_of(item)
            if prior:
                row = _carry_over(row, prior)
                stats["updated"] += 1
            else:
                stats["new"] += 1
                page_new += 1
            by_slug[slug] = row
        if mode == "incremental" and page_new == 0 and stats["pages"] >= 1:
            break

    if mode == "reparse":
        for slug, old_row in list(by_slug.items()):
            item = item_from_raw(old_row)
            if not item:
                stats["reparse_skipped_no_raw"] = stats.get("reparse_skipped_no_raw", 0) + 1
                continue
            ruling = apply_human_read(ruling_from_item(item), human_reads.get(slug))
            new_row = ruling.to_dict()
            new_row["parser_version"] = __version__
            new_row["raw"] = old_row.get("raw")
            by_slug[slug] = _carry_over(new_row, old_row)
            stats["reparsed"] = stats.get("reparsed", 0) + 1

    # apply human reads added since a statement was last parsed (the unchanged
    # short-circuit above skips them), and drop reads that were since removed
    for slug, read in human_reads.items():
        row = by_slug.get(slug)
        if not row:
            continue
        applied = (row.get("human_read") or {})
        if applied.get("read_at") == read.get("read_at") and applied.get("on_ice_call") == read.get("on_ice_call"):
            continue
        ruling = apply_human_read(ruling_from_item_dict(row), read)
        new_row = ruling.to_dict()
        new_row["parser_version"] = __version__
        for keep in ("crosscheck", "game_id_lookup_failed", "record_id"):
            if row.get(keep) is not None:
                new_row[keep] = row[keep]
        if new_row.get("outcome") != row.get("outcome"):
            new_row["crosscheck"] = None  # the claim changed; check it again
        by_slug[slug] = new_row
        stats["human_reads_applied"] += 1
    for slug, row in list(by_slug.items()):
        if row.get("human_read") and slug not in human_reads:
            ruling = ruling_from_item_dict(row)  # read withdrawn: back to the parser's reading
            new_row = ruling.to_dict()
            new_row["parser_version"] = __version__
            for keep in ("crosscheck", "game_id_lookup_failed"):
                if row.get(keep) is not None:
                    new_row[keep] = row[keep]
            by_slug[slug] = new_row

    # resolve game ids for untagged statements (cheap: one scoreboard call per date)
    if resolve_ids:
        for row in by_slug.values():
            if row.get("game_id") or row.get("game_id_lookup_failed") or not (row.get("away") and row.get("home")):
                continue
            gid, gdate, tried = resolve_game_id(fetcher, Ruling.from_dict(row))
            if gid:
                row["game_id"], row["game_id_source"], row["game_date"] = gid, "schedule", gdate
                row["season"] = season_from_game_id(gid)
                row["flags"] = sorted(set(row.get("flags") or []) | {"game_id_resolved_from_schedule"})
                stats["game_ids_resolved"] += 1
            else:
                row["game_id_lookup_failed"] = tried
                row["flags"] = sorted(set(row.get("flags") or []) | {"game_id_unresolved"})

    # cross-check changed rulings against the official play-by-play
    if crosscheck:
        budget = max_crosscheck
        for row in sorted(by_slug.values(), key=lambda r: r.get("content_date") or "", reverse=True):
            if budget <= 0:
                break
            if row.get("outcome") != "overturned" or not row.get("game_id") or row.get("period") is None or not row.get("clock"):
                continue
            prior_xc = row.get("crosscheck") or {}
            if prior_xc.get("status") in ("agree", "conflict") and prior_xc.get("game_state") in ("OFF", "FINAL"):
                continue
            ruling = Ruling.from_dict(row)
            if pbp_loader is not None:
                pbp, res = pbp_loader(ruling.game_id)
            else:
                pbp, res = fetcher.get_json(f"{API_BASE}/gamecenter/{ruling.game_id}/play-by-play")
            budget -= 1
            if not pbp:
                stats["fetch_errors"] += 1
                row["crosscheck"] = {"status": "inconclusive", "checked_at": utcnow(),
                                     "pbp_url": f"{API_BASE}/gamecenter/{ruling.game_id}/play-by-play",
                                     "notes": [f"play-by-play fetch failed: {getattr(res, 'error', None)}"]}
                continue
            row["crosscheck"] = crosscheck_with_pbp(pbp, ruling, fetch=res if isinstance(res, FetchResult) else None)
            stats["crosschecked"] += 1
            if verbose:
                print(f"  xcheck {ruling.game_id} P{ruling.period} {ruling.clock} {ruling.final_call}: {row['crosscheck']['status']}")

    records: List[Dict[str, Any]] = []
    stale: List[Dict[str, str]] = []
    for row in by_slug.values():
        previous_id = row.get("record_id")
        rec = ruling_to_record(Ruling.from_dict(row), run_id=run_id) if row.get("outcome") == "overturned" else None
        if rec:
            row["record_id"] = rec["record_id"]
            records.append(rec)
        else:
            row.pop("record_id", None)
        if previous_id and previous_id != row.get("record_id"):
            # A parser correction re-read this statement and the old record no
            # longer follows from it. Report it so the database can retire it
            # instead of carrying a claim nothing supports any more.
            stale.append({"record_id": previous_id, "slug": row.get("slug"), "public_url": row.get("public_url"),
                          "now": row.get("outcome"), "replacement": row.get("record_id")})
    stats["records"] = len(records)
    stats["stale_records"] = len(stale)
    ledger["rulings"] = list(by_slug.values())
    ledger["meta"].update({"last_run_id": run_id, "last_run_at": utcnow(), "last_mode": mode,
                           "last_stats": stats, "parser_version": __version__})
    save_ledger(ledger, ledger_path)
    return {"stats": stats, "records": records, "stale": stale, "ledger_path": ledger_path,
            "summary": summarize_rulings(ledger["rulings"])}


def retire_stale_records(existing: List[Dict[str, Any]], stale: List[Dict[str, str]], *, now: Optional[str] = None) -> int:
    """Mark records that no longer follow from their statement as ``retired``.
    Human-reviewed records (anything not machine-verified by this module) are
    left alone and only flagged."""
    now = now or utcnow()
    by_id = {r.get("record_id"): r for r in existing}
    n = 0
    for item in stale:
        rec = by_id.get(item["record_id"])
        if not rec or (rec.get("detection") or {}).get("check_id") != CHECK_ID:
            continue
        note = (f"{now}: the Situation Room statement ({item.get('public_url')}) was re-read by parser {__version__} as "
                f"'{item.get('now')}'" + (f"; replaced by {item['replacement']}" if item.get("replacement") else "") + ".")
        flags = set(rec.get("flags") or [])
        if db_mod.is_machine_verified(rec) or rec.get("status") in ("flagged", "pending_review"):
            rec["status"] = "retired"
            flags.add("superseded_by_reclassification")
            rec.setdefault("notes", [])
            if isinstance(rec["notes"], list):
                rec["notes"].append(note)
            n += 1
        else:
            flags.add("statement_reclassified_review_needed")
            rec.setdefault("notes", [])
            if isinstance(rec["notes"], list):
                rec["notes"].append(note + " Human-set status kept; please re-review.")
        rec["flags"] = sorted(flags)
    return n

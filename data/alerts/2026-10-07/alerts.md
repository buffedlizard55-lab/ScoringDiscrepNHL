# Scoring discrepancy alerts (3)

Run `20261007T051546Z-0.4.0`. Every entry below is machine-detected from official NHL artifacts and carries its source links. Nothing here has been adjudicated by a human.

### [IMMEDIATE] EDM at VAN - 2026-10-01 (game None)

- **What changed:** Marco Rossi goal: called a goal on the ice, changed to no-goal by the referee, then reinstated by Situation Room review as a legal shoulder deflection
- **Rule fired:** `MANUAL` Ruling change reported; official per-game artifact not yet linked (high)
- **Initial state:** M. Rossi; assists none (period 3 None, None)
- **Corrected state:** M. Rossi; assists none (period 3 None, None)
- **Goal total affected:** yes (total_changed=True; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** pending_review / confidence medium

**Why it matters for settlement:** A goal that did not exist at one moment exists at the next, inside the same game: the number of goals a live game-total market is watching moved while the game was in progress.

**Flags:** `game_id_not_resolved`, `not_challengeable_league_initiated`, `requires_human_verification`, `secondary_source_only`, `three_state_ruling_sequence`

**Official sources**
- [Official NHL daily scoreboard API (resolves the game id for 2026-10-01)](https://api-web.nhle.com/v1/score/2026-10-01) _(evidence: primary; retrieved: n/a)_
- [Scouting The Refs - quote of the NHL's own explanation](https://scoutingtherefs.com/2026/10/02/nhl-oversight-goal-marco-rossi-canucks-oilers/) _(evidence: secondary; retrieved: 2026-10-07)_
- [NHL Rule 78.4 (goal scored by legal means) / 37.3 (batted puck)](https://nhl.bamcontent.com/images/manual/NHL-Rulebook-2025-26.pdf) _(evidence: reference; retrieved: n/a)_

Record id: `SDN-42c8407955` - open each link and read the goal line before acting on this.

### [IMMEDIATE] CGY at VAN - 2026-10-03 (game None)

- **What changed:** Vancouver goal waived off on the ice, then awarded after Situation Room review; a 1-0 Calgary lead became part of a 4-1 Vancouver win
- **Rule fired:** `MANUAL` Ruling change reported; official per-game artifact not yet linked (high)
- **Initial state:** L. Ohgren; assists none (period 3 01:30, None)
- **Corrected state:** L. Ohgren; assists none (period 3 01:30, None)
- **Goal total affected:** yes (total_changed=True; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** pending_review / confidence medium

**Why it matters for settlement:** A goal that did not exist at one moment exists at the next, inside the same game: the number of goals a live game-total market is watching moved while the game was in progress.

**Flags:** `game_id_not_resolved`, `goal_line_review_admitted_inconclusive_risk`, `period_and_game_total_impact`, `requires_human_verification`, `secondary_source_only`

**Official sources**
- [Official NHL daily scoreboard API (resolves the game id for 2026-10-03)](https://api-web.nhle.com/v1/score/2026-10-03) _(evidence: primary; retrieved: n/a)_
- [Scouting The Refs - report of the review decision and the NHL's words](https://scoutingtherefs.com/2026/10/04/canucks-flames-ohgren-controversy/) _(evidence: secondary; retrieved: 2026-10-07)_
- [NHL Situation Room live blog (the official channel that documents such rulings)](https://www.nhl.com/news/frozen-frenzy-nhl-situation-room-live-blog-october-22-2024) _(evidence: reference; retrieved: n/a)_

Record id: `SDN-3916f9ce9a` - open each link and read the goal line before acting on this.

### [INFO] COL at DAL - 2000-10-04 (game 2000020001)

- **What changed:** COL at DAL 2000-10-04: assists ['C. DRURY'] in nhl_gs_report vs ['C. Drury', 'J. Sakic'] in nhl_api_landing
- **Rule fired:** `C11` Same goal, different assist credits between official artifacts (medium)
- **Initial state:** A. DEADMARSH; assists C. DRURY (period 2 18:31, PP)
- **Corrected state:** A. Deadmarsh; assists C. Drury; J. Sakic (period 2 18:31, PP)
- **Goal total affected:** no (total_changed=False; attribution-only=True)
- **Player props affected:** yes
- **When corrected:** unknown (timing uncertain)
- **Record status:** verified / confidence high

**Why it matters for settlement:** Goal total unaffected: the number of goals is identical in both records; only credit or timing moved. Player-prop exposure: anytime-scorer / points / assist markets turn on who is credited, not on how many goals were scored. NHL box scores are not a sportsbook source of record. This is an exposure flag for review, not a claim that any market was mis-settled.

**Flags:** `pre_2007_no_video_or_clip_to_adjudicate`, `requires_human_verification`, `single_artifact_evidence`, `which_artifact_is_final_unresolved`

**Official sources**
- [Official NHL Game Summary, sheet GS020001.HTM (SCORING SUMMARY, goal 4)](https://www.nhl.com/scores/htmlreports/20002001/GS020001.HTM) _(evidence: primary; retrieved: 2026-10-07)_
- [Official NHL Game Center JSON, summary.scoring goal eventId 10060839](https://api-web.nhle.com/v1/gamecenter/2000020001/landing) _(evidence: primary; retrieved: 2026-10-07)_
- [Game Center page (human view of the final box score)](https://www.nhl.com/gamecenter/col-vs-dal/2000/10/04/2000020001) _(evidence: primary; retrieved: n/a)_

Record id: `SDN-87fb3e543f` - open each link and read the goal line before acting on this.

---

### Limitations of this alert set
- Silent post-game edits are only detectable when we polled the endpoint beforehand.
- Cross-source findings cannot say which artifact is the corrected one, only that the league's two records disagree.
- No public feed of official scoring corrections exists to monitor; see docs/FEASIBILITY.md.
- Rule text (why the league changed something) usually lives only in a Situation Room statement or a beat report, which we do not auto-ingest.

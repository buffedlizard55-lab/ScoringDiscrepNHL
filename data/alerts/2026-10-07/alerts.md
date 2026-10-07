# Scoring discrepancy alerts (6)

Run `20261007T172255Z-0.4.0`. Every entry below is machine-detected from official NHL artifacts and carries its source links. Nothing here has been adjudicated by a human.

### [IMMEDIATE] EDM at VAN - 2026-10-01 (game None)

- **What changed:** Marco Rossi goal: called a goal on the ice, changed to no-goal by the referee, then reinstated by Situation Room review as a legal shoulder deflection
- **Rule fired:** `MANUAL` Ruling change reported; official per-game artifact not yet linked (high)
- **Initial state:** M. Rossi; assists none (period 3 None, None)
- **Corrected state:** M. Rossi; assists none (period 3 None, None)
- **Goal total affected:** yes (total_changed=None; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** pending_review / confidence medium

**Why it matters for settlement:** A goal that did not exist at one moment exists at the next, inside the same game: the number of goals a live game-total market is watching moved while the game was in progress.

**Flags:** `game_id_not_resolved`, `not_challengeable_league_initiated`, `requires_human_verification`, `secondary_source_only`, `three_state_ruling_sequence`, `total_change_reported_by_secondary_source_not_established`

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
- **Goal total affected:** yes (total_changed=None; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** pending_review / confidence medium

**Why it matters for settlement:** A goal that did not exist at one moment exists at the next, inside the same game: the number of goals a live game-total market is watching moved while the game was in progress.

**Flags:** `game_id_not_resolved`, `goal_line_review_admitted_inconclusive_risk`, `period_and_game_total_impact`, `requires_human_verification`, `secondary_source_only`, `total_change_reported_by_secondary_source_not_established`

**Official sources**
- [Official NHL daily scoreboard API (resolves the game id for 2026-10-03)](https://api-web.nhle.com/v1/score/2026-10-03) _(evidence: primary; retrieved: n/a)_
- [Scouting The Refs - report of the review decision and the NHL's words](https://scoutingtherefs.com/2026/10/04/canucks-flames-ohgren-controversy/) _(evidence: secondary; retrieved: 2026-10-07)_
- [NHL Situation Room live blog (the official channel that documents such rulings)](https://www.nhl.com/news/frozen-frenzy-nhl-situation-room-live-blog-october-22-2024) _(evidence: reference; retrieved: n/a)_

Record id: `SDN-3916f9ce9a` - open each link and read the goal line before acting on this.

### [REVIEW] NJD at CHI - 2025-03-26 (game 2024021140)

- **What changed:** goal at 6:50 of P1 credited to Timo Meier, later credited to Dawson Mercer
- **Rule fired:** `PARALLEL` Official scoring-change announcement, cross-checked against the corrected-state artifacts (medium)
- **Initial state:** Timo Meier; assists none (period 1 6:50, PP)
- **Corrected state:** Dawson Mercer; assists Luke Hughes; Nico Hischier (period 1 6:50, PP)
- **Goal total affected:** no (total_changed=False; attribution-only=True)
- **Player props affected:** yes
- **When corrected:** postgame
- **Record status:** verified / confidence high

**Why it matters for settlement:** Only player attribution changed. This cannot move a game total, but it can move goal-scorer / assist player-prop markets.

**Flags:** `assists_before_the_change_not_captured`, `initial_state_corroboration_withdrawn_on_reverification`, `initial_state_reported_by_secondary_source_only`, `ported_from_parallel_line`, `pre_change_assist_credits_unresolved`

**Official sources**
- [Official Game Summary (HTML): GS021140.HTM](https://www.nhl.com/scores/htmlreports/20242025/GS021140.HTM) _(evidence: primary; retrieved: 2026-10-07T00:00:00Z)_
- [NHL GameCenter play-by-play](https://api-web.nhle.com/v1/gamecenter/2024021140/play-by-play) _(evidence: primary; retrieved: 2026-10-07T00:00:00Z)_
- [Athlon Sports (syndicated via Yardbarker)](https://www.yardbarker.com/nhl/articles/nhl_issues_scoring_change_after_blackhawks_devils_game/s1_17615_41963992) _(evidence: secondary; retrieved: 2026-10-07T00:00:00Z)_
- [NHL Public Relations (@NHLPR)](https://x.com/NHLPR/status/1905120424146383077) _(evidence: primary; retrieved: 2026-10-07T00:00:00Z)_
- [NHL GameCenter boxscore](https://api-web.nhle.com/v1/gamecenter/2024021140/boxscore) _(evidence: primary; retrieved: 2026-10-07T00:00:00Z)_

Record id: `SDN-e84fc1c8ec` - open each link and read the goal line before acting on this.

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

### [INFO] NSH at CBJ - 2025-04-01 (game 2024021185)

- **What changed:** assist credits on the goal at 9:02 of P3 resolved to Cole Smith and Michael McCarron
- **Rule fired:** `PARALLEL` Official scoring-change announcement, cross-checked against the corrected-state artifacts (medium)
- **Initial state:** Jordan Oesterle; assists none (period 3 9:02, EV)
- **Corrected state:** Jordan Oesterle; assists Cole Smith; Michael McCarron (period 3 9:02, EV)
- **Goal total affected:** no (total_changed=False; attribution-only=True)
- **Player props affected:** yes
- **When corrected:** postgame
- **Record status:** verified / confidence high

**Why it matters for settlement:** Only player attribution changed. This cannot move a game total, but it can move goal-scorer / assist player-prop markets.

**Flags:** `assists_before_the_change_not_captured`, `declared_change_not_confirmable_from_states:assist_change`, `initial_state_not_retrievable_from_any_source`, `ported_from_parallel_line`, `pre_change_assist_credits_undetermined`

**Official sources**
- [Official Game Summary (HTML): GS021185.HTM](https://www.nhl.com/scores/htmlreports/20242025/GS021185.HTM) _(evidence: primary; retrieved: 2026-10-07T00:00:00Z)_
- [Athlon Sports (syndicated via Yardbarker)](https://www.yardbarker.com/nhl/articles/nhl_issues_scoring_change_after_predators_blue_jackets_game/s1_17615_41992037) _(evidence: secondary; retrieved: 2026-10-07T00:00:00Z)_
- [Same Game Summary, season totals](https://www.nhl.com/scores/htmlreports/20242025/GS021185.HTM) _(evidence: primary; retrieved: 2026-10-07T00:00:00Z)_
- [NHL Public Relations (@NHLPR)](https://x.com/NHLPR/status/1907298847056941350) _(evidence: primary; retrieved: 2026-10-07T00:00:00Z)_
- [NHL GameCenter play-by-play](https://api-web.nhle.com/v1/gamecenter/2024021185/play-by-play) _(evidence: primary; retrieved: 2026-10-07T00:00:00Z)_

Record id: `SDN-35d7818c51` - open each link and read the goal line before acting on this.

### [INFO] BOS at NJD - 2025-04-08 (game 2024021238)

- **What changed:** assist on the goal at 9:38 of P1 changed from Parker Wotherspoon to Morgan Geekie
- **Rule fired:** `PARALLEL` Official scoring-change announcement, cross-checked against the corrected-state artifacts (medium)
- **Initial state:** David Pastrnak; assists Parker Wotherspoon (period 1 9:38, EV)
- **Corrected state:** David Pastrnak; assists Morgan Geekie (period 1 9:38, EV)
- **Goal total affected:** no (total_changed=False; attribution-only=True)
- **Player props affected:** yes
- **When corrected:** postgame
- **Record status:** verified / confidence high

**Why it matters for settlement:** Only player attribution changed. This cannot move a game total, but it can move goal-scorer / assist player-prop markets.

**Flags:** `initial_state_citation_in_reproduction_points_at_a_different_goal`, `initial_state_reported_by_secondary_source_only`, `official_play_by_play_event_not_quoted_this_pass`, `ported_from_parallel_line`

**Official sources**
- [Official Game Summary (HTML): GS021238.HTM](https://www.nhl.com/scores/htmlreports/20242025/GS021238.HTM) _(evidence: primary; retrieved: 2026-10-07T00:00:00Z)_
- [Athlon Sports (syndicated via Yardbarker)](https://www.yardbarker.com/nhl/articles/nhl_issues_scoring_change_after_bruins_devils_game/s1_17615_42025683) _(evidence: secondary; retrieved: 2026-10-07T00:00:00Z)_
- [Same Game Summary, goal 2 of the same game](https://www.nhl.com/scores/htmlreports/20242025/GS021238.HTM) _(evidence: primary; retrieved: 2026-10-07T00:00:00Z)_
- [NHL Public Relations (@NHLPR)](https://x.com/NHLPR/status/1909831272047800540) _(evidence: primary; retrieved: 2026-10-07T00:00:00Z)_
- [NHL GameCenter play-by-play](https://api-web.nhle.com/v1/gamecenter/2024021238/play-by-play) _(evidence: primary; retrieved: 2026-10-07T00:00:00Z)_

Record id: `SDN-2247415389` - open each link and read the goal line before acting on this.

---

### Limitations of this alert set
- Silent post-game edits are only detectable when we polled the endpoint beforehand.
- Cross-source findings cannot say which artifact is the corrected one, only that the league's two records disagree.
- No public feed of official scoring corrections exists to monitor; see docs/FEASIBILITY.md.
- Rule text (why the league changed something) usually lives only in a Situation Room statement or a beat report, which we do not auto-ingest.

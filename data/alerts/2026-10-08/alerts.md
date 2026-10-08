# Scoring discrepancy alerts (9)

Run `20261008T204004Z-0.5.0`. Every entry below is machine-detected from official NHL artifacts and carries its source links. Nothing here has been adjudicated by a human.

### [IMMEDIATE] MIN at NSH - 2026-10-01 (game 2026020012)

- **What changed:** Coach's Challenge (Goaltender Interference): on-ice goal overturned, no goal MIN at 15:05 of period 1
- **Rule fired:** `SR1` Situation Room statement: on-ice call overturned (high)
- **Initial state:** goal, MIN (period 1 15:05)
- **Corrected state:** no_goal, MIN (period 1 15:05)
- **Goal total affected:** yes (total_changed=True; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** verified / confidence high

**Why it matters for settlement:** The number of goals in the game changed between the on-ice announcement and the official ruling, inside the same game. Live game-total, period-total and anytime-scorer markets that reacted to the on-ice call were exposed; the post-game box score already reflects the corrected state, so a settlement made from the final official record is not affected. NHL records are not a sportsbook source of record; this is an exposure flag, not a claim that any market was mis-settled.

**Official sources**
- [NHL Situation Room statement - Coach’s Challenge: MIN @ NSH – 15:05 of the First Period](https://www.nhl.com/news/minnesota-wild-nashville-predators-coach-challenge) _(evidence: primary; retrieved: 2026-10-07T20:43:32Z)_
- [Same statement, league content API record (machine-readable, with tags and timestamps)](https://forge-dapi.d3.nhle.com/v2/content/en-us/stories/minnesota-wild-nashville-predators-coach-challenge) _(evidence: primary; retrieved: 2026-10-07T20:43:32Z)_
- [Official play-by-play (api-web) - final record checked for the goal and the review stoppage](https://api-web.nhle.com/v1/gamecenter/2026020012/play-by-play) _(evidence: primary; retrieved: 2026-10-07T17:26:23Z; sha256 `e05cb598eab5`)_
- [Official Game Summary (GS) report - frozen post-game scoring summary](https://www.nhl.com/scores/htmlreports/20262027/GS020012.HTM) _(evidence: reference; retrieved: n/a)_

Record id: `SDN-61ee9676e1` - open each link and read the goal line before acting on this.

### [IMMEDIATE] EDM at VAN - 2026-10-01 (game 2026020015)

- **What changed:** Video review (Batted Puck): on-ice no-goal overturned, goal awarded to VAN at 04:43 of period 3
- **Rule fired:** `SR1` Situation Room statement: on-ice call overturned (high)
- **Initial state:** no_goal, VAN (period 3 04:43)
- **Corrected state:** goal: M. Rossi; assists A. Bains; L. Schenn (period 3 04:43, score 8-5)
- **Goal total affected:** yes (total_changed=True; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** verified / confidence high

**Why it matters for settlement:** The number of goals in the game changed between the on-ice announcement and the official ruling, inside the same game. Live game-total, period-total and anytime-scorer markets that reacted to the on-ice call were exposed; the post-game box score already reflects the corrected state, so a settlement made from the final official record is not affected. NHL records are not a sportsbook source of record; this is an exposure flag, not a claim that any market was mis-settled.

**Flags:** `game_id_resolved_from_schedule`, `on_ice_call_from_documented_human_read`, `on_ice_call_inferred_from_wording`

**Official sources**
- [NHL Situation Room statement - Video Review: EDM @ VAN – 4:43 of the Third Period](https://www.nhl.com/news/edmonton-oilers-vancouver-canucks-video-review-x7720) _(evidence: primary; retrieved: 2026-10-07T20:43:32Z)_
- [Same statement, league content API record (machine-readable, with tags and timestamps)](https://forge-dapi.d3.nhle.com/v2/content/en-us/stories/edmonton-oilers-vancouver-canucks-video-review-x7720) _(evidence: primary; retrieved: 2026-10-07T20:43:32Z)_
- [Official play-by-play (api-web) - final record checked for the goal and the review stoppage](https://api-web.nhle.com/v1/gamecenter/2026020015/play-by-play) _(evidence: primary; retrieved: 2026-10-07T17:26:23Z; sha256 `79773c33d7b1`)_
- [Scouting The Refs - Video review overturns batted-puck call, awards Rossi goal (independent corroboration of the on-ice no-goal)](https://scoutingtherefs.com/2026/10/53416/video-review-overturns-batted-puck-call-awards-rossi-goal/) _(evidence: secondary; retrieved: 2026-10-07T12:00:00Z)_
- [Official Game Summary (GS) report - frozen post-game scoring summary](https://www.nhl.com/scores/htmlreports/20262027/GS020015.HTM) _(evidence: reference; retrieved: n/a)_

Record id: `SDN-752f5a246e` - open each link and read the goal line before acting on this.

### [IMMEDIATE] NYR at DET - 2026-10-02 (game 2026020017)

- **What changed:** Coach's Challenge (Off-Side): on-ice goal overturned, no goal NYR at 07:08 of period 1
- **Rule fired:** `SR1` Situation Room statement: on-ice call overturned (high)
- **Initial state:** goal, NYR (period 1 07:08)
- **Corrected state:** no_goal, NYR (period 1 07:08)
- **Goal total affected:** yes (total_changed=True; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** verified / confidence high

**Why it matters for settlement:** The number of goals in the game changed between the on-ice announcement and the official ruling, inside the same game. Live game-total, period-total and anytime-scorer markets that reacted to the on-ice call were exposed; the post-game box score already reflects the corrected state, so a settlement made from the final official record is not affected. NHL records are not a sportsbook source of record; this is an exposure flag, not a claim that any market was mis-settled.

**Flags:** `game_id_resolved_from_schedule`

**Official sources**
- [NHL Situation Room statement - Coach’s Challenge: NYR @ DET – 7:08 of the First Period](https://www.nhl.com/news/new-york-rangers-detroit-red-wings-coach-challenge) _(evidence: primary; retrieved: 2026-10-07T20:43:31Z)_
- [Same statement, league content API record (machine-readable, with tags and timestamps)](https://forge-dapi.d3.nhle.com/v2/content/en-us/stories/new-york-rangers-detroit-red-wings-coach-challenge) _(evidence: primary; retrieved: 2026-10-07T20:43:31Z)_
- [Official play-by-play (api-web) - final record checked for the goal and the review stoppage](https://api-web.nhle.com/v1/gamecenter/2026020017/play-by-play) _(evidence: primary; retrieved: 2026-10-07T17:26:22Z; sha256 `345029c72288`)_
- [Official Game Summary (GS) report - frozen post-game scoring summary](https://www.nhl.com/scores/htmlreports/20262027/GS020017.HTM) _(evidence: reference; retrieved: n/a)_

Record id: `SDN-5619ac48fc` - open each link and read the goal line before acting on this.

### [IMMEDIATE] STL at DAL - 2026-10-02 (game 2026020020)

- **What changed:** Coach's Challenge (Off-Side): on-ice goal overturned, no goal STL at 01:06 of period 3
- **Rule fired:** `SR1` Situation Room statement: on-ice call overturned (high)
- **Initial state:** goal, STL (period 3 01:06)
- **Corrected state:** no_goal, STL (period 3 01:06)
- **Goal total affected:** yes (total_changed=True; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** verified / confidence high

**Why it matters for settlement:** The number of goals in the game changed between the on-ice announcement and the official ruling, inside the same game. Live game-total, period-total and anytime-scorer markets that reacted to the on-ice call were exposed; the post-game box score already reflects the corrected state, so a settlement made from the final official record is not affected. NHL records are not a sportsbook source of record; this is an exposure flag, not a claim that any market was mis-settled.

**Official sources**
- [NHL Situation Room statement - Coach’s Challenge: STL @ DAL – 1:06 of the Third Period](https://www.nhl.com/news/st-louis-blues-dallas-stars-coach-challenge) _(evidence: primary; retrieved: 2026-10-07T20:43:31Z)_
- [Same statement, league content API record (machine-readable, with tags and timestamps)](https://forge-dapi.d3.nhle.com/v2/content/en-us/stories/st-louis-blues-dallas-stars-coach-challenge) _(evidence: primary; retrieved: 2026-10-07T20:43:31Z)_
- [Official play-by-play (api-web) - final record checked for the goal and the review stoppage](https://api-web.nhle.com/v1/gamecenter/2026020020/play-by-play) _(evidence: primary; retrieved: 2026-10-07T17:26:22Z; sha256 `3f33fbfab231`)_
- [Official Game Summary (GS) report - frozen post-game scoring summary](https://www.nhl.com/scores/htmlreports/20262027/GS020020.HTM) _(evidence: reference; retrieved: n/a)_

Record id: `SDN-5c05cee8b5` - open each link and read the goal line before acting on this.

### [IMMEDIATE] MTL at PIT - 2026-10-03 (game 2026020026)

- **What changed:** Coach's Challenge (Off-Side): on-ice goal overturned, no goal PIT at 05:25 of period 3
- **Rule fired:** `SR1` Situation Room statement: on-ice call overturned (high)
- **Initial state:** goal, PIT (period 3 05:25)
- **Corrected state:** no_goal, PIT (period 3 05:25)
- **Goal total affected:** yes (total_changed=True; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** verified / confidence high

**Why it matters for settlement:** The number of goals in the game changed between the on-ice announcement and the official ruling, inside the same game. Live game-total, period-total and anytime-scorer markets that reacted to the on-ice call were exposed; the post-game box score already reflects the corrected state, so a settlement made from the final official record is not affected. NHL records are not a sportsbook source of record; this is an exposure flag, not a claim that any market was mis-settled.

**Official sources**
- [NHL Situation Room statement - Coach’s Challenge: MTL @ PIT – 5:25 of the Third Period](https://www.nhl.com/news/montreal-canadiens-pittsburgh-penguins-coach-challenge-x9847) _(evidence: primary; retrieved: 2026-10-07T20:43:30Z)_
- [Same statement, league content API record (machine-readable, with tags and timestamps)](https://forge-dapi.d3.nhle.com/v2/content/en-us/stories/montreal-canadiens-pittsburgh-penguins-coach-challenge-x9847) _(evidence: primary; retrieved: 2026-10-07T20:43:30Z)_
- [Official play-by-play (api-web) - final record checked for the goal and the review stoppage](https://api-web.nhle.com/v1/gamecenter/2026020026/play-by-play) _(evidence: primary; retrieved: 2026-10-07T17:26:22Z; sha256 `0f222c12d30e`)_
- [Official Game Summary (GS) report - frozen post-game scoring summary](https://www.nhl.com/scores/htmlreports/20262027/GS020026.HTM) _(evidence: reference; retrieved: n/a)_

Record id: `SDN-73e0895bf7` - open each link and read the goal line before acting on this.

### [IMMEDIATE] CGY at VAN - 2026-10-03 (game 2026020033)

- **What changed:** Video review (Puck Over Goal Line): on-ice no-goal overturned, goal awarded to VAN at 01:28 of period 3
- **Rule fired:** `SR1` Situation Room statement: on-ice call overturned (high)
- **Initial state:** no_goal, VAN (period 3 01:28)
- **Corrected state:** goal: L. Ohgren; assists P. Cotter; T. Willander (period 3 01:28, score 1-1)
- **Goal total affected:** yes (total_changed=True; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** verified / confidence high

**Why it matters for settlement:** The number of goals in the game changed between the on-ice announcement and the official ruling, inside the same game. Live game-total, period-total and anytime-scorer markets that reacted to the on-ice call were exposed; the post-game box score already reflects the corrected state, so a settlement made from the final official record is not affected. NHL records are not a sportsbook source of record; this is an exposure flag, not a claim that any market was mis-settled.

**Flags:** `on_ice_call_from_documented_human_read`, `on_ice_call_not_stated`

**Official sources**
- [NHL Situation Room statement - Video Review: CGY @ VAN – 1:28 of the Third Period](https://www.nhl.com/news/calgary-flames-vancouver-canucks-video-review) _(evidence: primary; retrieved: 2026-10-07T20:43:30Z)_
- [Same statement, league content API record (machine-readable, with tags and timestamps)](https://forge-dapi.d3.nhle.com/v2/content/en-us/stories/calgary-flames-vancouver-canucks-video-review) _(evidence: primary; retrieved: 2026-10-07T20:43:30Z)_
- [Official play-by-play (api-web) - final record checked for the goal and the review stoppage](https://api-web.nhle.com/v1/gamecenter/2026020033/play-by-play) _(evidence: primary; retrieved: 2026-10-07T21:03:41Z; sha256 `a887ad8340bd`)_
- [NHL.com official game recap, CGY @ VAN, 2026-10-03 (states the on-ice call)](https://www.nhl.com/news/calgary-flames-vancouver-canucks-game-recap-october-3-2026) _(evidence: secondary; retrieved: 2026-10-07T17:12:00Z)_
- [Official Game Summary (GS) report - frozen post-game scoring summary](https://www.nhl.com/scores/htmlreports/20262027/GS020033.HTM) _(evidence: reference; retrieved: n/a)_

Record id: `SDN-d967bb12d3` - open each link and read the goal line before acting on this.

### [IMMEDIATE] WPG at PIT - 2026-10-05 (game 2026020042)

- **What changed:** Video review (High-Sticking the Puck): on-ice no-goal overturned, goal awarded to PIT at 09:27 of period 2
- **Rule fired:** `SR1` Situation Room statement: on-ice call overturned (high)
- **Initial state:** no_goal, PIT (period 2 09:27)
- **Corrected state:** goal: B. Kindel; assists D. Carlile; E. Karlsson (period 2 09:27, score 0-1)
- **Goal total affected:** yes (total_changed=True; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** verified / confidence high

**Why it matters for settlement:** The number of goals in the game changed between the on-ice announcement and the official ruling, inside the same game. Live game-total, period-total and anytime-scorer markets that reacted to the on-ice call were exposed; the post-game box score already reflects the corrected state, so a settlement made from the final official record is not affected. NHL records are not a sportsbook source of record; this is an exposure flag, not a claim that any market was mis-settled.

**Flags:** `game_id_resolved_from_schedule`

**Official sources**
- [NHL Situation Room statement - Video Review: WPG @ PIT – 9:27 of the Second Period](https://www.nhl.com/news/winnipeg-jets-pittsburgh-penguins-video-review) _(evidence: primary; retrieved: 2026-10-07T20:43:30Z)_
- [Same statement, league content API record (machine-readable, with tags and timestamps)](https://forge-dapi.d3.nhle.com/v2/content/en-us/stories/winnipeg-jets-pittsburgh-penguins-video-review) _(evidence: primary; retrieved: 2026-10-07T20:43:30Z)_
- [Official play-by-play (api-web) - final record checked for the goal and the review stoppage](https://api-web.nhle.com/v1/gamecenter/2026020042/play-by-play) _(evidence: primary; retrieved: 2026-10-07T17:26:22Z; sha256 `850ff0fd0b75`)_
- [Official Game Summary (GS) report - frozen post-game scoring summary](https://www.nhl.com/scores/htmlreports/20262027/GS020042.HTM) _(evidence: reference; retrieved: n/a)_

Record id: `SDN-26e9b24b21` - open each link and read the goal line before acting on this.

### [IMMEDIATE] STL at CHI - 2026-10-06 (game 2026020050)

- **What changed:** Coach's Challenge (Off-Side): on-ice goal overturned, no goal STL at 01:05 of period 2
- **Rule fired:** `SR1` Situation Room statement: on-ice call overturned (high)
- **Initial state:** goal, STL (period 2 01:05)
- **Corrected state:** no_goal, STL (period 2 01:05)
- **Goal total affected:** yes (total_changed=True; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** verified / confidence high

**Why it matters for settlement:** The number of goals in the game changed between the on-ice announcement and the official ruling, inside the same game. Live game-total, period-total and anytime-scorer markets that reacted to the on-ice call were exposed; the post-game box score already reflects the corrected state, so a settlement made from the final official record is not affected. NHL records are not a sportsbook source of record; this is an exposure flag, not a claim that any market was mis-settled.

**Official sources**
- [NHL Situation Room statement - Coach’s Challenge: STL @ CHI – 1:05 of the Second Period](https://www.nhl.com/news/st-louis-blues-chicago-blackhawks-coach-challenge) _(evidence: primary; retrieved: 2026-10-07T20:43:29Z)_
- [Same statement, league content API record (machine-readable, with tags and timestamps)](https://forge-dapi.d3.nhle.com/v2/content/en-us/stories/st-louis-blues-chicago-blackhawks-coach-challenge) _(evidence: primary; retrieved: 2026-10-07T20:43:29Z)_
- [Official play-by-play (api-web) - final record checked for the goal and the review stoppage](https://api-web.nhle.com/v1/gamecenter/2026020050/play-by-play) _(evidence: primary; retrieved: 2026-10-07T17:26:21Z; sha256 `b14dc662921b`)_
- [Official Game Summary (GS) report - frozen post-game scoring summary](https://www.nhl.com/scores/htmlreports/20262027/GS020050.HTM) _(evidence: reference; retrieved: n/a)_

Record id: `SDN-21ad557cd4` - open each link and read the goal line before acting on this.

### [IMMEDIATE] NSH at TOR - 2026-10-06 (game 2026020044)

- **What changed:** Coach's Challenge (Off-Side): on-ice goal overturned, no goal TOR at 11:49 of period 3
- **Rule fired:** `SR1` Situation Room statement: on-ice call overturned (high)
- **Initial state:** goal, TOR (period 3 11:49)
- **Corrected state:** no_goal, TOR (period 3 11:49)
- **Goal total affected:** yes (total_changed=True; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** verified / confidence high

**Why it matters for settlement:** The number of goals in the game changed between the on-ice announcement and the official ruling, inside the same game. Live game-total, period-total and anytime-scorer markets that reacted to the on-ice call were exposed; the post-game box score already reflects the corrected state, so a settlement made from the final official record is not affected. NHL records are not a sportsbook source of record; this is an exposure flag, not a claim that any market was mis-settled.

**Official sources**
- [NHL Situation Room statement - Coach’s Challenge: NSH @ TOR – 11:49 of the Third Period](https://www.nhl.com/news/nashville-predators-toronto-maple-leafs-coach-challenge) _(evidence: primary; retrieved: 2026-10-07T20:43:29Z)_
- [Same statement, league content API record (machine-readable, with tags and timestamps)](https://forge-dapi.d3.nhle.com/v2/content/en-us/stories/nashville-predators-toronto-maple-leafs-coach-challenge) _(evidence: primary; retrieved: 2026-10-07T20:43:29Z)_
- [Official play-by-play (api-web) - final record checked for the goal and the review stoppage](https://api-web.nhle.com/v1/gamecenter/2026020044/play-by-play) _(evidence: primary; retrieved: 2026-10-07T17:26:21Z; sha256 `e031c35348f3`)_
- [Official Game Summary (GS) report - frozen post-game scoring summary](https://www.nhl.com/scores/htmlreports/20262027/GS020044.HTM) _(evidence: reference; retrieved: n/a)_

Record id: `SDN-261948dfcd` - open each link and read the goal line before acting on this.

---

### Limitations of this alert set
- Silent post-game edits are only detectable when we polled the endpoint beforehand.
- Cross-source findings cannot say which artifact is the corrected one, only that the league's two records disagree.
- No public feed of official scoring corrections exists to monitor; see docs/FEASIBILITY.md.
- Rule text (why the league changed something) usually lives only in a Situation Room statement or a beat report, which we do not auto-ingest.

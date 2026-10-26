# Scoring discrepancy alerts (8)

Run `20261026T013650Z-0.5.0`. Every entry below is machine-detected from official NHL artifacts and carries its source links. Nothing here has been adjudicated by a human.

### [IMMEDIATE] OTT at NJD - 2026-10-12 (game 2026020088)

- **What changed:** Coach's Challenge (Goaltender Interference): on-ice goal overturned, no goal NJD at 11:58 of period 3
- **Rule fired:** `SR1` Situation Room statement: on-ice call overturned (high)
- **Initial state:** goal, NJD (period 3 11:58)
- **Corrected state:** no_goal, NJD (period 3 11:58)
- **Goal total affected:** yes (total_changed=True; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** verified / confidence high

**Why it matters for settlement:** The number of goals in the game changed between the on-ice announcement and the official ruling, inside the same game. Live game-total, period-total and anytime-scorer markets that reacted to the on-ice call were exposed; the post-game box score already reflects the corrected state, so a settlement made from the final official record is not affected. NHL records are not a sportsbook source of record; this is an exposure flag, not a claim that any market was mis-settled.

**Official sources**
- [NHL Situation Room statement - Coach’s Challenge OTT @ NJD – 11:58 of the Third Period](https://www.nhl.com/news/ottawa-senators-new-jersey-devils-coach-challenge-x4281) _(evidence: primary; retrieved: 2026-10-13T01:58:26Z)_
- [Same statement, league content API record (machine-readable, with tags and timestamps)](https://forge-dapi.d3.nhle.com/v2/content/en-us/stories/ottawa-senators-new-jersey-devils-coach-challenge-x4281) _(evidence: primary; retrieved: 2026-10-13T01:58:26Z)_
- [Official play-by-play (api-web) - final record checked for the goal and the review stoppage](https://api-web.nhle.com/v1/gamecenter/2026020088/play-by-play) _(evidence: primary; retrieved: 2026-10-13T01:58:27Z; sha256 `7165b261e459`)_
- [Official Game Summary (GS) report - frozen post-game scoring summary](https://www.nhl.com/scores/htmlreports/20262027/GS020088.HTM) _(evidence: reference; retrieved: n/a)_

Record id: `SDN-321e69e3c7` - open each link and read the goal line before acting on this.

### [IMMEDIATE] DAL at COL - 2026-10-14 (game 2026020107)

- **What changed:** Video review (Distinct Kicking Motion): on-ice goal overturned, no goal COL at 09:29 of period 1
- **Rule fired:** `SR1` Situation Room statement: on-ice call overturned (high)
- **Initial state:** goal, COL (period 1 09:29)
- **Corrected state:** no_goal, COL (period 1 09:29)
- **Goal total affected:** yes (total_changed=True; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** verified / confidence high

**Why it matters for settlement:** The number of goals in the game changed between the on-ice announcement and the official ruling, inside the same game. Live game-total, period-total and anytime-scorer markets that reacted to the on-ice call were exposed; the post-game box score already reflects the corrected state, so a settlement made from the final official record is not affected. NHL records are not a sportsbook source of record; this is an exposure flag, not a claim that any market was mis-settled.

**Official sources**
- [NHL Situation Room statement - Video Review: DAL @ COL – 9:29 of the First Period](https://www.nhl.com/news/dallas-stars-colorado-avalanche-video-review) _(evidence: primary; retrieved: 2026-10-15T01:45:59Z)_
- [Same statement, league content API record (machine-readable, with tags and timestamps)](https://forge-dapi.d3.nhle.com/v2/content/en-us/stories/dallas-stars-colorado-avalanche-video-review) _(evidence: primary; retrieved: 2026-10-15T01:45:59Z)_
- [Official play-by-play (api-web) - final record checked for the goal and the review stoppage](https://api-web.nhle.com/v1/gamecenter/2026020107/play-by-play) _(evidence: primary; retrieved: 2026-10-15T07:19:23Z; sha256 `ebe883735fac`)_
- [Official Game Summary (GS) report - frozen post-game scoring summary](https://www.nhl.com/scores/htmlreports/20262027/GS020107.HTM) _(evidence: reference; retrieved: n/a)_

Record id: `SDN-363733aecb` - open each link and read the goal line before acting on this.

### [IMMEDIATE] DAL at COL - 2026-10-14 (game 2026020107)

- **What changed:** Coach's Challenge (Off-Side): on-ice goal overturned, no goal COL at 01:59 of period 1
- **Rule fired:** `SR1` Situation Room statement: on-ice call overturned (high)
- **Initial state:** goal, COL (period 1 01:59)
- **Corrected state:** no_goal, COL (period 1 01:59)
- **Goal total affected:** yes (total_changed=True; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** verified / confidence high

**Why it matters for settlement:** The number of goals in the game changed between the on-ice announcement and the official ruling, inside the same game. Live game-total, period-total and anytime-scorer markets that reacted to the on-ice call were exposed; the post-game box score already reflects the corrected state, so a settlement made from the final official record is not affected. NHL records are not a sportsbook source of record; this is an exposure flag, not a claim that any market was mis-settled.

**Official sources**
- [NHL Situation Room statement - Coach’s Challenge: DAL @ COL – 1:59 of the First Period](https://www.nhl.com/news/dallas-stars-colorado-avalanche-coach-challenge-x7698) _(evidence: primary; retrieved: 2026-10-15T01:45:59Z)_
- [Same statement, league content API record (machine-readable, with tags and timestamps)](https://forge-dapi.d3.nhle.com/v2/content/en-us/stories/dallas-stars-colorado-avalanche-coach-challenge-x7698) _(evidence: primary; retrieved: 2026-10-15T01:45:59Z)_
- [Official play-by-play (api-web) - final record checked for the goal and the review stoppage](https://api-web.nhle.com/v1/gamecenter/2026020107/play-by-play) _(evidence: primary; retrieved: 2026-10-15T07:19:23Z; sha256 `ebe883735fac`)_
- [Official Game Summary (GS) report - frozen post-game scoring summary](https://www.nhl.com/scores/htmlreports/20262027/GS020107.HTM) _(evidence: reference; retrieved: n/a)_

Record id: `SDN-c78eda74a3` - open each link and read the goal line before acting on this.

### [IMMEDIATE] NYI at OTT - 2026-10-15 (game 2026020109)

- **What changed:** Video review (Puck Over Goal Line): on-ice goal overturned, no goal OTT at 04:50 of period 1
- **Rule fired:** `SR1` Situation Room statement: on-ice call overturned (high)
- **Initial state:** goal, OTT (period 1 04:50)
- **Corrected state:** no_goal, OTT (period 1 04:50)
- **Goal total affected:** yes (total_changed=True; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** verified / confidence high

**Why it matters for settlement:** The number of goals in the game changed between the on-ice announcement and the official ruling, inside the same game. Live game-total, period-total and anytime-scorer markets that reacted to the on-ice call were exposed; the post-game box score already reflects the corrected state, so a settlement made from the final official record is not affected. NHL records are not a sportsbook source of record; this is an exposure flag, not a claim that any market was mis-settled.

**Flags:** `game_id_resolved_from_schedule`

**Official sources**
- [NHL Situation Room statement - Video Review: NYI @ OTT – 4:50 of the First Period](https://www.nhl.com/news/new-york-islanders-ottawa-senators-video-review) _(evidence: primary; retrieved: 2026-10-15T23:48:09Z)_
- [Same statement, league content API record (machine-readable, with tags and timestamps)](https://forge-dapi.d3.nhle.com/v2/content/en-us/stories/new-york-islanders-ottawa-senators-video-review) _(evidence: primary; retrieved: 2026-10-15T23:48:09Z)_
- [Official play-by-play (api-web) - final record checked for the goal and the review stoppage](https://api-web.nhle.com/v1/gamecenter/2026020109/play-by-play) _(evidence: primary; retrieved: 2026-10-18T01:28:46Z; sha256 `990cb07b2aa5`)_
- [Official Game Summary (GS) report - frozen post-game scoring summary](https://www.nhl.com/scores/htmlreports/20262027/GS020109.HTM) _(evidence: reference; retrieved: n/a)_

Record id: `SDN-a1883562a4` - open each link and read the goal line before acting on this.

### [IMMEDIATE] NYI at OTT - 2026-10-15 (game 2026020109)

- **What changed:** Coach's Challenge (Off-Side): on-ice goal overturned, no goal OTT at 11:50 of period 1
- **Rule fired:** `SR1` Situation Room statement: on-ice call overturned (high)
- **Initial state:** goal, OTT (period 1 11:50)
- **Corrected state:** no_goal, OTT (period 1 11:50)
- **Goal total affected:** yes (total_changed=True; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** verified / confidence high

**Why it matters for settlement:** The number of goals in the game changed between the on-ice announcement and the official ruling, inside the same game. Live game-total, period-total and anytime-scorer markets that reacted to the on-ice call were exposed; the post-game box score already reflects the corrected state, so a settlement made from the final official record is not affected. NHL records are not a sportsbook source of record; this is an exposure flag, not a claim that any market was mis-settled.

**Flags:** `game_id_resolved_from_schedule`

**Official sources**
- [NHL Situation Room statement - Coach’s Challenge: NYI @ OTT – 11:50 of the First Period](https://www.nhl.com/news/new-york-islanders-ottawa-senators-coach-challenge) _(evidence: primary; retrieved: 2026-10-15T23:48:09Z)_
- [Same statement, league content API record (machine-readable, with tags and timestamps)](https://forge-dapi.d3.nhle.com/v2/content/en-us/stories/new-york-islanders-ottawa-senators-coach-challenge) _(evidence: primary; retrieved: 2026-10-15T23:48:09Z)_
- [Official play-by-play (api-web) - final record checked for the goal and the review stoppage](https://api-web.nhle.com/v1/gamecenter/2026020109/play-by-play) _(evidence: primary; retrieved: 2026-10-16T04:20:49Z; sha256 `dfce7201bb2f`)_
- [Official Game Summary (GS) report - frozen post-game scoring summary](https://www.nhl.com/scores/htmlreports/20262027/GS020109.HTM) _(evidence: reference; retrieved: n/a)_

Record id: `SDN-cf3ee133a4` - open each link and read the goal line before acting on this.

### [IMMEDIATE] DAL at CHI - 2026-10-17 (game 2026020130)

- **What changed:** Coach's Challenge (Off-Side): on-ice goal overturned, no goal DAL at 12:10 of period 1
- **Rule fired:** `SR1` Situation Room statement: on-ice call overturned (high)
- **Initial state:** goal, DAL (period 1 12:10)
- **Corrected state:** no_goal, DAL (period 1 12:10)
- **Goal total affected:** yes (total_changed=True; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** verified / confidence high

**Why it matters for settlement:** The number of goals in the game changed between the on-ice announcement and the official ruling, inside the same game. Live game-total, period-total and anytime-scorer markets that reacted to the on-ice call were exposed; the post-game box score already reflects the corrected state, so a settlement made from the final official record is not affected. NHL records are not a sportsbook source of record; this is an exposure flag, not a claim that any market was mis-settled.

**Official sources**
- [NHL Situation Room statement - Coach’s Challenge: DAL @ CHI – 12:10 of the First Period](https://www.nhl.com/news/dallas-stars-chicago-blackhawks-coach-challenge) _(evidence: primary; retrieved: 2026-10-18T01:28:45Z)_
- [Same statement, league content API record (machine-readable, with tags and timestamps)](https://forge-dapi.d3.nhle.com/v2/content/en-us/stories/dallas-stars-chicago-blackhawks-coach-challenge) _(evidence: primary; retrieved: 2026-10-18T01:28:45Z)_
- [Official play-by-play (api-web) - final record checked for the goal and the review stoppage](https://api-web.nhle.com/v1/gamecenter/2026020130/play-by-play) _(evidence: primary; retrieved: 2026-10-18T06:32:15Z; sha256 `187b4f66d552`)_
- [Official Game Summary (GS) report - frozen post-game scoring summary](https://www.nhl.com/scores/htmlreports/20262027/GS020130.HTM) _(evidence: reference; retrieved: n/a)_

Record id: `SDN-935f2c114b` - open each link and read the goal line before acting on this.

### [IMMEDIATE] UTA at SEA - 2026-10-22 (game 2026020164)

- **What changed:** Coach's Challenge (Off-Side): on-ice goal overturned, no goal UTA at 01:47 of period 3
- **Rule fired:** `SR1` Situation Room statement: on-ice call overturned (high)
- **Initial state:** goal, UTA (period 3 01:47)
- **Corrected state:** no_goal, UTA (period 3 01:47)
- **Goal total affected:** yes (total_changed=True; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** verified / confidence high

**Why it matters for settlement:** The number of goals in the game changed between the on-ice announcement and the official ruling, inside the same game. Live game-total, period-total and anytime-scorer markets that reacted to the on-ice call were exposed; the post-game box score already reflects the corrected state, so a settlement made from the final official record is not affected. NHL records are not a sportsbook source of record; this is an exposure flag, not a claim that any market was mis-settled.

**Flags:** `game_id_resolved_from_schedule`

**Official sources**
- [NHL Situation Room statement - Coach’s Challenge: UTA @ SEA – 1:47 of the Third Period](https://www.nhl.com/news/utah-mammoth-seattle-kraken-coach-challenge) _(evidence: primary; retrieved: 2026-10-23T06:06:55Z)_
- [Same statement, league content API record (machine-readable, with tags and timestamps)](https://forge-dapi.d3.nhle.com/v2/content/en-us/stories/utah-mammoth-seattle-kraken-coach-challenge) _(evidence: primary; retrieved: 2026-10-23T06:06:55Z)_
- [Official play-by-play (api-web) - final record checked for the goal and the review stoppage](https://api-web.nhle.com/v1/gamecenter/2026020164/play-by-play) _(evidence: primary; retrieved: 2026-10-23T06:06:57Z; sha256 `27d2349b3939`)_
- [Official Game Summary (GS) report - frozen post-game scoring summary](https://www.nhl.com/scores/htmlreports/20262027/GS020164.HTM) _(evidence: reference; retrieved: n/a)_

Record id: `SDN-976324808d` - open each link and read the goal line before acting on this.

### [IMMEDIATE] UTA at SEA - 2026-10-22 (game 2026020164)

- **What changed:** Coach's Challenge (Off-Side): on-ice goal overturned, no goal SEA at 08:43 of period 3
- **Rule fired:** `SR1` Situation Room statement: on-ice call overturned (high)
- **Initial state:** goal, SEA (period 3 08:43)
- **Corrected state:** no_goal, SEA (period 3 08:43)
- **Goal total affected:** yes (total_changed=True; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** verified / confidence high

**Why it matters for settlement:** The number of goals in the game changed between the on-ice announcement and the official ruling, inside the same game. Live game-total, period-total and anytime-scorer markets that reacted to the on-ice call were exposed; the post-game box score already reflects the corrected state, so a settlement made from the final official record is not affected. NHL records are not a sportsbook source of record; this is an exposure flag, not a claim that any market was mis-settled.

**Flags:** `game_id_resolved_from_schedule`

**Official sources**
- [NHL Situation Room statement - Coach’s Challenge: UTA @ SEA – 8:43 of the Third Period](https://www.nhl.com/news/utah-mammoth-seattle-kraken-coach-challenge-october-22-2026) _(evidence: primary; retrieved: 2026-10-23T06:06:55Z)_
- [Same statement, league content API record (machine-readable, with tags and timestamps)](https://forge-dapi.d3.nhle.com/v2/content/en-us/stories/utah-mammoth-seattle-kraken-coach-challenge-october-22-2026) _(evidence: primary; retrieved: 2026-10-23T06:06:55Z)_
- [Official play-by-play (api-web) - final record checked for the goal and the review stoppage](https://api-web.nhle.com/v1/gamecenter/2026020164/play-by-play) _(evidence: primary; retrieved: 2026-10-23T06:06:57Z; sha256 `27d2349b3939`)_
- [Official Game Summary (GS) report - frozen post-game scoring summary](https://www.nhl.com/scores/htmlreports/20262027/GS020164.HTM) _(evidence: reference; retrieved: n/a)_

Record id: `SDN-cd6957d8f0` - open each link and read the goal line before acting on this.

---

### Limitations of this alert set
- Silent post-game edits are only detectable when we polled the endpoint beforehand.
- Cross-source findings cannot say which artifact is the corrected one, only that the league's two records disagree.
- No public feed of official scoring corrections exists to monitor; see docs/FEASIBILITY.md.
- Rule text (why the league changed something) usually lives only in a Situation Room statement or a beat report, which we do not auto-ingest.

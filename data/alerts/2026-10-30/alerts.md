# Scoring discrepancy alerts (4)

Run `20261030T001531Z-0.5.0`. Every entry below is machine-detected from official NHL artifacts and carries its source links. Nothing here has been adjudicated by a human.

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

### [IMMEDIATE] LAK at NYR - 2026-10-26 (game 2026020185)

- **What changed:** Coach's Challenge (Goaltender Interference): on-ice goal overturned, no goal LAK at 07:26 of period 2
- **Rule fired:** `SR1` Situation Room statement: on-ice call overturned (high)
- **Initial state:** goal, LAK (period 2 07:26)
- **Corrected state:** no_goal, LAK (period 2 07:26)
- **Goal total affected:** yes (total_changed=True; attribution-only=False)
- **Player props affected:** yes
- **When corrected:** in_game
- **Record status:** verified / confidence high

**Why it matters for settlement:** The number of goals in the game changed between the on-ice announcement and the official ruling, inside the same game. Live game-total, period-total and anytime-scorer markets that reacted to the on-ice call were exposed; the post-game box score already reflects the corrected state, so a settlement made from the final official record is not affected. NHL records are not a sportsbook source of record; this is an exposure flag, not a claim that any market was mis-settled.

**Flags:** `game_id_resolved_from_schedule`

**Official sources**
- [NHL Situation Room statement - Coach’s Challenge: LAK @ NYR – 7:26 of the Second Period](https://www.nhl.com/news/los-angeles-kings-new-york-rangers-coach-challenge-october-26-2026) _(evidence: primary; retrieved: 2026-10-27T04:52:08Z)_
- [Same statement, league content API record (machine-readable, with tags and timestamps)](https://forge-dapi.d3.nhle.com/v2/content/en-us/stories/los-angeles-kings-new-york-rangers-coach-challenge-october-26-2026) _(evidence: primary; retrieved: 2026-10-27T04:52:08Z)_
- [Official play-by-play (api-web) - final record checked for the goal and the review stoppage](https://api-web.nhle.com/v1/gamecenter/2026020185/play-by-play) _(evidence: primary; retrieved: 2026-10-27T04:52:09Z; sha256 `8a1b63407c19`)_
- [Official Game Summary (GS) report - frozen post-game scoring summary](https://www.nhl.com/scores/htmlreports/20262027/GS020185.HTM) _(evidence: reference; retrieved: n/a)_

Record id: `SDN-7337c7bd87` - open each link and read the goal line before acting on this.

---

### Limitations of this alert set
- Silent post-game edits are only detectable when we polled the endpoint beforehand.
- Cross-source findings cannot say which artifact is the corrected one, only that the league's two records disagree.
- No public feed of official scoring corrections exists to monitor; see docs/FEASIBILITY.md.
- Rule text (why the league changed something) usually lives only in a Situation Room statement or a beat report, which we do not auto-ingest.

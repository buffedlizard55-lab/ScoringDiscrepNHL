# Re-verification pass — 2026-10-07

Re-fetched the official artifacts behind the three verified records, plus one game
cited by a third-party lead, to check that what the database claims is still what
the league publishes.

## How these were retrieved, and what that means

- The Arena build sandbox has **no direct HTTP route to NHL hosts**. Measured again
  this session: `https://api-web.nhle.com/...` and
  `https://www.nhl.com/scores/htmlreports/...` both fail from the sandbox with
  `URLError: <urlopen error TLS/SSL connection has been closed (EOF)>`, while
  `https://api.github.com/rate_limit` returns 200.
- These artifacts were therefore retrieved through the **platform's page-fetch tool**
  (a text proxy), not raw sockets. What is stored below is the text that tool
  returned, transcribed verbatim. It is **not** a byte-for-byte capture of the HTTP
  response, and no response headers are available, so `http_status` is recorded as
  `200 (inferred: content returned)` rather than asserted.
- The retrieval clock is the session date, 2026-10-07. The exact wall-clock second is
  not recorded by the proxy and is therefore not claimed.
- This is a weaker evidence class than a runner-side capture. It is recorded as such,
  and `data/reference/probe_report.json` still describes the sandbox limitation.

## What was confirmed

| Artifact | Claim in the database | Result today |
| --- | --- | --- |
| `GS021140.HTM` scoring row 2 | `2 \| 1 \| 6:50 \| PP \| NJD \| 91 D.MERCER(16) \| 43 L.HUGHES(31) \| 13 N.HISCHIER(28)` | **confirmed, character for character** |
| `GS021140.HTM` footer | `2025-03-27 8.23.23` | **confirmed** (`© Copyright 2025, National Hockey League  2025-03-27 8.23.23`) |
| `GS021140.HTM` start/end | `Start 6:37 CDT; End 9:02 CDT` | **confirmed** |
| GameCenter 2024021140 event 146 | scorer 8482110 (Mercer, goal 16), assists 8482684 (Hughes, 31) and 8480002 (Hischier, 28) | **confirmed** |
| `GS021185.HTM` scoring row 12 | `12 \| 3 \| 9:02 \| EV \| NSH \| 82 J.OESTERLE(2) \| 36 C.SMITH(8) \| 47 M.MCCARRON(9)` | **confirmed, character for character** |
| `GS021185.HTM` start/end | `Start 7:09 EDT; End 9:43 EDT` | **confirmed** |
| GameCenter 2024021238 event 324 | assist on the 9:38 P1 goal is Morgan Geekie (8479987), `assistsToDate` 23 | **confirmed** |
| GameCenter 2024021238 event 495 | Parker Wotherspoon `assistsToDate` 6 in the same game | **confirmed** |

## What was NOT confirmed — one claim in the database is wrong

The record `NHL-20242025-021140-01` (and fact F17 in
`data/reference/verified_facts.json`) stated that the official GameCenter payload
carries **two different clip titles for the same goal**: an English title naming
Meier and a French title naming Mercer, quoted as

    https://nhl.com/fr/video/njd-chi-mercer-marque-un-but-en-a-n-contre-spencer-knight-6370608420112

The payload retrieved today carries, for event 146:

    highlightClipSharingUrl   https://nhl.com/video/njd-chi-meier-scores-ppg-against-spencer-knight-6370610304112
    highlightClipSharingUrlFr https://nhl.com/fr/video/njd-chi-meier-marque-un-but-en-a-n-contre-spencer-knight-6370610205112

Both read **meier**, and the French clip id (6370610205112) is not the one the
record quoted (6370608420112). So the "two different clip titles" corroboration is
**not reproducible from the official payload as it stands today**.

Two explanations are possible and this pass cannot choose between them: the payload
was edited after the original observation, or the original observation was
transcribed incorrectly. There is no stored raw capture from the original
observation to settle it — which is itself the finding: the database stored a
*paraphrase* of a payload instead of the payload, so the claim was never
auditable. The record has been corrected, the flag
`official_payload_contains_two_different_clip_titles_for_the_same_goal` has been
replaced by `initial_state_corroboration_not_reproducible_on_recheck`, and F17 is
amended rather than deleted, so the history of the error stays visible.

## Additional finding — a third-party lead that the official record does not support

`SDN-0bb32245dc` (from the third-party PBP audit log) asserts a **period 2** goal at
**18:07** in game 2018020443 that should read 18:05. The official GameCenter payload
retrieved today for 2018020443 contains **one** period-2 goal, at **01:53**
(eventId 244, C. Bishop, CAR). No goal at 18:07 exists in any period of that game.
The lead's `requires_human_verification` flag stands, with this measurement added:
the clock value it disputes is not present in the current official record at all.

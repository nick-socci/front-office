# 0031. A starter at the time has not pitched yet, has mostly started, or started his last two

- Status: accepted
- Date: 2026-10-09
- Spec: [0092-who-is-a-starter](../specs/0092-who-is-a-starter/design.md) · Issue: #92
- Amends: [0029](0029-the-start-pool-is-every-free-agent-start-by-a-starter.md), for who is a starter at the time

## Context

ADR 0029 made the start pool every free-agent start by a pitcher who was a starter at
the time, and took "a starter" to be `fo_replacement_group` on his earlier appearances
of the season: at least half were starts. The owner accepted that for now (#92).

Of 1,875 free-agent starts in 2026 it takes 1,290. It leaves out 120 by pitchers with no
appearance yet that season, 67 of them in the first fortnight, when every rotation takes
its first turn; and 108 by 24 pitchers who had started their last two appearances and
were still outnumbered by earlier relief outings. Both groups pitch like starters: 13.68
and 14.31 outs, with under 3% of starts facing nine batters or fewer. The rest of what
is left out, 357 starts, is more than half openers.

Starters pitch in a rotation, a turn every fifth or sixth day. Two starts running is a
pitcher taking his turn; one start after relief is as often an opener.

## Decision drivers

- A starter is someone doing the job, as a manager would see it that day (ADR 0029).
- No hindsight, and nothing from the outing being judged: a short start is a bad start,
  not a non-start.
- No parameter to tune, or as few as the rule can have.
- General across leagues: nothing fitted to this league's rosters or settings.
- Only data that is landed.

## Considered options

1. **Keep the rule**: at least half his earlier appearances were starts.
2. **Add the first appearance**: a pitcher who has not pitched yet this season counts.
3. **Option 2, and his last two appearances were both starts.**
4. **Option 2, and his last appearance was a start.**
5. **A window**: most of his last three appearances were starts, replacing the count.
6. **Judge the outing**: a start of normal length counts whoever threw it.
7. **Carry a role in** from the previous season, the minors, or ESPN's eligibility.

## Decision

Chosen by the owner on 2026-10-09, going through the spec's decisions: **option 3**.
A pitcher's first appearance of the season, if a start, counts as a starter's; a change
of role shows when his last two appearances were both starts; and a reliever's first
two starts stay out, since judging the outing itself is not allowed.

A free-agent start is in the pool when, on the pitcher's MLB days of the season before
it, he had not pitched, or `fo_replacement_group` says `SP`, or his two most recent
pitching days were both starts.

| 2026 | Starts | Pitchers | Outs | ERA | Faced 9 or fewer |
|---|---|---|---|---|---|
| 1 keep | 1,290 | 153 | 14.92 | 4.90 | 18 (1.4%) |
| 2 first appearance | 1,410 | 170 | 14.82 | 4.88 | 21 (1.5%) |
| 3 and last two (chosen) | 1,518 | 182 | 14.78 | 4.89 | 24 (1.6%) |
| 4 and last one | 1,584 | 202 | 14.62 | 4.89 | 42 (2.7%) |
| 5 window of three | 1,488 | 187 | 14.77 | 4.86 | 27 (1.8%) |
| 6 outing alone (9 or fewer out) | 1,656 | 209 | 14.73 | 4.84 | 0 |

Option 1 has the two gaps #92 names. Option 2 closes the first and not the second.
Option 4's extra 66 starts over option 3 run at 10.95 outs with 27% facing nine or
fewer: it is where openers come back in. Option 5 replaces the season count with a
window whose size is a choice, and drops 38 starts by season-long starters coming off a
relief outing. Option 6 chooses starts by how they went. Option 7 needs data that is not
landed, and ESPN's eligibility never covers a free agent.

## Consequences

- Good: the first turn of every rotation counts, so the pool is 113 starts in the first
  fortnight where it was 46, and a called-up starter counts from his debut.
- Good: a pitcher who joins a rotation counts from his third start.
- Good: the share of opener-like days in the pool stays where it was, 1.6% against 1.4%.
- Bad / accepted cost: a reliever's first two starts are never in, real ones included:
  114 full-length first starts in 2026 cannot be told from openers beforehand.
- Bad / accepted cost: an opener making the first appearance of his season is in (3
  starts in 2026), and a pitcher used as an opener twice running is in the third time.
- Bad / accepted cost: "a starter at the time" is now three conditions in the levels
  model, beside `fo_replacement_group`, which keeps labelling players elsewhere. The two
  no longer say the same thing about a pitcher, by design.
- Bad / accepted cost: the level moves again, slightly: 14.92 to 14.78 outs, ERA 4.90 to
  4.89. Starters' values move with it.
- Follow-ups: a role carried from a previous season, once more than one MLB season is
  landed. That is #83, which would land past seasons' boxscores; no separate issue (the
  owner, 2026-10-09). It would also give a second season to check "last two" on.

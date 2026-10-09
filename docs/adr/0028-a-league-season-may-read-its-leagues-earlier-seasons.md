# 0028. A league-season may read its own league's earlier seasons, and isolation is checked by building it with them

- Status: accepted
- Date: 2026-10-08
- Spec: [0057-category-scales-from-history](../specs/0057-category-scales-from-history/design.md) · Issue: #57
- Amends: [0013](0013-isolation-is-proved-by-building-each-league-season-alone.md)

## Context

ADR 0013 proves there is no cross-attribution by building each league-season alone and
requiring its rows to equal the combined build's. That encodes an invariant: a
league-season's rows depend on nothing but its own captures.

ADR 0027 breaks that on purpose. A category's scale blends in the same league's
earlier seasons, so a league-season's value facts depend on them. What must still hold
is narrower: another league's captures, and a later season's, never change a
league-season's rows.

As written the check would keep passing, because no fixture league-season has the 100
earlier matchups the blend needs. It would then establish nothing about the new
dependency, and would fail on correct results if a fixture ever qualified.

## Decision drivers

- The check must still name a model that leaks across leagues, including through the
  new blended scale, which is where a missing league key would now do most harm.
- It must exercise the blended path, not pass because nothing blends.
- No new fixture data.
- CI time.

## Considered options

1. **Leave the check, change its docstring.** It passes while fixtures stay under the
   threshold.
2. **Build each league-season with its league's earlier seasons, at a lowered
   threshold.**
3. **Exempt the scales and the value facts from the comparison**, as `dim_players` is.
4. **A fixture league with a hundred earlier matchups.**

## Decision

Chosen by the owner on 2026-10-08: **option 2**.

A single build holds the league's captures for the season under test and every earlier
season, with those seasons' MLB data; the rows compared are still those of the
league-season under test. Every build of the check, combined and single, sets
`fantasy_scale_prior_matchups` to 2, so that a fixture league-season with an earlier
season uses a blended scale and one without falls back. The main CI build keeps the
default.

The invariant becomes: **a league-season's rows depend only on its own league's captures
of that season and earlier ones.**

Option 1 leaves the new dependency unchecked. Option 3 removes the check from exactly
the models that gained a cross-season join. Option 4 means inventing or publishing a
hundred matchups of data for a check that two per season can make.

## Consequences

- Good: a blended scale that read another league, or a later season, shows as a
  difference, and the model is named.
- Good: both the blended path and the fallback run in every gate.
- Bad / accepted cost: single builds are larger, by a league's earlier fixture seasons.
- Bad / accepted cost: the check runs at a threshold the real build never uses. It shows
  which matchups are blended, not that 100 is the right number.
- Bad / accepted cost: a model that wrongly read an earlier season of its own league
  would no longer be caught by this check. Only the scales are meant to.
- Bad / accepted cost: a scale blended from two fixture matchups can be zero. The facts
  handle a zero scale already.

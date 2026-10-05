# Architecture decisions

One decision per record. `proposed` until the spec that carries it is approved.
Decisions made before 2026-10 are in [docs/design/](../design/).

| # | Decision | Status | Date | Spec |
|---|---|---|---|---|
| [0001](0001-replacement-level-is-the-free-agent-pool.md) | Replacement level is the free-agent pool | accepted; pitcher groups superseded by [0008](0008-a-pitchers-day-is-measured-against-the-same-kind-of-outing.md), [0009](0009-a-pitching-pool-is-ranked-by-appearances.md) | 2026-10-03 | [0011](../specs/0011-player-value/design.md) |
| [0002](0002-value-is-measured-per-played-day.md) | Value is measured per played day | accepted | 2026-10-03 | [0011](../specs/0011-player-value/design.md) |
| [0003](0003-total-value-is-a-sum-of-standardised-category-values.md) | Total value is a sum of standardised category values | accepted; denominator superseded by [0010](0010-category-values-are-scaled-by-the-matchup-margin.md) | 2026-10-03 | [0011](../specs/0011-player-value/design.md) |
| [0004](0004-a-transactions-acting-team-depends-on-its-message-type.md) | A transaction's acting team depends on its message type | accepted | 2026-10-03 | [0011](../specs/0011-player-value/design.md) |
| [0005](0005-a-drops-impact-is-the-rest-of-the-season.md) | A drop's impact is the rest of the season | accepted | 2026-10-03 | [0011](../specs/0011-player-value/design.md) |
| [0006](0006-player-value-counts-every-started-day.md) | Player value counts every started day | accepted | 2026-10-03 | [0011](../specs/0011-player-value/design.md) |
| [0007](0007-category-values-are-a-long-table.md) | Category values are a long table | accepted | 2026-10-03 | [0011](../specs/0011-player-value/design.md) |
| [0008](0008-a-pitchers-day-is-measured-against-the-same-kind-of-outing.md) | A pitcher's day is measured against the same kind of outing | accepted | 2026-10-03 | [0052](../specs/0052-pitcher-replacement-by-outing/design.md) |
| [0009](0009-a-pitching-pool-is-ranked-by-appearances.md) | A pitching pool is ranked by appearances | accepted | 2026-10-03 | [0052](../specs/0052-pitcher-replacement-by-outing/design.md) |
| [0010](0010-category-values-are-scaled-by-the-matchup-margin.md) | Category values are scaled by the matchup margin | accepted | 2026-10-03 | [0055](../specs/0055-matchup-margin-scale/design.md) |
| [0011](0011-a-raw-response-is-identified-by-its-request-path-and-parameters.md) | A raw response is identified by its request path and parameters | accepted | 2026-10-04 | [0028](../specs/0028-league-season-identity/design.md) |
| [0012](0012-players-have-a-conformed-dimension-and-a-league-season-table.md) | Players have a conformed dimension and a per-league-season table | accepted | 2026-10-04 | [0028](../specs/0028-league-season-identity/design.md) |
| [0013](0013-isolation-is-proved-by-building-each-league-season-alone.md) | Isolation is proved by building each league-season alone | accepted | 2026-10-04 | [0028](../specs/0028-league-season-identity/design.md) |
| [0014](0014-a-capture-is-committed-by-its-sidecar.md) | A capture is committed by its sidecar, published last and never over an existing file | proposed | 2026-10-05 | [0029](../specs/0029-committed-captures/design.md) |
| [0015](0015-incomplete-captures-are-quarantined-under-a-writer-lock.md) | Incomplete captures are quarantined at the start of a run, under a writer lock | proposed | 2026-10-05 | [0029](../specs/0029-committed-captures/design.md) |

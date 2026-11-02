"""DuckDB's ordered float aggregates against a Python mirror of BigQuery's JavaScript folds
(spec 0139, R3.3; ADR 0115).

On BigQuery `fo_sum_in_order`, `fo_avg_in_order` and `fo_corr_in_order` hand an array of
the rows, in the stated order, to `sum_in_order` and `corr_in_order` (dbt/functions/*.js).
Those fold one value at a time and are meant to give DuckDB's `sum(x order by k)`,
`avg(x order by k)` and `corr(y, x order by k)` to the last digit. CI never runs BigQuery,
so this file holds the other half: the mirror below is the JavaScript body of the design,
line for line, in Python (a float division by zero is NaN or an infinity there, as in
JavaScript, never an exception), and it must equal DuckDB `==` on seeded random groups
(sizes 1 to 500, about a tenth of the values null, magnitudes 1e-6 to 1e6, both signs).
It catches a DuckDB upgrade that changes the algorithm the JavaScript copies, and a mirror
that drifts from the JavaScript's statement order.

The test was checked to fail once, by hand: with the mirror's folds run over their values
reversed (`reversed(values)` in `sum_in_order`, `reversed(pairs)` in `corr_in_order`),
the random groups failed against DuckDB; the original order was then restored.

DuckDB runs in memory (`duckdb.connect()`); no warehouse is read.
"""

import math
import random

import duckdb
import pytest

NAN = float("nan")


def same(a: float | None, b: float | None) -> bool:
    """`==`, except that NaN equals NaN and None equals None (and nothing else does)."""
    if a is None or b is None:
        return a is None and b is None
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    return a == b


def _div(numerator: float, denominator: float) -> float:
    """JavaScript's `/` on doubles: 0 / 0 is NaN and x / 0 an infinity, not an error."""
    if denominator == 0:
        if numerator == 0 or math.isnan(numerator):
            return NAN
        negative = (numerator < 0) != (math.copysign(1.0, denominator) < 0)
        return -math.inf if negative else math.inf
    return numerator / denominator


def _sqrt(value: float) -> float:
    """`Math.sqrt`: NaN for a negative number."""
    return NAN if value < 0 else math.sqrt(value)


def sum_in_order(values: list[float] | None) -> float | None:
    # if (values === null || values.length === 0) return null;
    if values is None or len(values) == 0:
        return None
    # let total = 0;
    total = 0.0
    # for (const value of values) total += value;
    for value in values:
        total += value
    return total


def avg_in_order(values: list[float] | None) -> float | None:
    """The BigQuery form of fo_avg_in_order: sum_in_order(...) / nullif(count(e), 0)."""
    total = sum_in_order(values)
    if total is None or values is None or len(values) == 0:
        return None
    return _div(total, float(len(values)))


def corr_in_order(pairs: list[tuple[float | None, float | None]] | None) -> float | None:
    """`pairs` are (y, x) in the stated order, either side possibly null."""
    # let n = 0, meanX = 0, meanY = 0, coMoment = 0, squaresX = 0, squaresY = 0;
    n = 0
    mean_x = mean_y = co_moment = 0.0
    # Welford's state for each variance, with its own running mean: [count, mean, squares].
    count_x = count_y = 0
    own_mean_x = own_mean_y = 0.0
    squares_x = squares_y = 0.0
    # for (const pair of pairs || []) {
    for y, x in pairs or []:
        # if (pair.y === null || pair.x === null) continue;
        if y is None or x is None:
            continue
        # n += 1;
        n += 1
        # const dx = pair.x - meanX;
        dx = x - mean_x
        # meanX += dx / n;
        mean_x += _div(dx, float(n))
        # meanY += (pair.y - meanY) / n;
        mean_y += _div(y - mean_y, float(n))
        # coMoment += dx * (pair.y - meanY);
        co_moment += dx * (y - mean_y)
        # Welford's update of squaresX, with its own running mean
        count_x += 1
        delta_x = x - own_mean_x
        own_mean_x = own_mean_x + _div(delta_x, float(count_x))
        squares_x += delta_x * (x - own_mean_x)
        # and of squaresY
        count_y += 1
        delta_y = y - own_mean_y
        own_mean_y = own_mean_y + _div(delta_y, float(count_y))
        squares_y += delta_y * (y - own_mean_y)
    # }
    # if (n === 0) return null;
    if n == 0:
        return None
    # return (coMoment / n) / (Math.sqrt(squaresX / n) * Math.sqrt(squaresY / n));
    return _div(
        _div(co_moment, float(n)),
        _sqrt(_div(squares_x, float(n))) * _sqrt(_div(squares_y, float(n))),
    )


# A group is a list of (k, y, x); k is the order key, unique within the group.
Group = list[tuple[int, float | None, float | None]]


def mirror_sum(group: Group) -> float | None:
    """What BigQuery does for fo_sum_in_order('x', 'k'): array_agg(x ignore nulls order by k)."""
    ordered = sorted(group, key=lambda row: row[0])
    values = [x for _, _, x in ordered if x is not None]
    return sum_in_order(values or None)  # an all-null array_agg is NULL there


def mirror_avg(group: Group) -> float | None:
    ordered = sorted(group, key=lambda row: row[0])
    values = [x for _, _, x in ordered if x is not None]
    return avg_in_order(values or None)


def mirror_corr(group: Group) -> float | None:
    ordered = sorted(group, key=lambda row: row[0])
    return corr_in_order([(y, x) for _, y, x in ordered])


def duckdb_folds(groups: dict[int, Group], seed: int) -> dict[int, tuple[float | None, ...]]:
    """DuckDB's sum, avg and corr of each group, ordered by k; rows are inserted shuffled."""
    rows = [(g, k, y, x) for g, group in groups.items() for k, y, x in group]
    random.Random(seed).shuffle(rows)
    con = duckdb.connect()
    con.execute("create table t (g integer, k integer, y double, x double)")
    con.executemany("insert into t values (?, ?, ?, ?)", rows)
    result = con.execute(
        """
        select g, sum(x order by k), avg(x order by k), corr(y, x order by k)
        from t group by g order by g
        """
    ).fetchall()
    return {g: (s, a, c) for g, s, a, c in result}


def assert_group_matches(group: Group, duck: tuple[float | None, ...], label: str) -> None:
    mirrored = (mirror_sum(group), mirror_avg(group), mirror_corr(group))
    for name, got, want in zip(("sum", "avg", "corr"), mirrored, duck, strict=True):
        assert same(got, want), f"{label} {name}: mirror {got!r}, DuckDB {want!r}"


def random_value(rng: random.Random) -> float:
    """Magnitude 1e-6 to 1e6 (log-uniform), either sign."""
    return rng.choice((-1.0, 1.0)) * 10 ** rng.uniform(-6, 6)


def random_groups(seed: int, count: int) -> dict[int, Group]:
    rng = random.Random(seed)
    groups: dict[int, Group] = {}
    for g in range(count):
        size = rng.randint(1, 500)
        groups[g] = [
            (
                k,
                None if rng.random() < 0.1 else random_value(rng),
                None if rng.random() < 0.1 else random_value(rng),
            )
            for k in range(size)
        ]
    return groups


@pytest.mark.parametrize("seed", [139, 140, 141])
def test_the_mirror_equals_duckdbs_ordered_aggregates_on_random_groups(seed: int) -> None:
    """Catches a DuckDB algorithm that moved, or a mirror out of step with the JavaScript."""
    groups = random_groups(seed, count=150)
    folded = duckdb_folds(groups, seed)
    for g, group in groups.items():
        assert_group_matches(group, folded[g], f"seed {seed} group {g}")


def test_the_mirror_is_sensitive_to_order() -> None:
    """Catches a comparison too weak to see an order: reversing the values moves the digits."""
    rng = random.Random(139)
    ordered = [random_value(rng) for _ in range(200)]
    assert sum_in_order(ordered) != sum_in_order(ordered[::-1])


EDGES: dict[str, tuple[Group, float | None, float | None, float | None]] = {
    # name: (group, sum, avg, corr) as DuckDB 1.5.5 gives them (design, C7)
    "single pair": ([(0, 3.4, 8.9)], 8.9, 8.9, NAN),
    "zero variance": ([(0, 3.4, 2.0), (1, 3.9, 2.0), (2, 2.7, 2.0)], 6.0, 2.0, NAN),
    "all null": ([(0, None, None), (1, None, None)], None, None, None),
    "null side": (
        [(0, 3.4, 8.9), (1, 3.9, 2.0), (2, None, 5.0), (3, 2.7, 1.2), (4, 2.5, None)],
        17.1,
        4.275,
        0.18940207604965043,
    ),
    "a lone negative zero": ([(0, 1.0, -0.0)], 0.0, -0.0, NAN),
}


@pytest.mark.parametrize("name", list(EDGES))
def test_the_edge_cases_give_what_duckdb_gives(name: str) -> None:
    """Catches a fold that guards a case DuckDB leaves to NaN or NULL (design, C7)."""
    group, want_sum, want_avg, want_corr = EDGES[name]
    duck = duckdb_folds({0: group}, seed=0)[0]
    assert_group_matches(group, duck, name)
    # And the values stated here are DuckDB's, not only the mirror's.
    for got, want in zip(duck, (want_sum, want_avg, want_corr), strict=True):
        assert same(got, want), f"{name}: DuckDB {got!r}, stated {want!r}"

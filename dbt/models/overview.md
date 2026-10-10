{% docs __overview__ %}

# Front Office

Real MLB and ESPN fantasy baseball data, landed as raw JSON, transformed with dbt and
stored in DuckDB. This site is the project's own documentation of its models: what each
one holds, the SQL that builds it, the tests on it, and what it is built from.

The code, the design records and the reasoning behind each decision are in the
repository: [github.com/nick-socci/front-office](https://github.com/nick-socci/front-office).

## Start with the lineage graph

Click the round blue button at the bottom right of any page. It opens the whole graph:
one raw table on the left, the marts on the right, and at the far right the things that
read them. On a model's own page the same button shows just that model's parents and
children.

## The four layers

Every model belongs to one layer, and its name starts with the layer's prefix.

| Layer | Prefix | What it is for |
|---|---|---|
| Staging | `stg_` | One model per thing a source API returns: a game, a batting line, a roster entry. It flattens the JSON, keeps one row per entity, and converts to honest units (outs, not innings). No business rules. |
| Intermediate | `int_` | The same facts in the project's own terms and no platform's: a roster day, a player's day in MLB, a matchup side. This is where ESPN's vocabulary stops, so that another platform could be added beside it. |
| Marts | `fct_`, `dim_` | Shaped like a question: who won each category, what a player was worth, what a team left on its bench. These are the tables to query. |
| Reconciliation | `rec_` | Our numbers beside the platform's own, and every difference between them, explained or not. Nothing reads from here; it exists to be checked. |

Under all of them is one source, `raw.api_responses`: every API response exactly as it
was fetched, one row each. Ingestion saves; it never interprets. Everything that needs
to know what the data means happens in the models on this site.

## What you are looking at

This site is built by CI from a small set of committed fixtures, on every change to the
main branch. The fantasy league behind the project is private, so the site holds no
league data: no rows, no team names and nobody's name. Column types and descriptions
are real; they are the same models that run on the full season.

Two kinds of node sit to the right of the marts in the graph. They are *exposures*:
dbt's way of declaring something outside dbt that reads its models. One is a dashboard
that is planned and not yet built. The others are the example queries in the
repository's `docs/examples/`, each of which CI runs.

{% enddocs %}

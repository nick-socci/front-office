"""R3.4: a failed dbt build records the unique id and status of each failed node, and no message.

Catches: a node that ended `error` or `fail` missing from the failure; a `skipped`, `warn` or
`pass` node listed as failed; a dbt message (which can carry SQL or data) copied into metadata;
and a failed build that surfaces as dagster-dbt's own error instead of the fixed `Failure`.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from dagster import Failure
from dagster_dbt import DagsterDbtCliRuntimeError

from front_office_pipeline.dbt_assets import failed_nodes, stream_build

RUN_RESULTS: dict[str, Any] = {
    "results": [
        {"unique_id": "model.fo.a", "status": "success", "message": "OK"},
        {"unique_id": "model.fo.b", "status": "error", "message": "secret_value in SQL"},
        {"unique_id": "test.fo.c", "status": "fail", "message": "Got 3 results"},
        {"unique_id": "model.fo.d", "status": "skipped", "message": "SKIP"},
        {"unique_id": "test.fo.e", "status": "warn", "message": "Got 1 result"},
        {"unique_id": "test.fo.f", "status": "pass", "message": None},
    ]
}


class FakeInvocation:
    """What `stream_build` uses of a `DbtCliInvocation`: `stream()` and `get_artifact()`."""

    def __init__(self, artifact: Any, *, fails: bool = True) -> None:
        self.artifact = artifact
        self.fails = fails

    def stream(self) -> Iterator[str]:
        yield "event"
        if self.fails:
            raise DagsterDbtCliRuntimeError(description="dbt exited 1: secret_value")

    def get_artifact(self, name: str) -> dict[str, Any]:
        assert name == "run_results.json"
        if isinstance(self.artifact, Exception):
            raise self.artifact
        return self.artifact  # type: ignore[no-any-return]


def test_only_error_and_fail_nodes_are_listed_in_file_order_without_messages() -> None:
    text = failed_nodes(RUN_RESULTS)
    assert text == "model.fo.b: error\ntest.fo.c: fail"
    assert "secret_value" not in text and "Got" not in text


def test_no_failed_node_gives_an_empty_string() -> None:
    assert failed_nodes({"results": RUN_RESULTS["results"][:1]}) == ""
    assert failed_nodes({}) == ""


def test_a_failed_stream_raises_the_fixed_failure_with_the_failed_nodes() -> None:
    seen = []
    with pytest.raises(Failure) as caught:
        for event in stream_build(FakeInvocation(RUN_RESULTS)):  # type: ignore[arg-type]
            seen.append(event)
    assert seen == ["event"]
    failure = caught.value
    assert not isinstance(failure, DagsterDbtCliRuntimeError)
    assert failure.description == "dbt build failed"
    assert failure.metadata["failed_nodes"].value == "model.fo.b: error\ntest.fo.c: fail"
    assert isinstance(failure.__cause__, DagsterDbtCliRuntimeError)
    assert "secret_value" not in str(failure.description)


@pytest.mark.parametrize("artifact", [FileNotFoundError("no run_results.json"), {}])
def test_a_missing_artifact_still_fails_with_no_nodes(artifact: Any) -> None:
    with pytest.raises(Failure) as caught:
        list(stream_build(FakeInvocation(artifact)))  # type: ignore[arg-type]
    assert caught.value.description == "dbt build failed"
    assert caught.value.metadata["failed_nodes"].value == ""


def test_a_clean_stream_passes_its_events_through() -> None:
    events = list(stream_build(FakeInvocation(RUN_RESULTS, fails=False)))  # type: ignore[arg-type]
    assert events == ["event"]

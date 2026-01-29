import os
import sys
import yaml
import pytest
import json

# make repo root importable
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def load_cases():
    with open(os.path.join(os.path.dirname(__file__), "..", "cases_expected.yaml"), "r") as f:
        data = yaml.safe_load(f) or {}
    return data.get("cases", [])


@pytest.mark.parametrize("case", load_cases())
def test_expected_cases_placeholder(case):
    """
    Placeholder harness:
    - ensures YAML is well-formed
    - allows filling ExpectedOutcome later
    - asserts invariant for owner_conflict side effects (no writes) when current_output signals conflict
    """
    curr = case.get("current_output", {})
    side = curr.get("side_effects", {})
    status = curr.get("final_status", "") or ""

    # If current_output indicates owner_conflict, assert side_effects show no channel/membership/links writes.
    if "owner_conflict" in status:
        assert str(side.get("write_channels", "")).startswith("conflict:no") or side.get("write_channels") is False
        assert str(side.get("write_membership", "")).startswith("conflict:no") or side.get("write_membership") is False
        assert str(side.get("write_links", "")).startswith("conflict:no") or side.get("write_links") is False

    # ExpectedOutcome placeholder exists
    expected = case.get("expected", {})
    assert "final_status" in expected


def test_trace_to_yaml_script_smoke(tmp_path, monkeypatch):
    # create minimal trace
    trace = tmp_path / "trace.jsonl"
    yaml_path = tmp_path / "cases.yaml"
    yaml_path.write_text("cases: []", encoding="utf-8")
    ev = {
        "ts": 0,
        "event": "side_effects",
        "batch_id": "b1",
        "item_id": 1,
        "idx": 1,
        "url": "u1",
        "data": {"final_status": "already", "queue_transition": "done", "cache_keys_written": []},
    }
    trace.write_text(json.dumps(ev), encoding="utf-8")

    from tools import subscription_trace_to_yaml as tool

    events = tool.load_trace(trace)
    grouped = tool.group_events(events)
    # fabricate case and update current_output via aggregate
    cases = [{"id": 999, "input": {"url_norm": "u1"}, "expected": {"final_status": "TBD"}}]
    agg = tool.aggregate_item(list(grouped.values())[0])
    cases[0]["current_output"] = agg
    assert cases[0]["current_output"]["final_status"] == "already"

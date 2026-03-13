from __future__ import annotations

import json

from app.plugins import posts_watch_listener
from tools import posts_watch_trace_summary


def test_build_match_diagnostics_payload_contains_text_and_links_differences() -> None:
    match_diagnostics_payload = posts_watch_listener._build_match_diagnostics_payload(
        expected_html_text='<a href="https://t.me/expected">Expected</a>',
        actual_html_text='<a href="https://t.me/actual">Actual</a>',
        expected_plain_text="Expected",
        actual_plain_text="Actual",
        expected_links_values=["https://t.me/expected"],
        actual_links_values=["https://t.me/actual"],
    )

    assert match_diagnostics_payload["expected_links"] == ["https://t.me/expected"]
    assert match_diagnostics_payload["actual_links"] == ["https://t.me/actual"]
    assert match_diagnostics_payload["expected_only_links"] == ["https://t.me/expected"]
    assert match_diagnostics_payload["actual_only_links"] == ["https://t.me/actual"]
    assert match_diagnostics_payload["expected_plain_excerpt"] == "Expected"
    assert match_diagnostics_payload["actual_plain_excerpt"] == "Actual"


def test_trace_match_decision_trail_emits_reason_and_decision_stage(monkeypatch) -> None:
    trace_calls: list[tuple[str, dict]] = []

    def fake_trace(event_name: str, **event_payload) -> None:
        trace_calls.append((event_name, event_payload))

    monkeypatch.setattr(posts_watch_listener, "_trace", fake_trace)

    posts_watch_listener._trace_match_decision_trail(
        watch_id=8116,
        channel_id=1801542020,
        message_id=31428,
        session_name="tg_session_1",
        exact_html_match_succeeded=False,
        html_similarity_ratio=0.9991111111111111,
        plain_text_similarity_ratio=1.0,
        similarity_threshold=0.901,
        similarity_threshold_passed=True,
        links_mismatch_detected=False,
        final_watch_status="matched",
        reason_code="near_exact_text_links_match",
        expected_links_values=["https://t.me/one"],
        actual_links_values=["https://t.me/one"],
    )

    assert len(trace_calls) == 1
    event_name, event_payload = trace_calls[0]
    assert event_name == "match_decision_trail"
    assert event_payload["reason_code"] == "near_exact_text_links_match"
    assert event_payload["final_watch_status"] == "matched"
    assert event_payload["decision_stages"]["links_check_result"] == "links_match"


def test_posts_watch_trace_summary_filters_and_status_detection() -> None:
    trace_event_payload = {
        "event": "match_candidate",
        "watch_id": "8116",
        "channel_id": "1801542020",
        "notifier_group_id": "354",
        "reason_code": "similarity_above_threshold",
    }

    inferred_status = posts_watch_trace_summary.infer_match_decision_status(
        event_name=trace_event_payload["event"],
        trace_event_payload=trace_event_payload,
    )
    assert inferred_status == "candidate"
    assert posts_watch_trace_summary.is_mismatch_match_decision_status(inferred_status) is True
    assert posts_watch_trace_summary.normalize_reason_code(trace_event_payload) == "similarity_above_threshold"

    assert posts_watch_trace_summary.trace_event_matches_filters(
        trace_event_payload=trace_event_payload,
        event_name_filters={"match_candidate"},
        watch_identifier_filter=8116,
        channel_identifier_filter=1801542020,
        notifier_group_identifier_filter=354,
    )

    assert not posts_watch_trace_summary.trace_event_matches_filters(
        trace_event_payload=trace_event_payload,
        event_name_filters={"match_exact"},
        watch_identifier_filter=None,
        channel_identifier_filter=None,
        notifier_group_identifier_filter=None,
    )


def test_posts_watch_trace_summary_status_mapping_for_multiple_scenarios() -> None:
    scenario_mapping = {
        "match_exact": "matched",
        "match_candidate": "candidate",
        "match_no_match": "no_match",
        "match_foreign_links_mismatch": "foreign",
        "match_skipped_missing_expected_html": "skipped",
        "match_candidate_suppressed_duplicate_ttl": "candidate_suppressed_duplicate",
    }

    for event_name, expected_status in scenario_mapping.items():
        inferred_status = posts_watch_trace_summary.infer_match_decision_status(
            event_name=event_name,
            trace_event_payload={},
        )
        assert inferred_status == expected_status

    matched_from_decision_trail = posts_watch_trace_summary.infer_match_decision_status(
        event_name="match_decision_trail",
        trace_event_payload={"final_watch_status": "matched"},
    )
    assert matched_from_decision_trail == "matched"
    assert posts_watch_trace_summary.is_mismatch_match_decision_status("matched") is False
    assert posts_watch_trace_summary.is_mismatch_match_decision_status("foreign") is True


def test_load_trace_events_from_file_skips_invalid_rows(tmp_path) -> None:
    trace_file_path = tmp_path / "posts_watch_trace_sample.jsonl"
    trace_file_path.write_text(
        "\n".join(
            [
                json.dumps({"event": "match_exact", "watch_id": 1}),
                "not-a-json-line",
                json.dumps(["invalid"]),
                json.dumps({"event": "views_done", "watch_id": 1}),
            ]
        ),
        encoding="utf-8",
    )

    loaded_trace_events, skipped_lines_count = posts_watch_trace_summary.load_trace_events_from_file(trace_file_path)

    assert len(loaded_trace_events) == 2
    assert skipped_lines_count == 2

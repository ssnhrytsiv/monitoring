#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
import os
from pathlib import Path
from typing import Any, Iterable


def parse_command_line_arguments() -> argparse.Namespace:
    argument_parser = argparse.ArgumentParser(
        description="Summarize posts watch trace log and highlight mismatch reasons.",
    )
    argument_parser.add_argument(
        "--trace",
        default=str(os.getenv("WATCH_TRACE_LOG_PATH", "logs/posts_watch_trace_v2.log") or "").strip()
        or "logs/posts_watch_trace_v2.log",
        help="Path to posts watch trace log file (JSON per line).",
    )
    argument_parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Maximum rows in each top section.",
    )
    argument_parser.add_argument(
        "--event",
        action="append",
        dest="event_name_filters",
        default=[],
        help="Filter by event name. You can pass this argument multiple times.",
    )
    argument_parser.add_argument(
        "--watch-id",
        type=int,
        dest="watch_identifier_filter",
        help="Filter by watch_id.",
    )
    argument_parser.add_argument(
        "--channel-id",
        type=int,
        dest="channel_identifier_filter",
        help="Filter by channel_id.",
    )
    argument_parser.add_argument(
        "--notifier-group-id",
        type=int,
        dest="notifier_group_identifier_filter",
        help="Filter by notifier_group_id (ID from notifier message header).",
    )
    return argument_parser.parse_args()


def load_trace_events_from_file(trace_file_path: Path) -> tuple[list[dict[str, Any]], int]:
    trace_events: list[dict[str, Any]] = []
    skipped_lines_count = 0

    with trace_file_path.open(encoding="utf-8") as trace_file:
        for raw_line in trace_file:
            normalized_line = raw_line.strip()
            if not normalized_line:
                continue
            try:
                parsed_line = json.loads(normalized_line)
            except Exception:
                skipped_lines_count += 1
                continue
            if not isinstance(parsed_line, dict):
                skipped_lines_count += 1
                continue
            trace_events.append(parsed_line)

    return trace_events, skipped_lines_count


def parse_numeric_identifier(identifier_value: Any) -> int | None:
    if isinstance(identifier_value, bool):
        return None
    if isinstance(identifier_value, int):
        return identifier_value
    if isinstance(identifier_value, str):
        normalized_identifier = identifier_value.strip()
        if not normalized_identifier:
            return None
        try:
            return int(normalized_identifier)
        except Exception:
            return None
    return None


def normalize_reason_code(trace_event_payload: dict[str, Any]) -> str | None:
    reason_code_value = trace_event_payload.get("reason_code")
    if isinstance(reason_code_value, str):
        normalized_reason_code = reason_code_value.strip()
        if normalized_reason_code:
            return normalized_reason_code

    reason_value = trace_event_payload.get("reason")
    if isinstance(reason_value, str):
        normalized_reason_value = reason_value.strip()
        if normalized_reason_value:
            return normalized_reason_value

    return None


def infer_match_decision_status(event_name: str, trace_event_payload: dict[str, Any]) -> str | None:
    final_watch_status_value = trace_event_payload.get("final_watch_status")
    if isinstance(final_watch_status_value, str):
        normalized_final_watch_status = final_watch_status_value.strip()
        if normalized_final_watch_status:
            return normalized_final_watch_status

    legacy_event_status_mapping = {
        "match_exact": "matched",
        "match_candidate": "candidate",
        "match_no_match": "no_match",
        "match_foreign_links_mismatch": "foreign",
        "match_skipped_missing_expected_html": "skipped",
        "match_candidate_suppressed_duplicate_ttl": "candidate_suppressed_duplicate",
    }
    return legacy_event_status_mapping.get(event_name)


def is_mismatch_match_decision_status(match_decision_status: str) -> bool:
    non_mismatch_status_values = {"matched"}
    return match_decision_status not in non_mismatch_status_values


def trace_event_matches_filters(
    trace_event_payload: dict[str, Any],
    event_name_filters: set[str],
    watch_identifier_filter: int | None,
    channel_identifier_filter: int | None,
    notifier_group_identifier_filter: int | None,
) -> bool:
    event_name_value = trace_event_payload.get("event")
    event_name = event_name_value if isinstance(event_name_value, str) else ""

    if event_name_filters and event_name not in event_name_filters:
        return False

    if watch_identifier_filter is not None:
        watch_identifier_value = parse_numeric_identifier(trace_event_payload.get("watch_id"))
        if watch_identifier_value != watch_identifier_filter:
            return False

    if channel_identifier_filter is not None:
        channel_identifier_value = parse_numeric_identifier(trace_event_payload.get("channel_id"))
        if channel_identifier_value != channel_identifier_filter:
            return False

    if notifier_group_identifier_filter is not None:
        notifier_group_identifier_value = parse_numeric_identifier(trace_event_payload.get("notifier_group_id"))
        if notifier_group_identifier_value != notifier_group_identifier_filter:
            return False

    return True


def print_counter_section(section_title: str, section_counter: Counter[str], maximum_rows: int) -> None:
    print()
    print(section_title)
    if not section_counter:
        print("  (empty)")
        return

    top_counter_rows = section_counter.most_common(maximum_rows)
    maximum_label_width = max(len(row_label) for row_label, _ in top_counter_rows)
    for row_index, (row_label, row_count) in enumerate(top_counter_rows, start=1):
        print(f"  {row_index:>2}. {row_label:<{maximum_label_width}}  {row_count}")


def normalize_event_name_filters(event_name_filters: Iterable[str]) -> set[str]:
    normalized_event_name_filters: set[str] = set()
    for event_name_filter in event_name_filters:
        normalized_event_name_filter = str(event_name_filter or "").strip()
        if normalized_event_name_filter:
            normalized_event_name_filters.add(normalized_event_name_filter)
    return normalized_event_name_filters


def main() -> None:
    command_line_arguments = parse_command_line_arguments()
    trace_file_path = Path(command_line_arguments.trace)

    if not trace_file_path.exists():
        raise SystemExit(f"Trace file does not exist: {trace_file_path}")

    maximum_rows = max(1, int(command_line_arguments.top))
    event_name_filters = normalize_event_name_filters(command_line_arguments.event_name_filters)
    watch_identifier_filter = command_line_arguments.watch_identifier_filter
    channel_identifier_filter = command_line_arguments.channel_identifier_filter
    notifier_group_identifier_filter = command_line_arguments.notifier_group_identifier_filter

    loaded_trace_events, skipped_lines_count = load_trace_events_from_file(trace_file_path)
    selected_trace_events = [
        trace_event_payload
        for trace_event_payload in loaded_trace_events
        if trace_event_matches_filters(
            trace_event_payload=trace_event_payload,
            event_name_filters=event_name_filters,
            watch_identifier_filter=watch_identifier_filter,
            channel_identifier_filter=channel_identifier_filter,
            notifier_group_identifier_filter=notifier_group_identifier_filter,
        )
    ]

    event_name_counts: Counter[str] = Counter()
    reason_code_counts: Counter[str] = Counter()
    event_reason_code_counts: Counter[str] = Counter()
    match_decision_status_counts: Counter[str] = Counter()
    watch_identifier_counts: Counter[str] = Counter()
    channel_identifier_counts: Counter[str] = Counter()
    notifier_group_identifier_counts: Counter[str] = Counter()
    mismatch_watch_identifier_counts: Counter[str] = Counter()
    mismatch_channel_identifier_counts: Counter[str] = Counter()
    mismatch_notifier_group_identifier_counts: Counter[str] = Counter()

    for trace_event_payload in selected_trace_events:
        event_name_value = trace_event_payload.get("event")
        event_name = event_name_value if isinstance(event_name_value, str) and event_name_value else "<missing_event>"
        event_name_counts[event_name] += 1

        watch_identifier_value = parse_numeric_identifier(trace_event_payload.get("watch_id"))
        if watch_identifier_value is not None:
            watch_identifier_string = str(watch_identifier_value)
            watch_identifier_counts[watch_identifier_string] += 1

        channel_identifier_value = parse_numeric_identifier(trace_event_payload.get("channel_id"))
        if channel_identifier_value is not None:
            channel_identifier_string = str(channel_identifier_value)
            channel_identifier_counts[channel_identifier_string] += 1

        notifier_group_identifier_value = parse_numeric_identifier(trace_event_payload.get("notifier_group_id"))
        if notifier_group_identifier_value is not None:
            notifier_group_identifier_string = str(notifier_group_identifier_value)
            notifier_group_identifier_counts[notifier_group_identifier_string] += 1

        reason_code = normalize_reason_code(trace_event_payload)
        if reason_code:
            reason_code_counts[reason_code] += 1
            event_reason_code_counts[f"{event_name}:{reason_code}"] += 1

        match_decision_status = infer_match_decision_status(event_name=event_name, trace_event_payload=trace_event_payload)
        if not match_decision_status:
            continue

        match_decision_status_counts[match_decision_status] += 1
        if not is_mismatch_match_decision_status(match_decision_status):
            continue

        if watch_identifier_value is not None:
            mismatch_watch_identifier_counts[str(watch_identifier_value)] += 1
        if channel_identifier_value is not None:
            mismatch_channel_identifier_counts[str(channel_identifier_value)] += 1
        if notifier_group_identifier_value is not None:
            mismatch_notifier_group_identifier_counts[str(notifier_group_identifier_value)] += 1

    print(f"Trace file: {trace_file_path}")
    print(f"Loaded events: {len(loaded_trace_events)}")
    print(f"Skipped invalid lines: {skipped_lines_count}")
    print(f"Selected events after filters: {len(selected_trace_events)}")
    if event_name_filters:
        print(f"Event filters: {', '.join(sorted(event_name_filters))}")
    if watch_identifier_filter is not None:
        print(f"Watch filter: {watch_identifier_filter}")
    if channel_identifier_filter is not None:
        print(f"Channel filter: {channel_identifier_filter}")
    if notifier_group_identifier_filter is not None:
        print(f"Notifier group filter: {notifier_group_identifier_filter}")

    print_counter_section("Event counts", event_name_counts, maximum_rows)
    print_counter_section("Reason code counts", reason_code_counts, maximum_rows)
    print_counter_section("Event + reason code counts", event_reason_code_counts, maximum_rows)
    print_counter_section("Match decision status counts", match_decision_status_counts, maximum_rows)
    print_counter_section("Top notifier_group_id in mismatch decision events", mismatch_notifier_group_identifier_counts, maximum_rows)
    print_counter_section("Top watch_id in mismatch decision events", mismatch_watch_identifier_counts, maximum_rows)
    print_counter_section("Top channel_id in mismatch decision events", mismatch_channel_identifier_counts, maximum_rows)
    print_counter_section("Top notifier_group_id in all selected events", notifier_group_identifier_counts, maximum_rows)
    print_counter_section("Top watch_id in all selected events", watch_identifier_counts, maximum_rows)
    print_counter_section("Top channel_id in all selected events", channel_identifier_counts, maximum_rows)


if __name__ == "__main__":
    main()

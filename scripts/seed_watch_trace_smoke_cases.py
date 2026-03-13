#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict

from app.DAL import watch_events_operations
from app.DAL import watch_posts_operations
from app.DAL import watch_processing_operations
from app.services import watch_event_reason_codes
from app.utils.time_utils import MOSCOW_TIME_FORMAT, moscow_now


def _format_datetime(datetime_value: datetime) -> str:
    return datetime_value.strftime(MOSCOW_TIME_FORMAT)


def _parse_command_line_arguments() -> argparse.Namespace:
    command_line_parser = argparse.ArgumentParser(
        description="Seed watch smoke data for trace and notifier checks.",
    )
    command_line_parser.add_argument(
        "--scenario-tag",
        default="",
        help="Optional scenario suffix. Defaults to current datetime.",
    )
    command_line_parser.add_argument(
        "--trace-log-path",
        default=str(os.getenv("WATCH_TRACE_LOG_PATH", "logs/posts_watch_trace_v2.log") or "").strip()
        or "logs/posts_watch_trace_v2.log",
        help="Path for watch trace log file.",
    )
    command_line_parser.add_argument(
        "--skip-trace",
        action="store_true",
        help="Do not append synthetic events to trace log.",
    )
    command_line_parser.add_argument(
        "--send-notification",
        action="store_true",
        help="Send one notifier batch after seeding (requires notifier env vars).",
    )
    command_line_parser.add_argument(
        "--sleep-between-matches-seconds",
        type=float,
        default=1.2,
        help="Delay between matched marks to produce different matched_at timestamps.",
    )
    return command_line_parser.parse_args()


def _build_scenario_tag(raw_scenario_tag: str) -> str:
    normalized_scenario_tag = str(raw_scenario_tag or "").strip()
    if normalized_scenario_tag:
        return normalized_scenario_tag
    return moscow_now().strftime("%Y%m%d_%H%M%S")


def _seed_watch_rows_for_smoke_scenarios(
    scenario_tag: str,
    sleep_between_matches_seconds: float,
) -> Dict[str, int]:
    now_datetime = moscow_now().replace(microsecond=0)
    created_by_user_identifier = 900001
    project_name = f"SMOKE_WATCH_TRACE_{scenario_tag}"
    watch_group_title = f"Smoke watch group {scenario_tag}"

    watch_group_identifier = watch_posts_operations.create_watch_group(
        project=project_name,
        title=watch_group_title,
        created_by=created_by_user_identifier,
        created_via="smoke_seed_script",
    )

    matched_exact_watch_identifier = watch_posts_operations.create_watch(
        channel_id=1901001001,
        group_id=watch_group_identifier,
        source_url=f"https://t.me/smoke_exact_{scenario_tag}",
        created_by=created_by_user_identifier,
        created_via="smoke_seed_script",
        project=project_name,
        title=f"SMOKE exact {scenario_tag}",
        expected_text_hash="<b>SMOKE EXACT</b>",
        expected_links_json=json.dumps([f"https://t.me/smoke_exact_{scenario_tag}"]),
        time_window_end=_format_datetime(now_datetime + timedelta(hours=4)),
    )

    matched_near_exact_watch_identifier = watch_posts_operations.create_watch(
        channel_id=1901001002,
        group_id=watch_group_identifier,
        source_url=f"https://t.me/smoke_near_exact_{scenario_tag}",
        created_by=created_by_user_identifier,
        created_via="smoke_seed_script",
        project=project_name,
        title=f"SMOKE near exact {scenario_tag}",
        expected_text_hash="<b>SMOKE NEAR EXACT</b>",
        expected_links_json=json.dumps([f"https://t.me/smoke_near_exact_{scenario_tag}"]),
        time_window_end=_format_datetime(now_datetime + timedelta(hours=4)),
    )

    candidate_watch_identifier = watch_posts_operations.create_watch(
        channel_id=1901001003,
        group_id=watch_group_identifier,
        source_url=f"https://t.me/smoke_candidate_{scenario_tag}",
        created_by=created_by_user_identifier,
        created_via="smoke_seed_script",
        project=project_name,
        title=f"SMOKE candidate {scenario_tag}",
        expected_text_hash="<b>SMOKE CANDIDATE</b>",
        expected_links_json=json.dumps([f"https://t.me/smoke_candidate_{scenario_tag}"]),
        time_window_end=_format_datetime(now_datetime + timedelta(hours=4)),
    )

    foreign_watch_identifier = watch_posts_operations.create_watch(
        channel_id=1901001004,
        group_id=watch_group_identifier,
        source_url=f"https://t.me/smoke_foreign_{scenario_tag}",
        created_by=created_by_user_identifier,
        created_via="smoke_seed_script",
        project=project_name,
        title=f"SMOKE foreign {scenario_tag}",
        expected_text_hash="<b>SMOKE FOREIGN</b>",
        expected_links_json=json.dumps([f"https://t.me/smoke_foreign_{scenario_tag}"]),
        time_window_end=_format_datetime(now_datetime + timedelta(hours=4)),
    )

    expired_watch_identifier = watch_posts_operations.create_watch(
        channel_id=1901001005,
        group_id=watch_group_identifier,
        source_url=f"https://t.me/smoke_expired_{scenario_tag}",
        created_by=created_by_user_identifier,
        created_via="smoke_seed_script",
        project=project_name,
        title=f"SMOKE expired {scenario_tag}",
        expected_text_hash="<b>SMOKE EXPIRED</b>",
        expected_links_json=json.dumps([f"https://t.me/smoke_expired_{scenario_tag}"]),
        time_window_end=_format_datetime(now_datetime - timedelta(minutes=1)),
    )

    pending_watch_identifier = watch_posts_operations.create_watch(
        channel_id=1901001006,
        group_id=watch_group_identifier,
        source_url=f"https://t.me/smoke_pending_{scenario_tag}",
        created_by=created_by_user_identifier,
        created_via="smoke_seed_script",
        project=project_name,
        title=f"SMOKE pending {scenario_tag}",
        expected_text_hash="<b>SMOKE PENDING</b>",
        expected_links_json=json.dumps([f"https://t.me/smoke_pending_{scenario_tag}"]),
        time_window_end=_format_datetime(now_datetime + timedelta(hours=2)),
    )

    first_coverage_datetime = now_datetime - timedelta(minutes=18)
    second_coverage_datetime = now_datetime - timedelta(minutes=11)

    watch_processing_operations.mark_matched(
        matched_exact_watch_identifier,
        message_id=910001,
        coverage_check_at=_format_datetime(second_coverage_datetime),
        matched_session="smoke_session_exact",
    )
    time.sleep(max(0.0, float(sleep_between_matches_seconds)))
    watch_processing_operations.mark_matched(
        matched_near_exact_watch_identifier,
        message_id=910002,
        coverage_check_at=_format_datetime(first_coverage_datetime),
        matched_session="smoke_session_near_exact",
    )
    watch_processing_operations.mark_done_views(
        matched_near_exact_watch_identifier,
        final_views=15320,
    )
    watch_processing_operations.mark_expired(expired_watch_identifier)

    event_base_datetime = moscow_now().replace(microsecond=0) + timedelta(seconds=30)

    watch_events_operations.insert_watch_event(
        matched_exact_watch_identifier,
        "matched",
        json.dumps(
            {
                "watch_id": matched_exact_watch_identifier,
                "channel_id": 1901001001,
                "message_id": 910001,
                "session": "smoke_session_exact",
                "reason_code": watch_event_reason_codes.WATCH_EVENT_REASON_CODE_EXACT_HTML_MATCH,
            },
            ensure_ascii=False,
        ),
        created_at=_format_datetime(event_base_datetime + timedelta(seconds=1)),
    )
    watch_events_operations.insert_watch_event(
        matched_near_exact_watch_identifier,
        "views",
        json.dumps(
            {
                "watch_id": matched_near_exact_watch_identifier,
                "channel_id": 1901001002,
                "message_id": 910002,
                "views": 15320,
                "reason_code": watch_event_reason_codes.WATCH_EVENT_REASON_CODE_VIEWS_COVERAGE_CHECK,
            },
            ensure_ascii=False,
        ),
        created_at=_format_datetime(first_coverage_datetime),
    )
    watch_events_operations.insert_watch_event(
        candidate_watch_identifier,
        "candidate",
        json.dumps(
            {
                "watch_id": candidate_watch_identifier,
                "channel_id": 1901001003,
                "message_id": 910003,
                "similarity": 0.953,
                "reason_code": watch_event_reason_codes.WATCH_EVENT_REASON_CODE_SIMILARITY_ABOVE_THRESHOLD,
            },
            ensure_ascii=False,
        ),
        created_at=_format_datetime(event_base_datetime + timedelta(seconds=3)),
    )
    watch_events_operations.insert_watch_event(
        foreign_watch_identifier,
        "foreign",
        json.dumps(
            {
                "watch_id": foreign_watch_identifier,
                "channel_id": 1901001004,
                "message_id": 910004,
                "similarity": 0.941,
                "reason": watch_event_reason_codes.WATCH_EVENT_REASON_CODE_LINKS_MISMATCH,
                "reason_code": watch_event_reason_codes.WATCH_EVENT_REASON_CODE_LINKS_MISMATCH,
            },
            ensure_ascii=False,
        ),
        created_at=_format_datetime(event_base_datetime + timedelta(seconds=4)),
    )
    watch_events_operations.insert_watch_event(
        expired_watch_identifier,
        "expired",
        json.dumps(
            {
                "watch_id": expired_watch_identifier,
                "channel_id": 1901001005,
                "reason_code": watch_event_reason_codes.WATCH_EVENT_REASON_CODE_PENDING_WINDOW_EXPIRED,
            },
            ensure_ascii=False,
        ),
        created_at=_format_datetime(event_base_datetime + timedelta(seconds=5)),
    )

    return {
        "watch_group_identifier": watch_group_identifier,
        "matched_exact_watch_identifier": matched_exact_watch_identifier,
        "matched_near_exact_watch_identifier": matched_near_exact_watch_identifier,
        "candidate_watch_identifier": candidate_watch_identifier,
        "foreign_watch_identifier": foreign_watch_identifier,
        "expired_watch_identifier": expired_watch_identifier,
        "pending_watch_identifier": pending_watch_identifier,
    }


def _emit_trace_events_for_smoke_scenarios(
    watch_identifier_map: Dict[str, int],
    scenario_tag: str,
    trace_log_path: str,
) -> None:
    normalized_trace_log_path = str(trace_log_path or "").strip() or "logs/posts_watch_trace_v2.log"
    os.environ["WATCH_TRACE_LOG_PATH"] = normalized_trace_log_path

    posts_watch_listener_module = importlib.import_module("app.plugins.posts_watch_listener")

    expected_near_exact_html = f'<a href="https://t.me/smoke_near_exact_{scenario_tag}">SMOKE near exact</a>'
    actual_near_exact_html = expected_near_exact_html
    expected_candidate_html = f"<b>SMOKE CANDIDATE ORIGINAL {scenario_tag}</b>"
    actual_candidate_html = f"<b>SMOKE CANDIDATE MODIFIED {scenario_tag}</b>"
    expected_foreign_html = f'<a href="https://t.me/smoke_foreign_{scenario_tag}">SMOKE FOREIGN</a>'
    actual_foreign_html = f'<a href="https://t.me/smoke_foreign_other_{scenario_tag}">SMOKE FOREIGN</a>'
    expected_no_match_html = f"<b>SMOKE NO MATCH EXPECTED {scenario_tag}</b>"
    actual_no_match_html = f"<i>DIFFERENT CONTENT {scenario_tag}</i>"

    posts_watch_listener_module._trace(
        "match_exact",
        watch_id=watch_identifier_map["matched_exact_watch_identifier"],
        channel_id=1901001001,
        message_id=910001,
        session="smoke_session_exact",
        reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_EXACT_HTML_MATCH,
    )
    posts_watch_listener_module._trace(
        "match_auto_matched_near_exact",
        watch_id=watch_identifier_map["matched_near_exact_watch_identifier"],
        channel_id=1901001002,
        message_id=910002,
        session="smoke_session_near_exact",
        similarity=0.9992,
        similarity_text=1.0,
        similarity_threshold=0.901,
        plain_texts_equal=True,
        links_equal=True,
        reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_NEAR_EXACT_TEXT_LINKS_MATCH,
        expected_links=[f"https://t.me/smoke_near_exact_{scenario_tag}"],
        actual_links=[f"https://t.me/smoke_near_exact_{scenario_tag}"],
        expected_html_length=len(expected_near_exact_html),
        actual_html_length=len(actual_near_exact_html),
        expected_plain_length=len(f"SMOKE near exact {scenario_tag}"),
        actual_plain_length=len(f"SMOKE near exact {scenario_tag}"),
        expected_html_excerpt=expected_near_exact_html,
        actual_html_excerpt=actual_near_exact_html,
        expected_plain_excerpt=f"SMOKE near exact {scenario_tag}",
        actual_plain_excerpt=f"SMOKE near exact {scenario_tag}",
    )
    posts_watch_listener_module._trace(
        "match_candidate",
        watch_id=watch_identifier_map["candidate_watch_identifier"],
        channel_id=1901001003,
        message_id=910003,
        similarity=0.953,
        similarity_text=0.962,
        similarity_threshold=0.70,
        text_hash=f"smoke_candidate_hash_{scenario_tag}",
        reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_SIMILARITY_ABOVE_THRESHOLD,
        expected_links=[f"https://t.me/smoke_candidate_{scenario_tag}"],
        actual_links=[f"https://t.me/smoke_candidate_{scenario_tag}"],
        expected_only_links=[],
        actual_only_links=[],
        expected_html_length=len(expected_candidate_html),
        actual_html_length=len(actual_candidate_html),
        expected_plain_length=len(f"SMOKE CANDIDATE ORIGINAL {scenario_tag}"),
        actual_plain_length=len(f"SMOKE CANDIDATE MODIFIED {scenario_tag}"),
        expected_html_excerpt=expected_candidate_html,
        actual_html_excerpt=actual_candidate_html,
        expected_plain_excerpt=f"SMOKE CANDIDATE ORIGINAL {scenario_tag}",
        actual_plain_excerpt=f"SMOKE CANDIDATE MODIFIED {scenario_tag}",
    )
    posts_watch_listener_module._trace(
        "match_foreign_links_mismatch",
        watch_id=watch_identifier_map["foreign_watch_identifier"],
        channel_id=1901001004,
        message_id=910004,
        similarity=0.941,
        similarity_text=0.947,
        similarity_threshold=0.70,
        reason=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_LINKS_MISMATCH,
        reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_LINKS_MISMATCH,
        expected_links=[f"https://t.me/smoke_foreign_{scenario_tag}"],
        candidate_links=[f"https://t.me/smoke_foreign_other_{scenario_tag}"],
        expected_only_links=[f"https://t.me/smoke_foreign_{scenario_tag}"],
        actual_only_links=[f"https://t.me/smoke_foreign_other_{scenario_tag}"],
        expected_html_length=len(expected_foreign_html),
        actual_html_length=len(actual_foreign_html),
        expected_plain_length=len(f"SMOKE FOREIGN {scenario_tag}"),
        actual_plain_length=len(f"SMOKE FOREIGN {scenario_tag}"),
        expected_html_excerpt=expected_foreign_html,
        actual_html_excerpt=actual_foreign_html,
        expected_plain_excerpt=f"SMOKE FOREIGN {scenario_tag}",
        actual_plain_excerpt=f"SMOKE FOREIGN {scenario_tag}",
    )
    posts_watch_listener_module._trace(
        "match_no_match",
        watch_id=watch_identifier_map["pending_watch_identifier"],
        channel_id=1901001006,
        message_id=910006,
        similarity=0.22,
        similarity_text=0.19,
        similarity_threshold=0.70,
        reason=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_SIMILARITY_BELOW_THRESHOLD,
        reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_SIMILARITY_BELOW_THRESHOLD,
        expected_links=[f"https://t.me/smoke_pending_{scenario_tag}"],
        actual_links=[],
        expected_only_links=[f"https://t.me/smoke_pending_{scenario_tag}"],
        actual_only_links=[],
        expected_html_length=len(expected_no_match_html),
        actual_html_length=len(actual_no_match_html),
        expected_plain_length=len(f"SMOKE NO MATCH EXPECTED {scenario_tag}"),
        actual_plain_length=len(f"DIFFERENT CONTENT {scenario_tag}"),
        expected_html_excerpt=expected_no_match_html,
        actual_html_excerpt=actual_no_match_html,
        expected_plain_excerpt=f"SMOKE NO MATCH EXPECTED {scenario_tag}",
        actual_plain_excerpt=f"DIFFERENT CONTENT {scenario_tag}",
    )
    posts_watch_listener_module._trace(
        "views_done",
        watch_id=watch_identifier_map["matched_near_exact_watch_identifier"],
        channel_id=1901001002,
        message_id=910002,
        views=15320,
        reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_VIEWS_COVERAGE_CHECK,
    )
    posts_watch_listener_module._trace(
        "pending_expired",
        watch_id=watch_identifier_map["expired_watch_identifier"],
        channel_id=1901001005,
        reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_PENDING_WINDOW_EXPIRED,
    )


async def _send_single_notification_batch() -> bool:
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties

    from app.notificator_bot.config import NOTIFIER_BOT_TOKEN, NOTIFIER_TARGET_IDS
    from app.notificator_bot.service import send_notifications

    if not NOTIFIER_BOT_TOKEN:
        print("Notifier send skipped: NOTIFIER_BOT_TOKEN is empty.")
        return False
    if not NOTIFIER_TARGET_IDS:
        print("Notifier send skipped: NOTIFIER_TARGET_IDS is empty.")
        return False

    bot = Bot(
        token=NOTIFIER_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    try:
        await send_notifications(bot, debounce_sec=1)
    finally:
        await bot.session.close()
    return True


def main() -> None:
    command_line_arguments = _parse_command_line_arguments()
    scenario_tag = _build_scenario_tag(command_line_arguments.scenario_tag)

    watch_identifier_map = _seed_watch_rows_for_smoke_scenarios(
        scenario_tag=scenario_tag,
        sleep_between_matches_seconds=command_line_arguments.sleep_between_matches_seconds,
    )
    watch_group_identifier = watch_identifier_map["watch_group_identifier"]

    if not command_line_arguments.skip_trace:
        _emit_trace_events_for_smoke_scenarios(
            watch_identifier_map=watch_identifier_map,
            scenario_tag=scenario_tag,
            trace_log_path=command_line_arguments.trace_log_path,
        )

    notifier_sent_successfully = False
    if command_line_arguments.send_notification:
        notifier_sent_successfully = asyncio.run(_send_single_notification_batch())

    print("Smoke watch scenarios are seeded.")
    print(f"scenario_tag={scenario_tag}")
    print(f"watch_group_identifier={watch_group_identifier}")
    print(f"project=SMOKE_WATCH_TRACE_{scenario_tag}")
    print("watch_identifiers=" + json.dumps(watch_identifier_map, ensure_ascii=False))
    print(f"trace_log_path={command_line_arguments.trace_log_path}")
    print(f"notifier_batch_sent={notifier_sent_successfully}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve/create monitoring template for watch batch")
    parser.add_argument(
        "--db-path",
        default="",
        help="Absolute or relative path to monitoring sqlite database",
    )
    return parser.parse_args()


def _configure_environment(db_path_raw: str) -> None:
    if not db_path_raw:
        return
    db_path = Path(db_path_raw).expanduser().resolve()
    os.environ["DB_PATH"] = str(db_path)
    os.environ["SQLALCHEMY_DATABASE_URL"] = f"sqlite:///{db_path}"


def _read_payload() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("payload_must_be_json_object")
    return payload


def _safe_int(value) -> int | None:
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _first_line_title(text: str) -> str:
    raw_text = str(text or "").strip()
    if not raw_text:
        return ""
    raw_text = re.sub(r"^\W+", "", raw_text, flags=re.UNICODE)
    words = re.findall(r"[\w’'\-]+", raw_text, flags=re.UNICODE)
    words = [word for word in words if re.search(r"\w", word, flags=re.UNICODE)]
    if not words:
        return raw_text[:80]
    return " ".join(words[:2])[:80]


def main() -> int:
    args = _parse_args()
    _configure_environment(args.db_path)

    app_root = Path(__file__).resolve().parents[1]
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))

    try:
        payload = _read_payload()
    except Exception as error:
        print(json.dumps({"status": "error", "error": f"invalid_payload:{error}"}, ensure_ascii=False))
        return 1

    try:
        from app.DAL import post_templates_operations as post_templates_db
        from app.utils.watch_link_extractor import extract_links_from_text_for_watch, normalize_links_for_watch
    except Exception as error:
        print(json.dumps({"status": "error", "error": f"import_failed:{error}"}, ensure_ascii=False))
        return 1

    template_id = _safe_int(payload.get("template_id"))
    expected_html = str(payload.get("expected_html") or "").strip()
    preferred_title = str(payload.get("preferred_title") or "").strip()
    expected_links_json = payload.get("expected_links_json")

    if template_id:
        template_row = post_templates_db.get_template_by_id(int(template_id))
        if template_row:
            existing_links_json = template_row[6]
            if expected_links_json is not None:
                try:
                    raw_links = json.loads(str(expected_links_json or "[]"))
                    if isinstance(raw_links, list):
                        normalized_links = normalize_links_for_watch([str(value or "") for value in raw_links if str(value or "").strip()])
                        existing_links_json = json.dumps(normalized_links, ensure_ascii=False) if normalized_links else None
                except Exception:
                    pass
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "source": "provided",
                        "template_id": int(template_row[0]),
                        "created": False,
                        "expected_html": str(template_row[1] or ""),
                        "title": str(template_row[5] or "") or None,
                        "links_json": existing_links_json,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        if not expected_html:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "error": f"template_not_found:{template_id}",
                    },
                    ensure_ascii=False,
                )
            )
            return 1

    if not expected_html:
        print(json.dumps({"status": "error", "error": "expected_html_empty"}, ensure_ascii=False))
        return 1

    try:
        from app.plugins.posts_watch_listener import _normalize_html_full

        expected_html = _normalize_html_full(expected_html)
    except Exception:
        expected_html = expected_html.strip()

    normalized_links: list[str]
    if expected_links_json is not None:
        parsed_links_payload_is_valid = False
        try:
            payload_links = json.loads(str(expected_links_json or "[]"))
            if isinstance(payload_links, list):
                normalized_links = normalize_links_for_watch([str(value or "") for value in payload_links if str(value or "").strip()])
                parsed_links_payload_is_valid = True
            else:
                normalized_links = []
        except Exception:
            normalized_links = []
        if not parsed_links_payload_is_valid:
            normalized_links = extract_links_from_text_for_watch(expected_html)
    else:
        normalized_links = extract_links_from_text_for_watch(expected_html)
    links_json = json.dumps(normalized_links, ensure_ascii=False) if normalized_links else None

    existing_row = post_templates_db.find_template_exact(text=expected_html, links=links_json)
    if existing_row:
        print(
            json.dumps(
                {
                    "status": "ok",
                    "source": "existing",
                    "template_id": int(existing_row[0]),
                    "created": False,
                    "expected_html": str(existing_row[1] or ""),
                    "title": str(existing_row[5] or "") or None,
                    "links_json": existing_row[6],
                },
                ensure_ascii=False,
            )
        )
        return 0

    resolved_title = preferred_title or _first_line_title(expected_html)
    created_template_id = post_templates_db.add_template(
        text=expected_html,
        mode="exact",
        threshold=1.0,
        title=resolved_title or None,
        links=links_json,
    )

    print(
        json.dumps(
            {
                "status": "ok",
                "source": "created",
                "template_id": int(created_template_id),
                "created": True,
                "expected_html": expected_html,
                "title": resolved_title or None,
                "links_json": links_json,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create watch batch for network from JSON payload")
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
    try:
        payload = json.loads(raw)
    except Exception as error:
        raise ValueError(f"invalid_json_payload: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("payload_must_be_json_object")
    return payload


def main() -> int:
    args = _parse_args()
    _configure_environment(args.db_path)

    app_root = Path(__file__).resolve().parents[1]
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))

    try:
        payload = _read_payload()
    except Exception as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False))
        return 1

    try:
        from app.services.watch_network_batch import (
            WatchBatchCreateCommand,
            create_watches_from_network,
        )
    except Exception as error:
        print(json.dumps({"status": "error", "error": f"import_failed: {error}"}, ensure_ascii=False))
        return 1

    try:
        command = WatchBatchCreateCommand(
            network_id=int(payload.get("network_id") or 0),
            project=payload.get("project"),
            admin_id=payload.get("admin_id"),
            time_window_start=payload.get("time_window_start"),
            time_window_end=payload.get("time_window_end"),
            template_id=payload.get("template_id"),
            expected_html=payload.get("expected_html"),
            expected_links_json=payload.get("expected_links_json"),
            preferred_title=payload.get("preferred_title"),
            created_by=payload.get("created_by"),
            created_via=payload.get("created_via"),
        )
        result = create_watches_from_network(command)
        print(json.dumps(result.to_dict(), ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

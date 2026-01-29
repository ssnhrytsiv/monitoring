#!/usr/bin/env python3
"""
subscription_trace_to_yaml.py

Usage:
  python tools/subscription_trace_to_yaml.py --trace logs/subscription_trace.jsonl --yaml cases_expected.yaml [--db post_watchdog.sqlite3]

Reads JSONL trace produced by subscription_worker (logger 'subscription_trace'),
aggregates per (batch_id, item_id), and updates cases_expected.yaml current_output.
If cases_index.yaml exists with url_norm mapping, it will align cases by url_norm.
Prints mismatch report vs expected.final_status when expected != "TBD".
"""
import argparse
import json
from pathlib import Path
from collections import defaultdict
import sqlite3
import sys
import yaml


def load_trace(path: Path):
    events = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                continue
    return events


def group_events(events):
    grouped = defaultdict(list)
    for ev in events:
        key = (ev.get("batch_id"), ev.get("item_id"))
        grouped[key].append(ev)
    return grouped


def load_yaml(path: Path):
    if not path.exists():
        return {"cases": []}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {"cases": []}


def load_index():
    idx_path = Path("cases_index.yaml")
    if idx_path.exists():
        try:
            data = yaml.safe_load(idx_path.read_text(encoding="utf-8")) or {}
            return {e.get("url_norm"): e.get("id") for e in data.get("cases_index", []) if e.get("url_norm")}
        except Exception:
            return {}
    return {}


def db_snapshot(db_path: Path, url_norm: str, invite_hash: str | None):
    snap = {}
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        snap["link_cache"] = [dict(r) for r in conn.execute("select url_norm,status,channel_id,account from link_cache where url_norm=?", (url_norm,))]
        if invite_hash:
            snap["link_cache_invite"] = [dict(r) for r in conn.execute("select url_norm,status,channel_id,account from link_cache where url_norm=? or url_norm=?", (invite_hash, f"https://t.me/+{invite_hash}",))]
        snap["links"] = [dict(r) for r in conn.execute("select * from links where url_norm=?", (url_norm,))]
    except Exception:
        pass
    return snap


def aggregate_item(ev_list, db_path=None):
    out = {
        "final_status": None,
        "side_effects": {},
        "cache_keys_written": None,
        "queue_transition": None,
        "debug": {},
    }
    cache_hit = next((e for e in ev_list if e.get("event") == "precheck.cache_hit"), None)
    join_res = next((e for e in ev_list if e.get("event") == "slowpath.join_result"), None)
    owner_events = [e for e in ev_list if e.get("event") == "owner_gate"]
    side = next((e for e in ev_list if e.get("event") == "side_effects"), None)
    result_item = next((e for e in ev_list if e.get("event") == "result_item"), None)
    out["debug"]["cache_hit"] = cache_hit
    out["debug"]["join_result"] = join_res
    out["debug"]["last_owner_gate"] = owner_events[-1] if owner_events else None
    if cache_hit:
        out["debug"]["winning_path"] = "precheck_cache"
    elif join_res:
        out["debug"]["winning_path"] = "slowpath"
    elif owner_events:
        out["debug"]["winning_path"] = "precheck_links"
    if side:
        out["side_effects"] = side.get("data", {})
        out["queue_transition"] = side.get("data", {}).get("queue_transition")
        out["cache_keys_written"] = side.get("data", {}).get("cache_keys_written")
        out["final_status"] = side.get("data", {}).get("final_status")
    if result_item and not out.get("final_status"):
        out["final_status"] = result_item.get("data", {}).get("final_status")
    if db_path and ev_list:
        any_ev = ev_list[0]
        snap = db_snapshot(Path(db_path), any_ev.get("url_norm") or any_ev.get("url"), any_ev.get("invite_hash"))
        if snap:
            out.setdefault("debug", {})["db_snapshot"] = snap
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", required=True)
    parser.add_argument("--yaml", required=True)
    parser.add_argument("--db")
    args = parser.parse_args()

    trace_events = load_trace(Path(args.trace))
    grouped = group_events(trace_events)
    yaml_doc = load_yaml(Path(args.yaml))
    cases = yaml_doc.get("cases", [])
    idx = load_index()

    updated = 0
    for case in cases:
        url_norm = case.get("input", {}).get("url_norm") or case.get("current_output", {}).get("url_norm")
        cid = idx.get(url_norm) if url_norm else None
        key = None
        # heuristic: pick first event matching url_norm
        for k, evs in grouped.items():
            if any(e.get("url") == url_norm or e.get("url_norm") == url_norm for e in evs):
                key = k
                break
        if not key:
            continue
        agg = aggregate_item(grouped[key], args.db)
        case.setdefault("current_output", {}).update(agg)
        updated += 1

    with open(args.yaml, "w", encoding="utf-8") as f:
        yaml.safe_dump(yaml_doc, f, allow_unicode=True, sort_keys=False)

    # mismatch report
    for case in cases:
        exp = case.get("expected", {}).get("final_status")
        cur = case.get("current_output", {}).get("final_status")
        if exp and exp != "TBD" and cur and exp != cur:
            dbg = case.get("current_output", {}).get("debug", {})
            print(f"[mismatch] case_id={case.get('id')} expected={exp} current={cur} winning={dbg.get('winning_path')} owner_decision={(dbg.get('last_owner_gate') or {}).get('data',{}).get('decision')}")

if __name__ == "__main__":
    main()

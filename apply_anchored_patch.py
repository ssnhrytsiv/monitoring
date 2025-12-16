import sys, json, re, shutil, argparse, pathlib

def read_text(p):
    return pathlib.Path(p).read_text(encoding="utf-8")

def write_text(p, s):
    pathlib.Path(p).write_text(s, encoding="utf-8")

def backup_file(p):
    shutil.copy2(p, str(p)+".bak")

def apply_replace(content, before, after, allow_multiple=False):
    if allow_multiple:
        if before not in content:
            raise RuntimeError("before not found")
        return content.replace(before, after)
    count = content.count(before)
    if count != 1:
        raise RuntimeError(f"before occurrences != 1 (found {count})")
    return content.replace(before, after, 1)

def apply_insert_after(content, anchor, payload):
    idx = content.find(anchor)
    if idx < 0:
        raise RuntimeError("anchor not found")
    nxt = idx + len(anchor)
    return content[:nxt] + payload + content[nxt:]

def apply_insert_before(content, anchor, payload):
    idx = content.find(anchor)
    if idx < 0:
        raise RuntimeError("anchor not found")
    return content[:idx] + payload + content[idx:]

def apply_regex_replace(content, pattern, repl, count=1, flags=""):
    f = 0
    if "i" in flags: f |= re.IGNORECASE
    if "m" in flags: f |= re.MULTILINE
    if "s" in flags: f |= re.DOTALL
    rx = re.compile(pattern, f)
    if count == 0:
        if not rx.search(content):
            raise RuntimeError("pattern not found")
        return rx.sub(repl, content)
    m = len(rx.findall(content))
    if m != count:
        if m == 0:
            raise RuntimeError("pattern not found")
        raise RuntimeError(f"pattern occurrences != count (found {m}, expected {count})")
    return rx.sub(repl, content, count=count)

def apply_replace_between(content, begin_marker, end_marker, payload, include_markers=False):
    b = content.find(begin_marker)
    if b < 0:
        raise RuntimeError("begin marker not found")
    e = content.find(end_marker, b + len(begin_marker))
    if e < 0:
        raise RuntimeError("end marker not found")
    if include_markers:
        return content[:b] + begin_marker + payload + end_marker + content[e+len(end_marker):]
    return content[:b+len(begin_marker)] + payload + content[e:]

OPS = {
    "replace": apply_replace,
    "insert_after": apply_insert_after,
    "insert_before": apply_insert_before,
    "regex_replace": apply_regex_replace,
    "replace_between": apply_replace_between,
}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("patches_json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    spec = json.loads(pathlib.Path(args.patches_json).read_text(encoding="utf-8"))
    changes = 0

    for op in spec.get("ops", []):
        path = pathlib.Path(op["file"])
        original = read_text(path)
        updated = original
        t = op["type"]

        if t == "replace":
            updated = apply_replace(updated, op["before"], op["after"], op.get("allow_multiple", False))
        elif t == "insert_after":
            updated = apply_insert_after(updated, op["anchor"], op["payload"])
        elif t == "insert_before":
            updated = apply_insert_before(updated, op["anchor"], op["payload"])
        elif t == "regex_replace":
            updated = apply_regex_replace(updated, op["pattern"], op["repl"], int(op.get("count", 1)), op.get("flags", ""))
        elif t == "replace_between":
            updated = apply_replace_between(updated, op["begin"], op["end"], op["payload"], op.get("include_markers", False))
        else:
            raise RuntimeError(f"unknown op type: {t}")

        if updated != original:
            if args.check:
                changes += 1
                continue
            if not args.dry_run:
                backup_file(path)
                write_text(path, updated)
            changes += 1

    if args.check:
        print(changes)
    else:
        print(f"applied:{changes}")

if __name__ == "__main__":
    main()
"""Reconstruct a file from Claude Code session transcripts.

Claude Code stores every session as a JSONL transcript under
  C:\\Users\\<user>\\.claude\\projects\\<project-slug>\\<session-id>.jsonl
Each Write/Edit/MultiEdit tool_use is recorded with full input. If a file
gets clobbered or deleted and there is no git/backup, its exact prior
state can be replayed: take the last Write as the base, then apply every
subsequent Edit/MultiEdit in global timestamp order (across ALL sessions —
a file is often created in one session and edited in another).

Usage:
  py -3 recover_from_transcript.py --name "обзор.md" --list
  py -3 recover_from_transcript.py --name "report.md" --out report.recovered
  py -3 recover_from_transcript.py --path "C:/путь/к/файлу.md" --apply

Match by --name (basename, handy when path separators vary across OS) or
--path (exact file_path match). --list = analyse only. Default writes
<target>.recovered (never touches the live file). --apply overwrites the
target after backing the current version up to <target>.bak-<timestamp>.
"""
import argparse
import datetime
import glob
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def _default_project_dir():
    # Слаг проекта Claude Code: путь текущего каталога, где ':' и разделители -> '-'
    slug = re.sub(r"[:\\/]", "-", str(Path.cwd()))
    return str(Path.home() / ".claude" / "projects" / slug)


DEFAULT_PROJECT_DIR = _default_project_dir()


def basename(p):
    if not p:
        return ""
    return p.replace("\\", "/").rstrip("/").split("/")[-1]


def matches(file_path, want_name, want_path):
    if want_path:
        return file_path.replace("\\", "/") == want_path.replace("\\", "/")
    return basename(file_path) == want_name


def iter_ops(jsonl_path, want_name, want_path):
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            ts = obj.get("timestamp") or ""
            msg = obj.get("message") or {}
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") != "tool_use":
                    continue
                if item.get("name") not in ("Write", "Edit", "MultiEdit"):
                    continue
                inp = item.get("input") or {}
                if matches(inp.get("file_path", ""), want_name, want_path):
                    yield {
                        "ts": ts,
                        "session": os.path.basename(jsonl_path),
                        "line": ln,
                        "name": item.get("name"),
                        "input": inp,
                    }


def apply_edit(state, old, new, replace_all):
    occ = state.count(old)
    if occ == 0:
        return state, 0
    return (state.replace(old, new) if replace_all
            else state.replace(old, new, 1)), occ


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--name", help="target file basename")
    g.add_argument("--path", help="exact file_path as recorded in transcripts")
    ap.add_argument("--project-dir", default=DEFAULT_PROJECT_DIR,
                    help="Claude Code project transcript dir")
    ap.add_argument("--out", help="output path (default <target>.recovered)")
    ap.add_argument("--list", action="store_true",
                    help="analyse only, do not write")
    ap.add_argument("--apply", action="store_true",
                    help="overwrite the live target (backs up current first)")
    ap.add_argument("--force", action="store_true",
                    help="apply even if recovered content looks suspiciously small")
    args = ap.parse_args()

    pattern = os.path.join(args.project_dir, "*.jsonl")
    ops = []
    for jf in sorted(glob.glob(pattern)):
        ops.extend(iter_ops(jf, args.name, args.path))
    ops.sort(key=lambda o: (o["ts"], o["session"], o["line"]))

    print(f"Found {len(ops)} Write/Edit ops across "
          f"{len(set(o['session'] for o in ops))} session(s)")
    for o in ops:
        inp = o["input"]
        if o["name"] == "Write":
            d = f"content={len(inp.get('content',''))}"
        elif o["name"] == "Edit":
            d = (f"old={len(inp.get('old_string',''))} "
                 f"new={len(inp.get('new_string',''))} "
                 f"all={inp.get('replace_all', False)}")
        else:
            d = f"edits={len(inp.get('edits', []))}"
        print(f"  {o['ts']} {o['session'][:8]} L{o['line']:>5} "
              f"{o['name']:9} {d}")

    if not ops:
        print("No ops found — wrong --name/--path or --project-dir?")
        return 2

    state = None
    mism = 0
    for o in ops:
        inp = o["input"]
        if o["name"] == "Write":
            state = inp.get("content", "")
        elif o["name"] == "Edit":
            if state is None:
                mism += 1
                continue
            state, occ = apply_edit(state, inp.get("old_string", ""),
                                    inp.get("new_string", ""),
                                    inp.get("replace_all", False))
            if occ == 0:
                mism += 1
                print(f"  MISMATCH @ {o['session'][:8]} L{o['line']} "
                      f"(old_string not found — chain broken)")
        else:
            if state is None:
                mism += 1
                continue
            for e in inp.get("edits", []):
                state, occ = apply_edit(state, e.get("old_string", ""),
                                        e.get("new_string", ""),
                                        e.get("replace_all", False))
                if occ == 0:
                    mism += 1

    if state is None:
        print("No base Write found — cannot reconstruct (only Edits exist).")
        return 3

    nb = len(state.encode("utf-8"))
    lines = state.splitlines()
    sha = hashlib.sha256(state.encode("utf-8")).hexdigest()[:16]
    print(f"\nReconstructed: {len(state)} chars / {nb} bytes / "
          f"{len(lines)} lines / sha256={sha} / mismatches={mism}")
    print("  first: " + (lines[0] if lines else "<empty>")[:100])
    print("  last : " + (lines[-1] if lines else "<empty>")[:100])

    if args.list:
        return 0

    target = args.path or None
    out = args.out
    if not out:
        out = (target + ".recovered") if target else (args.name + ".recovered")

    if args.apply:
        if not target:
            print("--apply requires --path (need a concrete file to overwrite)")
            return 4
        if mism and not args.force:
            print(f"Refusing --apply: {mism} mismatch(es), chain may be "
                  f"incomplete. Re-run with --force to override.")
            return 5
        if nb < 64 and not args.force:
            print("Refusing --apply: recovered content < 64 bytes "
                  "(suspicious). Use --force.")
            return 5
        if os.path.exists(target):
            ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            bak = f"{target}.bak-{ts}"
            with open(target, "rb") as r, open(bak, "wb") as w:
                w.write(r.read())
            print(f"Backed up current -> {bak}")
        with open(target, "w", encoding="utf-8", newline="") as f:
            f.write(state)
        print(f"APPLIED -> {target}")
    else:
        with open(out, "w", encoding="utf-8", newline="") as f:
            f.write(state)
        print(f"Wrote -> {out} (live file untouched; review then "
              f"--apply or copy manually)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

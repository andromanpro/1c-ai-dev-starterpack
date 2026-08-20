# -*- coding: utf-8 -*-
"""Фактовая часть стартера/хэндоффа — генерируется, не пишется руками.

Собирает из git и тестовых отчётов ПРОВЕРЯЕМЫЕ факты о состоянии репозитория
и печатает markdown-блок для вклейки в СТАРТЕР_*.md (шаблон —
templates/СТАРТЕР-шаблон.md). Нарратив пишется поверх фактов; «✅» прошлых
сессий фактами не являются.

Запуск:
  py -3.14 tools/handoff-facts.py [РЕПО] [--last N] [--test-report GLOB] [--out ФАЙЛ]

РЕПО — каталог git-репозитория (по умолчанию текущий). --last — сколько последних
commit показать (по умолчанию 12). --test-report — образец поиска JUnit-XML
отчётов (например "**/TEST-*.xml"); отчёт старше 24 часов помечается как СТАРЫЙ.
"""
import argparse
import glob
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return r.stdout.strip() if r.returncode == 0 else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--last", type=int, default=12)
    ap.add_argument("--test-report")
    ap.add_argument("--out")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    if not git(repo, "rev-parse", "--git-dir"):
        print(f"ОШИБКА: {repo} — не git-репозиторий", file=sys.stderr)
        return 1

    lines: list[str] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append(f"## Факты (handoff-facts.py, {now} — не править руками, перегенерировать)")
    lines.append("")

    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    head = git(repo, "log", "-1", "--format=%h %ad %s", "--date=format:%Y-%m-%d %H:%M")
    lines.append(f"- Репозиторий: `{repo}`")
    lines.append(f"- Ветка: `{branch}`, HEAD: {head}")

    status = git(repo, "status", "--porcelain")
    if status:
        rows = status.splitlines()
        untracked = sum(1 for s in rows if s.startswith("??"))
        modified = len(rows) - untracked
        lines.append(f"- Рабочее дерево: ГРЯЗНОЕ — изменённых {modified}, неотслеживаемых {untracked}")
        for s in rows[:10]:
            lines.append(f"  - `{s.strip()}`")
        if len(rows) > 10:
            lines.append(f"  - … и ещё {len(rows) - 10}")
    else:
        lines.append("- Рабочее дерево: чистое")

    remotes = git(repo, "remote").splitlines()
    for rem in remotes:
        if not git(repo, "rev-parse", "--verify", "--quiet", f"{rem}/{branch}"):
            lines.append(f"- Синхронизация с `{rem}`: ветки `{branch}` там нет")
            continue
        ahead = git(repo, "rev-list", "--count", f"{rem}/{branch}..HEAD") or "0"
        behind = git(repo, "rev-list", "--count", f"HEAD..{rem}/{branch}") or "0"
        mark = "в синхроне" if ahead == behind == "0" else f"⚠ впереди на {ahead}, позади на {behind} (по локальному снимку, без fetch)"
        lines.append(f"- Синхронизация с `{rem}`: {mark}")

    lines.append("")
    lines.append(f"### Последние коммиты ({args.last})")
    lines.append("")
    log = git(repo, "log", f"-{args.last}", "--format=- %h %ad %s", "--date=format:%m-%d %H:%M")
    lines.append(log or "- (пусто)")

    stat = git(repo, "diff", "--stat", f"HEAD~{min(args.last, 5)}..HEAD")
    if stat:
        tail = stat.splitlines()[-1].strip()
        lines.append("")
        lines.append(f"- Сводка изменений последних {min(args.last, 5)} коммитов: {tail}")

    if args.test_report:
        lines.append("")
        lines.append("### Тестовые отчёты")
        lines.append("")
        found = sorted(glob.glob(str(repo / args.test_report), recursive=True))
        if not found:
            lines.append(f"- по образцу `{args.test_report}` отчётов НЕ найдено — статус тестов НЕИЗВЕСТЕН")
        for f in found[:10]:
            p = Path(f)
            age_h = (time.time() - p.stat().st_mtime) / 3600
            stale = f" ⚠ СТАРЫЙ ({age_h:.0f} ч)" if age_h > 24 else ""
            try:
                root = ET.parse(p).getroot()
                suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
                t = sum(int(s.get("tests", 0)) for s in suites)
                fails = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
                verdict = "зелёный" if fails == 0 else f"КРАСНЫЙ ({fails} провалов)"
                lines.append(f"- `{p.name}`: {t} тестов, {verdict}{stale}")
            except ET.ParseError:
                lines.append(f"- `{p.name}`: НЕ РАЗОБРАН (битый XML){stale}")

    lines.append("")
    lines.append("> Напоминание: «✅/готово» из прошлых сессий — непроверенные утверждения,")
    lines.append("> пока не подтверждены прогоном в текущей. Нарратив пишется ПОВЕРХ этого блока.")

    out = "\n".join(lines)
    if args.out:
        Path(args.out).write_text(out + "\n", encoding="utf-8")
        print(f"записано: {args.out}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

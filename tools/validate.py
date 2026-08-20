# -*- coding: utf-8 -*-
"""Проверка перед публикацией: секреты, адреса, личные пути, приватный словарь, англицизмы.

Публичный слой (этот файл, в репозитории): общие проверки + самотест.
Приватный слой (у владельца, ВНЕ репозитория): словарь запрещённых имён,
подключается параметром --deny-file или лежит в <репо>/../_private/словарь-запретов.txt.
В CI приватного словаря нет — проверка сообщает об этом и не падает;
перед экспортом наружу запуск с приватным словарём обязателен (--require-deny).

Запуск:  py -3.14 tools/validate.py [--selftest] [--deny-file ПУТЬ] [--require-deny] [--strict-lang]
Выход: 0 — чисто; 1 — нарушения или провал самотеста.
"""
import argparse
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parent.parent
SCAN_EXT = {".md", ".txt", ".yml", ".yaml", ".json", ".py", ".bsl", ".os", ".feature"}
SKIP_DIRS = {".git", "fixtures", "__pycache__", "node_modules"}
# Сам валидатор — единственный файл, которому положено содержать запрещённые образцы.
# Файл терминов — словарь замен, ему положено содержать англицизмы (см. lang_check).
SKIP_FILES = {"validate.py"}
NO_LANG_CHECK_FILES = {"термины.md"}

# Секреты и ключи — без исключений
SECRETS = [
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "токен GitHub"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "токен GitHub (fine-grained)"),
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "ключ API (sk-)"),
    (re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"), "приватный ключ"),
    (re.compile(r"Authorization:\s*(token|Bearer)\s+\S{16,}", re.I), "заголовок авторизации со значением"),
    (re.compile(r"(пароль|password)\s*[=:]\s*\S+", re.I), "пароль в открытом виде"),
]

# Внутренние адреса — без исключений
NETWORK = [
    (re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b"), "внутренний IP-адрес"),
    (re.compile(r"\b172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"), "внутренний IP-адрес"),
]

# Личные пути и следы машины автора — допускают разрешённые исключения
PERSONAL = [
    (re.compile(r"[FfDdGg]:[\\/]+WorkAI", re.I), "личный путь (WorkAI)"),
    (re.compile(r"[Cc]:[\\/]+Users[\\/]+(?!ИмяПользователя|<)", ), "личный путь (C:/Users/)"),
    (re.compile(r"[Dd]:[\\/]+home\b"), "личный путь (D:/home)"),
    (re.compile(r"EDT_Workspace"), "личный путь (EDT_Workspace)"),
    (re.compile(r"\bRoono\b"), "имя учётной записи автора"),
    (re.compile(r"[\w.+-]+@(?!example\.|носайта\.)[\w-]+\.\w{2,}"), "адрес почты"),
]

# Разрешённые исключения — только для категории PERSONAL (намеренная атрибуция)
ALLOW = ("androman.pro", "Roman Andriyanov", "andromanpro", "noreply"),

# Англицизмы (предупреждение; --strict-lang превращает в нарушение)
LANG = re.compile(
    r"\b(гейт\w*|скилл\w*|воркфлоу\w*|сетап\w*|квикстарт\w*|роадмап\w*|стейджинг\w*"
    r"|скоуп\w*|смоук\w*|аллоулист\w*|quickstart|hardening|allowlist|DoD)\b",
    re.I,
)


def line_allowed(line: str) -> bool:
    return any(a in line for a in ALLOW[0])


def scan_file(path: Path, deny: list[str], lang_check: bool = True):
    findings, warnings = [], []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings, warnings
    for n, line in enumerate(text.splitlines(), 1):
        for rx, what in SECRETS + NETWORK:
            if rx.search(line):
                findings.append((path, n, what, line.strip()[:100]))
        for rx, what in PERSONAL:
            if rx.search(line) and not line_allowed(line):
                findings.append((path, n, what, line.strip()[:100]))
        low = line.lower()
        for word in deny:
            if word in low:
                findings.append((path, n, f"запрещённое имя «{word}»", line.strip()[:100]))
        if lang_check:
            m = LANG.search(line)
            if m:
                warnings.append((path, n, f"англицизм «{m.group(0)}» — см. docs/термины.md"))
    return findings, warnings


def scan_tree(root: Path, deny: list[str]):
    findings, warnings = [], []
    for path in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in SCAN_EXT or not path.is_file():
            continue
        if path.name in SKIP_FILES:
            continue
        f, w = scan_file(path, deny, lang_check=path.name not in NO_LANG_CHECK_FILES)
        findings += f
        warnings += w
    return findings, warnings


def load_deny(args) -> tuple[list[str], bool]:
    candidates = []
    if args.deny_file:
        candidates.append(Path(args.deny_file))
    candidates.append(REPO.parent / "_private" / "словарь-запретов.txt")
    for c in candidates:
        if c.is_file():
            words = [
                w.strip().lower()
                for w in c.read_text(encoding="utf-8").splitlines()
                if w.strip() and not w.startswith("#")
            ]
            return words, True
    return [], False


def selftest() -> int:
    fx = REPO / "tools" / "tests" / "fixtures"
    deny = [
        w.strip().lower()
        for w in (fx / "тест-словарь.txt").read_text(encoding="utf-8").splitlines()
        if w.strip() and not w.startswith("#")
    ]
    dirty_f, _ = scan_file(fx / "грязная.md", deny)
    clean_f, _ = scan_file(fx / "чистая.md", deny)
    kinds = {what for _, _, what, _ in dirty_f}
    ok = True
    if len(dirty_f) < 5 or len(kinds) < 4:
        print(f"САМОТЕСТ ПРОВАЛЕН: грязная фикстура дала {len(dirty_f)} наход. / {len(kinds)} категорий (ждали >=5 / >=4)")
        ok = False
    if clean_f:
        print(f"САМОТЕСТ ПРОВАЛЕН: чистая фикстура дала {len(clean_f)} находок (ждали 0)")
        for p, n, what, frag in clean_f:
            print(f"  {p.name}:{n} {what}: {frag}")
        ok = False
    print("Самотест: ПРОЙДЕН" if ok else "Самотест: ПРОВАЛ")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--deny-file")
    ap.add_argument("--require-deny", action="store_true")
    ap.add_argument("--strict-lang", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    deny, deny_loaded = load_deny(args)
    if not deny_loaded:
        msg = "приватный словарь не найден — прогнан только публичный слой"
        if args.require_deny:
            print(f"ОШИБКА: {msg} (а требовался: --require-deny)")
            return 1
        print(f"Предупреждение: {msg}. Перед экспортом наружу — запуск с --require-deny.")

    findings, warnings = scan_tree(REPO, deny)
    for p, n, what, frag in findings:
        print(f"НАРУШЕНИЕ {p.relative_to(REPO)}:{n} [{what}] {frag}")
    shown = warnings[:20]
    for p, n, what in shown:
        print(f"предупреждение {p.relative_to(REPO)}:{n} {what}")
    if len(warnings) > len(shown):
        print(f"... и ещё {len(warnings) - len(shown)} предупреждений о языке")

    print(f"Итог: нарушений {len(findings)}, предупреждений {len(warnings)}")
    if findings:
        return 1
    if args.strict_lang and warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

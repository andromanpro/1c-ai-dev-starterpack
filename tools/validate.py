# -*- coding: utf-8 -*-
"""Проверка перед публикацией: секреты, адреса, личные пути, приватный словарь, язык.

Публичный слой (этот файл, в репозитории): общие классы утечек + самотест
на встроенных образцах (файлов-фикстур нет намеренно: образец «грязи» в публичном
репозитории сам был бы утечкой и кормом для сторонних сканеров секретов).
Приватный слой (у владельца, ВНЕ репозитория): словарь запрещённых имён —
параметр --deny-file или <репо>/../_private/словарь-запретов.txt.
В CI приватного словаря нет — проверка сообщает и не падает; перед экспортом
наружу обязателен запуск с --require-deny.

Найденные секреты в вывод НЕ печатаются (маскируются) — журнал CI публичен.

Запуск:  py -3 tools/validate.py [--selftest] [--deny-file ПУТЬ] [--require-deny] [--strict-lang]
         [--git-log ДИАПАЗОН] — проверить и сообщения коммитов: файл перед публикацией
         можно вычистить, а сообщение коммита уезжает в историю навсегда.
Выход: 0 — чисто; 1 — нарушения или провал самотеста.
"""
import argparse
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parent.parent
SCAN_EXT = {
    ".md", ".txt", ".yml", ".yaml", ".json", ".py", ".bsl", ".os", ".feature",
    ".toml", ".ini", ".cfg", ".env", ".ps1", ".bat", ".cmd", ".xml", ".sh",
}
SKIP_DIRS = {".git", "__pycache__", "node_modules"}
# Сам валидатор — единственный файл, которому положено содержать образцы запретов.
# Файл терминов — словарь замен, ему положено содержать англицизмы.
SKIP_FILES = {"validate.py"}
NO_LANG_CHECK_FILES = {"термины.md", "starter-facts-guard.py"}

# (образец, название, маскировать_ли_фрагмент)
SECRETS = [
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "токен GitHub", True),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "токен GitHub (fine-grained)", True),
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "ключ API (sk-)", True),
    (re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"), "приватный ключ", True),
    (re.compile(r"Authorization:\s*(token|Bearer)\s+\S{16,}", re.I), "заголовок авторизации со значением", True),
    (re.compile(r"(пароль|password)\s*[=:]\s*\S+", re.I), "пароль в открытом виде", True),
]

PRIVATE_IP = re.compile(
    r"\b(192\.168|172\.(?:1[6-9]|2\d|3[01])|10)\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b"
)

# Личные следы; допускают разрешённые исключения по САМОМУ совпадению
PERSONAL = [
    (re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+(?!ИмяПользователя|<)[^\\/\s\"']+"), "личный путь (Users)"),
    (re.compile(r"[\w.+-]+@[\w-]+\.\w{2,}"), "адрес почты"),
]
ALLOW_FRAGMENT = ("example.", "носайта.", "noreply", "androman.pro")

LANG = re.compile(
    r"\b(гейт\w*|скилл\w*|воркфлоу\w*|сетап\w*|квикстарт\w*|роадмап\w*|стейджинг\w*"
    r"|скоуп\w*|смоук\w*|аллоулист\w*|хэндофф\w*|хендофф\w*|нарратив\w*|залогир\w*"
    r"|quickstart|hardening|allowlist|environment|troubleshooting|end-to-end|DoD)\b",
    re.I,
)


def ip_is_real(m: re.Match) -> bool:
    try:
        return all(int(m.group(i)) <= 255 for i in (2, 3, 4))
    except ValueError:
        return False


def fragment_allowed(fragment: str) -> bool:
    low = fragment.lower()
    return any(a in low for a in ALLOW_FRAGMENT)


MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def scan_file(path: Path, deny: list[str], lang_check: bool = True):
    findings, warnings = [], []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings, warnings
    if path.suffix.lower() == ".md":
        for n, line in enumerate(text.splitlines(), 1):
            for m in MD_LINK.finditer(line):
                target = m.group(1)
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                rel = target.split("#")[0]
                if rel and not (path.parent / rel).exists():
                    findings.append((path, n, "битая ссылка", rel))
    for n, line in enumerate(text.splitlines(), 1):
        for rx, what, mask in SECRETS:
            if rx.search(line):
                findings.append((path, n, what, "«скрыто»" if mask else line.strip()[:100]))
        m = PRIVATE_IP.search(line)
        if m and ip_is_real(m):
            findings.append((path, n, "внутренний IP-адрес", "«скрыто»"))
        for rx, what in PERSONAL:
            m = rx.search(line)
            if m and not fragment_allowed(m.group(0)):
                findings.append((path, n, what, m.group(0)[:80]))
        low = line.lower()
        for word in deny:
            if word in low:
                findings.append((path, n, f"запрещённое имя «{word}»", "строка скрыта"))
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


def scan_commit_messages(root: Path, deny: list[str], rev_range: str):
    """Те же правила — по сообщениям коммитов, а не по файлам.

    Отдельная поверхность утечки: файл можно вычистить перед публикацией, а
    сообщение коммита уезжает в публичную историю навсегда и правится только
    переписыванием истории (а после публикации — ещё и с обращением к хостингу
    за удалением висячих объектов). Проверка файлов этого не видит — ровно так
    имена внутренних систем и попадают наружу.

    Возвращает (находки, удалось_ли_прочитать): «не репозиторий» и «нет
    коммитов» обязаны отличаться от «чисто», иначе молчание сойдёт за успех.
    """
    import subprocess

    marker = "@@КОММИТ@@"
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "log", "--format=" + marker + "%h %s %b", rev_range],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError:
        return [], False
    if out.returncode != 0:
        return [], False

    findings = []
    for chunk in out.stdout.split(marker):
        message = " ".join(chunk.split())
        if not message:
            continue
        sha = message.split(" ", 1)[0]
        low = message.lower()
        for rx, what, mask in SECRETS:
            if rx.search(message):
                findings.append((sha, what, "«скрыто»"))
        for word in deny:
            if word in low:
                findings.append((sha, "запрещённое имя «" + word + "»", "сообщение скрыто"))
    return findings, True


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


def _dirty_sample() -> str:
    # Образцы собираются конкатенацией, чтобы файл валидатора сам не выглядел утечкой
    return "\n".join([
        "Токен утёк: " + "ghp_" + "A" * 30,
        "Сервер живёт на 192.168." + "77.55 — внутренняя сеть.",
        "Профиль лежит в " + "C:/Users/" + "Иванов77/.claude/settings.json",
        "Пишите на ящик " + "vasya.pupkin" + "@" + "primer-pochty.ru",
        "Пароль = " + "СуперСекрет123",
        "По проекту " + "тестзапретноеимя" + " вопросы к аналитику.",
    ])


def _clean_sample() -> str:
    return "\n".join([
        "Обычный текст инструкции. Скопируйте базу в C:/Users/ИмяПользователя/базы/копия.",
        "Версия платформы 8.3.27, сборка Windows 10.0.19045 — не адрес.",
        "Пример почты в документации: support@example.com.",
        "Автор набора: Roman Andriyanov (androman.pro).",
        "Правки вносите через PR, сборка проверяется CI.",
    ])


def selftest() -> int:
    import tempfile, os
    deny = ["тестзапретноеимя"]
    ok = True
    with tempfile.TemporaryDirectory() as td:
        dirty = Path(td) / "грязный-образец.md"
        clean = Path(td) / "чистый-образец.md"
        dirty.write_text(_dirty_sample(), encoding="utf-8")
        clean.write_text(_clean_sample(), encoding="utf-8")
        dirty_f, _ = scan_file(dirty, deny)
        clean_f, _ = scan_file(clean, deny)
    kinds = {what for _, _, what, _ in dirty_f}
    if len(dirty_f) < 5 or len(kinds) < 5:
        print(f"САМОТЕСТ ПРОВАЛЕН: грязный образец дал {len(dirty_f)} наход. / {len(kinds)} категорий (ждали >=5 / >=5)")
        ok = False
    if clean_f:
        print(f"САМОТЕСТ ПРОВАЛЕН: чистый образец дал {len(clean_f)} находок (ждали 0)")
        for p, n, what, frag in clean_f:
            print(f"  строка {n}: {what}: {frag}")
        ok = False
    # Маскирование: секретные категории не должны попадать в вывод фрагментом
    masked = all(frag == "«скрыто»" for _, _, what, frag in dirty_f
                 if what in {w for _, w, m in SECRETS if m} or what == "внутренний IP-адрес")
    if not masked:
        print("САМОТЕСТ ПРОВАЛЕН: секретная находка напечатана открытым текстом")
        ok = False
    print("Самотест: ПРОЙДЕН" if ok else "Самотест: ПРОВАЛ")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--deny-file")
    ap.add_argument("--require-deny", action="store_true")
    ap.add_argument("--strict-lang", action="store_true")
    ap.add_argument("--git-log", metavar="ДИАПАЗОН",
                    help="проверить и сообщения коммитов, напр. origin/main..HEAD или --all")
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

    commit_findings = []
    if args.git_log:
        commit_findings, ran = scan_commit_messages(REPO, deny, args.git_log)
        if not ran:
            print(f"ОШИБКА: не удалось прочитать историю git по диапазону «{args.git_log}»")
            return 1
        for sha, what, frag in commit_findings:
            print(f"НАРУШЕНИЕ коммит {sha} [{what}] {frag}")

    total = len(findings) + len(commit_findings)
    tail = f" (в сообщениях коммитов: {len(commit_findings)})" if commit_findings else ""
    print(f"Итог: нарушений {total}, предупреждений {len(warnings)}" + tail)
    if findings or commit_findings:
        return 1
    if args.strict_lang and warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

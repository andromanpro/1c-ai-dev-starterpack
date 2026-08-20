# -*- coding: utf-8 -*-
"""Контрольная точка приёмки 2 (стенд).

Проверяет три исправления в модуле ОбменЗаказами.bsl:
  1) поиск контрагента по наименованию убран из цикла (один запрос до цикла);
  2) блок Исключение не пустой (ошибка логируется или пробрасывается);
  3) ТребуетсяСогласование инициализируется до условия.

На ИСХОДНОМ модуле проверка обязана быть красной — это её самотест:
  py -3.14 проверка-стенда.py --selftest
Обычный запуск:
  py -3.14 проверка-стенда.py src/ОбменЗаказами.bsl
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def check(text: str) -> list[tuple[str, bool]]:
    results = []

    # 1. НайтиПоНаименованию внутри блока "Для Каждого ... КонецЦикла"
    loop = re.search(r"Для\s+Каждого.*?КонецЦикла", text, re.S | re.I)
    in_loop = bool(loop and re.search(r"НайтиПоНаименованию", loop.group(0), re.I))
    results.append(("поиск по наименованию вынесен из цикла", not in_loop))

    # 2. Блок Исключение ... КонецПопытки содержит исполняемый код
    exc = re.search(r"Исключение(.*?)КонецПопытки", text, re.S | re.I)
    has_code = False
    if exc:
        for line in exc.group(1).splitlines():
            s = line.strip()
            if s and not s.startswith("//"):
                has_code = True
                break
    results.append(("блок Исключение не пустой (ошибка не глотается)", has_code))

    # 3. ТребуетсяСогласование инициализируется до условия "Если"
    func = re.search(r"Функция\s+СформироватьСтрокуВыгрузки(.*?)КонецФункции", text, re.S | re.I)
    initialized = False
    if func:
        body = func.group(1)
        first_if = re.search(r"^\s*Если\b", body, re.M | re.I)
        assign = re.search(r"^\s*ТребуетсяСогласование\s*=", body, re.M | re.I)
        initialized = bool(assign and first_if and assign.start() < first_if.start())
    results.append(("ТребуетсяСогласование инициализируется до условия", initialized))

    return results


def run(path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    results = check(text)
    failed = 0
    for name, ok in results:
        print(("ЗЕЛЁНАЯ " if ok else "КРАСНАЯ ") + "— " + name)
        failed += 0 if ok else 1
    print(f"Итог: {len(results) - failed}/{len(results)} исправлено")
    return 0 if failed == 0 else 1


def selftest() -> int:
    src = Path(__file__).resolve().parent / "src" / "ОбменЗаказами.bsl"
    results = check(src.read_text(encoding="utf-8", errors="replace"))
    bad = sum(1 for _, ok in results if not ok)
    if bad == 3:
        print("Самотест: ПРОЙДЕН — на исходном модуле все 3 проверки красные")
        return 0
    print(f"Самотест: ПРОВАЛ — на исходном модуле красных {bad}, ожидалось 3")
    return 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if len(sys.argv) < 2:
        print("укажите путь к модулю: py -3.14 проверка-стенда.py src/ОбменЗаказами.bsl")
        sys.exit(2)
    sys.exit(run(Path(sys.argv[1])))

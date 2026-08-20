# -*- coding: utf-8 -*-
"""Контрольная точка приёмки 2 (стенд).

Проверяет три исправления в модуле по требованиям приёмки:
  1) поиск по наименованию убран из цикла И появился запрос до цикла;
  2) в блоке Исключение — запись в журнал регистрации (не пустышка и не заглушка);
  3) ТребуетсяСогласование инициализируется значением Истина/Ложь до условия.

Это ЭВРИСТИКА по тексту исходника: она ловит типовые обходы, но не заменяет
просмотр разницы человеком — приёмка глазами обязательна (см. приемка-2-цикл.md).

На ИСХОДНОМ модуле проверка обязана быть красной — это её самотест:
  py -3 проверка-стенда.py --selftest
Обычный запуск (из корня набора):
  py -3 стенд/проверка-стенда.py стенд/src/ОбменЗаказами-моя.bsl
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def check(text: str) -> list[tuple[str, bool]]:
    results = []

    # 1. Поиск убран из цикла обхода заказов, взамен появился запрос (и не в цикле)
    loop = re.search(r"Для\s+Каждого.*?КонецЦикла", text, re.S | re.I)
    loop_text = loop.group(0) if loop else ""
    find_in_loop = bool(re.search(r"НайтиПоНаименованию", loop_text, re.I))
    query_anywhere = bool(re.search(r"Новый\s+Запрос", text, re.I))
    query_in_loop = bool(re.search(r"Новый\s+Запрос", loop_text, re.I))
    results.append(("поиск вынесен из цикла, контрагенты получены запросом",
                    (not find_in_loop) and query_anywhere and (not query_in_loop)))

    # 2. В блоке Исключение — именно запись в журнал регистрации
    exc = re.search(r"Исключение(.*?)КонецПопытки", text, re.S | re.I)
    logs_error = bool(exc and re.search(r"ЗаписьЖурналаРегистрации", exc.group(1), re.I))
    results.append(("в блоке Исключение — ЗаписьЖурналаРегистрации", logs_error))

    # 3. ТребуетсяСогласование инициализируется значением Истина/Ложь до условия
    func = re.search(r"Функция\s+СформироватьСтрокуВыгрузки(.*?)КонецФункции", text, re.S | re.I)
    initialized = False
    if func:
        body = func.group(1)
        first_if = re.search(r"^\s*Если\b", body, re.M | re.I)
        assign = re.search(r"^\s*ТребуетсяСогласование\s*=\s*(Истина|Ложь)\s*;", body, re.M | re.I)
        initialized = bool(assign and first_if and assign.start() < first_if.start())
    results.append(("ТребуетсяСогласование инициализируется Истина/Ложь до условия", initialized))

    return results


def run(path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    results = check(text)
    failed = 0
    for name, ok in results:
        print(("ЗЕЛЁНАЯ " if ok else "КРАСНАЯ ") + "— " + name)
        failed += 0 if ok else 1
    print(f"Итог: {len(results) - failed}/{len(results)} исправлено")
    print("Напоминание: точка — эвристика; приёмка человеком (просмотр разницы) обязательна.")
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

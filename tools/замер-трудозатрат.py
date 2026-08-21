# -*- coding: utf-8 -*-
"""Замер времени работы по журналам сессий агента — объединением интервалов.

Главная ловушка, ради которой написан отдельный инструмент: **параллельные сессии**.
Сессии агента накладываются во времени — фоновая задача, вторая среда, забытая
открытой вкладка. Сложение длительностей считает пересечения дважды и даёт
неправдоподобный итог: на реальном контуре так получилось 18,6 часа за сутки.
Здесь интервалы объединяются, а сумма печатается рядом — чтобы разрыв между ними
был виден, а не спрятан.

Вторая защита — потолок: в сутках 24 часа. Если посчитанное превышает физический
предел, это ошибка счёта, а не рекорд производительности; инструмент говорит
об этом прямо и возвращает ненулевой код.

Запуск:
    py -3 tools/замер-трудозатрат.py --logs <каталог с *.jsonl> [--days 7]
    py -3 tools/замер-трудозатрат.py --logs <каталог> --since 2026-08-01

Формат журналов — построчный JSON с полем времени (`timestamp`). Инструмент не
привязан к конкретной среде: подойдёт любой источник, где у записи есть время
и идентификатор сессии (имя файла).
"""
import argparse
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# Разрыв, после которого сессия считается прерванной: агент мог простоять ночь
# с открытым журналом, и этот простой не является работой.
IDLE_BREAK = timedelta(minutes=30)


def parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def session_intervals(path: Path):
    """Интервалы активности внутри одного журнала.

    Не «первая и последняя запись»: между ними бывают часы простоя. Поток
    времён режется по разрыву IDLE_BREAK, и каждый кусок — отдельный интервал.
    """
    times = []
    try:
        with io.open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                t = parse_time(rec.get("timestamp") or rec.get("time") or rec.get("ts"))
                if t:
                    times.append(t)
    except OSError:
        return []
    if not times:
        return []
    times.sort()
    intervals, start, prev = [], times[0], times[0]
    for t in times[1:]:
        if t - prev > IDLE_BREAK:
            intervals.append((start, prev))
            start = t
        prev = t
    intervals.append((start, prev))
    return [(a, b) for a, b in intervals if b > a]


def union_duration(intervals):
    """Длительность объединения интервалов — то, сколько времени реально шла работа."""
    if not intervals:
        return timedelta(0)
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return sum((end - start for start, end in merged), timedelta(0))


def fmt(td: timedelta) -> str:
    total = int(td.total_seconds())
    return f"{total // 3600} ч {total % 3600 // 60} мин"


def main() -> int:
    ap = argparse.ArgumentParser(description="Время работы по журналам сессий: объединение, а не сумма")
    ap.add_argument("--logs", required=True, help="каталог с журналами сессий (*.jsonl)")
    ap.add_argument("--days", type=int, default=7, help="за сколько последних суток считать (по умолчанию 7)")
    ap.add_argument("--since", help="считать с даты ГГГГ-ММ-ДД (перебивает --days)")
    args = ap.parse_args()

    root = Path(args.logs)
    if not root.is_dir():
        print(f"не каталог: {root}")
        return 2

    if args.since:
        try:
            since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
        except ValueError:
            print("дата в формате ГГГГ-ММ-ДД")
            return 2
    else:
        since = datetime.now(timezone.utc) - timedelta(days=args.days)

    per_day = {}
    files = sorted(root.rglob("*.jsonl"))
    for path in files:
        for start, end in session_intervals(path):
            if end < since:
                continue
            per_day.setdefault(start.date(), []).append((start, end))

    if not per_day:
        # Пустой результат обязан отличаться от «работы не было»: чаще это значит,
        # что каталог указан не тот или формат журналов другой.
        print(f"журналов с записями не найдено: просмотрено файлов {len(files)}, каталог {root}")
        return 1

    print(f"файлов журналов: {len(files)}, дней с активностью: {len(per_day)}\n")
    print(f"{'дата':12s} {'объединение':>14s} {'сумма':>12s} {'двойной счёт':>14s}  сессий")
    problems = 0
    total_union = timedelta(0)
    for day in sorted(per_day):
        intervals = per_day[day]
        union = union_duration(intervals)
        naive = sum((end - start for start, end in intervals), timedelta(0))
        overlap = naive - union
        total_union += union
        flag = ""
        if naive > timedelta(hours=24):
            flag, problems = "  ⚠ сумма больше суток — считать сложением нельзя", problems + 1
        print(f"{day.isoformat():12s} {fmt(union):>14s} {fmt(naive):>12s} {fmt(overlap):>14s}  {len(intervals)}{flag}")

    print(f"\nитого объединением: {fmt(total_union)}")
    if problems:
        print(f"дней с невозможной суммой: {problems} — это ловушка параллельных сессий, а не рекорд")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

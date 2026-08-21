# -*- coding: utf-8 -*-
"""Снимок состояния каталога множествами идентификаторов, а не счётчиками.

Зачем не счётчики. Счётчик не замечает подмену: удалили один объект, создали
другой — было 10, стало 10, «изменений нет». Тест, убравший за собой чужое
и создавший своё, покажет ровно тот же счётчик, что и честный прогон. Поэтому
здесь сравниваются МНОЖЕСТВА идентификаторов с их признаками: видно, что именно
исчезло, что появилось и что изменилось, не меняя количества.

Типовое применение — рамка вокруг любого прогона, который трогает общую среду:

    py -3 tools/снимок-состояния.py before.json --path <каталог>
    <прогон тестов, обмена, обработки>
    py -3 tools/снимок-состояния.py after.json --path <каталог>
    py -3 tools/снимок-состояния.py --diff before.json after.json

Выход `--diff`: код 0 — состояние совпало; код 1 — есть расхождения. Так снимок
годится шагом конвейера, а не только для чтения глазами.

Для данных информационной базы (справочники, регистры, задания) тот же приём
переносится один в один: вместо файлов — выборка ссылок с реквизитами, вместо
хэша содержимого — представление и ключевые поля.
"""
import argparse
import hashlib
import io
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".claude", "target", "build"}


def file_signature(path: Path, with_hash: bool) -> dict:
    """Признаки файла: размер и, по требованию, хэш содержимого.

    Хэш опционален намеренно: на больших деревьях он дорог, а для многих
    сценариев достаточно размера и состава. Но именно хэш ловит правку
    «в тот же размер», поэтому для контроля чужой среды он включается.
    """
    st = path.stat()
    sig = {"size": st.st_size}
    if with_hash:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        sig["sha256"] = h.hexdigest()[:16]
    return sig


def take(root: Path, with_hash: bool) -> dict:
    items = {}
    for path in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        try:
            items[rel] = file_signature(path, with_hash)
        except OSError as e:
            # Недоступный файл — это факт состояния, а не повод молча его пропустить:
            # исчезнувшая или залоченная позиция должна быть видна в сравнении.
            items[rel] = {"error": type(e).__name__}
    return {"root": str(root), "count": len(items), "items": items}


def diff(before: dict, after: dict) -> int:
    a, b = before["items"], after["items"]
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])

    print(f"было: {len(a)}, стало: {len(b)}")
    # Равенство счётчиков печатается отдельной строкой именно потому, что оно
    # обманчиво: одинаковое количество при непустых списках ниже — это подмена.
    if len(a) == len(b) and (added or removed):
        print("⚠ количество совпало, но состав изменился — счётчик такое пропускает")
    for title, group in (("появилось", added), ("исчезло", removed), ("изменилось", changed)):
        if group:
            print(f"\n{title} ({len(group)}):")
            for k in group[:40]:
                print(f"  {k}")
            if len(group) > 40:
                print(f"  … и ещё {len(group) - 40}")
    if not (added or removed or changed):
        print("состояние совпало")
        return 0
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Снимок состояния множествами, а не счётчиками")
    ap.add_argument("out", nargs="?", help="файл снимка (при съёмке)")
    ap.add_argument("--path", help="каталог для съёмки")
    ap.add_argument("--hash", action="store_true", help="считать хэш содержимого (медленнее, ловит правку в тот же размер)")
    ap.add_argument("--diff", nargs=2, metavar=("ДО", "ПОСЛЕ"), help="сравнить два снимка")
    args = ap.parse_args()

    if args.diff:
        before = json.load(io.open(args.diff[0], encoding="utf-8"))
        after = json.load(io.open(args.diff[1], encoding="utf-8"))
        return diff(before, after)

    if not args.out or not args.path:
        ap.error("нужны файл снимка и --path, либо --diff ДО ПОСЛЕ")
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"не каталог: {root}")
        return 2
    snap = take(root, args.hash)
    io.open(args.out, "w", encoding="utf-8").write(json.dumps(snap, ensure_ascii=False, indent=1))
    print(f"снимок: {snap['count']} позиций -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

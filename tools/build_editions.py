"""Сборка Start и Pro из явных списков одного Git-клона. Python 3.10+."""

import argparse
import hashlib
import io
import json
import os
import posixpath
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

import validate

ROOT = Path(__file__).resolve().parent.parent
EDITIONS = ("Start", "Pro")


def safe_name(name: str) -> str:
    path = PurePosixPath(name)
    reserved = {"con", "prn", "aux", "nul"} | {
        f"{prefix}{number}" for prefix in ("com", "lpt") for number in range(1, 10)}
    if (not name or name == "." or path.is_absolute() or path.as_posix() != name
            or any(part.casefold() in {".", "..", ".git"} for part in path.parts)
            or any(part.split(".")[0].casefold() in reserved for part in path.parts)
            or any(char in name for char in '\\:\x00<>"|?*')
            or any(part.endswith((".", " ")) for part in path.parts)):
        raise ValueError(f"Небезопасный путь в составе: {name!r}")
    return name


def read_list(root: Path, name: str) -> list[str]:
    document = json.loads((root / "packaging" / f"{name}.json").read_text(encoding="utf-8"))
    if (not isinstance(document, dict) or set(document) != {"files"}
            or not isinstance(document["files"], list)
            or not all(isinstance(item, str) for item in document["files"])):
        raise ValueError(f"Неверный список состава: {name}")
    return [safe_name(item) for item in document["files"]]


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True,
        capture_output=True, encoding="utf-8",
    ).stdout


def check_links(files: dict[str, bytes]) -> None:
    for name, data in files.items():
        if not name.endswith(".md"):
            continue
        for match in validate.MD_LINK.finditer(data.decode("utf-8")):
            link = match.group(1)
            url = urlsplit(link)
            if url.scheme or link.startswith("#"):
                continue
            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), unquote(url.path)))
            if target.startswith("../") or target.startswith("/"):
                raise ValueError(f"Ссылка выходит из архива: {name} -> {link}")
            if target != "." and target not in files and not any(
                    item.startswith(target.rstrip("/") + "/") for item in files):
                raise ValueError(f"Ссылка отсутствует в архиве: {name} -> {link}")


def make_zip(files: dict[str, bytes], metadata: dict) -> bytes:
    entries = dict(files)
    entries["EDITION.json"] = (json.dumps(metadata, ensure_ascii=False, indent=2,
                                         sort_keys=True) + "\n").encode("utf-8")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return stream.getvalue()


def build(root: Path, output: Path, deny: list[str]) -> dict[str, int]:
    root = root.resolve()
    output = output.absolute()
    if output.exists():
        raise ValueError("Каталог результата уже существует. Укажите новый каталог.")
    common = read_list(root, "common")
    compositions = {edition: common + read_list(root, edition) for edition in EDITIONS}
    tracked = {}
    for entry in git(root, "ls-files", "--stage", "-z").split("\0"):
        if entry:
            details, name = entry.split("\t", 1)
            mode, _, stage = details.split()
            if stage != "0":
                raise ValueError("В индексе Git есть неразрешённый конфликт.")
            tracked[name] = mode

    snapshot = {}
    for name in sorted(set().union(*compositions.values())):
        path = root / name
        if unicodedata.normalize("NFC", name).casefold() == "edition.json":
            raise ValueError(f"Зарезервированное имя квитанции: {name}")
        if tracked.get(name) not in {"100644", "100755"}:
            raise ValueError(f"Файл не отслеживается как обычный файл: {name}")
        if not path.is_file() or path.resolve() != path:
            raise ValueError(f"Файл отсутствует или перенаправлен: {name}")
        snapshot[name] = path.read_bytes()

    for name, data in snapshot.items():
        path = root / name
        if path.suffix.lower() in validate.SCAN_EXT and name != "tools/validate.py":
            findings, _ = validate.scan_text(path, data.decode("utf-8"), deny, lang_check=False)
            if findings:
                categories = sorted({finding[2] for finding in findings})
                raise ValueError(f"Проверка публикации отклонила {name}: {', '.join(categories)}")

    revision = git(root, "rev-parse", "HEAD").strip()
    dirty = bool(git(root, "status", "--porcelain", "--untracked-files=no").strip())
    archives = {}
    counts = {}
    for edition, names in compositions.items():
        keys = [unicodedata.normalize("NFC", name).casefold() for name in names]
        if len(keys) != len(set(keys)):
            raise ValueError(f"Дубликат пути в составе {edition}")
        if not names:
            raise ValueError(f"Пустой состав {edition}")
        files = {name: snapshot[name] for name in names}
        check_links(files)
        metadata = {
            "edition": edition, "revision": revision, "working_tree_dirty": dirty,
            "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
        }
        archives[edition] = make_zip(files, metadata)
        counts[edition] = len(files)

    # Общие байты берутся из одного снимка. Оба архива подготовлены до записи.
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".iiskra-", dir=output.parent) as temporary:
        staging = Path(temporary) / "editions"
        staging.mkdir()
        for edition, data in archives.items():
            (staging / f"iiskra-{edition}.zip").write_bytes(data)
        if output.exists():
            raise ValueError("Каталог результата появился во время сборки.")
        os.replace(staging, output)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--deny-file")
    parser.add_argument("--require-deny", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        import unittest
        import test_editions
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromModule(test_editions))
        return 0 if result.wasSuccessful() else 1
    if args.output is None:
        parser.error("укажите --output или --selftest")
    deny, loaded = validate.load_deny(args)
    if args.require_deny and not loaded:
        print("ОШИБКА: обязательный приватный словарь не найден.")
        return 1
    try:
        counts = build(ROOT, args.output, deny)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"ОШИБКА СБОРКИ: {error}")
        return 1
    for edition, count in counts.items():
        print(f"{edition}: {count} файлов, архив проверен")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())

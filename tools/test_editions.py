"""Отрицательные пробы состава, ссылок, приватности и атомарной записи."""

import io
import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

import build_editions


class EditionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve() / "repo"
        self.root.mkdir()
        self.output = self.root.parent / "result"
        self.write("README.md", "[Общие правила](rules/core.md)\n")
        self.write("rules/core.md", "Общие правила\n")
        self.write("docs/pro.md", "[Правила](../rules/core.md)\n")
        self.manifest("common", ["README.md", "rules/core.md"])
        self.manifest("Start", [])
        self.manifest("Pro", ["docs/pro.md"])
        self.git("init")
        self.git("add", "README.md", "rules", "docs", "packaging")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.com",
                 "commit", "-m", "fixture")

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def manifest(self, edition, files):
        self.write(f"packaging/{edition}.json", json.dumps({"files": files}))

    def assert_rejected(self, message, deny=None):
        with self.assertRaisesRegex(ValueError, message):
            build_editions.build(self.root, self.output, deny or [])
        self.assertFalse(self.output.exists())

    def test_common_bytes_and_separate_compositions(self):
        self.write("untracked-private.md", "Частный материал\n")
        counts = build_editions.build(self.root, self.output, [])
        self.assertEqual(counts, {"Start": 2, "Pro": 3})
        with zipfile.ZipFile(self.output / "iiskra-Start.zip") as start:
            with zipfile.ZipFile(self.output / "iiskra-Pro.zip") as pro:
                self.assertNotIn("docs/pro.md", start.namelist())
                self.assertIn("docs/pro.md", pro.namelist())
                self.assertNotIn("untracked-private.md", pro.namelist())
                for name in ("README.md", "rules/core.md"):
                    self.assertEqual(start.read(name), pro.read(name))
                receipt = json.loads(start.read("EDITION.json"))
                self.assertEqual(len(receipt["sha256"]), 2)
                self.assertFalse(receipt["working_tree_dirty"])
                self.assertEqual(receipt["revision"],
                                 build_editions.git(self.root, "rev-parse", "HEAD").strip())
                for name, expected in receipt["sha256"].items():
                    self.assertEqual(hashlib.sha256(start.read(name)).hexdigest(), expected)

    def test_repeatable_bytes_and_receipt_of_dirty_tree(self):
        self.write("rules/core.md", "Обновлённые правила\n")
        build_editions.build(self.root, self.output, [])
        again = self.output.parent / "again"
        build_editions.build(self.root, again, [])
        for edition in build_editions.EDITIONS:
            first = (self.output / f"iiskra-{edition}.zip").read_bytes()
            self.assertEqual(first, (again / f"iiskra-{edition}.zip").read_bytes())
            with zipfile.ZipFile(io.BytesIO(first)) as archive:
                self.assertTrue(json.loads(archive.read("EDITION.json"))["working_tree_dirty"])

    def test_missing_tracked_file(self):
        (self.root / "rules/core.md").unlink()
        self.assert_rejected("отсутствует")

    def test_untracked_private_file(self):
        self.write("private.md", "Частный материал\n")
        self.manifest("Pro", ["docs/pro.md", "private.md"])
        self.assert_rejected("не отслеживается")

    def test_secret_in_tracked_file(self):
        self.write("rules/core.md", "ghp_" + "A" * 30)
        self.assert_rejected("Проверка публикации")

    def test_nested_validator_name_is_scanned(self):
        self.write("nested/validate.py", "ghp_" + "A" * 30)
        self.git("add", "nested/validate.py")
        self.manifest("Pro", ["docs/pro.md", "nested/validate.py"])
        self.assert_rejected("Проверка публикации")

    def test_private_deny_dictionary(self):
        self.write("rules/core.md", "НепубликуемоеИмя\n")
        self.assert_rejected("Проверка публикации", ["непубликуемоеимя"])

    def test_duplicate_path(self):
        self.manifest("Start", ["rules/core.md"])
        self.assert_rejected("Дубликат")

    def test_unsafe_paths(self):
        for name in ("../private.md", "/private.md", "C:/private.md", "a\\b.md",
                     "a//b.md", "a/./b.md", ".git/config", ".GIT/config", "a/space ",
                     ".", "a/CON.txt", "a/question?.md", "a/NUL"):
            with self.subTest(name=name):
                self.manifest("Start", [name])
                self.assert_rejected("Небезопасный")

    def test_receipt_name_is_reserved_case_insensitively(self):
        for name in ("EDITION.json", "edition.json", "Edition.json"):
            with self.subTest(name=name):
                self.write(name, "{}")
                self.git("add", "--", name)
                self.manifest("Start", [name])
                self.assert_rejected("Зарезервированное имя квитанции")

    def test_omitted_link_target(self):
        self.write("README.md", "[Pro](docs/pro.md)\n")
        self.assert_rejected("Ссылка отсутствует в архиве")

    def test_link_escape(self):
        # Соседний файл существует, но не должен стать зависимостью архива.
        (self.root.parent / "outside.md").write_text("Вне проекта", encoding="utf-8")
        self.write("README.md", "[Внешний файл](../outside.md)\n")
        self.assert_rejected("Ссылка выходит из архива")

    def test_symlink_in_git_index(self):
        object_id = build_editions.git(self.root, "hash-object", "README.md").strip()
        self.git("update-index", "--cacheinfo", f"120000,{object_id},rules/core.md")
        self.assert_rejected("не отслеживается как обычный")

    def test_both_editions_checked_before_output(self):
        self.write("docs/excluded.md", "Существует в клоне, исключён из поставки\n")
        self.git("add", "docs/excluded.md")
        self.write("docs/pro.md", "[Зависимость Pro](excluded.md)\n")
        self.assert_rejected("Ссылка отсутствует в архиве: docs/pro.md")

    def test_existing_output_preserved(self):
        self.output.mkdir()
        marker = self.output / "existing.txt"
        marker.write_text("Сохранить", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "уже существует"):
            build_editions.build(self.root, self.output, [])
        self.assertEqual(marker.read_text(encoding="utf-8"), "Сохранить")


if __name__ == "__main__":
    unittest.main()

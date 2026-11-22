"""Tests for hash_files and the verify command (no network)."""
import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "find-skills" / "scripts"))
import skillfinder  # noqa: E402


def make_skill(root: Path, name: str = "demo") -> Path:
    skill = root / name
    skill.mkdir()
    (skill / "SKILL.md").write_text("hello\n")
    (skill / "scripts").mkdir()
    (skill / "scripts" / "run.py").write_text("print('ok')\n")
    return skill


def write_lock(root: Path, name: str, files: dict) -> None:
    (root / skillfinder.LOCK_NAME).write_text(
        json.dumps({name: {"source": "owner/repo", "files": files}}, indent=2))


def verify_args(root: Path) -> argparse.Namespace:
    return argparse.Namespace(dir=str(root), scope="workspace", agent="kiro")


class TestHashFiles(unittest.TestCase):
    def test_hashes_nested_files_with_posix_keys(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            make_skill(root)
            hashes = skillfinder.hash_files(root / "demo")
            self.assertIn("SKILL.md", hashes)
            self.assertIn("scripts/run.py", hashes)
            self.assertNotIn("scripts/", hashes)

    def test_hash_changes_with_content(self):
        with tempfile.TemporaryDirectory() as d:
            skill = make_skill(Path(d))
            before = skillfinder.hash_files(skill)
            (skill / "SKILL.md").write_text("changed\n")
            after = skillfinder.hash_files(skill)
            self.assertNotEqual(before["SKILL.md"], after["SKILL.md"])
            self.assertEqual(before["scripts/run.py"], after["scripts/run.py"])


class TestCmdVerify(unittest.TestCase):
    def test_intact_skill_passes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            skill = make_skill(root)
            write_lock(root, "demo", skillfinder.hash_files(skill))
            skillfinder.cmd_verify(verify_args(root))  # must not exit

    def test_changed_file_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            skill = make_skill(root)
            write_lock(root, "demo", skillfinder.hash_files(skill))
            (skill / "SKILL.md").write_text("tampered\n")
            with self.assertRaises(SystemExit) as cm:
                skillfinder.cmd_verify(verify_args(root))
            self.assertEqual(cm.exception.code, 2)

    def test_added_file_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            skill = make_skill(root)
            write_lock(root, "demo", skillfinder.hash_files(skill))
            (skill / "extra.md").write_text("surprise\n")
            with self.assertRaises(SystemExit) as cm:
                skillfinder.cmd_verify(verify_args(root))
            self.assertEqual(cm.exception.code, 2)

    def test_deleted_file_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            skill = make_skill(root)
            write_lock(root, "demo", skillfinder.hash_files(skill))
            (skill / "scripts" / "run.py").unlink()
            with self.assertRaises(SystemExit) as cm:
                skillfinder.cmd_verify(verify_args(root))
            self.assertEqual(cm.exception.code, 2)

    def test_missing_skill_folder_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write_lock(root, "gone", {"SKILL.md": "abc"})
            with self.assertRaises(SystemExit) as cm:
                skillfinder.cmd_verify(verify_args(root))
            self.assertEqual(cm.exception.code, 2)

    def test_no_hashes_entry_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            make_skill(root)
            (root / skillfinder.LOCK_NAME).write_text(json.dumps({"demo": {"source": "owner/repo"}}))
            with self.assertRaises(SystemExit) as cm:
                skillfinder.cmd_verify(verify_args(root))
            self.assertEqual(cm.exception.code, 2)

    def test_no_lock_file_is_reported_not_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            skillfinder.cmd_verify(verify_args(Path(d)))  # must not exit

    def test_invalid_lock_json_exits_1(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / skillfinder.LOCK_NAME).write_text("not json")
            with self.assertRaises(SystemExit) as cm:
                skillfinder.cmd_verify(verify_args(root))
            self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()

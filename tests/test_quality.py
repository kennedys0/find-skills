"""Tests for skillfinder.quality scoring and flags (no network)."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "find-skills" / "scripts"))
import skillfinder  # noqa: E402


def iso(days_ago: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.isoformat().replace("+00:00", "Z")


def meta(**over):
    base = {
        "full_name": "owner/repo", "stars": 1000, "fork": False, "archived": False,
        "owner_type": "User", "license": "MIT", "pushed_at": iso(10),
        "created_at": iso(400), "description": "a skill",
    }
    base.update(over)
    return base


class TestQuality(unittest.TestCase):
    def setUp(self):
        self._clone_watch = dict(skillfinder.CLONE_WATCH)

    def tearDown(self):
        skillfinder.CLONE_WATCH.clear()
        skillfinder.CLONE_WATCH.update(self._clone_watch)

    def test_score_in_bounds_and_positive(self):
        score, flags = skillfinder.quality(meta(), 500, set())
        self.assertTrue(0 <= score <= 100)
        self.assertNotIn("trusted owner", flags)

    def test_trusted_owner_flag_first(self):
        score, flags = skillfinder.quality(meta(), None, {"owner"})
        self.assertEqual(flags[0], "trusted owner")
        self.assertGreater(score, 0)

    def test_no_license_flag(self):
        _, flags = skillfinder.quality(meta(license=None), None, set())
        self.assertIn("no license", flags)

    def test_fork_and_archived_flags(self):
        _, flags = skillfinder.quality(meta(fork=True, archived=True), None, set())
        self.assertIn("fork", flags)
        self.assertIn("archived", flags)

    def test_stale_repo_flag(self):
        _, flags = skillfinder.quality(meta(pushed_at=iso(400)), None, set())
        self.assertTrue(any(f.startswith("stale:") for f in flags))

    def test_new_repo_flag(self):
        _, flags = skillfinder.quality(meta(created_at=iso(5)), None, set())
        self.assertTrue(any(f.startswith("new repo") for f in flags))

    def test_install_inflation_clone_pattern(self):
        # 31 stars vs 67k installs, untrusted owner: the clone-farm pattern.
        score, flags = skillfinder.quality(meta(stars=31), 67_000, set())
        self.assertTrue(any(f.startswith("INSTALL-INFLATION") for f in flags))
        self.assertLessEqual(score, 30)

    def test_install_inflation_trusted_is_flag_only(self):
        # Official vendors may legitimately have tool-driven installs; no penalty.
        _, flags = skillfinder.quality(meta(stars=31), 67_000, {"owner"})
        self.assertTrue(any("official vendor" in f for f in flags))
        self.assertFalse(any(f.startswith("INSTALL-INFLATION") for f in flags))

    def test_name_copy_clone_flag(self):
        skillfinder.CLONE_WATCH["superpowers"] = "obra/superpowers"
        _, flags = skillfinder.quality(meta(full_name="someone-else/superpowers"), None, set())
        self.assertTrue(any(f.startswith("NAME-COPY") for f in flags))

    def test_name_copy_ignores_original_repo(self):
        skillfinder.CLONE_WATCH["superpowers"] = "obra/superpowers"
        _, flags = skillfinder.quality(meta(full_name="obra/superpowers"), None, set())
        self.assertFalse(any(f.startswith("NAME-COPY") for f in flags))

    def test_more_stars_score_higher(self):
        low, _ = skillfinder.quality(meta(stars=10), None, set())
        high, _ = skillfinder.quality(meta(stars=10_000), None, set())
        self.assertGreater(high, low)


if __name__ == "__main__":
    unittest.main()

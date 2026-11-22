"""Tests for skillfinder.parse_frontmatter (pure stdlib, no network)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "find-skills" / "scripts"))
import skillfinder  # noqa: E402


class TestParseFrontmatter(unittest.TestCase):
    def test_simple_scalars(self):
        fm, body = skillfinder.parse_frontmatter("---\nname: foo\ndescription: does things\n---\nbody text")
        self.assertEqual(fm["name"], "foo")
        self.assertEqual(fm["description"], "does things")
        self.assertEqual(body, "body text")

    def test_no_frontmatter(self):
        fm, body = skillfinder.parse_frontmatter("just text\nno yaml here")
        self.assertEqual(fm, {})
        self.assertEqual(body, "just text\nno yaml here")

    def test_unclosed_frontmatter(self):
        fm, body = skillfinder.parse_frontmatter("---\nname: foo\nno end marker")
        self.assertEqual(fm, {})
        self.assertEqual(body, "---\nname: foo\nno end marker")

    def test_quoted_values(self):
        fm, _ = skillfinder.parse_frontmatter('---\nname: "my-skill"\ndescription: \'single\'\n---\n')
        self.assertEqual(fm["name"], "my-skill")
        self.assertEqual(fm["description"], "single")

    def test_block_scalar(self):
        text = "---\ndescription: |\n  line one\n  line two\n---\nbody"
        fm, _ = skillfinder.parse_frontmatter(text)
        self.assertEqual(fm["description"], "line one\nline two")

    def test_folded_scalar(self):
        text = "---\ndescription: >\n  line one\n  line two\n---\nbody"
        fm, _ = skillfinder.parse_frontmatter(text)
        self.assertEqual(fm["description"], "line one line two")

    def test_continued_plain_scalar(self):
        text = "---\ndescription: first part\n  second part\nname: x\n---\n"
        fm, _ = skillfinder.parse_frontmatter(text)
        self.assertEqual(fm["description"], "first part second part")
        self.assertEqual(fm["name"], "x")

    def test_bom_is_stripped(self):
        fm, _ = skillfinder.parse_frontmatter("\ufeff---\nname: foo\n---\n")
        self.assertEqual(fm["name"], "foo")

    def test_hyphens_in_key(self):
        fm, _ = skillfinder.parse_frontmatter("---\nallowed-tools: Bash, Read\n---\n")
        self.assertEqual(fm["allowed-tools"], "Bash, Read")


if __name__ == "__main__":
    unittest.main()

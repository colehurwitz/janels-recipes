"""Offline unit tests for migrate.py.

Run with either:
    python3 -m pytest tests/test_migrate.py
    python3 -m unittest discover -s tests

All tests work against committed sample fixtures under tests/fixtures/ and
temporary output directories — nothing touches the real content/recipes/.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import migrate  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE = FIXTURES / "eval_sample.md"
MISSING = FIXTURES / "missing_category.md"


def run_on(text: str, tmp: Path, force: bool = False, dry_run: bool = False) -> dict:
    out = tmp / "recipes"
    report = tmp / "MIGRATION_REPORT.md"
    return migrate.migrate(
        source_text=text,
        out_dir=out,
        report_path=report,
        force=force,
        dry_run=dry_run,
        source_name="test",
    )


class SlugifyTests(unittest.TestCase):
    def test_convention(self):
        self.assertEqual(migrate.slugify("Grandma's Apple Cake"), "grandmas-apple-cake")
        self.assertEqual(migrate.slugify("Vegetables & Sides"), "vegetables-and-sides")
        self.assertEqual(migrate.slugify("  Spicy   Soup!  "), "spicy-soup")
        self.assertEqual(migrate.slugify("Crème Brûlée"), "creme-brulee")
        self.assertEqual(migrate.slugify("House Spice Blend."), "house-spice-blend")


class YamlTests(unittest.TestCase):
    def test_apostrophe_and_colon_quoted_safely(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            pie = (
                "## Mom's Famous: Pie\n\n"
                "A deep-dish pie with plenty of body text so it clears the fragment threshold cleanly.\n"
            )
            full = self._all_eight(extra_desserts=pie)
            run_on(full, tmp)
            content = (tmp / "recipes" / "moms-famous-pie.md").read_text()
        self.assertIn('title: "Mom\'s Famous: Pie"', content)
        self.assertIn('category: "Desserts"', content)
        self.assertIn('image: ""', content)
        self.assertIn("review: false", content)

    @staticmethod
    def _all_eight(extra_desserts: str = "") -> str:
        body = "Plenty of body text here so this recipe clears the fragment threshold.\n"
        parts = []
        for c in migrate.CATEGORIES:
            parts.append(f"# {c}\n")
            parts.append(f"## {c} Sample Recipe\n\n{body}")
            if c == "Desserts" and extra_desserts:
                parts.append("\n" + extra_desserts)
        return "\n".join(parts)


class CleanRecipeTests(unittest.TestCase):
    def test_clean_recipe_frontmatter_and_location(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            run_on(SAMPLE.read_text(), tmp)
            clean = tmp / "recipes" / "weeknight-lemon-chicken.md"
            self.assertTrue(clean.exists(), "clean recipe should land in content/recipes/")
            text = clean.read_text()
            self.assertIn('title: "Weeknight Lemon Chicken"', text)
            self.assertIn('category: "Dinner"', text)
            self.assertIn('image: ""', text)
            self.assertIn('notes: ""', text)
            self.assertIn("review: false", text)
            self.assertIn("Sear the chicken", text)
            # A clean recipe is NOT routed to the review folder.
            self.assertFalse((tmp / "_needs_review" / "weeknight-lemon-chicken.md").exists())


class CategoryDetectionTests(unittest.TestCase):
    def test_all_eight_detected(self):
        with tempfile.TemporaryDirectory() as d:
            summary = run_on(SAMPLE.read_text(), Path(d))
        self.assertEqual(summary["categories_detected"], 8)
        self.assertEqual(summary["recipes_total"], 16)

    def test_missing_category_halts(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(migrate.MigrationError):
                run_on(MISSING.read_text(), Path(d))

    def test_duplicate_category_halts(self):
        text = YamlTests._all_eight() + "\n# Desserts\n\n## Another Dessert\n\nBody text long enough here.\n"
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(migrate.MigrationError):
                run_on(text, Path(d))

    def test_unexpected_top_level_heading_halts(self):
        text = YamlTests._all_eight() + "\n# Random Section\n\n## Stray\n\nBody text here that is long enough.\n"
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(migrate.MigrationError):
                run_on(text, Path(d))


class FlaggingTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._dir.name)
        self.summary = run_on(SAMPLE.read_text(), self.tmp)
        self.flagged = {f["slug"]: f for f in self.summary["flagged"]}

    def tearDown(self):
        self._dir.cleanup()

    def _reasons(self, slug):
        return " ".join(self.flagged[slug]["reasons"]).lower()

    def test_flagged_routed_to_needs_review(self):
        review_dir = self.tmp / "_needs_review"
        self.assertTrue((review_dir / "layered-berry-trifle.md").exists())
        # Flagged recipes must NOT be published to content/recipes/.
        self.assertFalse((self.tmp / "recipes" / "layered-berry-trifle.md").exists())

    def test_nested_subrecipe_flagged(self):
        self.assertIn("layered-berry-trifle", self.flagged)
        self.assertIn("sub-recipe", self._reasons("layered-berry-trifle"))

    def test_image_flagged(self):
        self.assertIn("sheet-pan-sausage-and-peppers", self.flagged)
        self.assertIn("image", self._reasons("sheet-pan-sausage-and-peppers"))

    def test_table_flagged(self):
        self.assertIn("glazed-green-beans-nutrition", self.flagged)
        self.assertIn("table", self._reasons("glazed-green-beans-nutrition"))

    def test_fragment_flagged(self):
        self.assertIn("quick-bruschetta", self.flagged)
        self.assertIn("short", self._reasons("quick-bruschetta"))

    def test_duplicate_slug_flagged_and_both_written(self):
        self.assertIn("house-spice-blend", self.flagged)
        self.assertIn("duplicate slug", self._reasons("house-spice-blend"))
        review_dir = self.tmp / "_needs_review"
        self.assertTrue((review_dir / "house-spice-blend.md").exists())
        self.assertTrue((review_dir / "house-spice-blend-2.md").exists())

    def test_report_lists_reasons(self):
        report = (self.tmp / "MIGRATION_REPORT.md").read_text()
        self.assertIn("Layered Berry Trifle", report)
        self.assertIn("Review queue", report)
        self.assertIn("Grand total", report)
        self.assertIn("possible sub-recipe", report)

    def test_no_body_flagged(self):
        text = YamlTests._all_eight(extra_desserts="## Empty One\n\n")
        with tempfile.TemporaryDirectory() as d:
            summary = run_on(text, Path(d))
        flagged = {f["slug"]: f for f in summary["flagged"]}
        self.assertIn("empty-one", flagged)
        self.assertIn("no clear body", " ".join(flagged["empty-one"]["reasons"]).lower())


class NonDestructiveTests(unittest.TestCase):
    def test_rerun_does_not_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            run_on(SAMPLE.read_text(), tmp)
            target = tmp / "recipes" / "weeknight-lemon-chicken.md"
            # Simulate a hand-edit by the owner.
            target.write_text("HAND EDITED — do not clobber\n")
            summary = run_on(SAMPLE.read_text(), tmp)  # default: non-destructive
            self.assertEqual(target.read_text(), "HAND EDITED — do not clobber\n")
            self.assertGreater(summary["skipped"], 0)

    def test_force_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            run_on(SAMPLE.read_text(), tmp)
            target = tmp / "recipes" / "weeknight-lemon-chicken.md"
            target.write_text("HAND EDITED\n")
            run_on(SAMPLE.read_text(), tmp, force=True)
            self.assertIn("Weeknight Lemon Chicken", target.read_text())


class DryRunTests(unittest.TestCase):
    def test_dry_run_writes_report_only(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            summary = run_on(SAMPLE.read_text(), tmp, dry_run=True)
            self.assertTrue((tmp / "MIGRATION_REPORT.md").exists())
            self.assertFalse((tmp / "recipes").exists())
            self.assertFalse((tmp / "_needs_review").exists())
            self.assertEqual(summary["written"], 0)
            self.assertEqual(summary["categories_detected"], 8)


class CliTests(unittest.TestCase):
    def test_url_input_refused(self):
        rc = migrate.main(["--input", "https://docs.google.com/document/d/abc", "--out", "x", "--json"])
        self.assertEqual(rc, 2)

    def test_missing_file_refused(self):
        rc = migrate.main(["--input", "/no/such/file.md", "--json"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()

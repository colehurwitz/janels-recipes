#!/usr/bin/env python3
"""One-time migration: a LOCAL Google-Docs Markdown export -> one .md per recipe.

Converts an exported "Janel's Recipes" Markdown document into the site's
per-recipe file contract: `content/recipes/<slug>.md` with the exact frontmatter
the Eleventy site expects (title, category, image, notes, review).

Design rules this script lives by (see .factory/strategy/current.md):
  * NEVER GUESS structure. Categories are matched against a fixed 8-name list;
    a missing / duplicated / unexpected top-level heading HALTS the migration.
  * FLAG the messy ~15% rather than inventing structure. When a heuristic trips
    (nested sub-recipe, embedded image, table, anomalous length, no body,
    duplicate slug) the recipe is written with `review: true` and routed to
    `content/_needs_review/` so it is held back from publish until a human
    reviews it. Every flagged recipe is listed WITH ITS REASON in
    MIGRATION_REPORT.md.
  * NON-DESTRUCTIVE by default. An existing target file is skipped (never
    overwritten) so re-runs can't clobber the editor's hand-edits; pass --force
    to overwrite. --dry-run writes ONLY the report and no recipe files.
  * LOCAL input only. The CLI refuses anything that looks like a URL.

Assumption about export shape: category names appear as top-level headings and
each recipe is the heading one level below its category. Recipes carry their
Ingredients / Directions as bold labels or plain lists, NOT as their own
headings — so any heading found *inside* a recipe body is treated as a possible
nested sub-recipe and flagged for review.

Usage:
    python migrate.py --input export.md --out content/recipes
    python migrate.py --input export.md --out content/recipes --dry-run
    python migrate.py --input export.md --out content/recipes --force
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from markdown_it import MarkdownIt

# The 8 fixed categories from the source doc's table of contents. SINGLE SOURCE
# OF TRUTH must agree with content/_data/categories.js.
CATEGORIES = [
    "Desserts",
    "Dinner",
    "Breads",
    "Appetizers",
    "Vegetables & Sides",
    "Breakfast",
    "Soups & Stews",
    "Miscellaneous",
]

# Known wording variants of the 8 categories as they actually appear as headings
# in the real exported doc, mapped to their canonical name above. The source doc
# titles two sections differently from the site's category list — this is an
# explicit, deterministic alias table (NOT a guess): the heading text is matched
# verbatim (normalized) and only these exact variants are accepted. Keys are
# normalized (lowercase, whitespace-collapsed) the same way headings are.
CATEGORY_ALIASES = {
    "vegetables and side dishes": "Vegetables & Sides",
    "soups/stews": "Soups & Stews",
}

# Connector words kept lowercase when title-casing an ALL-CAPS source title
# (except as the first word). Conservative set — when unsure we prefer faithful.
TITLE_SMALL_WORDS = {
    "a", "an", "and", "as", "at", "by", "de", "for", "from", "in", "of",
    "on", "or", "the", "to", "with",
}

# Apostrophe variants seen in the export (straight + curly + modifier letters).
_APOSTROPHES = "'‘’ʼʻ"

# Heuristic thresholds (non-whitespace character counts of the recipe body).
FRAGMENT_MIN_CHARS = 40      # below this => likely a stray fragment
MERGED_MAX_CHARS = 4000      # above this => likely several recipes merged


class MigrationError(Exception):
    """Raised when the document structure cannot be trusted — we HALT, never guess."""


# --------------------------------------------------------------------------- #
# Slug — deterministic, matches the site's category/file slug convention:
# lowercase, '&' -> 'and', drop apostrophes, non-alphanumerics -> hyphens, trim.
# (Mirrors categorySlug() in .eleventy.js; apostrophes are elided so
# "Grandma's Apple Cake" -> "grandmas-apple-cake" rather than "grandma-s-...".)
# --------------------------------------------------------------------------- #
def slugify(text: str) -> str:
    s = unicodedata.normalize("NFKD", str(text))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = s.replace("&", " and ")
    s = re.sub(r"['‘’ʼʻ]", "", s)  # drop apostrophes
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def yaml_double(value: str) -> str:
    """Emit a safely double-quoted YAML scalar (handles apostrophes, colons, etc.)."""
    s = str(value).replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\n", " ").replace("\t", " ")
    return f'"{s}"'


def normalize_heading(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def canonical_category_map() -> dict[str, str]:
    """Normalized heading text -> canonical category name.

    Includes the 8 canonical names plus the explicit CATEGORY_ALIASES for the
    real doc's two differently-worded section headings. Matching is exact (on
    the normalized key) — unknown headings still HALT, so this widens what's
    recognized without ever guessing.
    """
    m = {normalize_heading(c): c for c in CATEGORIES}
    for variant, canon in CATEGORY_ALIASES.items():
        m[normalize_heading(variant)] = canon
    return m


# --------------------------------------------------------------------------- #
# Title casing — the source titles are predominantly ALL-CAPS, which fights the
# warm-cookbook goal. Convert an all-caps title to Title Case for the display
# `title` frontmatter; leave anything already mixed-case untouched (faithful).
# The slug is unaffected (slugify lowercases regardless).
# --------------------------------------------------------------------------- #
_WORD_RE = re.compile(rf"[^\W\d_]+(?:[{_APOSTROPHES}][^\W\d_]+)*", re.UNICODE)


def _cap_word(word: str) -> str:
    """Capitalize the first letter, lowercase the rest — turns KRISTA'S into
    Krista's and AMYGDALOTA into Amygdalota while preserving apostrophes."""
    out: list[str] = []
    capped = False
    for ch in word:
        if not capped and ch.isalpha():
            out.append(ch.upper())
            capped = True
        else:
            out.append(ch.lower())
    return "".join(out)


def title_case_display(text: str) -> str:
    """Title-case an ALL-CAPS source heading for display.

    If the text already contains a lowercase letter it is left verbatim (it was
    authored with intentional casing — e.g. a parenthetical like
    "(KIENOW'S - Sakineh's favorite)" — and must not be destroyed). Connector
    words stay lowercase except when first; separators/punctuation are kept as-is.
    """
    if any(c.islower() for c in text):
        return text

    parts: list[str] = []
    last_end = 0
    first = True
    for m in _WORD_RE.finditer(text):
        parts.append(text[last_end:m.start()])  # punctuation/space verbatim
        word = m.group(0)
        if not first and word.lower() in TITLE_SMALL_WORDS:
            parts.append(word.lower())
        else:
            parts.append(_cap_word(word))
        last_end = m.end()
        first = False
    parts.append(text[last_end:])
    return "".join(parts)


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class Heading:
    level: int
    text: str
    start: int          # source line index of the heading
    end: int            # source line index immediately after the heading


@dataclass
class Recipe:
    title: str
    category: str
    body: str
    slug: str = ""
    notes: str = ""
    reasons: list[str] = field(default_factory=list)

    @property
    def review(self) -> bool:
        return bool(self.reasons)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def make_md() -> MarkdownIt:
    # CommonMark + tables (tables are a review trigger, so we must detect them).
    return MarkdownIt("commonmark").enable("table")


def clean_heading_text(inline) -> str:
    """Plain text of a heading with inline markup removed.

    The real export wraps headings in emphasis (`# **DESSERTS**`,
    `## **APPLE PIE**`). `inline.content` keeps the raw `**` markers, which
    breaks category matching — so we walk the inline token's parsed children and
    concatenate only the text/code leaves, dropping bold/italic markers while
    preserving apostrophes, parentheses, hyphens and accented characters. Falls
    back to stripping emphasis markers from the raw content if children are
    unavailable (and for non-emphasis headings the result is unchanged).
    """
    if inline is None:
        return ""
    children = getattr(inline, "children", None)
    if children:
        parts: list[str] = []
        for c in children:
            if c.type in ("text", "code_inline"):
                parts.append(c.content)
            elif c.type in ("softbreak", "hardbreak"):
                parts.append(" ")
        text = "".join(parts).strip()
        if text:
            return text
    # Fallback: strip surrounding/inline emphasis markers from the raw content.
    return re.sub(r"(\*\*|__|\*|_)", "", inline.content or "").strip()


def build_headings(tokens) -> list[Heading]:
    headings: list[Heading] = []
    for i, tok in enumerate(tokens):
        if tok.type != "heading_open":
            continue
        level = int(tok.tag[1])
        inline = tokens[i + 1] if i + 1 < len(tokens) else None
        text = clean_heading_text(inline)
        start, end = (tok.map or [0, 0])
        headings.append(Heading(level=level, text=text, start=start, end=end))
    return headings


def detect_categories(headings: list[Heading]) -> tuple[int, list[int]]:
    """Find the category level and indices; HALT loudly on any structural problem."""
    canonical = canonical_category_map()
    matches = [(i, h) for i, h in enumerate(headings) if normalize_heading(h.text) in canonical]

    if not matches:
        raise MigrationError(
            "No category headings found. Expected all 8 of: " + ", ".join(CATEGORIES)
        )

    levels = {h.level for _, h in matches}
    if len(levels) > 1:
        raise MigrationError(
            f"Category headings appear at inconsistent heading levels {sorted(levels)} — "
            "refusing to guess the document structure."
        )
    category_level = levels.pop()

    found = [canonical[normalize_heading(h.text)] for _, h in matches]
    counts = Counter(found)
    dups = [c for c in CATEGORIES if counts[c] > 1]
    if dups:
        raise MigrationError(
            "Duplicate category heading(s): " + ", ".join(dups) + " — refusing to guess."
        )
    missing = [c for c in CATEGORIES if counts[c] == 0]
    if missing:
        raise MigrationError(
            "Missing category section(s): " + ", ".join(missing) + ". "
            "Expected all 8: " + ", ".join(CATEGORIES) + "."
        )

    # Any non-category heading at (or above) the category level, appearing within
    # the category region, means the structure isn't what we expect.
    first_cat_line = matches[0][1].start
    for h in headings:
        if h.level <= category_level and h.start >= first_cat_line:
            if normalize_heading(h.text) not in canonical:
                raise MigrationError(
                    f"Unexpected top-level heading {h.text!r} at the category level — "
                    "the document does not fit the category->recipe nesting; refusing to guess."
                )

    return category_level, [i for i, _ in matches]


def extract_recipes(headings: list[Heading], lines: list[str], category_level: int) -> list[Recipe]:
    canonical = canonical_category_map()
    recipe_level = category_level + 1
    recipes: list[Recipe] = []
    current_category: str | None = None
    n = len(headings)

    for i, h in enumerate(headings):
        norm = normalize_heading(h.text)
        if h.level == category_level and norm in canonical:
            current_category = canonical[norm]
            continue
        if h.level == recipe_level and current_category is not None:
            # Body runs until the next heading at the recipe level or shallower
            # (so deeper sub-headings stay inside this recipe's body).
            boundary = len(lines)
            for j in range(i + 1, n):
                if headings[j].level <= recipe_level:
                    boundary = headings[j].start
                    break
            body = "\n".join(lines[h.end:boundary]).strip()
            recipes.append(Recipe(title=h.text, category=current_category, body=body))
    return recipes


# --------------------------------------------------------------------------- #
# Heuristics — flag, don't guess
# --------------------------------------------------------------------------- #
def _walk_inline(tokens):
    for tok in tokens:
        if tok.type == "inline" and tok.children:
            yield from tok.children


def _is_pipe_table(text: str) -> bool:
    rows = text.splitlines()
    sep = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)+\|?\s*$")
    for i in range(len(rows) - 1):
        if "|" in rows[i] and sep.match(rows[i + 1]):
            return True
    return False


def analyze_body(body: str, md: MarkdownIt) -> list[str]:
    reasons: list[str] = []
    stripped = body.strip()
    content_len = len(re.sub(r"\s+", "", body))

    if not stripped:
        reasons.append("no clear body under the recipe heading")
    else:
        if content_len < FRAGMENT_MIN_CHARS:
            reasons.append(f"anomalously short body ({content_len} chars) — likely a fragment")
        if content_len > MERGED_MAX_CHARS:
            reasons.append(
                f"anomalously long body ({content_len} chars) — possibly several recipes merged"
            )

    tokens = md.parse(body)

    if any(t.type == "heading_open" for t in tokens):
        reasons.append("nested sub-heading inside the recipe — possible sub-recipe")

    # Multiple Ingredients / Directions sections (headings OR bold labels) suggest
    # several merged recipes.
    labels = re.findall(
        r"(?im)^[ \t>]*(?:#{1,6}\s*)?\*{0,2}\s*(ingredients?|directions?|method|instructions?|steps)\b",
        body,
    )
    ing = sum(1 for label in labels if label.lower().startswith("ingredient"))
    other = len(labels) - ing
    if ing > 1 or other > 1:
        reasons.append(
            f"multiple Ingredients/Directions sections (ingredients x{ing}, directions x{other}) "
            "— possible merged recipes"
        )

    has_image = (
        any(c.type == "image" for c in _walk_inline(tokens))
        or re.search(r"!\[[^\]]*\]\([^)]*\)", body) is not None
        or re.search(r"<img\b", body, re.IGNORECASE) is not None
    )
    if has_image:
        reasons.append("embedded image in source — editor should re-add it via the web UI")

    if any(t.type == "table_open" for t in tokens) or _is_pipe_table(body):
        reasons.append("table in source — verify formatting after migration")

    return reasons


def flag_duplicate_slugs(recipes: list[Recipe]) -> None:
    counts = Counter(r.slug for r in recipes)
    for r in recipes:
        if counts[r.slug] > 1:
            r.reasons.append(
                f"duplicate slug '{r.slug}.md' — {counts[r.slug]} recipes map to the same filename"
            )


# --------------------------------------------------------------------------- #
# Rendering & writing
# --------------------------------------------------------------------------- #
def render_recipe(r: Recipe) -> str:
    fm = [
        "---",
        f"title: {yaml_double(r.title)}",
        f"category: {yaml_double(r.category)}",
        'image: ""',
        f"notes: {yaml_double(r.notes)}",
        f"review: {'true' if r.review else 'false'}",
        "---",
        "",
    ]
    parts = ["\n".join(fm)]
    if r.review and r.reasons:
        parts.append("<!-- NEEDS REVIEW — " + "; ".join(r.reasons) + " -->\n")
    body = r.body.strip()
    if body:
        parts.append(body + "\n")
    return "\n".join(parts)


def _unique_path(directory: Path, slug: str, used: set[Path]) -> Path:
    target = directory / f"{slug}.md"
    n = 2
    while target in used:
        target = directory / f"{slug}-{n}.md"
        n += 1
    return target


@dataclass
class WriteResult:
    recipe: Recipe
    status: str          # "written" | "skipped-exists" | "dry-run"
    path: Path


def write_outputs(
    recipes: list[Recipe], out_dir: Path, force: bool, dry_run: bool
) -> list[WriteResult]:
    needs_dir = out_dir.parent / "_needs_review"
    used: set[Path] = set()
    results: list[WriteResult] = []

    for r in recipes:
        target_dir = needs_dir if r.review else out_dir
        target = _unique_path(target_dir, r.slug, used)
        used.add(target)

        if dry_run:
            results.append(WriteResult(r, "dry-run", target))
            continue
        if target.exists() and not force:
            results.append(WriteResult(r, "skipped-exists", target))
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(render_recipe(r), encoding="utf-8")
        results.append(WriteResult(r, "written", target))

    return results


def write_report(report_path: Path, recipes: list[Recipe], results: list[WriteResult], source: str) -> None:
    flagged = [r for r in recipes if r.review]
    clean = [r for r in recipes if not r.review]
    skipped = [w for w in results if w.status == "skipped-exists"]

    by_cat = {c: [r for r in recipes if r.category == c] for c in CATEGORIES}
    path_of = {id(w.recipe): w.path for w in results}

    out: list[str] = []
    out.append("# Migration Report\n")
    out.append(f"_Generated by `migrate.py` on {time.strftime('%Y-%m-%d %H:%M:%S')} from `{source}`._\n")
    out.append("## Summary\n")
    out.append(f"- **Total recipes parsed:** {len(recipes)}")
    out.append(f"- **Clean (publish to `content/recipes/`):** {len(clean)}")
    out.append(f"- **Flagged for review (held in `content/_needs_review/`):** {len(flagged)}")
    out.append(f"- **Skipped (existing files, not overwritten):** {len(skipped)}")
    out.append("")
    out.append("## Per-category counts\n")
    out.append("| Category | Recipes | Flagged |")
    out.append("|---|---:|---:|")
    for c in CATEGORIES:
        rs = by_cat[c]
        out.append(f"| {c} | {len(rs)} | {sum(1 for r in rs if r.review)} |")
    out.append(f"| **Grand total** | **{len(recipes)}** | **{len(flagged)}** |")
    out.append("")

    out.append("## Review queue (flagged recipes)\n")
    out.append(
        "These do **not** appear on the live site or in search until a human moves "
        "them into `content/recipes/` and clears `review: true`.\n"
    )
    if flagged:
        for r in sorted(flagged, key=lambda x: (x.category, x.title.lower())):
            rel = path_of.get(id(r))
            loc = f" (`{rel}`)" if rel else ""
            out.append(f"### {r.category} — {r.title}{loc}")
            for reason in r.reasons:
                out.append(f"- {reason}")
            out.append("")
    else:
        out.append("_None — every recipe parsed cleanly._\n")

    if skipped:
        out.append("## Skipped (already existed; re-run with `--force` to overwrite)\n")
        for w in skipped:
            out.append(f"- `{w.path}` — {w.recipe.title}")
        out.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(out), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def migrate(source_text: str, out_dir: Path, report_path: Path, force: bool, dry_run: bool, source_name: str) -> dict:
    md = make_md()
    lines = source_text.splitlines()
    tokens = md.parse(source_text)
    headings = build_headings(tokens)

    category_level, _ = detect_categories(headings)
    recipes = extract_recipes(headings, lines, category_level)

    for r in recipes:
        # Title-case the (predominantly ALL-CAPS) source title for display; the
        # slug derives from the cleaned title and is case-insensitive regardless.
        r.title = title_case_display(r.title)
        r.slug = slugify(r.title) or "untitled"
        if r.slug == "untitled":
            r.reasons.append("could not derive a slug from the title")
        r.reasons.extend(analyze_body(r.body, md))
    flag_duplicate_slugs(recipes)

    results = write_outputs(recipes, out_dir, force, dry_run)
    write_report(report_path, recipes, results, source_name)

    flagged = [r for r in recipes if r.review]
    return {
        "input": source_name,
        "out": str(out_dir),
        "report": str(report_path),
        "dry_run": dry_run,
        "categories_expected": len(CATEGORIES),
        "categories_detected": len(CATEGORIES),  # detect_categories asserts all 8
        "recipes_total": len(recipes),
        "clean": len(recipes) - len(flagged),
        "flagged_count": len(flagged),
        "skipped": sum(1 for w in results if w.status == "skipped-exists"),
        "written": sum(1 for w in results if w.status == "written"),
        "per_category": {
            c: {
                "total": sum(1 for r in recipes if r.category == c),
                "flagged": sum(1 for r in recipes if r.category == c and r.review),
            }
            for c in CATEGORIES
        },
        "flagged": [
            {"title": r.title, "category": r.category, "slug": r.slug, "reasons": r.reasons}
            for r in flagged
        ],
    }


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Migrate a LOCAL Google-Docs Markdown export into per-recipe .md files.")
    p.add_argument("--input", required=True, help="Path to the LOCAL exported Markdown file (never a URL).")
    p.add_argument("--out", default="content/recipes", help="Output dir for clean recipes (default: content/recipes).")
    p.add_argument("--report", default="MIGRATION_REPORT.md", help="Path for the migration report.")
    p.add_argument("--dry-run", action="store_true", help="Write ONLY the report; generate no recipe files.")
    p.add_argument("--force", action="store_true", help="Overwrite existing recipe files (default: skip them).")
    p.add_argument("--json", action="store_true", help="Print a machine-readable JSON summary to stdout.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logger = logging.getLogger("migrate")

    args = parse_args(argv)

    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", args.input):
        msg = f"--input must be a LOCAL file path, not a URL ({args.input!r})."
        print(json.dumps({"error": msg}) if args.json else f"ERROR: {msg}", file=sys.stderr)
        return 2

    src_path = Path(args.input)
    if not src_path.is_file():
        msg = f"input file not found: {src_path}"
        print(json.dumps({"error": msg}) if args.json else f"ERROR: {msg}", file=sys.stderr)
        return 2

    source_text = src_path.read_text(encoding="utf-8")
    try:
        summary = migrate(
            source_text=source_text,
            out_dir=Path(args.out),
            report_path=Path(args.report),
            force=args.force,
            dry_run=args.dry_run,
            source_name=str(src_path),
        )
    except MigrationError as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"MIGRATION HALTED — {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        logger.exception("unexpected error during migration")
        if args.json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary))
    else:
        mode = "DRY RUN (report only)" if args.dry_run else "wrote files"
        print(f"Migration {mode}.")
        print(f"  Categories detected: {summary['categories_detected']}/8")
        print(f"  Recipes parsed:      {summary['recipes_total']}")
        print(f"  Clean:               {summary['clean']}")
        print(f"  Flagged for review:  {summary['flagged_count']}")
        print(f"  Skipped (existing):  {summary['skipped']}")
        print(f"  Report:              {summary['report']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

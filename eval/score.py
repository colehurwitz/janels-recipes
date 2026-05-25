#!/usr/bin/env python3
"""Phase-1 eval harness for janels-recipes.

Runs the six eval dimensions from the build plan against the local project and
prints a single CompositeScore JSON object to stdout. Pure stdlib; safe to run
locally or in CI. The auto-discovery invariant is the load-bearing test — it
adds a temp recipe, rebuilds, asserts the recipe surfaces on its category page
AND in the Pagefind index with no other file touched, then cleans up.

Usage:  python3 eval/score.py
Exit code: 0 if the run passes the threshold and the auto-discovery invariant
holds, else 1. (The JSON is always printed regardless of exit code.)
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "_site"
RECIPES_DIR = ROOT / "content" / "recipes"
PROFILE_PATH = ROOT / ".factory" / "eval_profile.json"

# Fallbacks if the profile can't be read.
DEFAULT_PREFIX = "/janels-recipes/"
DEFAULT_WEIGHTS = {
    "build_succeeds": 0.30,
    "search_index_built": 0.15,
    "auto_discovery_invariant": 0.20,
    "link_integrity": 0.15,
    "print_mobile_css": 0.10,
    "migration_correctness": 0.10,
}


def load_profile() -> dict:
    try:
        return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


PROFILE = load_profile()
PREFIX = PROFILE.get("path_prefix", DEFAULT_PREFIX)
WEIGHTS = {
    d["key"]: d.get("weight", 0.0) for d in PROFILE.get("dimensions", [])
} or DEFAULT_WEIGHTS
PASS_THRESHOLD = PROFILE.get("pass_threshold", 0.8)


def run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    """Run a command at the project root, capturing output."""
    return subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def ensure_deps() -> str:
    """Install node deps if the eleventy binary is missing. Returns a note."""
    if (ROOT / "node_modules" / ".bin" / "eleventy").exists():
        return "node_modules present"
    cmd = ["npm", "ci"] if (ROOT / "package-lock.json").exists() else ["npm", "install"]
    res = run(cmd, timeout=600)
    return f"ran {' '.join(cmd)} (exit {res.returncode})"


def build() -> subprocess.CompletedProcess:
    return run(["npx", "@11ty/eleventy"])


def pagefind() -> subprocess.CompletedProcess:
    return run(["npx", "-y", "pagefind", "--site", "_site"])


def pagefind_page_count(stdout: str) -> int | None:
    m = re.search(r"Indexed\s+(\d+)\s+pages", stdout)
    return int(m.group(1)) if m else None


def content_file_set() -> set[str]:
    """Every file under content/ (relative paths) — to prove nothing else changed."""
    base = ROOT / "content"
    return {
        str(p.relative_to(base))
        for p in base.rglob("*")
        if p.is_file()
    }


# --------------------------------------------------------------------------- #
# Dimensions
# --------------------------------------------------------------------------- #
def dim_build() -> dict:
    note = ensure_deps()
    res = build()
    ok = res.returncode == 0 and (SITE / "index.html").exists()
    n_recipes = len(list((SITE / "recipes").glob("*/index.html"))) if SITE.exists() else 0
    ok = ok and n_recipes > 0
    return {
        "score": 1.0 if ok else 0.0,
        "status": "pass" if ok else "fail",
        "detail": f"{note}; eleventy exit {res.returncode}; _site/index.html "
        f"{'present' if (SITE / 'index.html').exists() else 'MISSING'}; "
        f"{n_recipes} recipe page(s)."
        + ("" if ok else f" stderr: {res.stderr[-300:]}"),
    }


def dim_search() -> dict:
    res = pagefind()
    bundle = SITE / "pagefind"
    has_ui = (bundle / "pagefind-ui.js").exists()
    fragments = list((bundle / "fragment").glob("*")) if (bundle / "fragment").is_dir() else []
    count = pagefind_page_count(res.stdout)
    ok = res.returncode == 0 and bundle.is_dir() and has_ui and len(fragments) > 0
    return {
        "score": 1.0 if ok else 0.0,
        "status": "pass" if ok else "fail",
        "detail": f"pagefind exit {res.returncode}; /pagefind/ "
        f"{'present' if bundle.is_dir() else 'MISSING'}; ui.js "
        f"{'yes' if has_ui else 'no'}; {len(fragments)} fragment(s); "
        f"indexed {count} page(s)."
        + ("" if ok else f" stderr: {res.stderr[-300:]}"),
        "indexed_pages": count,
    }


def dim_auto_discovery() -> dict:
    """Add a temp recipe, rebuild, assert it appears on its category page AND in
    the Pagefind index, with no other content file changed. Always cleans up."""
    # Baseline: clean build + pagefind page count.
    build()
    base_count = pagefind_page_count(pagefind().stdout)
    before = content_file_set()

    token = secrets.token_hex(4)
    slug = f"eval-probe-{token}"
    title = f"Eval Probe Recipe {token.upper()}"
    probe_path = RECIPES_DIR / f"{slug}.md"
    category = "Desserts"
    cat_page = SITE / "categories" / "desserts" / "index.html"

    checks: list[tuple[str, bool]] = []
    try:
        probe_path.write_text(
            f"---\ntitle: {title}\ncategory: {category}\n---\n\n"
            f"## Ingredients\n\n- probe ingredient {token}\n\n"
            f"## Directions\n\n1. Probe step {token}.\n",
            encoding="utf-8",
        )

        b = build()
        pf = pagefind()
        new_count = pagefind_page_count(pf.stdout)

        # 1. No other content file changed — only the temp file was added.
        after = content_file_set()
        added = after - before
        removed = before - after
        only_temp_added = added == {f"recipes/{slug}.md"} and not removed
        checks.append(("only the temp .md added to content/ (no registry edit)", only_temp_added))

        # 2. Build succeeded and the recipe page was generated from its filename.
        page_built = (SITE / "recipes" / slug / "index.html").exists()
        checks.append(("recipe page generated from filename (permalink)", page_built))

        # 3. Appears on its category page.
        cat_html = cat_page.read_text(encoding="utf-8") if cat_page.exists() else ""
        on_category = (f"/recipes/{slug}/" in cat_html) or (title in cat_html)
        checks.append(("recipe appears on its category page", on_category))

        # 4. Entered the Pagefind index (page count grew by exactly one).
        in_index = (
            base_count is not None
            and new_count is not None
            and new_count == base_count + 1
        )
        checks.append(
            (f"recipe entered Pagefind index (pages {base_count} -> {new_count})", in_index)
        )

        ok = b.returncode == 0 and pf.returncode == 0 and all(c[1] for c in checks)
    finally:
        # Cleanup: remove temp source AND its built output (Eleventy doesn't
        # prune stale output), then restore a clean build + index.
        if probe_path.exists():
            probe_path.unlink()
        stale = SITE / "recipes" / slug
        if stale.is_dir():
            for p in sorted(stale.rglob("*"), reverse=True):
                p.unlink() if p.is_file() else p.rmdir()
            stale.rmdir()
        build()
        pagefind()

    detail = "; ".join(f"{'OK' if v else 'FAIL'}: {name}" for name, v in checks)
    return {
        "score": 1.0 if ok else 0.0,
        "status": "pass" if ok else "fail",
        "detail": detail,
    }


def dim_link_integrity() -> dict:
    html_files = list(SITE.rglob("*.html"))
    attr_re = re.compile(r'(?:href|src)\s*=\s*"([^"]*)"')

    violations: list[str] = []
    broken: list[str] = []
    prefixed_seen = 0

    skip_prefixes = ("#", "mailto:", "tel:", "data:", "javascript:")

    for html in html_files:
        rel_html = html.relative_to(SITE)
        text = html.read_text(encoding="utf-8", errors="ignore")
        for raw in attr_re.findall(text):
            link = raw.strip()
            if not link or link.startswith(skip_prefixes):
                continue
            if link.startswith(("http://", "https://", "//")):
                continue  # external — out of scope
            target = link.split("#", 1)[0].split("?", 1)[0]
            if not target:
                continue
            if target.startswith("/"):
                # Root-absolute internal link MUST carry the path prefix.
                if not target.startswith(PREFIX):
                    violations.append(f"{rel_html}: '{link}' missing prefix {PREFIX}")
                    continue
                prefixed_seen += 1
                rel = target[len(PREFIX):]
            else:
                # Relative link — resolve against this page's directory.
                rel = os.path.normpath(str(rel_html.parent / target))
            fs = SITE / rel
            if fs.is_dir() or target.endswith("/") or fs.suffix == "":
                fs = (SITE / rel / "index.html") if fs.suffix == "" else fs
            if not fs.exists():
                broken.append(f"{rel_html}: '{link}' -> {rel} (not found)")

    home_ok = (SITE / "index.html").exists()
    cat_ok = bool(list((SITE / "categories").glob("*/index.html")))
    recipe_ok = bool(list((SITE / "recipes").glob("*/index.html")))

    ok = (
        not violations
        and not broken
        and prefixed_seen > 0
        and home_ok
        and cat_ok
        and recipe_ok
    )
    detail = (
        f"{len(html_files)} HTML files; {prefixed_seen} prefixed internal links; "
        f"home={home_ok} category={cat_ok} recipe={recipe_ok}; "
        f"{len(violations)} prefix violation(s); {len(broken)} broken link(s)."
    )
    if violations:
        detail += " VIOLATIONS: " + " | ".join(violations[:5])
    if broken:
        detail += " BROKEN: " + " | ".join(broken[:5])
    return {"score": 1.0 if ok else 0.0, "status": "pass" if ok else "fail", "detail": detail}


def dim_print_mobile_css() -> dict:
    css_files = list((SITE / "assets" / "css").glob("*.css"))
    css = "\n".join(f.read_text(encoding="utf-8", errors="ignore") for f in css_files)
    has_print = "@media print" in css
    has_break = re.search(r"break-inside\s*:\s*avoid", css) is not None
    has_responsive = re.search(r"@media[^{]*\((?:max|min)-width", css) is not None
    ok = has_print and has_break and has_responsive
    return {
        "score": 1.0 if ok else 0.0,
        "status": "pass" if ok else "fail",
        "detail": f"{len(css_files)} stylesheet(s); @media print={has_print}; "
        f"break-inside:avoid={has_break}; responsive media query={has_responsive}.",
    }


def dim_migration() -> dict:
    """Stubbed until Phase 3 lands migrate.py. Never fails the run."""
    script = ROOT / "migrate.py"
    if not script.exists():
        return {
            "score": None,
            "status": "not_applicable",
            "detail": "migrate.py not present (Phase 3+). Excluded from composite; "
            "does not fail Phase 1.",
        }
    return {
        "score": None,
        "status": "not_applicable",
        "detail": "migrate.py present but Phase-1 harness does not yet score it; "
        "activate in Phase 3.",
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    runners = [
        ("build_succeeds", dim_build),
        ("search_index_built", dim_search),
        ("auto_discovery_invariant", dim_auto_discovery),
        ("link_integrity", dim_link_integrity),
        ("print_mobile_css", dim_print_mobile_css),
        ("migration_correctness", dim_migration),
    ]

    dimensions: dict[str, dict] = {}
    for key, fn in runners:
        try:
            result = fn()
        except Exception as exc:  # never let one dimension crash the report
            result = {"score": 0.0, "status": "error", "detail": f"{type(exc).__name__}: {exc}"}
        result["weight"] = WEIGHTS.get(key, 0.0)
        dimensions[key] = result

    # Composite: weighted mean over applicable dimensions (renormalized).
    applicable = {
        k: v for k, v in dimensions.items()
        if v.get("score") is not None and v.get("status") != "not_applicable"
    }
    total_w = sum(v["weight"] for v in applicable.values()) or 1.0
    composite = sum(v["score"] * v["weight"] for v in applicable.values()) / total_w

    auto_ok = dimensions["auto_discovery_invariant"].get("score") == 1.0
    build_ok = dimensions["build_succeeds"].get("score") == 1.0
    passed = composite >= PASS_THRESHOLD and auto_ok and build_ok

    report = {
        "project": "janels-recipes",
        "phase": 1,
        "composite_score": round(composite, 4),
        "passed": passed,
        "pass_threshold": PASS_THRESHOLD,
        "human_reviewed": False,
        "auto_discovery_invariant_passed": auto_ok,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dimensions": dimensions,
    }
    print(json.dumps(report, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())

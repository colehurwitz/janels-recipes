// capture-screenshots.mjs
// ---------------------------------------------------------------------------
// Captures the screenshots used by EDITING.md, saved into docs/editing-images/.
//
// There are two kinds of shots:
//   * PUBLIC  — the repo file listings and live site. No login needed; these
//               work for anyone because the repo is public.
//   * GATED   — the buttons/panels you only see once you're signed in to
//               GitHub (the pencil edit screen, the "Commit changes" panel,
//               the "Add file" menu, the "Upload files" drop zone). These need
//               a saved login session in `auth.json` (see docs/SCREENSHOTS.md).
//
// Usage:
//   node docs/capture-screenshots.mjs            # captures public shots; adds
//                                                # gated shots too if auth.json exists
//   node docs/capture-screenshots.mjs --public   # only the public (no-login) shots
//
// To produce auth.json the first time, run the one-time login helper:
//   node docs/capture-screenshots.mjs --login    # opens a browser; sign in, then
//                                                # the session is saved to auth.json
//
// auth.json is a LIVE GitHub credential. It is gitignored. NEVER commit it.
// ---------------------------------------------------------------------------

import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { existsSync, mkdirSync } from "node:fs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT_DIR = join(__dirname, "editing-images");
const AUTH_FILE = join(__dirname, "..", "auth.json");

const REPO = "https://github.com/colehurwitz/janels-recipes";
const SITE = "https://colehurwitz.github.io/janels-recipes/";

// A phone-sized viewport so the screenshots match what Janel will actually tap.
const MOBILE = { width: 390, height: 844 }; // ~iPhone 12/13/14
const DESKTOP = { width: 1280, height: 900 };

const args = process.argv.slice(2);
const PUBLIC_ONLY = args.includes("--public");
const LOGIN = args.includes("--login");

function ensureOutDir() {
  if (!existsSync(OUT_DIR)) mkdirSync(OUT_DIR, { recursive: true });
}

async function shoot(page, name) {
  const path = join(OUT_DIR, `${name}.png`);
  await page.screenshot({ path });
  console.log(`  ✓ saved ${name}.png`);
}

// Give a page a moment to settle WITHOUT waiting for "networkidle" — GitHub holds
// long-lived connections open, so networkidle never resolves and would time out.
async function settle(page, ms = 1500) {
  await page.waitForLoadState("domcontentloaded");
  await page.waitForTimeout(ms);
}

// ---------------------------------------------------------------------------
// One-time login: opens a real browser window, you sign in (incl. 2FA), then
// the authenticated session is saved to auth.json for the gated captures.
// ---------------------------------------------------------------------------
async function doLogin() {
  console.log(
    "Opening a browser. Sign in to GitHub (including 2FA), wait until you see\n" +
      "your repo, then come back to this terminal and press Enter."
  );
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext({ viewport: DESKTOP });
  const page = await context.newPage();
  await page.goto("https://github.com/login");

  // Wait for the human to finish signing in.
  await new Promise((resolve) => {
    process.stdin.resume();
    process.stdin.once("data", resolve);
  });

  await context.storageState({ path: AUTH_FILE });
  console.log(`\nSaved login session to ${AUTH_FILE} (gitignored — never commit it).`);
  await browser.close();
}

// ---------------------------------------------------------------------------
// PUBLIC shots — no login required.
// ---------------------------------------------------------------------------
async function capturePublic(browser) {
  console.log("Public screenshots (no login needed):");

  // Mobile shots for the file-navigation steps (what she sees on a phone).
  const mobile = await browser.newContext({ viewport: MOBILE, deviceScaleFactor: 2 });
  const mp = await mobile.newPage();

  await mp.goto(`${REPO}/tree/main/content/recipes`);
  await settle(mp);
  await shoot(mp, "recipes-folder");

  await mp.goto(`${REPO}/blob/main/content/recipes/grandmas-apple-cake.md`);
  await settle(mp);
  await shoot(mp, "recipe-file-view");

  await mp.goto(`${REPO}/tree/main/content/images`);
  await settle(mp);
  await shoot(mp, "images-folder");

  await mobile.close();

  // Desktop shots of the live site (nicer for the "here's your site" section).
  const desktop = await browser.newContext({ viewport: DESKTOP, deviceScaleFactor: 2 });
  const dp = await desktop.newPage();

  await dp.goto(SITE);
  await settle(dp);
  await shoot(dp, "live-homepage");

  await dp.goto(`${SITE}recipes/grandmas-apple-cake/`);
  await settle(dp);
  await shoot(dp, "live-recipe-page");

  await desktop.close();
}

// ---------------------------------------------------------------------------
// GATED shots — require a signed-in session (auth.json).
//
// NOTE: GitHub's web UI changes over time, so the selectors below are
// best-effort and UNVERIFIED — they need a quick manual check against the real
// signed-in site when you run this. If a click target has moved, the script
// still captures the full page at each step, which is usually enough for the
// guide; adjust the get-by-role names if a specific button isn't framed well.
// ---------------------------------------------------------------------------
async function captureGated(browser) {
  console.log("Signed-in screenshots (using auth.json):");

  const ctx = await browser.newContext({
    viewport: MOBILE,
    deviceScaleFactor: 2,
    storageState: AUTH_FILE,
  });
  const page = await ctx.newPage();

  // --- Edit flow: file view -> pencil -> edit mode -> commit panel ---
  await page.goto(`${REPO}/blob/main/content/recipes/grandmas-apple-cake.md`);
  await settle(page);

  // The pencil/edit control. On mobile it may be inside a "..." overflow menu.
  try {
    const pencil = page.getByRole("link", { name: /edit this file|edit file/i }).first();
    await pencil.scrollIntoViewIfNeeded();
    await shoot(page, "edit-pencil");
    await pencil.click();
    await settle(page, 2500);
    await shoot(page, "edit-mode");
  } catch (e) {
    console.warn("  ! could not open edit mode automatically — capturing full page");
    await shoot(page, "edit-pencil");
  }

  // The "Commit changes" panel (button opens a dialog).
  try {
    await page.getByRole("button", { name: /commit changes/i }).first().click();
    await settle(page, 1500);
    await shoot(page, "commit-changes");
    // Close the dialog without committing.
    await page.keyboard.press("Escape");
  } catch (e) {
    console.warn("  ! could not open the commit panel — skipping commit-changes.png");
  }

  // --- Add file menu: Create new file ---
  await page.goto(`${REPO}/tree/main/content/recipes`);
  await settle(page);
  try {
    await page.getByRole("button", { name: /add file/i }).first().click();
    await page.waitForTimeout(800);
    await shoot(page, "add-file-menu");
    await page.getByRole("menuitem", { name: /create new file/i }).first().click();
    await settle(page, 2000);
    await shoot(page, "create-new-file");
  } catch (e) {
    console.warn("  ! could not open the Add file menu — skipping add-file/create-new-file");
  }

  // --- Upload files drop zone ---
  await page.goto(`${REPO}/upload/main/content/images`);
  await settle(page, 2000);
  await shoot(page, "upload-files");

  await ctx.close();
}

async function main() {
  ensureOutDir();

  if (LOGIN) {
    await doLogin();
    return;
  }

  const browser = await chromium.launch();
  try {
    await capturePublic(browser);

    if (!PUBLIC_ONLY && existsSync(AUTH_FILE)) {
      await captureGated(browser);
    } else if (!PUBLIC_ONLY) {
      console.log(
        "\nNo auth.json found — skipping the signed-in screenshots.\n" +
          "Run `node docs/capture-screenshots.mjs --login` once to sign in,\n" +
          "then run this script again. See docs/SCREENSHOTS.md."
      );
    }
  } finally {
    await browser.close();
  }
  console.log(`\nDone. Images are in ${OUT_DIR}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

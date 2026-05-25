# Screenshots for EDITING.md

`EDITING.md` shows a picture at each step. They live in `docs/editing-images/`
and are produced by `docs/capture-screenshots.mjs` (a small
[Playwright](https://playwright.dev/) script).

There are two kinds:

| Kind | Needs login? | What it shows |
|------|-------------|----------------|
| **Public** | No | The repo's `content/recipes/` and `content/images/` file listings, a recipe `.md` file view, the live homepage, and a live recipe page. |
| **Signed-in (gated)** | Yes | The buttons you only see once you're logged in: the pencil/edit screen, the **Commit changes** panel, the **Add file** menu, and the **Upload files** drop zone. |

The **public** ones are already captured and committed. The **signed-in** ones
need a one-time login, described below. Until they're captured, `EDITING.md`
shows a text placeholder at those steps — the written instructions are complete
on their own, so the guide is fully usable without them.

---

## Captured screenshots (public — already done)

- `recipes-folder.png` — the `content/recipes/` file listing (phone view)
- `recipe-file-view.png` — viewing `apple-pie.md` (phone view)
- `images-folder.png` — the `content/images/` file listing (phone view)
- `live-homepage.png` — the live site homepage
- `live-recipe-page.png` — a live recipe page

## Pending screenshots (need a one-time sign-in)

- `edit-pencil.png` — the pencil ✏️ / "Edit this file" control
- `edit-mode.png` — the recipe open in the editor
- `commit-changes.png` — the "Commit changes" panel
- `add-file-menu.png` — the "Add file" menu with "Create new file"
- `create-new-file.png` — the new-file screen (name box + text area)
- `upload-files.png` — the "Upload files" drop zone

---

## How to capture the signed-in screenshots (one time, ~5 minutes)

You need [Node.js](https://nodejs.org/) installed. From the project folder:

**1. Install Playwright (once):**

```bash
npm install --no-save playwright
npx playwright install chromium
```

**2. Sign in once.** This opens a real browser window:

```bash
node docs/capture-screenshots.mjs --login
```

Sign in to GitHub the normal way — username, password, and your 2FA code if you
use one. When you can see your repository, switch back to the terminal and press
**Enter**. The script saves your session to a file called **`auth.json`**.

> ⚠️ **`auth.json` is a live key to your GitHub account.** It is already listed in
> `.gitignore`, so git will not track it — **never** commit it or share it. If you
> ever think it leaked, sign out of GitHub everywhere (Settings → Sessions) and
> delete the file.

**3. Capture everything:**

```bash
node docs/capture-screenshots.mjs
```

This re-captures the public shots and, because `auth.json` now exists, also
captures the signed-in ones. All images land in `docs/editing-images/`.

**4. Save the images into the repo** (the images, *not* `auth.json`):

```bash
git add docs/editing-images
git commit -m "Add signed-in editing screenshots"
git push
```

That's it — the placeholders in `EDITING.md` will now show real pictures.

---

### Notes

- The script uses a **phone-sized** browser window for the file-navigation shots
  so they match what you'll see on your phone, and a desktop window for the live
  site shots.
- GitHub occasionally rearranges its buttons, so the click targets in the script
  are **best-effort and unverified** — if a specific button isn't framed nicely,
  the script still captures the full screen at each step, which is usually enough.
  Re-run it and glance at the results.
- To capture **only** the public shots (no login), run:
  `node docs/capture-screenshots.mjs --public`

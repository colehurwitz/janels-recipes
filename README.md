# Janel's Recipes

A warm personal cookbook — a static site built with [Eleventy](https://www.11ty.dev/)
and [Pagefind](https://pagefind.app/), deployed free on GitHub Pages at
`https://colehurwitz.github.io/janels-recipes/`.

> Editing the cookbook needs **no terminal and no git** — see `EDITING.md`
> (added in a later phase) for the phone-friendly web-UI guide. This README is
> for developers.

## Local development

```bash
npm ci                      # install (CI uses this; needs package-lock.json)
npx @11ty/eleventy          # build to _site/
npx -y pagefind --site _site  # build the search index into _site/pagefind/
python3 eval/score.py       # run the Phase-1 eval harness (prints JSON)

npm run serve               # live-reload dev server (search needs the step above)
npm run build:full          # build + pagefind in one go
```

Order matters: **build → pagefind → upload**. Pagefind crawls the *built HTML*,
so it must run after Eleventy or search ships empty. The CI workflow
(`.github/workflows/deploy.yml`) enforces this order and deploys on every push
to `main`.

## How it's wired (the auto-discovery contract)

Adding a recipe is **copy an existing `.md` + rename it** — no config, registry,
or index is ever edited. This is the project's #1 invariant:

- Any `.md` in `content/recipes/` becomes a page automatically; its **permalink
  derives from the filename** (`content/recipes/apple-cake.md` →
  `/janels-recipes/recipes/apple-cake/`).
- A single collection rule in `.eleventy.js` (`recipesByCategory`) groups recipes
  by their frontmatter `category` and powers all 8 category pages forever.
- Pagefind re-crawls the built HTML on every deploy, so new recipes become
  searchable with nothing to register.
- `eval/score.py`'s `auto_discovery_invariant` dimension encodes this as a test:
  it adds a temp recipe, rebuilds, and asserts it appears on its category page
  **and** in the search index with no other file changed.

### Recipe frontmatter (forgiving — extra/missing optional fields never hard-fail)

```markdown
---
title: Grandma's Apple Cake
category: Desserts        # one of the 8 fixed categories
image: apple-cake.svg     # optional — file in content/images/
notes: Even better the next day.   # optional
---

## Ingredients
- ...

## Directions
1. ...
```

The 8 fixed categories live in one place — `content/_data/categories.js` —
imported by both the templates and the collection rule.

## pathPrefix discipline

The site is served from `/janels-recipes/`, not a domain root. **Every** internal
link and asset reference goes through Eleventy's `url` filter; never hard-code
root-absolute paths. Self-hosted fonts are referenced with relative paths inside
the CSS. The eval's `link_integrity` dimension fails the build if any internal
link drops the prefix or dangles.

## Layout

```
.eleventy.js                 ESM config: pathPrefix, passthrough, the one collection rule
content/
  _data/categories.js        the 8 fixed categories (single source of truth)
  _data/site.js              site metadata
  _includes/base.njk         warm-cookbook chrome (header/nav/footer)
  _includes/recipe.njk       recipe page (hero, print button, @media print)
  index.njk                  homepage: 8 cards + Pagefind search box
  categories.njk             one page per category (paginated)
  recipes/*.md               recipes (auto-discovered) + recipes.11tydata.json (layout)
  assets/css/style.css       warm theme, mobile-first, @font-face, print block
  assets/fonts/*.woff2       self-hosted Fraunces + Lora (zero third-party requests)
  images/*                   recipe images
.github/workflows/deploy.yml build → pagefind → upload → deploy (Pages via Actions)
eval/score.py                Phase-1 eval harness
.factory/eval_profile.json   eval dimensions + weights
```

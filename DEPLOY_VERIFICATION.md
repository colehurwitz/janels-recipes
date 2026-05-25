# Deploy Verification — Phase 2 (Operational)

Records the live deployment of the Phase-1 scaffold to GitHub Pages and the
end-to-end checks proving the editor's **commit → auto-deploy** loop works on
real infrastructure before any content lands.

## Identity

| Item | Value |
|---|---|
| Repository | https://github.com/colehurwitz/janels-recipes (PUBLIC) |
| Live site | https://colehurwitz.github.io/janels-recipes/ |
| Pages source | GitHub Actions (`build_type: workflow`) |
| Deployed commit | `35f00f7830a30cb6a07ebf0572aba8acee02385d` (= `main` HEAD) |
| Verified on | 2026-05-25 |

## Green Actions deploy run

| Item | Value |
|---|---|
| Workflow | Build and deploy to GitHub Pages |
| Run ID | `26417769138` |
| Run URL | https://github.com/colehurwitz/janels-recipes/actions/runs/26417769138 |
| Status / conclusion | completed / **success** |
| build job | `77765826512` — ✓ (checkout → setup-node → `npm ci` → Eleventy → Pagefind → configure-pages → upload-pages-artifact) |
| deploy job | `77765855695` — ✓ (`deploy-pages@v4`, environment `github-pages`) |

> Note: a non-blocking annotation warns that the pinned Node-20 actions will be
> forced to Node 24 in June 2026. This is a future-deprecation notice only — the
> run completed green. Bumping action versions is out of Phase-2 scope.

## Live verification checks

All checks performed with `curl` against the public URL after deploy.

| # | Check | Method | Result |
|---|---|---|---|
| 1 | Homepage responds | `curl -sI https://colehurwitz.github.io/janels-recipes/` | **HTTP 200** |
| 2 | Homepage renders site title | grep `<title>` | `Janel's Recipes` ✓ |
| 3 | Homepage renders category nav | count `categories/*` links | **8/8** categories present (appetizers, breads, breakfast, desserts, dinner, miscellaneous, soups-and-stews, vegetables-and-sides) ✓ |
| 4 | Homepage tagline renders | grep tagline | "A warm little cookbook…" ✓ |
| 5 | Sample recipe page responds | `curl -sI .../recipes/grandmas-apple-cake/` | **HTTP 200** |
| 6 | Recipe page renders title + body | grep title/heading | `Grandma's Apple Cake · Janel's Recipes`, "Apple Cake" body present ✓ |
| 7 | Recipe print affordance present | grep `window.print()` | ✓ |
| 8 | Recipe links respect path prefix | count `/janels-recipes/` refs | 12 prefixed links, no root-absolute leakage ✓ |
| 9 | Pagefind runtime loads | `curl -sI .../pagefind/pagefind.js` | **HTTP 200** |
| 10 | Pagefind entry manifest loads | `curl -sI .../pagefind/pagefind-entry.json` | **HTTP 200** |
| 11 | Search corpus indexed | parse `pagefind-entry.json` | `en` index, **page_count = 6** (all 6 sample recipes indexed and searchable) ✓ |

### Search note

Pagefind search executes client-side via JavaScript, which `curl` cannot run.
Verification is therefore at the data layer: the live `/pagefind/` bundle loads
(checks 9–10) and its index manifest reports all **6** recipe pages indexed
(check 11), confirming a search query has a populated corpus to return results
from under the `/janels-recipes/` prefix.

## Summary

✅ All Phase-2 exit criteria met: PUBLIC repo created, scaffold pushed to `main`,
Pages source set to GitHub Actions, deploy run green, and the live site verified
(homepage + category nav render, sample recipe renders with print support and
correct path-prefixed links, Pagefind bundle loads with all 6 recipes indexed).
The commit → auto-deploy loop is proven on real infrastructure.

No blockers. Phases 3–5 remain out of scope for this phase.

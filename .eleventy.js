// Eleventy v3 config — ESM (package.json has "type": "module").
//
// Design contract this file protects (do not weaken):
//   * AUTO-DISCOVERY — any `.md` dropped into content/recipes/ becomes a recipe
//     page with ZERO config/registry edits. Permalinks derive from the filename,
//     so "add a recipe" = copy an existing .md + rename it in the GitHub web UI.
//   * ONE category rule — the `recipesByCategory` collection below groups every
//     recipe by its frontmatter `category`. A new file with `category: Desserts`
//     auto-appears under Desserts. Nothing here is edited per recipe.
//   * pathPrefix `/janels-recipes/` — the site is served from a project subpath,
//     so every internal link/asset ref in templates must go through the `url`
//     filter. Never hard-code root-absolute paths.

import categories from "./content/_data/categories.js";

// Forgiving, deterministic slug used for BOTH category permalinks and the links
// that point at them — defining it once guarantees the two always agree, which
// is what the link-integrity eval dimension checks. "&" -> "and" on purpose so
// "Vegetables & Sides" -> "vegetables-and-sides".
function categorySlug(value) {
  return String(value)
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export default function (eleventyConfig) {
  // --- Static assets (copied verbatim into _site) ---------------------------
  // CSS references fonts with RELATIVE paths, so passthrough survives pathPrefix.
  eleventyConfig.addPassthroughCopy({ "content/assets": "assets" });
  // Recipe images. Editors drag-drop files in here via the web UI.
  eleventyConfig.addPassthroughCopy({ "content/images": "images" });

  // --- Shortcodes -----------------------------------------------------------
  eleventyConfig.addShortcode(
    "recipeJsonLd",
    function (title, category, notes, image, pageUrl, siteUrl, siteTitle, siteDescription) {
      const obj = {
        "@context": "https://schema.org",
        "@type": "Recipe",
        name: title,
      };

      if (category) {
        obj.recipeCategory = category;
      }

      obj.description = notes || siteDescription;

      if (image) {
        obj.image = siteUrl + "/images/" + image;
      }

      obj.url = siteUrl + pageUrl;
      obj.mainEntityOfPage = siteUrl + pageUrl;

      obj.author = {
        "@type": "Person",
        name: siteTitle,
      };

      return `<script type="application/ld+json">${JSON.stringify(obj, null, 2)}</script>`;
    }
  );

  // --- Filters --------------------------------------------------------------
  eleventyConfig.addFilter("categorySlug", categorySlug);

  // --- The single category-driven collection rule ---------------------------
  // Groups every recipe by frontmatter `category`, alphabetised by title.
  // Forgiving: unknown / missing category falls back to "Miscellaneous" rather
  // than hard-failing the build (a non-technical editor must never be able to
  // break the whole site with one stray frontmatter value).
  eleventyConfig.addCollection("recipesByCategory", (collectionApi) => {
    const groups = Object.fromEntries(categories.map((c) => [c, []]));
    const canonical = new Map(categories.map((c) => [c.toLowerCase(), c]));

    for (const item of collectionApi.getFilteredByGlob("./content/recipes/*.md")) {
      const raw = String(item.data.category || "").trim();
      const key = canonical.get(raw.toLowerCase()) || "Miscellaneous";
      groups[key].push(item);
    }

    for (const c of categories) {
      groups[c].sort((a, b) =>
        String(a.data.title || "").localeCompare(String(b.data.title || ""), "en", {
          sensitivity: "base",
        })
      );
    }
    return groups;
  });

  // Flat list of all recipes (handy for counts / future use).
  eleventyConfig.addCollection("recipes", (collectionApi) =>
    collectionApi
      .getFilteredByGlob("./content/recipes/*.md")
      .sort((a, b) =>
        String(a.data.title || "").localeCompare(String(b.data.title || ""))
      )
  );

  return {
    pathPrefix: "/janels-recipes/",
    markdownTemplateEngine: "njk",
    htmlTemplateEngine: "njk",
    dir: {
      input: "content",
      output: "_site",
      includes: "_includes",
      data: "_data",
    },
  };
}

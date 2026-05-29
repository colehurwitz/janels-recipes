// Site-wide metadata. Kept tiny and forgiving.
export default {
  title: "Janel's Recipes",
  tagline: "A warm little cookbook, kept by hand.",
  description:
    "Janel's personal recipe collection — desserts, dinners, breads and more, all in one cosy place.",
  // Canonical origin + project subpath (matches pathPrefix), no trailing slash.
  // Used to build absolute URLs for JSON-LD structured data. Because this value
  // already includes the `/janels-recipes` path prefix, absolute URLs are built
  // from the RAW (pre-prefix) page.url — NOT the `| url` filter, which would
  // re-add the prefix and double it.
  url: "https://colehurwitz.github.io/janels-recipes",
};

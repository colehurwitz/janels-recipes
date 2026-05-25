// The 8 fixed categories from the source doc's table of contents.
// SINGLE SOURCE OF TRUTH — imported by templates (as global data `categories`)
// AND by .eleventy.js (the category-driven collection rule). Order here is the
// order the cards/nav render in. Editors never touch this; recipes attach to a
// category purely via their frontmatter `category:` field.
export default [
  "Desserts",
  "Dinner",
  "Breads",
  "Appetizers",
  "Vegetables & Sides",
  "Breakfast",
  "Soups & Stews",
  "Miscellaneous",
];

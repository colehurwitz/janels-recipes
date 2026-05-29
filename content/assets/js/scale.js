/*
 * Janel's Recipes — client-side recipe scaling (progressive enhancement).
 *
 * Dependency-free, self-hosted. With JavaScript disabled, recipe pages render
 * exactly as today: plain 1x text with no controls. With JavaScript on, this
 * script parses the leading quantity token of each ingredient paragraph inside
 * ".recipe-content p" and injects a ½x / 1x / 2x / 3x toolbar so a reader can
 * rescale the displayed amounts. The parsed decimal is the source of truth;
 * visible text is recomputed on each factor change.
 *
 * Safety: every paragraph is processed inside its own try/catch and the whole
 * setup is guarded — this script never throws and silently no-ops on anything
 * it cannot parse. Events are bound in JS (no inline handlers).
 */
(function () {
  "use strict";

  // Unicode vulgar fractions -> decimal value.
  var FRACTION_VALUES = {
    "½": 1 / 2,  // ½
    "⅓": 1 / 3,  // ⅓
    "⅔": 2 / 3,  // ⅔
    "¼": 1 / 4,  // ¼
    "¾": 3 / 4,  // ¾
    "⅛": 1 / 8,  // ⅛
    "⅜": 3 / 8,  // ⅜
    "⅝": 5 / 8,  // ⅝
    "⅞": 7 / 8,  // ⅞
    "⅕": 1 / 5,  // ⅕
    "⅖": 2 / 5,  // ⅖
    "⅗": 3 / 5,  // ⅗
    "⅘": 4 / 5,  // ⅘
    "⅙": 1 / 6,  // ⅙
    "⅚": 5 / 6   // ⅚
  };

  // Cooking-friendly fractions to snap a computed fractional part to.
  var SNAP_TARGETS = [
    { value: 0, glyph: "" },
    { value: 1 / 8, glyph: "⅛" },
    { value: 1 / 6, glyph: "⅙" },
    { value: 1 / 4, glyph: "¼" },
    { value: 1 / 3, glyph: "⅓" },
    { value: 1 / 2, glyph: "½" },
    { value: 2 / 3, glyph: "⅔" },
    { value: 3 / 4, glyph: "¾" },
    { value: 5 / 6, glyph: "⅚" },
    { value: 1, glyph: "" } // carries to the whole number
  ];
  var SNAP_TOLERANCE = 0.075;

  // Character class of every supported unicode fraction.
  var FRACTION_CLASS = "[½⅓⅔¼¾⅛⅜⅝⅞⅕⅖⅗⅘⅙⅚]";

  // A single quantity value, most-specific alternative first:
  //   mixed (1½ / 1 ½), mixed ascii (1 1/2), ascii fraction (3/4),
  //   lone unicode fraction (½), decimal / integer (2, 0.5, 350).
  var VALUE =
    "(?:\\d+\\s*" + FRACTION_CLASS + ")" +
    "|(?:\\d+\\s+\\d+\\/\\d+)" +
    "|(?:\\d+\\/\\d+)" +
    "|(?:" + FRACTION_CLASS + ")" +
    "|(?:\\d+(?:\\.\\d+)?)";

  // Dash characters that may join a range: hyphen-minus, en dash, em dash.
  var DASHES = "[\\-–—]";

  // Leading quantity token, anchored at position 0, with optional range tail.
  // Paragraphs that begin with a letter (instruction prose) fail this match.
  var LEAD_RE = new RegExp(
    "^((?:" + VALUE + ")(?:\\s*" + DASHES + "\\s*(?:" + VALUE + "))?)"
  );

  // Splits a matched leading token into its two range endpoints, if any.
  var RANGE_RE = new RegExp(
    "^(" + VALUE + ")\\s*" + DASHES + "\\s*(" + VALUE + ")$"
  );

  // If the leading number is immediately followed by a size unit it describes a
  // dimension (e.g. 1/8-1/4" thick, 9 inch pan, 5 cm) and must NOT be scaled.
  var SIZE_UNIT_RE = /^\s*(?:"|″|′|”|’|''|inch(?:es)?\b|cm\b)/i;

  // A leading number immediately followed by "x"/"×" then a digit is a pan
  // dimension (e.g. "9x13 pan") — the "9" is not an ingredient amount.
  var PAN_DIM_RE = /^\s*[x×]\s*\d/i;

  // A leading number followed by a temperature/time/degree marker is not an
  // ingredient amount (e.g. "350°F oven", "10 minutes", "2 hours"). Only ever
  // suppress scaling for these — never scale them. We deliberately do NOT match
  // a bare "F"/"C": with the /i flag it also matches lowercase "c" (= cups, a
  // common ingredient abbreviation), wrongly suppressing scaling for "2 c flour".
  // Temperatures with a degree symbol (°/℉/℃) are still caught below, and
  // letter-led lines like "Bake at 350 F" already fail LEAD_RE.
  var NON_AMOUNT_RE =
    /^\s*(?:°|℉|℃|degrees?\b|min(?:ute)?s?\b|hours?\b|seconds?\b)/i;

  // Parse a single quantity string into a decimal, or null if unparseable.
  function valueToDecimal(raw) {
    var str = raw.trim();
    var m;

    if (str.length === 1 && FRACTION_VALUES[str] != null) {
      return FRACTION_VALUES[str];
    }
    m = str.match(new RegExp("^(\\d+)\\s*(" + FRACTION_CLASS + ")$"));
    if (m) {
      return parseInt(m[1], 10) + FRACTION_VALUES[m[2]];
    }
    m = str.match(/^(\d+)\s+(\d+)\/(\d+)$/);
    if (m) {
      return parseInt(m[1], 10) + parseInt(m[2], 10) / parseInt(m[3], 10);
    }
    m = str.match(/^(\d+)\/(\d+)$/);
    if (m) {
      return parseInt(m[1], 10) / parseInt(m[2], 10);
    }
    if (/^\d+(?:\.\d+)?$/.test(str)) {
      return parseFloat(str);
    }
    return null;
  }

  // Format a decimal as a cooking-friendly amount, snapping the fractional part
  // to the nearest nice fraction, falling back to one decimal place when the
  // value is not close to any clean fraction.
  function formatQuantity(value) {
    if (!isFinite(value) || value < 0) {
      return String(value);
    }
    var whole = Math.floor(value);
    var frac = value - whole;

    var best = SNAP_TARGETS[0];
    var bestDiff = Infinity;
    for (var i = 0; i < SNAP_TARGETS.length; i++) {
      var diff = Math.abs(frac - SNAP_TARGETS[i].value);
      if (diff < bestDiff) {
        bestDiff = diff;
        best = SNAP_TARGETS[i];
      }
    }

    if (bestDiff <= SNAP_TOLERANCE) {
      var glyph = best.glyph;
      if (best.value === 1) {
        whole += 1; // fractional part rounded up to a whole unit
      }
      if (glyph === "") {
        return String(whole);
      }
      if (whole === 0) {
        return glyph;
      }
      return whole + glyph;
    }

    var rounded = Math.round(value * 10) / 10;
    return rounded.toFixed(1);
  }

  // Wrap the matched leading token of a paragraph in a <span class="qty"> that
  // records the base decimal(s). Returns the span, or null if it could not.
  function wrapLeadingQuantity(paragraph) {
    var node = paragraph.firstChild;
    if (!node || node.nodeType !== 3) {
      return null; // must begin with a text node
    }

    var text = node.nodeValue;
    var match = LEAD_RE.exec(text);
    if (!match) {
      return null; // starts with a letter / no leading quantity
    }

    var token = match[1];
    var rest = text.slice(token.length);
    if (SIZE_UNIT_RE.test(rest) || NON_AMOUNT_RE.test(rest) || PAN_DIM_RE.test(rest)) {
      return null; // dimension, pan size, or temperature/time marker, not an amount
    }

    var span = document.createElement("span");
    span.className = "qty";

    var range = RANGE_RE.exec(token);
    if (range) {
      var lo = valueToDecimal(range[1]);
      var hi = valueToDecimal(range[2]);
      if (lo == null || hi == null || lo <= 0 || hi <= 0 || hi < lo) {
        return null;
      }
      span.setAttribute("data-base-lo", String(lo));
      span.setAttribute("data-base-hi", String(hi));
    } else {
      var base = valueToDecimal(token);
      if (base == null || base <= 0) {
        return null;
      }
      span.setAttribute("data-base", String(base));
    }
    // Preserve the original token verbatim so the 1x render is byte-identical
    // to the source text (no snapping/reformatting until the user scales).
    span.setAttribute("data-orig", token);
    span.textContent = token;

    var after = document.createTextNode(rest);
    paragraph.insertBefore(after, node);
    paragraph.insertBefore(span, after);
    paragraph.removeChild(node);
    return span;
  }

  // Recompute the visible text of one quantity span for the given factor.
  function renderSpan(span, factor) {
    // At 1x, show the original source text verbatim — never reformat/snap.
    if (factor === 1) {
      var orig = span.getAttribute("data-orig");
      if (orig !== null) {
        span.textContent = orig;
        return;
      }
    }
    var lo = span.getAttribute("data-base-lo");
    if (lo !== null) {
      var hi = span.getAttribute("data-base-hi");
      span.textContent =
        formatQuantity(parseFloat(lo) * factor) +
        "–" +
        formatQuantity(parseFloat(hi) * factor);
      return;
    }
    var base = span.getAttribute("data-base");
    if (base !== null) {
      span.textContent = formatQuantity(parseFloat(base) * factor);
    }
  }

  function init() {
    try {
      var content = document.querySelector(".recipe-content");
      if (!content) {
        return;
      }

      var paragraphs = content.querySelectorAll("p");
      var spans = [];
      for (var i = 0; i < paragraphs.length; i++) {
        try {
          var span = wrapLeadingQuantity(paragraphs[i]);
          if (span) {
            spans.push(span);
          }
        } catch (perParagraphError) {
          // Ignore a single unparseable paragraph and keep going.
        }
      }

      if (!spans.length) {
        return; // nothing scalable on this page; do not show controls
      }

      var factors = [
        { factor: 0.5, label: "½×" }, // ½×
        { factor: 1, label: "1×" },
        { factor: 2, label: "2×" },
        { factor: 3, label: "3×" }
      ];

      var toolbar = document.createElement("div");
      toolbar.className = "recipe-scaler";
      toolbar.setAttribute("role", "group");
      toolbar.setAttribute("aria-label", "Scale recipe");
      toolbar.setAttribute("data-pagefind-ignore", "");

      var caption = document.createElement("span");
      caption.className = "scale-label";
      caption.textContent = "Scale:";
      toolbar.appendChild(caption);

      var status = document.createElement("span");
      status.className = "scale-status";
      status.setAttribute("aria-live", "polite");

      var indicator = document.querySelector(".scale-indicator");
      var buttons = [];

      function selectFactor(choice, button) {
        for (var b = 0; b < spans.length; b++) {
          renderSpan(spans[b], choice.factor);
        }
        for (var k = 0; k < buttons.length; k++) {
          buttons[k].setAttribute(
            "aria-pressed",
            buttons[k] === button ? "true" : "false"
          );
        }
        status.textContent = "Showing quantities at " + choice.label;
        if (indicator) {
          indicator.textContent =
            choice.factor === 1 ? "" : "Quantities scaled to " + choice.label;
        }
      }

      for (var j = 0; j < factors.length; j++) {
        (function (choice) {
          var button = document.createElement("button");
          button.type = "button";
          button.className = "scale-btn";
          button.textContent = choice.label;
          button.setAttribute("aria-pressed", choice.factor === 1 ? "true" : "false");
          button.addEventListener("click", function () {
            selectFactor(choice, button);
          });
          toolbar.appendChild(button);
          buttons.push(button);
        }(factors[j]));
      }

      toolbar.appendChild(status);
      content.parentNode.insertBefore(toolbar, content);

      // Normalise the initial display to 1x (default selected button).
      selectFactor(factors[1], buttons[1]);
    } catch (setupError) {
      // Progressive enhancement: on any failure leave the plain page intact.
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
}());

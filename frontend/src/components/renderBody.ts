/**
 * Heuristic renderer for the engine's plain-prose markdown bodies.
 *
 * The Strapi `bodyMarkdown` field is flat prose: blank-line-separated
 * fragments with no `#` heading markers. Short standalone fragments are either
 * section headings, list items, or (rarely) short paragraphs. We disambiguate:
 *
 *  - A LIST ITEM is a short fragment in a run of 2+ consecutive short
 *    fragments, where the FIRST of the run is treated as a heading only if it
 *    reads like a section label (not a numbered step / field label).
 *  - A HEADING is a short fragment that introduces a following long paragraph
 *    and is not itself a numbered step, a "Key: Value" field label, or a
 *    bare "Pros:"/"Cons:" marker.
 *  - Everything else is a paragraph.
 */
import type { TocItem } from "./TableOfContents";

export interface RenderedBody {
  html: string;
  toc: TocItem[];
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[’'"]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** Render inline markdown: **bold**, *italic*, [text](url). */
function inline(text: string): string {
  let out = escapeHtml(text);
  out = out.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/(^|\W)\*([^*\n]+)\*/g, "$1<em>$2</em>");
  return out;
}

const isShort = (t: string) =>
  t.length > 0 && t.length <= 80 && !/[.!?…]$/.test(t) && t.split(/\s+/).length <= 12;
const isLong = (t: string) => t.length > 90 || /[.!?…]$/.test(t);
const hasMarker = (t: string) => /^[-*•]\s/.test(t);

/** "1. Tbilisi", "Step 2: ...", "Pros:", "Tax Rate: 0%", list lead-ins, and
 *  imperative/continuation openers — NOT section headings. Applied everywhere
 *  (isolated fragments AND run detection) so these break up heading runs. */
function isNonHeadingShort(t: string): boolean {
  if (/^\d+[.)]\s/.test(t)) return true;                    // numbered step "1. Foo"
  if (/^step\s+\d+/i.test(t)) return true;                  // "Step 2: ..."
  if (/^(pros?|cons?)\s*:?$/i.test(t)) return true;         // bare "Pros:" / "Cons:"
  if (/^[A-Z][A-Za-z /&-]{1,22}:\s*\S/.test(t)) return true; // "Tax Rate: 0%", "Minimum Spend: None"
  if (/\(/.test(t)) return true;                            // contains parenthetical detail -> field/line item
  if (/[,;:]$/.test(t)) return true;                        // list lead-in "Options include:"
  // Imperative verbs / sentence-continuation openers read as steps or list
  // items, never as section labels.
  if (/^(calculate|evaluate|explore|consider|once|before|after|shop|receive|present|reduce[ds]?|language|cross-cultural|location-independent|comfort|remote work infrastructure|options|sign up|keep|prioritize|choose|set up|make|use|avoid|check|plan|start|get|pick|compare|research|book|pack|test)\b/i.test(t)) return true;
  // Short fragments starting with a lowercase word or a participial/gerund
  // phrase are list continuations, not headings.
  if (/^[a-z]/.test(t)) return true;                        // starts lowercase
  if (/^(adaptability|negotiating|stable|cost of living|multi-currency|establish|secure|loss of|opportunity|largest|slightly|intuitive|more expensive|unlimited|newer|user-friendly|can be|genuine|free plan|excellent|smaller|massive|optimized|limited|interface|travel (in)?frequently|travel regularly)\b/i.test(t)) return true;
  // Continuation fragments: gerund/participle openers, feature-benefit noun
  // phrases, and second-person conditional list items.
  if (/^[A-Z][a-z]+ing\b/.test(t)) return true;             // "Navigating...", "Transitioning..."
  if (/^(global|paid|visa|tax planning|build|24\/7|strong|some|highly|not suitable|free version|advanced|are new|have found|double)\b/i.test(t)) return true;
  // Feature/benefit fragments: adjective-led, list-noun-led, or second-person
  // desire statements — these are bullets, not section labels.
  if (/^(expertise|cultural adjustments?|not location|internet reliability|emergency fund|\d+ simultaneous|genuinely|fast speeds?|good speed|want maximum|want to|need to)\b/i.test(t)) return true;
  if (/^(safety considerations?|investment accounts?|climate preferences?|cultural and language|healthcare quality)\b/i.test(t)) return true;
  if (/^(manage all|cryptocurrency|premium \(|government-issued|download the|fbar reporting|monitor exchange)\b/i.test(t)) return true;
  if (/^(stock and commodity|proof of address|complete digital|tax implications)\b/i.test(t)) return true;
  if (/^(travel insurance|social security|fund your|compliance with)\b/i.test(t)) return true;
  if (/^support for\b/i.test(t)) return true;
  if (/^physical and virtual\b/i.test(t)) return true;
  if (/^real-time\b/i.test(t)) return true;
  if (/^integration with\b/i.test(t)) return true;
  return false;
}

export function renderBody(bodyMarkdown: string): RenderedBody {
  const fragments = bodyMarkdown
    .split(/\n\s*\n+/)
    .map((f) => f.trim())
    .filter((f) => f.length > 0);

  const toc: TocItem[] = [];
  const htmlParts: string[] = [];
  const usedIds = new Set<string>();
  let listBuffer: string[] = [];

  const flushList = () => {
    if (listBuffer.length > 0) {
      htmlParts.push(`<ul>${listBuffer.map((li) => `<li>${inline(li)}</li>`).join("")}</ul>`);
      listBuffer = [];
    }
  };

  const uniqueId = (base: string) => {
    let id = base || "section";
    let n = 2;
    while (usedIds.has(id)) id = `${base}-${n++}`;
    usedIds.add(id);
    return id;
  };

  const kinds: Array<"h" | "li" | "p"> = new Array(fragments.length).fill("p");
  for (let i = 0; i < fragments.length; i++) {
    const t = fragments[i];
    if (hasMarker(t)) { kinds[i] = "li"; continue; }
    if (!isShort(t)) { kinds[i] = "p"; continue; }
    if (isNonHeadingShort(t)) { kinds[i] = "p"; continue; }  // render as its own line/paragraph

    // Run of consecutive heading-eligible short fragments.
    let runStart = i;
    while (runStart > 0 && isShort(fragments[runStart - 1]) && !hasMarker(fragments[runStart - 1]) && !isNonHeadingShort(fragments[runStart - 1])) runStart--;
    let runEnd = i;
    while (runEnd < fragments.length - 1 && isShort(fragments[runEnd + 1]) && !hasMarker(fragments[runEnd + 1]) && !isNonHeadingShort(fragments[runEnd + 1])) runEnd++;
    const runLength = runEnd - runStart + 1;

    const next = fragments[i + 1];
    const followedByLong = next !== undefined && isLong(next);

    if (runLength >= 2) {
      kinds[i] = i === runStart ? "h" : "li";
    } else {
      // Isolated short fragment: heading only if it introduces a long paragraph.
      kinds[i] = followedByLong ? "h" : "p";
    }
  }

  let seenParagraph = false;
  for (let i = 0; i < fragments.length; i++) {
    const frag = fragments[i];
    const kind = kinds[i];

    if (kind === "h") {
      flushList();
      if (!seenParagraph) { htmlParts.push(`<p>${inline(frag)}</p>`); continue; }
      const id = uniqueId(slugify(frag));
      toc.push({ id, text: frag });
      htmlParts.push(`<h2 id="${id}">${inline(frag)}</h2>`);
      continue;
    }

    if (kind === "li") {
      listBuffer.push(frag.replace(/^[-*•]\s+/, ""));
      continue;
    }

    flushList();
    seenParagraph = true;
    htmlParts.push(`<p>${inline(frag)}</p>`);
  }
  flushList();

  return { html: htmlParts.join("\n"), toc };
}

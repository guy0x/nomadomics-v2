/**
 * GFM markdown renderer for article bodies.
 *
 * Renders `bodyMarkdown` with full GitHub-flavored markdown (headings, bullet
 * and ordered lists, tables, blockquotes, bold/italic, links) via
 * react-markdown + remark-gfm, serialized to an HTML string for the existing
 * `dangerouslySetInnerHTML` contract.
 *
 * Behavior notes:
 *  - The leading `# Title` H1 is dropped — the page already renders its own
 *    H1 from `article.title`, and the house voice mandates a single H1.
 *  - H2 headings get slugified ids and feed the returned `toc` (sidebar TOC).
 *  - Links open in a new tab with `rel="noopener noreferrer"`.
 */
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
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

/** Flatten React children (strings/numbers/nested arrays) to plain text. */
function extractText(node: unknown): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (typeof node === "object" && "props" in (node as Record<string, unknown>)) {
    return extractText((node as { props?: { children?: unknown } }).props?.children);
  }
  return "";
}

export function renderBody(bodyMarkdown: string): RenderedBody {
  // Drop a leading single H1 (the article title — page renders its own).
  const body = bodyMarkdown.replace(/^\s*#\s+[^\n]+\n?/, "");

  const toc: TocItem[] = [];
  const usedIds = new Set<string>();

  const uniqueId = (base: string): string => {
    let id = base || "section";
    let n = 2;
    while (usedIds.has(id)) id = `${base}-${n++}`;
    usedIds.add(id);
    return id;
  };

  const components: Components = {
    h2: ({ node: _node, children, ...props }) => {
      const text = extractText(children);
      const id = uniqueId(slugify(text));
      toc.push({ id, text });
      return (
        <h2 id={id} {...props}>
          {children}
        </h2>
      );
    },
    a: ({ node: _node, href, children, ...props }) => (
      <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
        {children}
      </a>
    ),
  };

  const html = renderToStaticMarkup(
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {body}
    </ReactMarkdown>
  );

  return { html, toc };
}

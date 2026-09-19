import { ImageResponse } from "next/og";

/**
 * Homepage Open Graph card (1200x630).
 *
 * The homepage previously shipped no `og:image` at all, so sharing the site
 * produced a bare link with no card. Article pages keep their own per-slug OG art
 * (set in `[slug]/page.tsx` metadata); this covers the root segment only.
 *
 * Drawn in code, deterministic, no image model involved — generated covers have
 * shipped misspelled headlines, and a site card is exactly the wrong place to
 * risk that.
 */
export const alt = "Nomadomics — money tips for travelers";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const BRAND = "#0f8a5f";
const INK = "#0b1220";
const PAPER = "#f4faf7";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: PAPER,
          padding: "64px 72px",
        }}
      >
        {/* wordmark */}
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <div
            style={{
              position: "relative",
              width: 72,
              height: 72,
              display: "flex",
              border: "5px solid #ffffff",
              borderRadius: "50%",
              background: BRAND,
            }}
          >
            <div
              style={{
                position: "absolute",
                top: 31,
                left: 0,
                width: 72,
                height: 5,
                background: "#ffffff",
              }}
            />
            {/* full ellipse, not a borders-only box: satori drops border-radius
                on those and the "meridian" renders as straight bars */}
            <div
              style={{
                position: "absolute",
                top: 0,
                left: 21,
                width: 30,
                height: 72,
                border: "5px solid #ffffff",
                borderRadius: "50%",
              }}
            />
          </div>
          <div style={{ display: "flex", fontSize: 54, fontWeight: 700, color: INK }}>
            Nomad<span style={{ color: BRAND }}>omics</span>
          </div>
        </div>

        {/* headline + tagline */}
        <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              fontSize: 76,
              fontWeight: 700,
              lineHeight: 1.1,
              color: INK,
              maxWidth: 980,
            }}
          >
            Keep more of what you earn. Live wherever you want.
          </div>
          <div style={{ display: "flex", fontSize: 32, color: "#3d5a52", maxWidth: 900 }}>
            No-fluff money guides: banking that doesn&apos;t bleed you, taxes you can
            understand, and the real cost of every border.
          </div>
        </div>

        {/* footer strip */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            borderTop: `3px solid ${BRAND}`,
            paddingTop: 26,
            fontSize: 26,
            color: "#3d5a52",
          }}
        >
          <div style={{ display: "flex" }}>nomadomics.blog</div>
          <div style={{ display: "flex", color: BRAND, fontWeight: 700 }}>
            Banking · Taxes · Travel · Gear · Cities
          </div>
        </div>
      </div>
    ),
    size
  );
}

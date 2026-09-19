import { ImageResponse } from "next/og";

/**
 * Apple touch icon (180x180) — the home-screen tile for iOS/iPadOS.
 *
 * Drawn in code rather than shipped as a binary so it can never drift from the
 * brand: same `brand-600` tile and globe mark as the header logo (SiteHeader).
 * The globe is composed from bordered divs because ImageResponse supports only
 * flexbox + absolute positioning, not SVG.
 */
export const size = { width: 180, height: 180 };
export const contentType = "image/png";

const BRAND = "#0f8a5f";
const MARK = 116;

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: BRAND,
        }}
      >
        {/* globe: ring + equator + meridian.
            The meridian is a full bordered ellipse, not a div with only left/right
            borders — satori ignores border-radius on a borders-only box, which
            renders as two straight bars ("H") instead of arcs. */}
        <div
          style={{
            position: "relative",
            width: MARK,
            height: MARK,
            display: "flex",
            border: "7px solid #ffffff",
            borderRadius: "50%",
          }}
        >
          <div
            style={{
              position: "absolute",
              top: MARK / 2 - 3,
              left: 0,
              width: MARK,
              height: 7,
              background: "#ffffff",
            }}
          />
          <div
            style={{
              position: "absolute",
              top: 0,
              left: 32,
              width: 52,
              height: MARK,
              border: "7px solid #ffffff",
              borderRadius: "50%",
            }}
          />
        </div>
      </div>
    ),
    size
  );
}

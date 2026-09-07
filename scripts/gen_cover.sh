#!/bin/bash
# Branded OG/card image generator — HTML template → headless screenshot.
# Usage: gen_cover.sh "<TITLE LINE>" "<CATEGORY>" <width> <height> <out.png>
# Uses the CDP automation browser (Brave) in headless screenshot mode.
# Template: warm off-white, emerald brand bar, oversized display title.
TITLE="$1"; CATEGORY="$2"; W="$3"; H="$4"; OUT="$5"

HTML=$(cat <<EOF
<!doctype html><html><head><meta charset="utf-8"><style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { width:${W}px; height:${H}px; overflow:hidden;
         background:#FAF9F6; font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;
         display:flex; flex-direction:column; justify-content:space-between;
         padding:64px 72px; position:relative; }
  .bar { position:top; left:0; width:96px; height:10px; background:#059669; border-radius:6px; }
  .cat { color:#059669; font-size:22px; font-weight:800; letter-spacing:3px; text-transform:uppercase; margin-top:8px; }
  h1 { color:#0F172A; font-size:78px; line-height:1.08; font-weight:800; letter-spacing:-2px; max-width:${W}px; }
  .foot { display:flex; justify-content:space-between; align-items:flex-end; }
  .brand { font-size:30px; font-weight:800; color:#0F172A; }
  .brand span { color:#059669; }
  .gl { width:54px; height:54px; border-radius:50%; border:4px solid #059669; position:relative; }
  .gl::after { content:''; position:absolute; inset:-10px; border-radius:50%; border:2px solid #A7F3D0; }
</style></head><body>
  <div><div class="bar"></div><div class="cat">${CATEGORY}</div></div>
  <h1>${TITLE}</h1>
  <div class="foot"><div class="brand">Nomad<span>omics</span></div><div class="gl"></div></div>
</body></html>
EOF
)

TMPHTML=$(mktemp /tmp/cover_XXXXXX.html)
echo "$HTML" > "$TMPHTML"

"/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" \
  --headless --disable-gpu --screenshot="$OUT" --window-size="${W},${H}" \
  --hide-scrollbars --no-first-run --no-default-browser-check "file://$TMPHTML" 2>/dev/null

sleep 1
rm -f "$TMPHTML"
[ -s "$OUT" ] && echo "OK $OUT ($(stat -f%z "$OUT") bytes)" || echo "FAILED $OUT"

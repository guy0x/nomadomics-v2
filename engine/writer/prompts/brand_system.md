# Brand System — Nomadomics (LIVE tokens)

> Replaces the archived 2026-07-13 brand system (sage/terracotta) — that palette
> was never implemented. **This file reflects the shipped frontend** as of 2026-09-07.
> Source of truth: `frontend/src/app/globals.css` `@theme` block.

## Live palette

| Token | Hex | Role |
|---|---|---|
| `brand` (emerald) | 50 `#ECFDF5` … 500 `#10B981` … 600 `#059669` … 700 `#047857` … 950 | Primary accent: links, CTAs, highlights, card covers |
| `ink` (slate) | 50 `#F8FAFC` … 600/700 body … 950 `#020617` | Text + neutral surfaces |
| Background | `#FFFFFF` / `ink-50` | Page canvas (warm off-white feel via hero gradient `from-ink-50 to-white`) |

## Typography

| Token | Value | Use |
|---|---|---|
| `--font-inter` | Inter var | Body |
| `--font-display` | Satoshi var → Inter fallback | Headings (h1/h2/h3, hero) |

## Article cover / OG style (for image generation prompts)

- Photorealistic travel scenes, 16:9, no text/logos/watermarks, no readable signage.
- Warm golden-hour light, shallow depth of field, aspirational but authentic.
- Scene derived from the article's subject (terrace + laptop, ATM on stone street,
  boarding pass on hotel bed, etc.) — matching the WordPress corpus's opener vignettes.

## Writer/editor prompt implications

- Voice and structure contracts live in `writer.py` + `editor/editor.py` system prompts
  (they embed `voice_exemplar.md` verbatim — keep that file authoritative for voice).
- No color/palette language is injected into article copy; palette only matters for
  cover imagery and site chrome.

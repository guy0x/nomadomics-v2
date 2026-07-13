# Brand System — Nomadomics

> Generated: 2026-07-13 | Source: superplan Task 0.5 | Ready to export to Notion

---

## Tailwind CSS Configuration

```js
// tailwind.config.js
module.exports = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  darkMode: ['class'],
  theme: {
    extend: {
      colors: {
        // Core palette
        background: '#F8F5F0',
        foreground: '#2C2C2C',
        
        // Accent colors
        primary: {
          DEFAULT: '#5C6B5E',   // sage green
          50: '#F5F6F4',
          100: '#E6E9E6',
          200: '#CCD2CC',
          300: '#B3BDB3',
          400: '#99A399',
          500: '#5C6B5E',
          600: '#4A564E',
          700: '#38403B',
          800: '#262B27',
          900: '#141513',
        },
        accent: {
          DEFAULT: '#C17B5E',   // terracotta
          50: '#FBF5F2',
          100: '#F2E6E1',
          200: '#E6CCC3',
          300: '#D9B3A5',
          400: '#CC9989',
          500: '#C17B5E',
          600: '#A66146',
          700: '#804733',
          800: '#593020',
          900: '#331A0D',
        },
        
        // Semantic colors
        muted: {
          DEFAULT: '#6B6B6B',
          foreground: '#9CA3AF',
        },
        navy: {
          DEFAULT: '#1E3A8A',  // deep navy for links
        },
      },
      
      fontFamily: {
        sans: ['Inter var', 'Inter', 'system-ui', 'sans-serif'],
        heading: ['Satoshi var', 'Satoshi', 'Inter var', 'system-ui'],
      },
      
      fontSize: {
        // Article reading rhythm
        'h1': ['2.5rem', { lineHeight: '1.2', letterSpacing: '-0.02em' }],
        'h2': ['1.875rem', { lineHeight: '1.3' }],
        'h3': ['1.5rem', { lineHeight: '1.4' }],
        'body': ['1.125rem', { lineHeight: '1.75' }],
      },
      
      maxWidth: {
        'article': '72ch',
      },
      
      spacing: {
        '18': '4.5rem',
        '22': '5.5rem',
      },
      
      borderRadius: {
        'xl': '1.25rem',
      },
      
      boxShadow: {
        'card': '0 4px 12px rgba(0, 0, 0, 0.03)',
        'card-hover': '0 8px 24px rgba(0, 0, 0, 0.06)',
      },
    },
  },
  plugins: [],
}
```

---

## Component Descriptions

### 1. Button Styles

**Primary Button:**
- Background: `bg-primary-600`
- Text: `text-white font-medium`
- Hover: `hover:bg-primary-700 transition-colors`
- Padding: `px-6 py-3 rounded-xl`
- Shadow: `shadow-sm hover:shadow-md`

**Secondary Button:**
- Background: `bg-white`
- Border: `border border-primary-300`
- Text: `text-primary-700 font-medium`
- Hover: `hover:bg-primary-50 transition-colors`

**Ghost Button:**
- Background: `bg-transparent`
- Text: `text-primary-600`
- Hover: `hover:bg-primary-50 rounded-lg transition-colors`

---

### 2. Card Styles

**Article Card:**
```
class="bg-card rounded-xl p-6 shadow-card hover:shadow-card-hover transition-shadow"
```
- Image aspect ratio: 16/9 or 3/2
- Title: `text-h2 font-heading`
- Excerpt: `text-muted line-clamp-2 mt-2`

**Resource Card:**
- Background: `bg-white border border-border rounded-xl p-5`
- Icon badge: `w-12 h-12 bg-primary-100 rounded-lg flex-center`
- Link arrow on hover

---

### 3. Navigation

**Top Nav (desktop):**
- Transparent background on scroll-up, white with shadow on scroll-down
- Logo left, nav links center, CTA right
- Mobile: hamburger triggers slide-over drawer

**Mobile Drawer:**
- Full-height slide from right
- `bg-background/95 backdrop-blur`

---

### 4. Hero Section

**Default (3 variants):**
1. **Text-focused:** Headline + subhead + primary CTA + secondary link
2. **Image-focused:** Large hero image (770x400) with overlay text
3. **Data-heavy:** Stats grid (3-up) + headline + CTA

---

### 5. Article Reading Experience

- Max width: `max-w-article mx-auto`
- Typography: Inter/Satoshi, generous leading (1.75)
- Table of contents: left rail on desktop, top accordion on mobile
- Inline link style: `border-b border-dotted border-navy hover:border-solid`

---

### 6. Footer

- Background: `bg-primary-900 text-white`
- 3-column layout: About / Links / Newsletter signup
- Newsletter form: email input + subscribe button

---

## Design Tokens Summary

| Token | Value | Use Case |
|---|---|---|
| `--color-background` | `#F8F5F0` | Page background |
| `--color-primary` | `#5C6B5E` | Primary actions, links |
| `--color-accent` | `#C17B5E` | Secondary actions, highlights |
| `--font-family-sans` | Inter var | Body text |
| `--font-family-heading` | Satoshi var | Headings |
| `--line-height-body` | 1.75 | Reading comfort |
| `--max-width-article` | 72ch | Content width |

---

*Ready to paste into Notion Brand System page. Also suitable for shadcn/ui ThemeProvider or direct CSS variables.*
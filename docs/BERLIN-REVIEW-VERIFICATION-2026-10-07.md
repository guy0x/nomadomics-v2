# Berlin Cost-of-Living Article — Verification Record

- Article: `cost-of-living-berlin-digital-nomads` (Strapi documentId `slvs6a8atlt276fdkpabgt4z`, id 672)
- Lane: t_8e6cf189 (verifier) · fixes applied to DRAFT layer by t_ed813311 + precision edit by t_8e6cf189
- Date: 2026-10-07 · Status in Strapi: `in_review` (unpublished — do not flip to published here; t_717c120d republishes)
- Primary-source rule: every corrected figure verified against official sources (BVG, VBB, S-Bahn Berlin, Amt für Statistik Berlin-Brandenburg, Staatliche Museen zu Berlin, Bundesregierung, steuergo/ELSTER tax portal). No blogs relied on.

## Correction → Primary source

| # | Corrected figure in article | Primary source (fetched 2026-10-07) |
|---|---|---|
| 1 | BVG AB monthly ticket €113 (no subscription) | bvg.de/en/subscriptions-and-tickets/all-tickets — "Monthly ticket … Standard fare from 113,00 €"; detail page /time-tickets/monthly-ticket |
| 1b | Deutschlandticket €63/mo from 01.01.2026 | bvg.de/de/deutschlandticket (FAQs: "Seit Januar 2026 kostet es monatlich 63 Euro"); bundesregierung.de "Seit Januar 2026 kostet es monatlich 63 Euro" |
| 2 | Potsdam = fare zone C, NOT A/B | sbahn.berlin (Tarifbereich Berlin c "einschließlich der Stadt Potsdam"); VBB tariff |
| 2b | ABC single ticket €5.00 | vbb.de/news/neue-fahrpreise-im-vbb-ab-1-januar-2026 — "Einzelfahrausweis ABC … steigt auf 5,00 Euro"; S-Bahn Preisliste Berlin ABC 5,00 € |
| 3 | Single AB €4.00; Kurzstrecke €2.80 | bvg.de/en — Single ticket "Standard fare from 4,00 €"; Short trip "from 2,80 €"; VBB Kurzstrecke Berlin 2,80 |
| 4 | Home-office flat rate €6/day → max €1,260/yr (210 days) | steuergo.de (official tax portal): "6 Euro per day, up to a maximum of 1,260 euros per year" (since 2023, §4(5) EStG) |
| 5 | Museumssonntag (first-Sunday free) ended Dec 2024; free Thursdays remain | berlin.de/museum/eintritt-frei/museumssonntag — "Am 01. Dezember 2024 … zum letzten Mal kostenlos"; SMB: Neue Nationalgalerie free every first Thursday 16–20 (Art4All); Hamburger Bahnhof free first Thursday (Volkswagen Art4All) |
| 9 | Inflation Berlin 3.4% y/y Sep 2026, fuel-driven | statistik-berlin-brandenburg.de/presse/2026/127-verbraucherpreise-september-2026 — "im September 2026 in Berlin um 3,4 %"; Kraftstoffe +41,3%; food −0,2% Berlin |
| 10 | Deutschlandsemesterticket €34.80/mo (WS 2025/26) | sbahn.berlin deutschlandsemesterticket — "Winter semester 2025/2026 €34.80"; HWR Berlin Mitteilungsblatt (208,80 €/6 mo = 34,80 €/mo) |
| 11 | Semester ticket = enrolled university students only | sbahn.berlin — ticket requires the university's contract; VHS/private language schools not in scheme |
| 13 | Factory Berlin flagship closed 2024 (removed from article) | Tagesspiegel (2024-02): "Factory Berlin schließt seinen größten Standort am Görlitzer Park im April 2024" |
| 16 | Markthalle Neun (spelling) | Well-known Kreuzberg market (house-style typo fix; no source change) |

## Link checks (live, 2026-10-07, HTTP status)

- https://www.bvg.de/en/subscriptions-and-tickets/all-tickets → 200 (replaces dead bvg price-overview 404 + bfz.de stray domain)
- https://www.statistik-berlin-brandenburg.de/presse/2026/127-verbraucherpreise-september-2026/ → 200 (replaces dead thelocal.de 2023 article 404)
- The Local 2023 404 removed; Nomad List + Outsite blog sources removed (co-living re-sourced to coliving.com/berlin/ → 200; Nomad List attribution softened to "a typical non-rent spend")
- Internal `/cash-vs-card-abroad` → 200 on www.nomadomics.blog AND nomadomics-v2.vercel.app (both with/without trailing slash) — destination article exists (published 2026-10-05); link target intact
- `/budgeting-apps-for-digital-nomads` → 200
- Cover art exists and serves: /cards/cost-of-living-berlin-digital-nomads.png → 200; /og/… → 200 (committed fc4b6f5, 8ca67ca)

## Audit result (draft layer, 2026-10-07 11:2x)

24/24 acceptance checks PASS: AB €113, D-Ticket €63, zone C, ABC €5.00, single €4.00/Kurzstrecke €2.80, home-office €1,260/210d, Museumssonntag ended, free Thursdays, BVG all-tickets URL, statistik source, inflation 3.4% fuel, semester €34.80, uni-only eligibility, no Outsite/NomadList, no Factory, Betahaus €25–35, Markthalle Neun, metaTitle contains keyword (56 chars), H1/metaTitle aligned, 1,765 words (≥1,600), internal links intact.
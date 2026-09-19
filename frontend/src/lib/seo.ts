/**
 * SERP title rules.
 *
 * Meta titles are authored against a ~60-character budget (Google truncates the
 * rendered title around there). The site-wide template appends " · Nomadomics",
 * which is worth spending characters on only while the result still fits —
 * otherwise the truncation eats headline words rather than the brand.
 */

export const BRAND_SUFFIX = " · Nomadomics";
export const TITLE_BUDGET = 60;

/** Title with the brand suffix, or without it when the pair would exceed the budget. */
export function titledWithBrand(title: string, brand: string = BRAND_SUFFIX): string {
  const combined = `${title}${brand}`;
  return combined.length <= TITLE_BUDGET ? combined : title;
}

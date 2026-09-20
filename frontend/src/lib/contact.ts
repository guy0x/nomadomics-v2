/**
 * Editorial contact address — single source of truth for every page that
 * publishes it (About, Privacy).
 *
 * LAUNCH GATE: the mailbox must actually exist before this address is
 * advertised anywhere. `nomadomics.blog` does not currently serve the site and
 * nothing is behind this address, so a reader who writes today gets a bounce.
 * Fix the mailbox (or swap this value) before the domain goes live — launch
 * checklist item L4.
 */
export const CONTACT_EMAIL = "hello@nomadomics.blog";
export const CONTACT_MAILTO = `mailto:${CONTACT_EMAIL}`;

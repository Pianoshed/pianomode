# ADR 0002 — Design tokens, theming and navigation

**Status:** accepted

- **Identity:** the palette comes from the instrument: key white, ebony, and the green baize of old key slips as the single accent. Typeface is Schibsted Grotesk (variable, bundled via Fontsource so no build-time network fetch to Google). Weight and tight tracking carry the headings.
- **Tokens:** colours are CSS variables (`--c-*`, RGB triples) in `app/globals.css`, mapped to Tailwind names (`bg`, `surface`, `fg`, `muted`, `accent`, ...). Components use token classes, not raw colours or `dark:` variants.
- **Hand colours:** `hand-left` / `hand-right` tokens are reserved for the piano and lessons (phase 3+).
- **Contrast:** text pairs were checked at 4.5:1 or better in both themes. Re-check when changing a value.
- **Theme:** `system | light | dark`, stored in `localStorage` (`piano.theme`). An inline script sets `data-theme` before first paint. Server-side account preferences arrive with accounts.
- **Navigation:** one config (`lib/nav.ts`) drives sidebar, mobile menu and unbuilt-area pages. Items can carry `roles`; users without the role neither see the item nor can open its route (404). This is a UI gate only; every API endpoint must enforce authorization itself.
- **Unbuilt areas:** `app/(app)/[section]` renders an honest "not built yet" page. A real page replaces it by adding a folder with that slug.
- **Dashboard data:** `lib/dashboard.ts` returns only stored activity, which is empty until accounts exist. No sample figures.

# Earthward Foundry Public Field Guide QA Record

## Source candidate — 2026-08-27

The public field-guide source was created as an intentionally separate `public-site/` directory. It provides a readable introduction to the documented narrow Evidence-Ledger Pilot and makes the following boundaries visible before a reader reaches a source route: protected versus public state, human-only acceptance and disposition, no public service/API, no visitor data collection, and no certification/customer-outcome claim.

The first release candidate includes an original Workshop Ledger composition, conceptual work-and-record SVG, self-canonical GitHub Pages metadata, WebSite/WebPage/SoftwareSourceCode structured data, sitemap, robots instructions, manifest, `llms.txt`, custom error page, and source/correction footer. The page uses only semantic HTML, local CSS, and source-controlled SVG; it has no runtime script, form, cookie, storage, analytics, fetch/XHR, tracking pixel, or third-party dependency.

Before publication, run `node public-site/scripts/validate-static.mjs`, review in a local static server at wide and narrow widths, confirm the `404.html` return route, and re-check every public claim against `docs/production-offer.md`. Publication must use the documented static-only `gh-pages` branch process. It must not expose or change the protected Compute Engine pilot, network rules, service configuration, keys, ledgers, or databases.

## Desktop visual and error-path review — 2026-08-27

The field guide rendered locally at desktop scale with the intended mineral-paper, graphite, calibration-blue, and iron-oxide Workshop Ledger composition. The lead, original conceptual work-and-record chain, human decision pin, five-stage evidence loop, public/protected boundary ledger, source cards, and source/correction routes were legible and visibly separated. The visual makes the pilot’s narrow informational state clear before describing its technical pattern.

The plain Python local static server returns its own generic response for an unknown path rather than rewriting to `404.html`; this is expected local-server behavior and is not evidence that the custom error asset fails. The explicit `/404.html` asset is served successfully and contains a project-root return path. GitHub Pages must be checked after any approved publication because it is the intended custom-404 host behavior.

## Palette calibration — 2026-08-27

The field guide keeps a deliberately restrained material palette rather than adopting a generic technology gradient or a high-saturation warning interface. **Mineral paper** carries long-form reading; **graphite** carries primary text; **calibration blue** establishes the record/evidence field; **evidence mint** marks the closing inspection surface; and **iron oxide** is reserved for a held condition, a decision seam, or a human-governed exception. The rust accent was deepened from `#b54a2b` to `#a64027` because the former only achieved `4.55:1` against mineral paper while the revised token achieves `5.35:1`.

`node public-site/scripts/audit-palette.mjs` passed for all measured text/field pairs. The browser review confirms that the more deliberate iron-oxide accent remains visually distinct from the blue evidence field and reads as a controlled quality signal, not a generic conversion CTA. `palette.css` contains the small, semantic token override so the textual system and conceptual workpiece share the same decision color.

## Pages source activation — 2026-08-27

The immutable public-source commit is `eb1f74f922285377bae71dc586e1ab121d36cb21`. Its `public-site/` subtree produced static-only candidate `b07a98fbd3302d5f0649bf62b4e9c8671623e94c`, pushed to the dedicated `gh-pages` branch. The branch inventory contains only the field-guide files, identity/discovery artifacts, local validation scripts, and release notes; it contains no protected-service, deployment, database, key, or cloud-configuration path.

The GitHub Pages settings show `gh-pages` and `/ (root)` as the configured publishing source and report that the site is being built from that branch. Public route, custom-404 behavior, and discovery-asset responses have not yet been recorded as live checks.

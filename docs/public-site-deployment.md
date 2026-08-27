# Earthward Foundry Static Public-Site Deployment Plan

## Scope and separation

The public page is a **static informational property**. Its source lives under `public-site/` on `main`; its deployable output is a clean static-only `gh-pages` branch. This separation prevents the GitHub Pages website from exposing, importing, or operating the protected Python services, VM configuration, database locations, API keys, or Docker material.

The intended GitHub Pages URL is `https://virtualmase.github.io/earthward-foundry/`. It is a self-canonical project site. There is no custom domain, DNS change, Vercel configuration, analytics activation, Search Console mutation, or API exposure in this plan.

## Directory structure

```text
earthward-foundry/
├── public-site/                         # only content eligible for public static hosting
│   ├── index.html                       # public field guide
│   ├── 404.html                         # project-scoped recovery page
│   ├── site.css                         # responsive visual system
│   ├── favicon.svg                      # source-controlled simple mark
│   ├── og-image.svg                     # source-controlled social preview
│   ├── manifest.webmanifest
│   ├── robots.txt
│   ├── sitemap.xml
│   ├── llms.txt
│   ├── README.md                        # scope and source map
│   ├── QA.md                            # validation record
│   └── scripts/
│       └── validate-static.mjs          # no-network release validation
├── docs/public-site-launch-brief.md     # reader, evidence, and boundary record
└── docs/public-site-deployment.md       # this release and rollback plan
```

## Owner-gated release sequence

1. Review the current `main` diff and run `node public-site/scripts/validate-static.mjs` using a plain local static server.
2. Check the production copy against `docs/public-site-launch-brief.md`; remove any customer, certification, safety, performance, or public-API implication that is not evidence-supported.
3. Select a known-good `main` commit. Create static-only output from `public-site/` into `gh-pages` with `git subtree split --prefix=public-site -b gh-pages-candidate`, then fast-forward or force-with-lease only after the owner approves the exact candidate SHA.
4. In GitHub Pages settings, select the `gh-pages` branch and `/ (root)` as source. This must be done only by the repository owner or after their explicit approval.
5. Wait for the Pages build to report `built`. Confirm the canonical root, `404.html`, `robots.txt`, `sitemap.xml`, `llms.txt`, favicon, manifest, and social image responses at the project-site origin.
6. Record the immutable source and `gh-pages` SHAs in `public-site/QA.md` and release a focused documentation update.

## Rollback and containment

| Situation | Static-site response | Internal-pilot boundary |
|---|---|---|
| Incorrect public copy or broken route | Revert the associated `main` source commit, regenerate the static-only branch from the known-good source commit, and verify the project URL. | Do not restart, expose, or modify any protected service. |
| Static branch mistake | Repoint `gh-pages` to the known-good immutable static SHA through a reviewed, source-controlled Git operation. | No service, VM, data, or key action is required. |
| Page implies unsupported capability | Immediately remove the claim, document the correction in `QA.md`, and restore a known-good version if needed. | Do not compensate by exposing technical pilot evidence or sensitive details. |
| Security concern in public source | Remove the published artifact, follow `SECURITY.md`, rotate any affected secret outside the repository if one was disclosed, and review history. | Never place service credentials, database contents, network details, or operational access paths on the public site. |

## Explicit non-actions

This release must not open public firewall ports, proxy the local-only services, set `ALLOW_UNAUTHENTICATED=true`, add a client-side API key, create a public service endpoint, collect contact information, or modify the current Compute Engine deployment. Those are separate product/security decisions and not prerequisites for publishing a static field guide.

# Earthward Foundry Public Field Guide

`public-site/` is the only Earthward Foundry directory intended for a public static project site. It is deliberately separate from code and documentation for the protected technical pilot.

## Public purpose

The page explains the proposed **Evidence-Ledger Pilot**: one facility, one high-mix/low-volume part family, and one release-to-acceptance evidence loop. It describes a human-governed design for making a quality decision reviewable; it does not claim certification, customer outcomes, public SaaS availability, metrological traceability, public API access, or life-safety use.

## Local review

```bash
cd public-site
node scripts/validate-static.mjs
python3 -m http.server 8097
```

Visit `http://localhost:8097/`. No package installation or build step is required.

## Release separation

Publish only this directory to a dedicated static `gh-pages` branch as described in [`../docs/public-site-deployment.md`](../docs/public-site-deployment.md). Do not publish from `main` root because it contains protected pilot source, service code, and operational documentation not intended for a public website bundle.

## Source and correction routes

The public page links to the source-controlled pilot specification, repository, schema, contribution route, and security guidance. Use only sanitized public issues. Follow [`../SECURITY.md`](../SECURITY.md) for a security concern.

## License

The repository-level license applies. Public visibility of this field guide does not grant a broader reuse right beyond that license.

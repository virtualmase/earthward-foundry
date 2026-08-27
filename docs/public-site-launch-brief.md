# Earthward Foundry Public-Site Experience Brief

**Property:** Earthward Foundry public field guide  
**Owner:** Virtualmase repository owner  
**Date/version:** 2026-08-27 / proposed launch 01  
**Reviewer:** Maintainer plus accountable product owner  
**Deployment target:** `https://virtualmase.github.io/earthward-foundry/` via a dedicated static `gh-pages` branch  
**Rollback point:** Previous immutable `gh-pages` commit or a normal source-controlled revert of `public-site/`

## Reader and job

**Primary reader:** A Quality Director, Quality Engineer, or manufacturing owner responsible for a high-mix, low-volume part family.  
**Situation:** They are assessing whether a narrow evidence-led approach could make a release-to-acceptance decision more reviewable without displacing accountable quality work.  
**Job to be done:** Understand the first proposed Earthward offer, what has a public source basis, what remains a protected technical pilot, and where to inspect or challenge the work.  
**Meaningful action:** Read the published pilot scope and source boundaries before opening a scoped conversation through the repository.  
**Success in the reader’s words:** “I understand what Earthward is trying to make easier, what the software does not decide, and what would still have to be true before I trust it for my work.”

## Context and boundary

| Topic | Decision |
|---|---|
| What the page knows | The public repository’s documented evidence-led pilot scope, append-only record design, human-only acceptance boundary, public source files, and cited contextual material. |
| What the page does not know | A visitor’s facility, part family, standards, drawings, inspection process, data classification, contract, or readiness for a pilot. |
| Human owner/reviewer | A named quality/operations owner remains responsible for part disposition and acceptance. |
| Actions that remain human | Acceptance, release, deviation/disposition, safety- or quality-relevant decision, pricing, contract, integration, and sharing non-public material. |
| Data allowed | None. The public page has no form, account, visitor storage, analytics, or API call. |
| Data prohibited | Production records, drawings, inspection data, PII, secrets, non-public quality evidence, and visitor identifiers. |
| External services or dependencies | None at runtime. Source links point to GitHub and documented public NIST pages only. |
| Failure/uncertainty state | The 404 page returns a reader to the field guide; missing fit is named as a reason to inspect scope rather than submit data. |
| Escalation or safe next step | Read the documented pilot boundary or open a GitHub issue with sanitized, non-sensitive feedback. |

## Evidence and claims

**Evidence informing this change:** The repository’s `docs/production-offer.md`, `docs/institutional-framework.md`, services documentation, and cited NIST traceability/digital-thread material.  
**Public claim permitted by the evidence:** Earthward’s source contains append-only part-record, quality/metrology, and human-sign-off design work; its proposed first offer is a narrow, human-governed quality and traceability evidence ledger.  
**Claims excluded or requiring qualification:** Customer outcomes, certification, accredited metrological traceability, active paid pilots, public SaaS availability, public API access, uptime/security guarantees, pricing availability, industry compliance, and all life-safety use.  
**Source links/citations:** See `docs/production-offer.md` and `public-site/README.md`.

## Essential path

1. A reader identifies the public property as a field guide for a proposed narrow evidence-led pilot, not an active general-purpose agent fleet.
2. The reader sees the five human-controlled moments from part release through final acceptance and the explicit excluded claims.
3. The reader reaches the pilot scope, public source, correction path, or an independently useful related Virtualmase route.

## Acceptance checks

| Dimension | Check | Result before release |
|---|---|---|
| Task clarity | The lead names the part-family evidence-led pilot reader and question. | Required |
| State legibility | Live public page versus protected technical pilot is visibly distinguished. | Required |
| Human authority | Human-only acceptance and excluded decision rights are visible. | Required |
| Keyboard/semantics | Skip link, landmarks, semantic headings, native links, focus state, and custom 404 recovery exist. | Required |
| Small-screen behavior | The page and decision-chain visual remain readable at narrow widths. | Required |
| Data boundary | No forms, cookies, storage, beacons, runtime fetches, or third-party scripts. | Required |
| Failure path | The static error page returns to the project root and safe source routes. | Required |
| Dependencies | Plain HTML/CSS/SVG only; no framework, build, package install, or runtime service. | Required |
| Rollback | The dedicated `gh-pages` output can return to a known-good static commit without touching the internal pilot. | Required |

## Known limitations and next evidence

**Known limitation:** The public page is informational. It does not supply customer-specific onboarding, an active pilot workspace, a public service endpoint, or evidence of a completed customer outcome.  
**Next observation or test:** A qualified, sanitized discovery conversation should test whether a real Quality Director values rapid record reconstruction, missing-evidence visibility, NCR closure support, audit preparation, or another specifically defined outcome.  
**Publication decision:** Creating the source package is reversible. Pushing the static output to a `gh-pages` branch and enabling GitHub Pages requires the owner’s explicit confirmation immediately before the external launch action.

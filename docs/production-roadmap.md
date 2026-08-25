# Earthward Foundry Production Roadmap

## Operating principle

Build one trusted evidence loop before extending the agent fleet. A workflow should move from released part to human acceptance with complete, retrievable evidence before Earthward adds more agents, verticals, or automation.

## First 30 days: make the pilot safe to trust

The first milestone is a customer-ready technical pilot, not a broad launch. Add organization-scoped users and roles; a simple web workspace for part records, gaps, and human acceptance; encrypted backup with a documented restore drill; and a staging deployment path. The operational owner should be the product lead, while a named Quality Director from the design partner approves the workflow model.

The customer-development milestone is five structured discovery sessions with Quality Directors, manufacturing leads, and technical-records owners. The objective is to secure one paid design partner around one part family, define the evidence template, and baseline how long the team currently spends locating acceptance records and closing nonconformances.

## Days 31–60: deliver one real evidence loop

Onboard one facility, one part family, and one controlled release workflow. Import released part metadata and inspection results through CSV or a documented API. Require a named quality user for acceptance. Export a complete part package—including events, evidence references, open gaps, and approval history—for the customer to review outside the system.

The product metric is not model accuracy. It is record completeness: the percentage of parts whose release, inspection, deviation, rework, and final acceptance are linked by a retrievable history. The operational metric is time to assemble an acceptance package or respond to a quality record request.

## Days 61–90: convert evidence into a repeatable offer

After the first loop runs successfully, standardize the implementation kit: evidence-template configuration, role mapping, data-import worksheet, security questionnaire, onboarding guide, and success-review format. Add a controlled nonconformance coordination workflow based on the Rescue service’s human-gated pattern, but do not use the Rescue product for life-safety or emergency response.

The commercial milestone is a paid renewal or expansion into a second part family. Only then consider productized recurring pricing, an inspection-system integration, or a second design partner.

## Go-to-market sequence

Start with relationship-led outbound to precision machining, fabrication, specialty manufacturing, and other discrete-production teams where quality records are operationally important and ownership is direct. The first message should describe a concrete outcome: a faster, reviewable acceptance package and fewer missing evidence links—not “AI agents.” Demonstrate a traced record, an intentionally blocked acceptance, a human release, and an exportable evidence package.

## Non-negotiable release gates

| Gate | Evidence required before paid customer use |
|---|---|
| Data integrity | Append-only history, explicit corrections, and stable event schema covered by regression tests |
| Access control | Organization identity, role checks, least-privilege approval rights, and audit attribution |
| Recovery | Encrypted backup, restore test, recovery owner, and documented retention policy |
| Human control | Irreversible approvals remain blocked until an authorized human acts |
| Product usability | A non-developer can review gaps, add evidence references, and perform approval without direct API calls |
| Customer outcome | One real part family completes the full loop, and the customer validates that the exported record is useful |

## Deliberate exclusions

Earthward should not claim regulatory certification, autonomous acceptance authority, completed metrological traceability, life-safety decision support, or comprehensive MES/QMS replacement in the initial offer. The product earns the right to expand through working evidence loops and customer trust.

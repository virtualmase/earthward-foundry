# Earthward Foundry: First Production Offer

## Executive decision

Earthward Foundry should **not** launch as a general agent fleet or as a live emergency-response product. Its credible first offer is a narrow, human-governed **quality and traceability evidence ledger** for high-mix, low-volume manufacturers that need to prove why a part was accepted, blocked, or reworked.

The product promise is simple: **every material production decision has an accountable owner, linked evidence, and an append-only record that can be reviewed later.** It helps people make and explain quality decisions; it does not claim to certify parts, replace a quality professional, or establish metrological traceability by itself.

## The initial human workflow

The first workflow should serve one discrete-manufacturing part family from release through acceptance. The operating user is a Quality Engineer or Technical Records / Traceability Specialist. The adjacent users are the Manufacturing Engineer, CMM or inspection technician, and final acceptance inspector. The buyer is typically the owner/GM, Director of Quality, or Director of Manufacturing.

| Moment in the workflow | Existing Earthward capability | Human benefit |
|---|---|---|
| Part and revision released | Traceability part record | A single, durable record begins before work starts. |
| Inspection is run | CMM / quality logic | Results remain tied to the part and cannot be adjusted to force a pass. |
| A nonconformance appears | NCR and blocked-status logic | The system exposes the issue instead of smoothing it away. |
| Rework or disposition occurs | Append-only corrective event | The reason and authority for a correction remain inspectable. |
| Final release is considered | Human-only acceptance event | The responsible person, not the software, makes the irreversible decision. |

## Why this can serve people

Manufacturing teams do not need another generic assistant that produces plausible text. They need a system that reduces the administrative and evidentiary burden around consequential work without taking decision rights away from the people responsible for quality. Earthward’s existing code already centers named human gates, provenance, sequence rules, gap reporting, and immutable correction trails. That makes it useful for teams who are currently coordinating inspections, deviations, disposition, and acceptance through disconnected spreadsheets, shared folders, email, and verbal handoffs.

The technical framing is aligned with NIST’s manufacturing work on trusted records, data integrity, secure access, and traceability event recording, as well as its digital-thread emphasis on linked design, manufacturing, and inspection information. [1] [2] The implementation must avoid any representation that the application itself delivers certification or NIST traceability; NIST states that the provider of a measurement result is responsible for supporting any traceability claim. [3]

## Revenue model: start services-led, then productize

The first revenue should come from a paid design-partner implementation, not freemium self-service. A production-quality workflow must be configured around the customer’s parts, release rules, inspection process, and responsible roles. That early configuration work produces real customer value and supplies the evidence needed to productize responsibly.

| Offer | Customer receives | Commercial purpose | Working price hypothesis |
|---|---|---|---|
| **Evidence-Ledger Pilot** | One part family, one facility, structured record template, role map, data import, operator training, and acceptance-review workflow | Proves a repeatable outcome with a design partner | $10,000–$25,000 fixed implementation |
| **Managed Production Workspace** | Hosted ledger, backups, support, monthly evidence review, and controlled releases | Recurring revenue while the product matures | $1,000–$3,000 per facility per month |
| **Quality Workflow Expansion** | Additional part families, inspection imports, NCR analytics, and integrations | Increases account value only after the first loop is trusted | Scoped implementation plus recurring usage tier |

These are **hypotheses**, not market facts. The first five discovery conversations should test whether the buyer sees more value in reduced time-to-record, fewer missing acceptance artifacts, faster NCR closure, lower audit-preparation effort, or reduced escape risk. The price should then be tied to the measurable operational outcome, not to the number of agent calls.

## What not to sell yet

The Rescue service demonstrates a valuable pattern—governed incident coordination with explicit human approval—but it should not be marketed as a life-safety or public-safety decision system without domain-specific validation, specialist oversight, legal review, operational integrations, and field trials. Near term, its safer commercial use is as the coordination pattern for **non-life-critical manufacturing deviations**: a production hold, supplier issue, or quality containment workflow where named humans still approve every material step.

## Production gates before a paid pilot

The current VM is a protected technical pilot: both services are healthy, systemd-managed, locally bound, and bearer-key protected. A customer-facing offer requires stronger product and operating controls. The traceability API now includes an authenticated JSON evidence-package export with a SHA-256 integrity digest. This is a useful first portability control, but it is not a signed export; customer-ready signing and identity-bound attestations remain future gates.

| Gate | Why it matters | Minimum production standard |
|---|---|---|
| Tenant and user identity | Customer records cannot share an API key or a single trust boundary | Organization-scoped identity, user accounts, role-based permissions, and immutable user attribution |
| Evidence portability | Customers need access to their own record | Portable record export now; signed export of part record, event history, and attachments in a documented schema before customer scale |
| Data resilience | A single VM and disk are not a recovery strategy | Automated encrypted backups, tested restore procedure, retention policy, and recovery objective |
| Operational visibility | A customer issue cannot depend on ad hoc SSH | Centralized logs, uptime checks, alert ownership, and a staffed support channel |
| Release discipline | Quality software cannot change casually | Staging environment, migration plan, versioned releases, rollback, and approval before production deployment |
| Workflow usability | API-only tools do not serve shop-floor and quality users well | A simple web workspace for record review, approval, gaps, and evidence export |
| Integration boundary | Manual re-entry kills adoption | Start with CSV/API import for inspection results and production metadata; add shop-system connectors only after one workflow proves value |

## The next 90 days

The operational goal is one paid design partner, one facility, one part family, and one evidence loop—not broad agent coverage. Success means the customer can run a real release-to-acceptance cycle, retrieve a complete record quickly, and identify a blocked or missing step before a human signs off.

The first implementation milestone should be an authenticated multi-tenant web workspace over the traceability service, including a record-review screen, human acceptance action, gap queue, CSV inspection-result import, audit export, backup/restore verification, and production monitoring. The rescue code should remain private reference infrastructure until it has an appropriate non-life-critical workflow and domain validation.

## References

[1] [NIST, *Supply Chain Traceability: Manufacturing Meta-Framework*](https://csrc.nist.gov/News/2024/supply-chain-traceability-manufacturing-framework)

[2] [NIST, *Digital Thread for Smart Manufacturing*](https://www.nist.gov/programs-projects/digital-thread-smart-manufacturing)

[3] [NIST, *Metrological Traceability: Frequently Asked Questions and NIST Policy*](https://www.nist.gov/metrology/metrological-traceability)

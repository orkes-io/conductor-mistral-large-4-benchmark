> **FICTIONAL DOCUMENT.** Written for the Mistral Large 4 benchmark ("your data" category). Ferngate, Inc., its
> people, systems, customers and policies are invented. Any resemblance to a real organization is coincidental.

# Ferngate Platform Operations Handbook

**Incident response, on-call, change management and data handling**

| | |
|---|---|
| Version | 4.2 |
| Effective | 2026-07-01 |
| Owner | Reliability Engineering (Director of Reliability: Imogen Achterberg) |
| Approved by | Tobias Renwick, VP of Engineering |
| Next scheduled review | 2027-01-15 |

## 1. About this handbook

This handbook applies to every engineer who joins the production on-call rotation for the Ferngate Data
Platform: the ingest service, pipeline orchestration, warehouse sync and the customer-facing API. It also
applies to managers who approve changes or access for those services, and to anyone acting as Incident
Commander.

Reliability Engineering reviews the handbook every six months. Proposed edits go to
reliability@ferngate.example as a pull request against the `ops-handbook` repository; edits that change a
number in sections 2, 5, 6 or 7 need sign-off from the Director of Reliability.

If anything here conflicts with a signed customer contract, the contract wins. Raise the conflict with Legal
Operations (legal-ops@ferngate.example) the same business day you notice it.

### 1.1 Definitions used throughout

- **Business hours**: 09:00 to 18:00 in the engineer's local time zone, Monday to Friday, excluding Ferngate
  company holidays.
- **Business day**: Monday to Friday, excluding Ferngate company holidays.
- **Out-of-hours page**: any page an engineer receives outside their business hours.
- **Overnight**: 22:00 to 06:00 in the engineer's local time zone.
- **Mitigated**: customer impact has stopped or a workaround is in place, even if the root cause is still
  being fixed.
- **Declaration**: the moment an incident is opened in Beacon with a severity attached. All response targets
  are measured from declaration.

## 2. Severity levels

Anyone can declare an incident and anyone can raise its severity. Only the Incident Commander (IC) can lower a
severity, and they must record the reason in the incident channel.

| Severity | Use it when |
|---|---|
| SEV-1 (Critical) | Full outage of ingest or the customer API in any region; confirmed or suspected loss or exposure of customer data; or more than 25% of active customers impacted. |
| SEV-2 (Major) | A single region is degraded; the API error rate is above 5% for 10 consecutive minutes; or pipeline lag exceeds 60 minutes for any Platinum customer. |
| SEV-3 (Minor) | Degradation with a working workaround; pipeline lag above 4 hours for non-Platinum customers; or a single internal tool is down. |
| SEV-4 (Low) | Cosmetic problems, documentation errors, or anything with no customer impact. |

### 2.1 Response targets

| Severity | Acknowledge | IC assigned | First status page update | Later status page updates |
|---|---|---|---|---|
| SEV-1 | within 5 minutes | within 15 minutes | within 20 minutes of declaration | every 30 minutes until resolved |
| SEV-2 | within 15 minutes | within 30 minutes | within 45 minutes of declaration | every 60 minutes until resolved |
| SEV-3 | within 4 business hours | not required | optional | optional |
| SEV-4 | next business day | not required | not used | not used |

SEV-4 items go straight to the owning team's backlog and do not page anyone.

### 2.2 Incident lifecycle

Every incident moves through the same states in Beacon: **Declared**, **Mitigated**, **Resolved** and
**Closed**. The IC moves the incident to Mitigated once customer impact has stopped, and to Resolved once the
fix is in place and monitoring has been clean for 30 minutes. An incident is Closed when its postmortem
(if one is required) has been reviewed and every P1 action item has an owner. Reopening a Resolved incident
within 24 hours keeps the original declaration time; after 24 hours, declare a new incident and link the two.

## 3. Roles during an incident

- **Incident Commander (IC)**: coordinates the response, owns the severity, decides when the incident is
  mitigated and resolved, approves Emergency changes (section 7.1) and approves break-glass access
  (section 10.2). For SEV-1 and SEV-2 the IC must have completed the IC-101 course.
- **Communications Lead**: writes status page updates and coordinates customer communication with Technical
  Account Managers. For a SEV-1 the Communications Lead must be a different person from the IC.
- **Scribe**: keeps the timeline in the incident channel (decisions, actions, timestamps).
- **Responders**: subject-matter engineers pulled in by the IC.

Incident channels are named `#inc-YYYYMMDD-<short-name>`, for example `#inc-20260814-api-5xx`.

## 4. On-call rotation

Each service group (Ingest, Orchestration, Warehouse Sync, API) runs its own rotation with a **primary** and a
**secondary** on-call engineer.

- **Shift length**: 7 days. Handoff happens every Tuesday at 10:00 UTC in a 15-minute handoff call. The
  outgoing primary writes a handoff note in Beacon covering open incidents, risky changes in flight and any
  noisy alerts.
- **Limits**: no more than 2 consecutive weeks as primary, and no more than 12 primary weeks per calendar year.
- **Recovery rule**: after any on-call week with 3 or more SEV-1 or SEV-2 pages, the engineer gets at least
  48 hours off the rotation before their next on-call shift of any kind.
- **Eligibility**: new hires join the rotation no earlier than 60 days after their start date. Before a first
  primary shift an engineer must complete one shadow week and the IC-101 course.
- **Swaps**: arrange swaps in the Beacon scheduler with at least 48 hours' notice. A swap with less than
  48 hours' notice needs approval from the team's engineering manager.
- **Secondary duties**: the secondary is paged automatically if the primary does not acknowledge within the
  acknowledgement target (section 6.2) and covers the primary's breaks during long incidents.

### 4.1 Handoff note checklist

The outgoing primary's handoff note must cover:

1. Open incidents and their current state, with links to the incident channels.
2. Normal changes that are mid-rollout or scheduled during the incoming shift.
3. Alerts that fired more than twice during the shift without needing action (candidates for tuning).
4. Any customer escalations that a TAM is still tracking.
5. Upcoming freeze windows or CAB decisions that affect the service group.

The incoming primary acknowledges the note in Beacon before 12:00 UTC on the handoff day. If the note is
missing, the incoming primary asks the outgoing primary directly and copies the engineering manager.

## 5. On-call compensation

Compensation applies to primary and secondary shifts and is submitted through the payroll on-call form by the
3rd business day of the following month.

- **Weekly stipend**: $450 for a week as primary; $250 for a week as secondary.
- **Page pay**: the stipend covers the first 5 out-of-hours pages in a week. Each additional out-of-hours page
  in the same week pays $120. Pages during business hours never earn page pay.
- **Time in lieu**: 4 hours of time off for each overnight incident that lasts more than 45 minutes. Time in
  lieu must be taken within 30 days of the incident or it expires.
- Stipends are paid for complete weeks only. If you swap away part of a week, the stipend goes to whoever
  covered the Tuesday handoff.

## 6. Escalation

### 6.1 Escalation tiers

| Tier | Who | When to page |
|---|---|---|
| Tier 1 | On-call primary (secondary as backup) | Every incident, at declaration. |
| Tier 2 | The owning team's service owner | A SEV-1 with no mitigation after 20 minutes, or a SEV-2 with no mitigation after 45 minutes. |
| Tier 3 | Director of Reliability | A SEV-1 lasting more than 60 minutes; a SEV-2 lasting more than 3 hours; or the third SEV-2 on the same service within 7 days. |
| Tier 4 | VP of Engineering and CTO | Immediately for any suspected customer data exposure, or a SEV-1 lasting more than 2 hours. |

"Lasting" is measured from declaration to resolution, not to mitigation.

### 6.2 Automatic escalation in Beacon

Beacon re-pages the next person in the chain when a page is not acknowledged in time: after 5 minutes for a
SEV-1 and after 15 minutes for a SEV-2. SEV-3 pages are not auto-escalated.

### 6.3 Security incidents

If an incident involves possible unauthorized access, credential leakage or customer data exposure, page the
Security on-call (`security-oncall` in Beacon) at declaration, in addition to the tiers above. Security can
take over the IC role at any time.

### 6.4 Third-party providers

When an incident looks like it is caused by a cloud or SaaS provider, the IC (or a responder they name) opens
a support case with that provider within 30 minutes of declaration for a SEV-1, or within 60 minutes for a
SEV-2, at the provider's highest available priority. Record the case number in the incident channel. A
provider outage does not pause our own response targets or status page cadence.

## 7. Change management

### 7.1 Change classes

- **Standard**: pre-approved, low-risk changes listed in the Standard Change Catalog (for example flipping a
  catalog feature flag, or scaling a service within its approved bounds). No approval beyond the author.
- **Normal**: everything else. Needs one approval from the owning team. High-risk Normal changes (schema
  migrations, network or ACL changes, and authentication changes) also need approval from the Change Advisory
  Board (CAB). The CAB meets Tuesdays and Thursdays at 16:00 UTC; submit by 12:00 UTC the same day to be
  reviewed in that meeting.
- **Emergency**: changes made to mitigate an active incident. Approved by the IC. Every Emergency change must
  get a post-hoc CAB review within 2 business days.

### 7.2 Deploy windows

- **Monday to Thursday**: production deploys may run between 14:00 and 20:00 UTC.
- **Friday**: production deploys may start from 14:00 UTC, and the change must reach 100% of traffic before
  16:00 UTC.
- **Saturday and Sunday**: no production deploys except Emergency changes.

### 7.3 Progressive rollout

Normal changes roll out in three stages:

1. Canary at 5% of traffic for 30 minutes.
2. 25% of traffic for 60 minutes.
3. 100% of traffic.

Rollout tooling rolls back automatically if, during any stage, the error rate exceeds 2% or p99 latency exceeds
1.5 times the pre-deploy baseline. Every Normal change must have a tested rollback that completes within
15 minutes. Standard changes skip the canary stages.

### 7.4 Change freezes

- **Quarter-end freeze**: from 00:00 UTC on the 25th day of the last month of each quarter through the end of
  the 3rd business day of the next quarter.
- **Holiday freeze**: December 18 through January 4, inclusive.

During a freeze only Standard and Emergency changes are allowed, with one exception: a patch for a security
vulnerability rated CVSS 9.0 or higher may ship as a Normal change with approval from the VP of Engineering.
It still follows the progressive rollout in section 7.3. Every freeze exception must be logged in the CAB
register within 1 business day.

## 8. Customer communication and SLAs

### 8.1 Status page

The public status page is status.ferngate.example. The Communications Lead posts updates on the cadence in
section 2.1. Updates say what is affected, what customers should expect and when the next update will come.
They never name individual customers.

### 8.2 Customer tiers and uptime commitments

Uptime is measured for the customer API per calendar month.

| Customer tier | Monthly uptime commitment |
|---|---|
| Platinum | 99.95% |
| Gold | 99.9% |
| Standard | no uptime commitment |

### 8.3 Service credits

If a Platinum or Gold customer's monthly uptime falls below their commitment, they receive a service credit of
10% of that month's fees. If monthly uptime falls below 99.0%, the credit is 25% of that month's fees.
Customers must request credits within 30 days of the end of the affected month; Customer Success processes
requests within 10 business days.

### 8.4 Direct notification and RCAs

- For a SEV-1, each affected Platinum customer receives a direct email from their Technical Account Manager
  (TAM) within 60 minutes of declaration. Everyone else follows the status page.
- For a SEV-1, a customer-facing root cause analysis (RCA) is published within 5 business days of
  resolution.
- For a SEV-2 that affected Platinum customers, the customer-facing RCA is published within 10 business days
  of resolution.

## 9. Postmortems

- A postmortem is required for every SEV-1 and SEV-2. For a SEV-3 the IC decides.
- Postmortems are blameless and use template PM-7.
- The draft is due within 3 business days of resolution. The review meeting happens within 7 business days of
  resolution. The IC owns the postmortem and may delegate the draft.
- Every action item has a named owner and a due date. P1 action items are due within 30 days and P2 action
  items within 90 days. Overdue P1 items are reported to the Director of Reliability every Monday.

## 10. Data handling and production access

### 10.1 Retention

| Record | Retention |
|---|---|
| Incident channel chat logs | 400 days, then deleted automatically |
| Beacon pager logs | 2 years |
| Postmortem documents | kept indefinitely |
| Production audit logs, including break-glass sessions | 7 years |
| Customer data exports created during an incident | deleted within 72 hours after the incident is resolved |

Customer-identifying data (email addresses, or account identifiers other than the workspace ID) pasted into an
incident ticket must be redacted within 14 days of the ticket closing.

### 10.2 Production access and break-glass

Engineers have no standing production access. Day-to-day access goes through the Gatehouse just-in-time
system, with grants of up to 8 hours.

Break-glass access is only for an active SEV-1 or SEV-2. It needs approval from the IC and a second engineer
on the session for its whole duration (the two-person rule). Break-glass sessions expire automatically after
4 hours. Security reviews every break-glass session within 1 business day.

## 11. Tools and contacts

| Need | Where |
|---|---|
| Paging, schedules, swaps | Beacon |
| Production access | Gatehouse |
| Incident chat | `#inc-YYYYMMDD-<short-name>` channels |
| Status page | status.ferngate.example |
| Reliability Engineering | reliability@ferngate.example |
| Legal Operations | legal-ops@ferngate.example |
| Security on-call | `security-oncall` in Beacon |

### 11.1 Alert hygiene

Pages should be rare and actionable. Any alert that pages more than 3 times in one on-call week without
anyone needing to act must be tuned or removed within 10 business days; the outgoing primary files the ticket
from the handoff note. New paging alerts need a runbook link before they are enabled, and each service group
reviews its paging alerts once a quarter in its operations review. Alerts that only need attention during
business hours should create SEV-4 tickets instead of pages.

## 12. Worked examples

These examples show how the rules combine. They are illustrations, not extra rules.

**A slow Gold customer pipeline.** A Gold customer reports 90 minutes of pipeline lag on a Wednesday afternoon
with no other symptoms. That is under the 4-hour SEV-3 threshold for non-Platinum customers and the customer
is not Platinum, so it is not a SEV-2. Open a SEV-3 if the lag keeps growing; otherwise track it as a support
ticket.

**A risky migration in late March.** A schema migration planned for March 26 falls inside the quarter-end
freeze, which starts on March 25. It is a high-risk Normal change and is not a security patch, so it waits
until the freeze ends after the 3rd business day of April, then goes through CAB.

**A noisy week.** An engineer on primary handles two SEV-2 pages and one SEV-1 page in their week. That is
3 SEV-1/SEV-2 pages, so the recovery rule gives them at least 48 hours off the rotation before their next
shift.

## 13. Change log

| Version | Date | Change |
|---|---|---|
| 4.2 | 2026-07-01 | Raised the primary stipend from $400 to $450; added the Friday 16:00 UTC rule for reaching 100% of traffic. |
| 4.1 | 2026-01-12 | Added the recovery rule after high-severity weeks; moved break-glass review to Security. |
| 4.0 | 2025-07-01 | Introduced Tier 4 escalation and the two-person rule for break-glass access. |

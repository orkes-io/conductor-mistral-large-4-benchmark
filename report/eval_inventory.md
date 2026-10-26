# Eval set inventory (generated)

76 items. Every expected answer was verified by code or by sources; see `evals/verify/`.

## reasoning (20 items; difficulty hard 15, medium 5)

| id | title | scoring |
|---|---|---|
| reasoning-001 | Six-digit numbers with digit sum 27 | final answer (number) |
| reasoning-002 | Seven-seat row logic puzzle | final answer (sequence) |
| reasoning-003 | String rotate-and-shift trace | final answer (exact_ci) |
| reasoning-004 | New York to London across the DST gap | final answer (sequence) |
| reasoning-005 | Divisible by exactly two of 4, 6 and 9 | final answer (number) |
| reasoning-006 | Four dice: max is twice the min | final answer (regex) |
| reasoning-007 | Friday the 13ths in 2026-2030 | final answer (number) |
| reasoning-008 | SLA deadline over the holidays | final answer (exact_ci) |
| reasoning-009 | Round-robin scheduler with arrivals | final answer (sequence) |
| reasoning-010 | Shift-and-xor hash trace | final answer (number) |
| reasoning-011 | Shortest route that must pass through D | final answer (number) |
| reasoning-012 | Counting paths in a dependency graph | final answer (number) |
| reasoning-013 | Most jobs finished by their deadlines | final answer (number) |
| reasoning-014 | Upgrade budget with dependencies | final answer (number) |
| reasoning-015 | Drawing all three marble colors | final answer (regex) |
| reasoning-016 | Four houses: owners and pets | final answer (sequence) |
| reasoning-017 | Sydney call in three other time zones | final answer (sequence) |
| reasoning-018 | Two pipes, a drain and a 3/4 tank | final answer (number) |
| reasoning-019 | ABC strings with no repeats, each letter twice | final answer (number) |
| reasoning-020 | Smallest number above 10,000 from remainders | final answer (number) |

## coding (20 items; difficulty easy 1, hard 5, medium 14)

| id | title | scoring |
|---|---|---|
| coding-001 | ISO 8601 duration to seconds | 20 hidden asserts |
| coding-002 | Semantic version range check | 19 hidden asserts |
| coding-003 | Merge labeled intervals | 12 hidden asserts |
| coding-004 | Next run time for a cron expression | 17 hidden asserts |
| coding-005 | Strict CSV line parser | 17 hidden asserts |
| coding-006 | RFC 6901 JSON Pointer lookup | 18 hidden asserts |
| coding-007 | Glob matching with character classes | 20 hidden asserts |
| coding-008 | Subtract IPv4 CIDR blocks | 17 hidden asserts |
| coding-009 | Exact arithmetic expression evaluator | 20 hidden asserts |
| coding-010 | Optimal string alignment distance | 13 hidden asserts |
| coding-011 | Add business days with holidays | 15 hidden asserts |
| coding-012 | Token bucket rate limiter | 13 hidden asserts |
| coding-013 | Lexicographically smallest topological order | 13 hidden asserts |
| coding-014 | Greedy text wrapping with long words | 13 hidden asserts |
| coding-015 | Accept-Language negotiation | 16 hidden asserts |
| coding-016 | Natural sort order | 13 hidden asserts |
| coding-017 | LFU cache with LRU tie-break | 12 hidden asserts |
| coding-018 | Split a SQL script into statements | 17 hidden asserts |
| coding-019 | Earliest common free meeting slot | 15 hidden asserts |
| coding-020 | Currency formatting with banker's rounding | 18 hidden asserts |

## agentic (12 items; difficulty easy 2, hard 1, medium 9)

| id | title | scoring |
|---|---|---|
| agentic-001 | Roll back only the service with a fresh deploy | 2 required / 2 forbidden calls |
| agentic-002 | Book a cross-time-zone meeting inside working hours | 1 required / 4 forbidden calls |
| agentic-003 | Book travel inside the per-diem policy | 2 required / 8 forbidden calls |
| agentic-004 | Delete only stale unattached volumes, snapshot first | 4 required / 4 forbidden calls |
| agentic-005 | Approve or deny database access per policy | 3 required / 2 forbidden calls |
| agentic-006 | Hold a release that has an open SEV2 | 2 required / 1 forbidden calls |
| agentic-007 | Reorder low stock from the fastest approved supplier | 2 required / 5 forbidden calls |
| agentic-008 | Triage a failed pipeline run | 2 required / 4 forbidden calls |
| agentic-009 | Escalate a SEV1 to the right on-call | 2 required / 2 forbidden calls |
| agentic-010 | Roll firmware out only to eligible thermostats | 2 required / 6 forbidden calls |
| agentic-011 | Pick a laptop vendor by procurement rules | 3 required / 3 forbidden calls |
| agentic-012 | Route support tickets by tier and priority | 4 required / 6 forbidden calls |

## grounding (12 items; difficulty easy 4, medium 8)

| id | title | scoring |
|---|---|---|
| grounding-001 | 2026 Nobel Prize in Physics | 2 patterns + citation |
| grounding-002 | 2026 Nobel Prize in Physiology or Medicine | 4 patterns + citation |
| grounding-003 | 2026 Nobel Literature and Peace laureates | 1 patterns + citation |
| grounding-004 | 2026 US Open men's singles final | 1 patterns + citation |
| grounding-005 | 2026 US Open women's singles final score | 4 patterns + citation |
| grounding-006 | 2026 Asian Games medal table leader | 2 patterns + citation |
| grounding-007 | Python 3.15.0 release date and release manager | 2 patterns + citation |
| grounding-008 | Kubernetes v1.37 release name and date | 2 patterns + citation |
| grounding-009 | Latest stable Conductor OSS release (Oct 2026) | 1 patterns + citation |
| grounding-010 | Vega-C flight VV30 payloads | 2 patterns + citation |
| grounding-011 | US 2025 median household income and poverty rate | 2 patterns + citation |
| grounding-012 | Mistral Large 4 announcement and size | 3 patterns + citation |

## your_data (12 items; difficulty easy 3, hard 2, medium 7)

| id | title | scoring |
|---|---|---|
| your_data-001 | SEV-1 status page cadence | answerable + judge |
| your_data-002 | Escalating an unmitigated API error spike | answerable + judge |
| your_data-003 | Platinum downtime budget | answerable + judge |
| your_data-004 | Security patch during the holiday freeze | answerable + judge |
| your_data-005 | Time in lieu for overnight incidents | answerable + judge |
| your_data-006 | Incident chat log retention | answerable + judge |
| your_data-007 | Postmortem draft vs customer RCA deadlines | answerable + judge |
| your_data-008 | Friday deploy with the standard canary | answerable + judge |
| your_data-009 | Weekly on-call pay with extra pages | answerable + judge |
| your_data-010 | Silver tier uptime SLA | not in the document + judge |
| your_data-011 | On-call exemption after parental leave | not in the document + judge |
| your_data-012 | Disaster recovery region | not in the document + judge |

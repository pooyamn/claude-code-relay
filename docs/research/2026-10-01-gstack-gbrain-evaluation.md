# GStack and GBrain evaluation (2026-10-01)

Verdict: useful with controlled integration. Adapt selected GStack methodologies for the existing roles; use GBrain as a local memory retrieval/projection service behind the router. Neither replaces role authentication, evidence verification, publication gates, subscription pacing, or the operational action ledger. This evaluation authorizes design additions, not a live installation.

## Revisions and scope

- GBrain: version `0.60.27.0`, commit [`ad7900d8dcd221e22b885fef0f4030b73a1d69c9`](https://github.com/garrytan/gbrain/tree/ad7900d8dcd221e22b885fef0f4030b73a1d69c9), MIT. Source inspection plus synthetic PGLite and native macOS backup tests.
- GStack: commit [`7fca42ad8b6c707b8a38f579f72bf3c4f7de6d85`](https://github.com/garrytan/gstack/tree/7fca42ad8b6c707b8a38f579f72bf3c4f7de6d85), MIT. Source/workflow fit assessment only; no browser, model-quality, or installation tests. Productivity claims were not validated.
- Both checkouts were temporary. GBrain dependencies used the frozen lockfile with lifecycle scripts disabled. Its runtime requires Bun ≥1.4.0; a temporary official Bun 1.4.0 was used instead of upgrading the installed 1.3.14. The runtime archive matched the official SHA-256 manifest.
- Test processes ran with a clean environment, no subscription credentials/API keys, denied access to `/Users`, `/Volumes`, and `/Network`, writes restricted to evaluation scratch space, and external networking denied. Loopback was allowed for synthetic provider fixtures. No live memory, daemon, agent configuration, hooks, scheduler, or subscriptions were changed. Initial sandbox-launch errors were harness errors corrected before the completed runs below.

## Measured GBrain results

| Run | Passed | Failed | Skipped | What it established |
|---|---:|---:|---:|---|
| Seven upstream memory/authorization test files | 127 | 0 | 0 | In-process scoped reads/writes, private visibility, grant snapshots, keyless recall, receipt replay/concurrency, withdrawal ordering and bounded effects |
| Upstream native backup portability file | 23 | 0 | 10 | Actual archive creation/verification, absent-root restore, fresh-process reopen, preserved synthetic DB-only facts, corrupt archive rejection, path/privacy failures, unfinished-job quarantine |
| Two evaluator-written contract probes | 2 | 0 | 0 | Demonstrated the correctness gaps described below; passing means the gaps were reproduced, not fixed |

Total: 152 passed, zero failed, ten skipped. The skipped tests require native Windows ACL/PowerShell behavior. This is not a full audit, HTTP authentication penetration test, model-similarity benchmark, PostgreSQL deployment test, or clean Windows/WSL machine recovery drill.

Upstream runs, from the pinned checkout:

```sh
bun test test/authorization-boundaries.test.ts \
  test/memory-verbs-conformance.test.ts test/facts-visibility.test.ts \
  test/client-grants.test.ts test/no-grant-federated-scope.test.ts \
  test/persistence-memory-mutations.test.ts test/withdrawal-bounded-safety.test.ts
bun test test/backup-portability-native.serial.test.ts
```

The evaluated fixtures use synthetic data and mostly PGLite; provider callbacks in the relevant tests are substitutions, not paid model calls. The backup test reopens a restored store in a new process, but deliberately does not start restored automation. [Memory publication tests](https://github.com/garrytan/gbrain/blob/ad7900d8dcd221e22b885fef0f4030b73a1d69c9/test/persistence-memory-mutations.test.ts), [native restore test](https://github.com/garrytan/gbrain/blob/ad7900d8dcd221e22b885fef0f4030b73a1d69c9/test/backup-portability-native.serial.test.ts).

### Reproduced mismatch with our memory rules

1. In keyless mode, two opposing synthetic motor-voltage claims were both inserted and remained remotely retrievable. Invented evidence attribution, including an unauthenticated claim of owner approval, was accepted verbatim. Both defaulted to `world` visibility. GBrain's provenance requirement checks an attribution string, not its authenticity or factual support.
2. With a deterministic embedding callback returning the same vector for opposing claims, a new unsupported claim superseded the earlier attributed claim. This tests the supersession decision once similarity qualifies; it does **not** establish how frequently a real embedding model produces that similarity. GBrain's rule compares similarity, kind, and changed text, not the validity of correction evidence. Without embeddings, that path reports degraded deduplication instead. [Single-fact implementation](https://github.com/garrytan/gbrain/blob/ad7900d8dcd221e22b885fef0f4030b73a1d69c9/src/core/facts/write-single.ts), [remember contract](https://github.com/garrytan/gbrain/blob/ad7900d8dcd221e22b885fef0f4030b73a1d69c9/src/core/verbs.ts).

These are documented semantics, not assertions of upstream defects. They prevent using unrestricted `remember` as our canonical-memory writer. The router must validate evidence, preserve disputed records, and publish explicit curator-approved changes. Source grants and operation snapshots are useful enforcement mechanisms; directory routing and the local CLI are not agent authentication. Existing legacy no-grant federation must not be used for worker access. [Grant tests](https://github.com/garrytan/gbrain/blob/ad7900d8dcd221e22b885fef0f4030b73a1d69c9/test/client-grants.test.ts), [legacy federation tests](https://github.com/garrytan/gbrain/blob/ad7900d8dcd221e22b885fef0f4030b73a1d69c9/test/no-grant-federated-scope.test.ts), [source boundaries](https://github.com/garrytan/gbrain/blob/ad7900d8dcd221e22b885fef0f4030b73a1d69c9/docs/architecture/brains-and-sources.md).

### Useful contribution

- Bounded, source-scoped retrieval and context packing can supply relevant memory without loading every file into each turn. Keyless keyword retrieval works in the tested configuration; local semantic retrieval remains a separate compatibility/quality test.
- Durable request receipts and coordinated writes reduce custom implementation work for projection publication and replay. They are not evidence of exactly-once email, GitHub, Telegram, or other external actions.
- Explicit withdrawal history and native full-store snapshots are substantially more useful than treating a Markdown export as complete recovery. Native restore preserves DB-only data and pauses unfinished automation; our full-system encrypted backup and external-action reconciliation remain necessary. [Snapshot implementation](https://github.com/garrytan/gbrain/blob/ad7900d8dcd221e22b885fef0f4030b73a1d69c9/src/core/backup/snapshot.ts).

Costs: another Bun/PGLite component, schema migrations, private service storage, snapshot integration, and a policy adapter. Start with a single local service and one memory workflow, not a second autonomous coordination system. GBrain's standalone synthesis/extraction/dream jobs must not introduce separately billed API work or model wakes outside the scheduler.

## GStack fit

Useful methodology: risk-focused review categories, scoped engineering review, evidence-backed investigation, and QA charters with explicit expected outcomes and retained reports. Assign those to the existing reviewer, on-demand CTO, support, and builder/reviewer QA workflow; they do not require adding persistent management agents. [Review checklist](https://github.com/garrytan/gstack/blob/7fca42ad8b6c707b8a38f579f72bf3c4f7de6d85/review/checklist.md), [engineering review](https://github.com/garrytan/gstack/blob/7fca42ad8b6c707b8a38f579f72bf3c4f7de6d85/plan-eng-review/sections/review-sections.md), [investigation](https://github.com/garrytan/gstack/blob/7fca42ad8b6c707b8a38f579f72bf3c4f7de6d85/investigate/SKILL.md), [QA-only](https://github.com/garrytan/gstack/blob/7fca42ad8b6c707b8a38f579f72bf3c4f7de6d85/qa-only/SKILL.md).

Stock execution is not compatible unchanged: review can auto-edit, specialist workflows spawn several reviewers, outside opinions invoke another CLI directly, and shipping pushes/creates PRs. Adapt these to findings → builder fixes → fresh SHA-bound review; additional opinions use admitted native sessions, and publication remains a router action. Automatic team updates also conflict with reviewed version pins. [Review behavior](https://github.com/garrytan/gstack/blob/7fca42ad8b6c707b8a38f579f72bf3c4f7de6d85/review/SKILL.md), [specialist dispatch](https://github.com/garrytan/gstack/blob/7fca42ad8b6c707b8a38f579f72bf3c4f7de6d85/review/sections/review-army.md), [shipping](https://github.com/garrytan/gstack/blob/7fca42ad8b6c707b8a38f579f72bf3c4f7de6d85/ship/SKILL.md), [team installation](https://github.com/garrytan/gstack/blob/7fca42ad8b6c707b8a38f579f72bf3c4f7de6d85/README.md).

GStack's GBrain setup can register broad local stdio access, select available cloud embedding keys, and sync artifacts to a remote repository. Those are not our default. Adopt methodology and compatible helpers only after review; keep memory local, credentials isolated, telemetry/artifact egress off, and browser QA in an isolated test profile rather than importing Pouya's logged-in cookies. [Integration guide](https://github.com/garrytan/gstack/blob/7fca42ad8b6c707b8a38f579f72bf3c4f7de6d85/USING_GBRAIN_WITH_GSTACK.md).

## Admission before live use

Implement and demonstrate one brokered memory workflow on the target WSL runtime: proposal → evidence check → canonical file → GBrain projection → scoped recall → explicit correction/withdrawal → restart/replay → encrypted backup/restore. Attempt role/source spoofing, forbidden operations, false approval attribution, unauthorized supersession, cross-role retrieval, and restoration of withdrawn claims. Verify no hidden model spending, background autonomous jobs, or external egress.

For GStack, demonstrate one adapted review and one isolated QA report without reviewer edits, direct publication, hidden child model work, or quota/cap bypass. Measure finding usefulness, completed tasks, interventions, and quota per useful outcome before expanding use. These acceptance checks remain work to do, not results of this evaluation.

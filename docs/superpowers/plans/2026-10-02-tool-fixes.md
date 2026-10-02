# Verified individual-tool fixes

Approved in conversation 2026-10-02. Implement inline with Superpowers executing-plans,
TDD, fresh final code review, and end-to-end verification after review.

## Contract

Fix TA01–TA08 from docs/audits/2026-10-01-tools.md. Retain the legacy deploy helper
and x4cat, handing later migration decisions to Claude in documentation. X4 Live
is offline-only. No production mod, game, reference, profile, save, or archive edits.
Use isolated checkouts and preserve unrelated dirty files. Agent-facing files are
generated: edit agent/ and regenerate when necessary. Never push.

## Tasks

1. Legacy deploy: explicit checks under -O, batch preflight, reject links/reparse
   points, destination containment, recheck before mutations; scratch apply only.
2. BaseX: lexical QName validation; restricted content-search grammar for zero
   certification (unrecognized positive queries run; zeros rc 4); optional --limit
   and --offset on refs/attr/xq, defaults unlimited/zero, limit 0 unlimited. Count
   and classify the full sequence once before paging whole items. Unsupported
   requested paging rc 2 without unbounded fallback. Existing reach refusals stay.
3. Xref: strict complete TSV validation, new artifact_sha256 sidecar field;
   integrity failures rc 2; unsigned legacy positives warned, absence only with
   integrity and current freshness; no automatic production rebuild.
4. Save/effective: invalid DEFLATE and corrupt/incompatible stores return rc 2
   without tracebacks; preserve valid inputs and ordinary SQL error semantics.
5. x4cat: validate pinned complete template before output; --template-dir and
   keyword-only library parameter; invalid present templates rc 2, absent default
   retains retrieval; successful scaffold and official pack/unpack tests.
6. Documentation, final review, fix important findings with red/green evidence,
   then full suites, CLI checks, 125-mod/250-report corpus baseline comparison,
   scratch BaseX/archive/deploy E2E, protected-data snapshots, integration.

## Initial confidence and assumptions

Deploy explicit checks 98%, reparse protection 96%; BaseX attr 98%, grammar 92%,
paging 93%; xref 96%; save 98%; effective 97%; template 97%. These estimates are
pre-implementation. Each regression must fail for its named root cause first.
BaseX accepted grammar: literal whole-db root; child/descendant/attribute paths;
relative content predicates; literal comparisons; boolean combinations; exists,
empty, not. Outside grammar never certify zero. Stop and reassess if semantics or
compatibility invalidate the model. Legacy deployment assumes a trusted local
filesystem, not hostile concurrent modifications or transactional rollback.

## Verification

Focused regressions and positive controls per task; complete applicable suites
before declaring completion. Real subprocess BaseX tests, actual Windows junction
tests, normal/-O deploy refusal sentinels, malformed index/save/store tests, valid
pinned scaffold. Final corpus compares per-mod reports (existing mod errors remain).
Disclose skips/limitations; no live game or production deployment. Update README,
CLI/query guides, generated reference, KB, blind spots, audit status, changelogs and
legacy handoff. Back up installed tool-code files before installing reviewed fixes.

## Completion

Tasks 1–6 completed and installed locally on 2026-10-02. Independent final review
corrections passed red/green tests; later metadata-boundary E2E correction was
reviewed locally and included in the final 2914-passed / 49-skipped toolkit suite.
Installed launchers, external suites, scratch workflows and the unchanged
250-report corpus are documented in the [repair report](../../audits/2026-10-02-tool-fixes.md).
No push or production artifact rebuild. Evidence/worktrees are retained.

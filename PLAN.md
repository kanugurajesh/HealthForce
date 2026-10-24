# HealthForce Intelligence — Implementation Plan

## Starting point (assessment, 2026-10-23)

- The repository was **empty**: no code, no git history, no existing conventions to preserve.
- Toolchain available: Python 3.13, Node 24 / npm 11, Docker CLI (daemon not running), no local PostgreSQL.
- Consequence: greenfield build using the preferred stack (Next.js + FastAPI + SQLAlchemy/Alembic),
  with a portable data layer so the app runs with zero infrastructure (SQLite) and on PostgreSQL via docker-compose.

## Product scope for the first release

A recruiter/reviewer workflow application that answers five questions per candidate:
who matches a role, what evidence supports it, which credentials are not ready, what remains before
onboarding, and what to do next. AI is used only for document → structured-claims extraction (and an
optional summary); every decision-relevant number or status is computed deterministically.

### In scope
| Area | First release |
|---|---|
| Auth | Email/password demo users, JWT in httpOnly cookie, 4 roles, server-side permission checks |
| Tenancy | Organization-scoped data, enforced in every query; two seeded orgs to prove isolation |
| Candidates | List, search, filters, profile, pipeline status workflow with guarded transitions |
| Jobs | Create/edit roles with typed requirements (credential, qualification, skill, experience; required vs preferred) |
| Matching | Deterministic per-requirement outcomes (met / pending / unknown / not met), eligibility gate, explainable weighted score, next actions |
| Extraction | Upload → validate → text extraction → provider (mock or gpt-oss-120b on Groq) → schema validation → evidence verification → normalization → human review |
| Credentials | Separate extraction / review / verification / time facts, derived status with documented precedence, conflict detection |
| Review | Evidence viewer with highlighted source text, accept / correct / reject claims, notes and decisions |
| Onboarding | Org-configurable checklist template, owners, due dates, derived blockers, completion history |
| Audit | Append-only audit events for every important state change |
| Processing | DB-backed jobs with states, bounded retries, failure visibility and manual retry |

### Explicitly out of scope (documented as gaps)
OCR for scanned documents, real registry integrations (Nursys, OIG, SAM.gov, state boards), SSO, e-signature
paperwork collection, interview calendar integration, email notifications, HIPAA-grade controls.

## Phases

| # | Phase | Acceptance criteria | Status |
|---|---|---|---|
| 1 | Assessment, architecture docs, runnable skeleton | Docs written; backend + frontend start | ✅ done |
| 2 | Data model, migrations, auth, tenancy | Alembic migration creates schema on SQLite; auth + role tests pass | ✅ done |
| 3 | Deterministic rules (credential status, matching) | Unit tests for every status and precedence rule, matching scenarios | ✅ done |
| 4 | Extraction pipeline + mock/Groq providers + job worker | Injection, invalid output, missing fields, retry, duplicate tests pass | ✅ done |
| 5 | APIs: candidates, jobs, review, onboarding, audit, dashboard | Integration tests through HTTP; cross-org access returns 404 | ✅ done |
| 6 | Seed via real pipeline | `python -m app.seed` produces the scenario set | ✅ done |
| 7 | Frontend: dashboard, candidates, profile/review, jobs/matching, processing, settings | `npm run build`, lint and type-check pass | ✅ done |
| 8 | Evaluation dataset + metrics, frontend tests | `python -m eval.run` reports real metrics | ✅ done |
| 9 | README, final review, known gaps | Documented commands verified end-to-end | ✅ done |

## Key risks and mitigations

| Risk | Mitigation |
|---|---|
| LLM fabricates qualifications/dates | Model returns verbatim quotes + raw date text only; code verifies text exists in the document, parses dates itself, discards unsupported values |
| Prompt injection in uploaded documents | No tools, schema-only output with no status fields, delimited untrusted content, heuristic injection detector that forces human review |
| Overstating compliance | Verification states distinguish manual attestation from simulated demo verification; no registry claims |
| Opaque scoring | Score is a documented weighted formula; hard requirements gate eligibility separately; never auto-reject |
| Stuck/duplicated processing | Atomic job claim, lease timeout reclaim, bounded retries, document dedupe by SHA-256, idempotent result application |
| Data exposure | PII redaction before provider calls, no document contents in logs, uploads stored under random names |
| SQLite/Postgres drift | Portable column types (no native enums), constraints expressed portably, migrations reviewed |

## Status (end of first implementation pass)

All phases are implemented and verified; see README → "Verification performed" for the exact commands and
results. Notable changes to the original plan, each recorded in DECISIONS.md:

- No Redis/Celery (ADR-003); PostgreSQL supported but SQLite is the zero-setup default (ADR-002).
- Credential status uses the best record per type and precision-aware conflicts (ADR-012, ADR-013) —
  both found by running the seeded scenarios, not anticipated in the original plan.
- Separation of duties between recruiter and reviewer (ADR-015); no OCR (ADR-016).

### Next priorities (not started)

1. Run the test suite and seed against PostgreSQL in CI (migration DDL is verified offline only).
2. Run `python -m eval.run --provider groq` with a GROQ_API_KEY and compare to the mock baseline;
   expand the evaluation set with real-world-style (still synthetic) document layouts.
3. Materialized readiness for large organizations; scheduled re-evaluation for date-driven changes.
4. SSO/OIDC, per-user audit export, document retention policy, OCR behind an explicit review step.

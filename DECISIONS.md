# Architectural Decision Log

Each entry: context → decision → alternatives rejected → trade-offs.

---

## ADR-001 — Greenfield monorepo: Next.js frontend + FastAPI backend
**Context.** The repository was empty; the brief prefers Next.js/TypeScript and Python/FastAPI/Pydantic.
**Decision.** `frontend/` (Next.js App Router, TypeScript, Tailwind) and `backend/` (FastAPI, SQLAlchemy 2, Alembic, Pydantic v2) in one repository. The frontend proxies `/api/*` to the backend through a Next.js rewrite, so the browser sees a single origin.
**Rejected.** Next.js API routes only (would put extraction and rules in TypeScript, losing Pydantic validation and the Python document tooling); separate CORS-based origins (forces cross-site cookies or tokens in JS-readable storage).
**Trade-off.** Two processes to run; documented in the README.

## ADR-002 — Portable relational model; SQLite by default, PostgreSQL supported
**Context.** PostgreSQL is the target, but the reviewer's machine (and this build machine) may not have it running.
**Decision.** SQLAlchemy models use only portable types (strings validated against Python enums plus CHECK constraints rather than native ENUM types, generic JSON). Alembic migrations run on both. `HF_DATABASE_URL` selects the engine; `docker-compose.yml` provides PostgreSQL.
**Trade-off.** No PostgreSQL-specific features (e.g. `SKIP LOCKED`, full-text search). The job claim uses a conditional `UPDATE ... WHERE status='pending'`, which is atomic on both engines.

## ADR-003 — No Redis/Celery: DB-backed job table + in-process worker
**Context.** The brief suggests a queue "only if justified". Extraction may take seconds to a minute with an LLM, so it must not block requests and needs retries and visible status, but volume is low and this is a single-node demo.
**Decision.** `processing_jobs` table (pending → processing → succeeded/failed) with attempt counts, `next_attempt_at` backoff, a lease timestamp, and a reclaim of stale leases. A daemon thread polls and claims jobs atomically. `POST /documents/{id}/retry` re-queues failed jobs.
**Rejected.** Celery + Redis (two more services, a broker to secure, and no throughput need); FastAPI `BackgroundTasks` (lost on restart, no retry/state).
**Trade-off.** Throughput is bounded by one worker thread per API process. The worker logic is isolated in `app/worker.py` behind `process_job(job_id)`, so moving to RQ/Celery means swapping only the dispatcher.

## ADR-004 — The LLM extracts quotes, never conclusions
**Context.** Hallucinated credentials or dates are the dominant risk; the brief forbids LLM-invented scores.
**Decision.** The provider returns a strict Pydantic schema in which every claim carries a verbatim `evidence_quote`, and dates come back as **raw text as printed**. Deterministic code then (1) verifies the quote exists in the document (whitespace/case-normalized) and records character offsets; (2) parses dates itself, keeping a date only if its raw text is found in the document; (3) keeps identifiers and issuers only if their literal text appears in the document; (4) maps names to the credential/qualification/skill catalogs. The schema has **no status, verification, or score fields**, so no document content can set them.
**Rejected.** Free-form LLM JSON with model-provided ISO dates (can silently invent or "correct" dates); LLM-computed match scores.
**Trade-off.** Unusual date formats may be dropped and routed to manual review rather than guessed. That is the intended failure direction.

## ADR-005 — Credential status is derived, with explicit precedence
**Decision.** Extraction facts, reviewer decision (`review_state`), verification (`verification_status` + method), and time (`expiration_date` vs as-of date) are stored separately. Status is computed by a pure function with this precedence:
`rejected > unable_to_determine (conflicting evidence) > expired > unable_to_determine (no expiration date) > pending_review > pending_verification > expiring_soon > verified`.
A requirement with no record is `missing`. Editing a verified credential's facts resets verification.
**Why.** An expired credential can never look ready because it was once reviewed; a conflict is never resolved by guessing.
**Conflict definition.** Same credential type and same identifier (or same issue date) with different expiration dates. Different issue dates are treated as renewals, not contradictions; the requirement then uses the best-ranked record.

## ADR-006 — No fake registry integrations
**Decision.** Two verification paths: `manual` (a reviewer attests they checked a primary source and records a reference) and `simulated` (demo-only, enabled by `HF_VERIFICATION_MODE=simulated`, labelled "Simulated" everywhere in the UI and API). No Nursys/OIG/SAM.gov calls exist in the code.

## ADR-007 — Matching: eligibility gate + transparent weighted score
**Decision.** Each requirement evaluates to `met | pending | unknown | not_met`, with evidence and an explanation. **Eligibility** is derived from required requirements only (any `not_met` → "requirement not met"; any `unknown` → "missing information"; any `pending` → "pending review/verification"; otherwise "meets all required"). The **score** is `Σ(weight × credit) / Σ(weight)` with credit met = 1, pending = 0.5, unknown/not met = 0. Ranking sorts by eligibility tier, then score. Nothing is auto-rejected.
**Missing ≠ not met.** No evidence yields `unknown` ("request information"), not `not_met`. `not_met` requires evidence: an expired or rejected credential, or documented experience below the minimum.

## ADR-008 — Authentication: JWT in an httpOnly cookie, roles enforced server-side
**Decision.** Demo users with PBKDF2-hashed passwords; a signed JWT (HS256) in an `httpOnly`, `SameSite=Lax` cookie (a Bearer header is also accepted for API clients and tests). Roles: `admin`, `recruiter`, `reviewer`, `viewer`, with a permission matrix checked on every mutating route. Every query is scoped by `organization_id`, and cross-tenant lookups return 404 (not 403) to avoid leaking existence.
**Rejected.** NextAuth/SSO (out of scope for a demo; documented as a gap); tokens in `localStorage` (XSS-exfiltratable).

## ADR-009 — Seed data goes through the real pipeline
**Decision.** `python -m app.seed` creates candidates, uploads synthetic documents through the same service the API uses, runs extraction synchronously with the mock provider, then applies reviewer actions to create the demo scenarios. Evidence offsets in the demo are therefore real pipeline output, not hand-written fixtures.

## ADR-010 — Mock provider is a real (heuristic) extractor, clearly labelled
**Decision.** Without an API key, the `mock` provider is a deterministic section/regex-based extractor that emits the same schema as the AI provider. It goes through the same validation/evidence pipeline, and every claim it produces is labelled `source = mock`. The evaluation harness reports its real accuracy on the synthetic dataset, so it is not presented as AI.

## ADR-011 — PII minimization before provider calls
**Decision.** Before text reaches an external provider: email addresses, phone numbers, SSN-like numbers, and street addresses are replaced with placeholders. Document text is never logged; logs carry ids, counts, and durations only.

## ADR-012 — Readiness is computed on read, using the best record per credential type
**Context.** Candidates often have several records of one credential (resume mention + license printout, old + renewed card).
**Decision.** Status for lists, filters, dashboard and requirements uses the best-ranked record per type (status rank → later expiration → credential document over resume mention). All records stay visible on the profile.
**Why.** Found during seeding: an undated resume mention next to a verified license made the candidate show as "unable to determine" and inflated the dashboard's credential-issue count.
**Trade-off.** Computation per request; see ARCHITECTURE.md → Scaling notes for the materialization path.

## ADR-013 — Conflict detection is precision-aware
**Context.** A resume says "valid through 12/2027"; the certificate says "December 31, 2027". Treating these as contradictory (found during seeding) is wrong.
**Decision.** The printed precision of each expiration is kept (derived from `expiration_text`); dates conflict only if they differ beyond that precision. Records with different identifiers or different issue dates are treated as separate instances (renewals), never as conflicts.

## ADR-014 — Unreviewed evidence earns "pending", never "met"
**Decision.** Every requirement outcome of `met` requires human-reviewed evidence (accepted or corrected). Machine-extracted but unreviewed evidence yields `pending` (half credit). A bulk "accept evidence-supported items" action exists for efficiency, but skips anything flagged and is disabled for documents with injection signals.
**Rejected.** Letting high-confidence extractions count as met — it would make the AI's output decision-relevant without a human.

## ADR-015 — Separation of duties between recruiter and reviewer
**Decision.** Recruiters create candidates/jobs and move the pipeline; reviewers accept/correct evidence, record verifications and complete the final review. Admin can do both. Forward moves despite an unmet required requirement need an audited override reason.
**Trade-off.** Small teams need two accounts (or an admin) to clear a candidate — intentional for a compliance-sensitive workflow.

## ADR-016 — No OCR in the first release
**Decision.** PDFs without a text layer fail with a permanent, explained error (`no_text_layer`) and a "add credential manually" path exists.
**Why.** OCR adds a heavy dependency and its own error modes (misread digits in license numbers/dates); a clear failure + manual entry is safer for a first release. Documented as a gap.

## ADR-017 — Evaluation dataset is separate from seed data and labelled independently
**Decision.** `backend/eval/dataset` uses formats the seed data does not (two-digit years, ISO dates, "YYYY-YYYY:" lines, comma-joined credentials). Gold labels record what a human would read, so conservative refusals (e.g. "exp 6/27") are counted as misses, not hidden.
**Caveat.** The mock extractor was written alongside these formats; its numbers are an optimistic bound. The same harness runs the Groq provider (`--provider groq`), which has not been run in this environment (no API key).

## ADR-018 — Frontend tests render real pages against captured API responses
**Decision.** `frontend/scripts/capture-fixtures.py` captures responses from a seeded backend; Vitest renders the actual page components with those fixtures (navigation mocked). This catches contract drift between backend and frontend types without a browser.

## ADR-019 — AI provider: gpt-oss-120b on Groq instead of Claude
**Context.** The owner chose Groq's hosted `openai/gpt-oss-120b` over the Claude API.
**Decision.** `GroqProvider` (official `groq` SDK) replaces the Claude provider. It calls chat completions with `response_format = json_schema` and **`strict: true`**; the schema is generated from the same Pydantic `ExtractionOutput` model the pipeline validates against (`schemas.strict_json_schema()`): every property required, optional values as nullable types, `additionalProperties: false` everywhere — Groq's strict-mode rules. `reasoning_effort` is configurable (default `medium`); reasoning text is not requested (`include_reasoning=false`). The untrusted-document framing, system prompt and PII redaction are unchanged.
**Error handling.** 429/5xx/connection errors retry with backoff; 401/403 and most 400s fail permanently; a 400 `json_validate_failed` is treated as retryable invalid output; 413 → "document too long"; `finish_reason=length` → truncated; any other non-`stop` finish → declined. A missing `GROQ_API_KEY` fails the job immediately with a clear message, and the UI banner warns.
**Trade-offs.** Document text (contact details redacted) is sent to Groq; review Groq's data-handling terms before using non-synthetic documents. Strict structured output guarantees shape, not truth — grounding still discards anything not literally in the document (covered by `test_model_output_is_grounded_like_any_provider`). Not yet exercised against the live API in this environment.

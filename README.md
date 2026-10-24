# HealthForce Intelligence

An employer-facing healthcare recruitment application that helps a recruiter answer, for every candidate:

1. **Does this candidate match the role?** — deterministic per-requirement outcomes, an eligibility gate and a transparent weighted score.
2. **What evidence supports it?** — every extracted fact carries a verbatim quote, highlighted in the source document.
3. **Which credentials are missing, expired, expiring or unverified?** — explicit, precedence-ordered credential states.
4. **What remains before onboarding?** — a configurable checklist with rule-derived blockers.
5. **What should I do next?** — ranked, explained next actions.

AI is used for exactly one bounded job — turning uploaded resumes and credential documents into candidate facts **with quotes**. Scores, statuses, eligibility and blockers are computed by deterministic code over **human-reviewed** data. Nothing is rejected or completed automatically.

> **Independent proof-of-work.** Inspired by public descriptions of healthcare recruitment and credentialing workflows (e.g. CaresLink). It is not affiliated with, derived from, or integrated with any CaresLink system. All people, organizations, license numbers and documents are synthetic.
>
> **Not a compliance product.** No HIPAA or regulatory claims; no real registry (Nursys, OIG, SAM.gov, state boards) is integrated. "Simulated" verification is labelled as such everywhere.

---

## Quick start (≈ 3 minutes, no Docker, no API key)

Prerequisites: **Python 3.12+**, **Node.js 20+** (tested with Python 3.13.3 and Node 24.1).

```bash
# 1. Backend
cd backend
python -m pip install -r requirements.txt
python -m app.seed --reset          # creates SQLite DB via Alembic + synthetic demo data (runs the real pipeline)
python -m uvicorn app.main:app --port 8000

# 2. Frontend (second terminal)
cd frontend
npm install
npm run dev                          # http://localhost:3000  (or: npm run build && npm start)
```

Sign in at <http://localhost:3000> — password for every demo account: **`demo-password-2026`**

| Account | Role | Can |
|---|---|---|
| `recruiter@northwind.example` | Recruiter | create candidates & job roles, upload, move pipeline, onboarding tasks |
| `reviewer@northwind.example` | Reviewer | accept/correct/reject evidence, record verification, final review |
| `admin@northwind.example` | Admin | everything, incl. onboarding template |
| `viewer@northwind.example` | Viewer | read-only |
| `recruiter@lakeside.example` | Recruiter, *other organization* | demonstrates tenant isolation |

API docs (OpenAPI): <http://localhost:8000/docs>.

## A recruiter walkthrough (what to click)

The seed creates 13 Northwind candidates, each illustrating one situation (dates are relative to today, so the scenarios stay valid):

| Candidate | Situation | Where to look |
|---|---|---|
| **Maya Thompson** | Everything verified; onboarding with only the final review left | *Onboarding* tab; sign in as reviewer to complete the final review, then as recruiter → *Change stage → Cleared* |
| **Rachel Adams** | Fully cleared to start | *Notes & activity* shows the full audit trail |
| **Tom Becker** | Score 79 (CCRN, 7 yrs ICU) but **RN license expired** → "Requirement not met" | *Overview* → expand the RN requirement; try moving to Interview (override reason required) |
| **Samuel Brooks** | Eligible, BLS **expiring soon** → renewal action | Dashboard expirations |
| **Daniel Okafor** | ACLS **missing** → "missing information", not a failure | *Credentials* tab |
| **Priya Raman** | BLS **expired** | Candidates → filter "Expired" |
| **Luis Hernandez** | License record has **no expiration date** → unable to determine | *Credentials* → *Correct* to enter the date |
| **Grace Liu** | Resume and license record **contradict** each other | *Credentials* → reject the outdated record and watch the status resolve |
| **Aisha Bello** | Freshly uploaded, nothing reviewed | *Documents* → *Review evidence* → accept items |
| **Jordan Ellis** | Resume contains a **prompt-injection** attempt | Document page: warning, no bulk accept, nothing became verified |
| **Elena Petrova** | CNA in onboarding; certification verified in **SIMULATED** mode | *Credentials* tab labels |
| **Noah Kim** | Uploaded a **scanned PDF** with no text → processing failed | *Document processing* page; *Add credential manually* |
| **Hannah Wright** | No job role assigned | *Edit* → assign; or *Job roles → ICU RN → Assign* |

Typical flow: **Dashboard** → click a metric tile (it opens the exact filtered list) → open a candidate → **Overview** explains eligibility and the score requirement by requirement → **"source"** opens the document with the evidence highlighted → accept/correct/reject → **Verify** (record the primary source you checked) → **Change stage** → **Onboarding** checklist → **Notes & activity** for decisions and the audit trail. **Job roles** ranks every candidate against a role and explains each ranking ("Why?").

## Architecture

The design rests on one rule: **AI extracts, code decides, humans confirm.** The language model only turns documents into quoted facts. Credential status, requirement outcomes, eligibility, scores, blockers and next actions all come from pure, deterministic functions that run over data a reviewer has checked.

### System overview

```mermaid
flowchart LR
  subgraph Browser
    UI["Next.js pages<br/>React 19 · TypeScript · Tailwind · SWR"]
  end
  subgraph "Next.js server :3000"
    RW["/api/* rewrite proxy<br/>same origin → httpOnly cookie, no CORS"]
  end
  subgraph "FastAPI process :8000"
    MW["middleware<br/>request id · security headers · JSON access log"]
    API["api/ routers<br/>auth · candidates · claims · documents · job-roles<br/>onboarding · dashboard · audit · meta"]
    SEC["security.py<br/>JWT session · role → permission matrix"]
    SVC["services/<br/>evaluation · workflow · documents<br/>processing · serializers · audit"]
    RULES["rules/ (pure)<br/>credentials.py · matching.py"]
    W["Worker thread<br/>polls processing_jobs"]
    EXT["extraction/<br/>text · redact · screen · providers · ground"]
  end
  DB[("SQLite (dev) / PostgreSQL<br/>SQLAlchemy 2 + Alembic")]
  FS[("Upload store<br/>data/uploads/&lt;org&gt;/&lt;uuid&gt;")]
  LLM["Groq · openai/gpt-oss-120b<br/>(optional — mock provider by default)"]

  UI --> RW --> MW --> API
  API --> SEC
  API --> SVC --> RULES
  SVC --> DB
  SVC --> FS
  W --> DB
  W --> EXT --> LLM
  W --> FS
```

There are two processes and one database. The browser only ever talks to the Next.js origin, and Next.js forwards `/api/*` to FastAPI (`frontend/next.config.ts`). Background extraction runs in a daemon thread inside the FastAPI process. That thread is started in the app lifespan (`app/main.py`) and can be turned off with `HF_RUN_WORKER=false`. The only external call is the optional Groq request.

### Backend layers

Dependencies point one way: `api → services → rules`. `extraction/` is used only by the worker.

| Layer | Path | Responsibility | Must not |
|---|---|---|---|
| HTTP | `app/api/` | Validates input (Pydantic), checks permissions (`deps.py`, `security.py`), shapes responses | contain business rules |
| Services | `app/services/` | Runs transactions, loads data scoped to the caller's organization, applies extraction results, enforces workflow guards, writes audit events, runs the job worker | handle HTTP concerns |
| Rules | `app/rules/` | Computes credential status and conflicts, requirement outcomes, eligibility, score and next actions | touch the DB, the clock (the as-of date is passed in) or any AI |
| Extraction | `app/extraction/` | Validates files, extracts text, redacts PII, screens for prompt injection, calls the provider, **grounds** the output | write to the DB or decide statuses |
| Domain | `app/domain.py`, `app/dates.py`, `app/clock.py` | Holds the credential, qualification and skill catalogs, a conservative date parser and an injectable "today" | — |
| Persistence | `app/models.py`, `migrations/` | Defines the schema with CHECK/UNIQUE constraints and an `organization_id` on every tenant row | — |

### Request lifecycle (read path)

```mermaid
sequenceDiagram
  participant B as Browser (SWR)
  participant N as Next.js proxy
  participant A as FastAPI router
  participant S as services/evaluation
  participant R as rules/
  participant D as DB
  B->>N: GET /api/candidates/{id} (cookie)
  N->>A: forward
  A->>A: decode JWT · reload user/role from DB · check permission
  A->>S: load candidate scoped by organization_id (other org → 404)
  S->>D: candidate + claims + documents + job role
  S->>R: assess_all(credentials, as_of) · evaluate_match(requirements, facts, as_of)
  R-->>S: statuses · outcomes · eligibility · score · next actions
  S-->>A: readiness view
  A-->>B: JSON (Cache-Control: no-store, X-Request-ID)
```

Derived state, such as status, eligibility, score and blockers, is **computed on read** and never stored. It therefore cannot go stale when a date passes, a reviewer changes a decision or a job role is edited.

### Write path: upload → extraction → review

```mermaid
flowchart TD
  U["POST upload"] --> V{"validate<br/>extension · magic bytes · size · UTF-8"}
  V -- invalid --> E["415 / 413 / 400 with a clear message"]
  V -- ok --> H{"same SHA-256 already<br/>on this candidate?"}
  H -- yes --> DUP["return existing document (nothing re-queued)"]
  H -- no --> S["store under random name · insert processing_job (pending)"]
  S --> C["worker claims job atomically<br/>UPDATE … WHERE status='pending'"]
  C --> T["text (pypdf / UTF-8) — no text layer → permanent failure"]
  T --> P["redact emails · phones · SSNs · addresses"]
  P --> I["injection screen (flags, never blocks)"]
  I --> X["provider.extract()<br/>Groq strict JSON schema or mock"]
  X --> G["validate + ground<br/>quotes, dates, ids, issuers must appear verbatim<br/>dates parsed by our code, not the model"]
  G --> A["apply in one transaction<br/>replace only unreviewed machine claims"]
  A --> REV["human review: accept · correct · reject · verify"]
```

Jobs have the states `pending → processing → succeeded | failed`. Retryable errors back off for 5 s, 30 s and then 120 s, up to 3 attempts. A job whose lease has expired is reclaimed, which covers a worker that crashed. Manual retry and re-extract keep everything a reviewer has already decided. Idempotency comes from three places: one job per document (unique `document_id`), `process_job` doing nothing unless the job is in `processing`, and a unique constraint on the document hash for each candidate.

### Why extracted facts can't turn into qualifications on their own

1. **Schema** (`extraction/schemas.py`): the model can return only facts, an `evidence_quote` and raw date *text*. There is no status, validity, score or recommendation field for it, or for an injected instruction, to fill in.
2. **Grounding** (`extraction/pipeline.py`): a claim whose quote isn't found in the document is dropped. An identifier, issuer, employer or date whose literal text isn't present is removed, and a flag explains why.
3. **Parsing**: `app/dates.py` parses dates. An ambiguous date, such as one with a two-digit year, becomes *unable to determine* instead of a guess.
4. **Review gate**: an unreviewed claim can produce only a `pending` outcome (half credit), never `met`.

### Decision engine (`app/rules/`)

- **Credential status** has a fixed order of precedence: `rejected` → `unable to determine` (conflicting records) → `expired` → `unable to determine` (no expiration date) → `pending review` → `pending verification` → `expiring soon` (≤ 60 days) → `verified`. An expired credential stays expired even if it was verified.
- **Requirements** each resolve to `met | pending | unknown | not_met`, with an explanation, evidence references and a next action. A missing credential gives `unknown` ("missing information"), not `not_met`.
- **Eligibility** looks only at required requirements. **Score** = Σ weight × credit / Σ weight, where met = 1, pending = 0.5 and anything else = 0. **Ranking** sorts by eligibility tier first, so a high score can never hide an unmet hard requirement.
- **Experience**: overlapping roles are merged before years are summed. Unusable dates give `unknown`, not `not_met`.

### Workflow and onboarding

Pipeline stages are `new → screening → interview → offer → onboarding → cleared`. A candidate can also move to `withdrawn` or `not_selected`, and leaving those states requires a reason. Moving forward past an unmet hard requirement requires a recorded **override reason**, because the app supports decisions rather than rejecting anyone automatically. Entering `onboarding` creates the checklist from the organization's template, and doing this twice has no extra effect. Task blockers are derived, not stored. Only a reviewer or admin can complete the final review, and `cleared` requires every task to be closed and every required requirement to be `met`.

### Security and tenancy

- **AuthN**: passwords are hashed with PBKDF2-SHA256. The session is an HS256 JWT in an `httpOnly`, `SameSite=Lax` cookie, and the role is re-read from the DB on every request. Login is rate-limited and returns generic errors.
- **AuthZ**: a role → permission matrix enforces separation of duties. Recruiters run the pipeline. Reviewers accept evidence, verify credentials and complete the final review.
- **Tenancy**: every query is scoped by `organization_id`. A request for another organization's id returns 404.
- **Uploads**: an extension allow-list plus magic-byte checks, random storage names, a path-containment check, and downloads served as `attachment` + `nosniff`.
- **Privacy**: PII is redacted before any provider call. Logs are structured JSON that carry ids, counts and durations, never document text. `audit_events` is append-only.

### Data model

```mermaid
erDiagram
  organizations ||--o{ users : has
  organizations ||--o{ job_roles : defines
  organizations ||--o{ candidates : owns
  organizations ||--o{ onboarding_template_tasks : configures
  organizations ||--o{ audit_events : records
  job_roles ||--o{ job_requirements : "typed, weighted"
  job_roles |o--o{ candidates : "assigned to"
  candidates ||--o{ documents : uploads
  documents ||--|| processing_jobs : "one job"
  documents |o--o{ credentials : "source of (also other claims)"
  candidates ||--o{ credentials : ""
  candidates ||--o{ experiences : ""
  candidates ||--o{ qualifications : ""
  candidates ||--o{ skills : ""
  candidates ||--o{ candidate_notes : ""
  candidates ||--o{ onboarding_tasks : ""
```

Credentials, experiences, qualifications and skills share a claim mixin. Each row stores its source document, evidence quote, `source` (machine or manual) and `review_state`, and credentials also store `verification_status` and method. Status is never a column. It is always derived.

### Frontend

The frontend uses the Next.js App Router. Pages live in `src/app/(app)/` behind a session-aware shell, and `/login` is outside it. Data is fetched with SWR through a small typed client (`src/lib/api.ts`, `src/lib/types.ts`). Filters are synced to the URL, so dashboard tiles link to exact filtered lists. Every control is backed by a server-side permission check, and the UI only hides actions a role can't perform.

### Deployment and scaling path

| Today (demo) | When it grows |
|---|---|
| SQLite file, single writer | PostgreSQL (`docker compose up -d db`, same Alembic migration) |
| In-process worker thread polling `processing_jobs` | RQ/Celery consumer calling `process_job(job_id)`. Claim and lease semantics already live in the table |
| Readiness computed on read | Materialized readiness row refreshed in the same transaction as any change, plus a nightly job for date-driven transitions |
| In-process login rate limiter | Redis or API-gateway rate limiting across replicas |

More detail, including the full job state machine, status-precedence diagram and workflow state diagram, is in **[ARCHITECTURE.md](ARCHITECTURE.md)**. **[DECISIONS.md](DECISIONS.md)** records every significant choice and the alternatives that were rejected. **[PLAN.md](PLAN.md)** covers phases and status.

### Technology choices

| Choice | Why |
|---|---|
| **FastAPI + Pydantic v2** | Strict request/response contracts; the same validation library guards untrusted model output |
| **SQLAlchemy 2 + Alembic** | Portable schema with CHECK/UNIQUE constraints; runs on SQLite with zero setup and on PostgreSQL |
| **DB-backed job table + in-process worker** (no Redis/Celery) | Background processing, bounded retries, leases and manual retry without extra infrastructure at demo scale (ADR-003) |
| **`openai/gpt-oss-120b` on Groq, strict JSON-schema output** | Fast, low-cost open-weight model; the schema is generated from the Pydantic model and the output is still re-validated and grounded (ADR-019) |
| **Next.js (App Router) + Tailwind + SWR** | Fast, typed UI; the rewrite proxy keeps the session cookie first-party and httpOnly |
| **No component library** | ~15 small accessible primitives (`components/ui.tsx`) instead of a dependency tree |

## Configuration

Backend variables (prefix `HF_`) are documented in [`backend/.env.example`](backend/.env.example) — copy it to `backend/.env`. The important ones:

| Variable | Default | Meaning |
|---|---|---|
| `HF_DATABASE_URL` | SQLite file in `backend/data/` | e.g. `postgresql+psycopg://healthforce:healthforce@localhost:5432/healthforce` |
| `HF_JWT_SECRET` | dev-only value | **Must** be set in production (the app refuses to start otherwise) |
| `HF_EXTRACTION_PROVIDER` | `mock` | `groq` to use gpt-oss-120b on Groq |
| `GROQ_API_KEY` | — | Required for `groq` (also accepted as `HF_GROQ_API_KEY`); server-side only |
| `HF_GROQ_MODEL` | `openai/gpt-oss-120b` | Any Groq model that supports strict structured outputs |
| `HF_GROQ_REASONING_EFFORT` | `medium` | `low` / `medium` / `high` |
| `HF_VERIFICATION_MODE` | `simulated` | `disabled` removes the simulated verification option |
| `HF_COOKIE_SECURE` | `false` | `true` behind HTTPS |

Frontend: `BACKEND_URL` (default `http://127.0.0.1:8000`) — see [`frontend/.env.example`](frontend/.env.example).

### Using gpt-oss-120b (Groq) for extraction

Create a key at <https://console.groq.com/keys>, then either put it in `backend/.env`:

```bash
HF_EXTRACTION_PROVIDER=groq
GROQ_API_KEY=gsk_...
```

or set it in the shell before starting the backend (PowerShell: `$env:HF_EXTRACTION_PROVIDER="groq"; $env:GROQ_API_KEY="gsk_..."`). Restart the backend; newly uploaded documents are then extracted by gpt-oss-120b, and **Re-extract** on an existing document re-runs it with the new provider (reviewed items are kept). The key never reaches the browser and is never logged.

What is sent: only the document text, with emails, phone numbers, SSN-like numbers and street addresses replaced by placeholders, inside delimiters marking it as untrusted data. The system prompt forbids following instructions in the document, inferring values or judging validity. The request uses strict JSON-schema structured output generated from the pipeline's own Pydantic model. Provider errors are classified: rate limits/timeouts/5xx and schema-validation failures retry with backoff (max 3 attempts); auth errors, other bad requests, truncation and a missing key fail permanently with a clear message. **The live Groq API has not been called in this environment (no key available)** — the provider is tested with a fake client (request shape, schema strictness, every error class, grounding of its output).

### Database & migrations

```bash
cd backend
python -m alembic upgrade head          # create/upgrade schema (the seed also does this)
python -m app.seed --reset              # drop everything (incl. uploads) and reseed
```

PostgreSQL: `docker compose up -d db`, set `HF_DATABASE_URL` as above, then run the seed. The migration compiles to valid PostgreSQL DDL (verified with `alembic upgrade head --sql`), but **a live PostgreSQL run was not possible here** (Docker daemon not running) — see Known gaps.

## Tests & evaluation

```bash
# Backend: 148 tests — rules, extraction safety, job lifecycle, API/authz/tenancy, workflow
cd backend
python -m pytest
python -m ruff check . && python -m mypy app

# Frontend: 14 tests — real pages rendered against captured API responses
cd frontend
npm test && npm run lint && npm run typecheck && npm run build

# Extraction & rules evaluation (writes backend/eval/results/<provider>.{json,md})
cd backend
python -m eval.run                       # mock provider
python -m eval.run --provider groq       # gpt-oss-120b on Groq (needs GROQ_API_KEY)
```

The 14 scenarios required by the brief map to tests as follows:

| # | Scenario | Test(s) |
|---|---|---|
| 1 | Candidate meeting every requirement | `test_api.py::test_scenario_1_*`, `test_rules_matching.py::test_candidate_meeting_every_requirement` |
| 2 | Missing credential | `test_scenario_2_missing_credential` |
| 3 | Expired credential (even if verified) | `test_scenario_3_expired_credential`, `test_expired_beats_review_and_verification` |
| 4 | Undeterminable expiration | `test_scenario_4_*`, `test_missing_expiration_for_expiring_type_is_unable_to_determine` |
| 5 | Contradictory evidence | `test_scenario_5_contradictory_evidence`, `TestConflicts`, `TestPrecisionAwareConflicts` |
| 6 | Malformed/unsupported upload | `test_rejects_malformed_or_unsupported_uploads`, `test_upload_validation_errors_are_clear`, scanned/corrupt PDF tests |
| 7 | Invalid fields / wrong types in AI output | `test_invalid_item_types_are_dropped_individually`, `test_malformed_top_level_output_is_retryable_failure`, `test_unexpected_status_fields_are_ignored_and_reported` |
| 8 | AI output omitting information | `test_omitted_sections_and_fields_are_explicitly_unknown`, fabricated date/identifier tests |
| 9 | Prompt injection | `test_injection_text_is_detected_and_forces_review`, `test_bulk_accept_skips_flagged_items_and_refuses_injected_documents`, benign-text false-positive tests |
| 10 | Failed extraction + retry | `test_transient_failure_is_retried_with_backoff_then_succeeds`, `test_retries_are_bounded_*`, `test_manual_retry_of_failed_job`, `test_stale_lease_is_reclaimed` |
| 11 | Unauthorized operation | `test_role_permissions_are_enforced_server_side` (6 cases), `test_recruiter_cannot_complete_final_review` |
| 12 | Cross-organization access | `test_other_organization_cannot_read_or_modify_data` |
| 13 | Duplicate submission / repeated processing | `test_duplicate_upload_returns_existing_document`, `test_duplicate_delivery_of_a_job_is_a_no_op`, `test_reprocessing_preserves_human_reviewed_claims` |
| 14 | Strong match with unmet hard requirement | `test_scenario_14_*`, `test_high_score_but_unmet_hard_requirement` |

### Evaluation results (mock provider, actual output of `python -m eval.run`)

Dataset: 12 synthetic documents in formats the seed does not use, 14 credential-status rule cases.

| Metric | Result |
|---|---|
| Credential detection — precision / recall | 1.00 / 1.00 |
| Credential field accuracy when the document states the value | **94.4%** (34/36; 2 conservative misses) |
| Values wrong or inferred when absent ("incorrectly inferred") | **0** |
| Missing-field detection (document states nothing → stored nothing) | 100% |
| Experience entries — recall / precision · date accuracy | 0.89 / 0.89 · 100% |
| Qualifications — precision / recall | 0.83 / 1.00 |
| Skills — precision / recall | 1.00 / 1.00 |
| Evidence quotes located in source | 100% of 53 claims |
| Injection screen (12 docs) | 1 TP, 0 FP, 0 FN |
| Credential-status rule cases | 14/14 |

The five individual errors are listed in `backend/eval/results/mock.md`: two expiration dates refused by design (`exp 6/27` two-digit year; "certified through" phrasing), one experience line where title and employer are comma-joined, and an in-progress degree ("expected 2027") counted as a qualification — it is extracted with a flag asking the reviewer to confirm completion. **Read these numbers with care:** the dataset is tiny and the mock extractor was written alongside these formats, so they are an optimistic bound, not a measure of real-world accuracy. The same harness measures gpt-oss-120b when a Groq key is configured.

### Verification performed for this delivery

- `pytest`: **148 passed**; `ruff check`: clean; `mypy app`: no issues (42 files).
- `vitest`: **14 passed**; `eslint` + `tsc --noEmit`: clean; `next build`: succeeds (12 routes).
- Live end-to-end smoke test through the Next.js proxy against the running backend + background worker: login cookie flags, all 12 pages, upload processed by the worker, duplicate upload, unsupported type (415), attachment/nosniff downloads, cross-tenant 404s, viewer 403, anonymous 401 — **25/25 checks passed**.
- Headless-Chrome screenshots of 11 pages (desktop + 390 px mobile): no console errors, no horizontal overflow after fixes.

## Security considerations

Implemented: server-side role checks with separation of duties; organization scoping on every query (cross-tenant ids → 404); httpOnly SameSite=Lax session cookie; PBKDF2 password hashing; generic, rate-limited login errors; upload allow-list + magic-byte checks + size bound; random storage names with path containment; attachment/nosniff downloads; security headers; structured logs without document content; PII redaction before AI calls; append-only audit log; production refuses the default JWT secret.

Limitations of this demo: no MFA/SSO; the login rate limiter is in-process; no virus scanning of uploads; no encryption at rest beyond the filesystem/DB; no data-retention or deletion workflow; audit log is append-only by API but not tamper-evident; SQLite is single-writer. Not suitable for real candidate or patient data as-is.

## Completed features

Dashboard with live metrics and drill-down tiles · candidate list with search and 7 filters (URL-synced) · candidate profile (overview, credentials, experience & education, documents, onboarding, notes & activity) · job roles with typed requirements editor and ranked, explained matching · upload → background extraction with retries, dedupe and failure visibility · evidence review with source highlighting · accept / correct (with diffs) / reject / bulk-accept-supported · manual credential entry · manual and simulated verification · guarded pipeline with override reasons · configurable onboarding template with rule-gated tasks · notes and review decisions · org-wide activity log · responsive layout and keyboard-accessible controls.

## Known gaps

- PostgreSQL verified only at the DDL level here; run the suite against Postgres in CI before relying on it.
- Groq provider implemented and tested with a fake client, but not yet run against the live API (no key in this environment).
- No OCR: scanned documents fail clearly and must be entered manually.
- Credential, qualification and skill catalogs are fixed in code (`app/domain.py`); no admin UI for them.
- No real primary-source integrations, SSO, notifications, interview scheduling integration, or e-signature paperwork.
- Readiness is computed on read — fine for demo scale; see ARCHITECTURE.md for the scaling path.
- Mock extraction handles the document layouts in this repo well and unfamiliar layouts poorly; that is what the gpt-oss-120b provider is for.

## Repository layout

```
backend/
  app/
    api/            HTTP routers (auth, candidates, review, documents, job roles, onboarding, audit, dashboard)
    rules/          pure credential-status and matching rules
    extraction/     validation, text, redaction, injection screen, providers, grounding pipeline
    services/       evaluation, workflow, documents, processing (worker), serializers, audit
    demo/           synthetic document + PDF generators
    seed.py         demo dataset via the public API
  migrations/       Alembic
  eval/             evaluation dataset, gold labels, runner, results
  tests/            pytest suite
frontend/
  src/app/          pages (dashboard, candidates, documents, jobs, processing, activity, settings, login)
  src/components/   UI primitives, review components, candidate tabs
  src/__tests__/    Vitest page/component tests + captured fixtures
```

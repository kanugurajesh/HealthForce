"""Extraction & rules evaluation on the synthetic dataset.

    python -m eval.run                      # mock provider (offline, deterministic)
    python -m eval.run --provider groq      # gpt-oss-120b on Groq (needs GROQ_API_KEY)

Runs every document through the production pipeline (redaction → injection screen →
provider → validation/grounding) and compares the result with eval/gold.json.
Writes eval/results/<provider>.json and .md. Numbers are computed, never hand-edited.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from app.domain import ReviewState, VerificationMethod, VerificationStatus
from app.extraction.errors import ExtractionError
from app.extraction.pipeline import PlannedClaim, build_plan
from app.extraction.providers import GroqProvider, MockProvider
from app.extraction.text import detect_injection, redact_pii
from app.rules.credentials import CredentialFacts, assess_credential

HERE = Path(__file__).parent
AS_OF = date(2026, 10, 23)
CRED_FIELDS = ("identifier", "jurisdiction", "issue_date", "expiration_date")


def _norm(field: str, value: Any) -> str | None:
    if value is None:
        return None
    if field == "identifier":
        return re.sub(r"[^a-z0-9]", "", str(value).lower())
    if field in ("issue_date", "expiration_date"):
        return value.isoformat() if isinstance(value, date) else str(value)
    return str(value).strip().lower()


def _ym(d: date | None, current: bool) -> str | None:
    return "present" if current else (d.strftime("%Y-%m") if d else None)


def _title_match(a: str, b: str) -> bool:
    ta, tb = set(re.findall(r"[a-z]+", a.lower())), set(re.findall(r"[a-z]+", b.lower()))
    return bool(ta and tb) and len(ta & tb) / max(len(ta), len(tb)) >= 0.6


def score_credentials(gold: list[dict[str, Any]], extracted: list[PlannedClaim], tally: Counter[str], errors: list[str], doc: str) -> None:
    pool = list(extracted)
    for g in gold:
        options = [e for e in pool if e.fields["type_code"] == g["type_code"]]
        if not options:
            tally["cred_fn"] += 1
            errors.append(f"{doc}: missed credential {g['type_code']}")
            continue
        best = max(options, key=lambda e: sum(_norm(f, e.fields.get(f)) == _norm(f, g[f]) for f in CRED_FIELDS))
        pool.remove(best)
        tally["cred_tp"] += 1
        for f in CRED_FIELDS:
            gv, ev = _norm(f, g[f]), _norm(f, best.fields.get(f))
            if gv is not None:
                tally["field_gold_present"] += 1
                if ev == gv:
                    tally["field_correct"] += 1
                elif ev is None:
                    tally["field_missing"] += 1
                    errors.append(f"{doc}: {g['type_code']}.{f} missing (gold {gv})")
                else:
                    tally["field_incorrect"] += 1
                    errors.append(f"{doc}: {g['type_code']}.{f} = {ev} (gold {gv})")
            else:
                tally["field_gold_absent"] += 1
                if ev is None:
                    tally["field_correctly_absent"] += 1
                else:
                    tally["field_inferred"] += 1
                    errors.append(f"{doc}: {g['type_code']}.{f} inferred '{ev}' but document states none")
    gold_types = {g["type_code"] for g in gold}
    for e in pool:
        if e.fields["type_code"] in gold_types:
            tally["cred_duplicate"] += 1
        else:
            tally["cred_fp"] += 1
            errors.append(f"{doc}: spurious credential {e.fields['type_code']} ({e.fields['name']})")


def score_experiences(gold: list[dict[str, Any]], extracted: list[PlannedClaim], tally: Counter[str], errors: list[str], doc: str) -> None:
    pool = list(extracted)
    for g in gold:
        match = next((e for e in pool if _title_match(e.fields["title"], g["title"])), None)
        if not match:
            tally["exp_fn"] += 1
            errors.append(f"{doc}: missed experience '{g['title']}'")
            continue
        pool.remove(match)
        tally["exp_tp"] += 1
        for key, value in (("start", _ym(match.fields["start_date"], False)), ("end", _ym(match.fields["end_date"], match.fields["is_current"]))):
            tally["exp_dates"] += 1
            if value == g[key]:
                tally["exp_dates_correct"] += 1
            else:
                errors.append(f"{doc}: experience '{g['title']}' {key}={value} (gold {g[key]})")
    tally["exp_fp"] += len(pool)
    errors.extend(f"{doc}: spurious experience '{e.fields['title']}'" for e in pool)


def score_codes(kind: str, gold: list[str], extracted: list[PlannedClaim], tally: Counter[str], errors: list[str], doc: str) -> None:
    got = {e.fields["code"] for e in extracted if e.fields["code"] not in ("other", "OTHER")}
    want = set(gold)
    tally[f"{kind}_tp"] += len(got & want)
    tally[f"{kind}_fp"] += len(got - want)
    tally[f"{kind}_fn"] += len(want - got)
    errors.extend(f"{doc}: spurious {kind} {c}" for c in sorted(got - want))
    errors.extend(f"{doc}: missed {kind} {c}" for c in sorted(want - got))


def status_cases(cases: list[dict[str, Any]]) -> tuple[int, int, list[str]]:
    wrong = []
    for case in cases:
        f = case["facts"]
        facts = CredentialFacts(
            id=case["name"],
            type_code=f["type_code"],
            expiration_date=date.fromisoformat(f["expiration_date"]) if f["expiration_date"] else None,
            review_state=ReviewState(f["review_state"]),
            verification_status=VerificationStatus(f["verification_status"]),
            verification_method=VerificationMethod(f["verification_method"]) if f.get("verification_method") else None,
        )
        got = assess_credential(facts, AS_OF).status.value
        if got != case["expected"]:
            wrong.append(f"{case['name']}: got {got}, expected {case['expected']}")
    return len(cases) - len(wrong), len(cases), wrong


def ratio(n: int, d: int) -> float | None:
    return round(n / d, 3) if d else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["mock", "groq"], default="mock")
    args = parser.parse_args()
    provider = MockProvider() if args.provider == "mock" else GroqProvider()
    gold = json.loads((HERE / "gold.json").read_text(encoding="utf-8"))

    tally: Counter[str] = Counter()
    errors: list[str] = []
    started = time.monotonic()
    for name, g in gold["documents"].items():
        text, _ = redact_pii((HERE / "dataset" / name).read_text(encoding="utf-8"))
        signals = detect_injection(text)
        tally["inj_tp" if signals and g["injection"] else "inj_fp" if signals else "inj_fn" if g["injection"] else "inj_tn"] += 1
        try:
            plan = build_plan(provider.extract(text, g["kind"]), text, injection_signals=signals)
        except ExtractionError as exc:
            tally["doc_failures"] += 1
            errors.append(f"{name}: extraction failed ({exc.code})")
            continue
        tally["docs"] += 1
        by_kind = {k: [c for c in plan.claims if c.kind == k] for k in ("credential", "experience", "qualification", "skill")}
        tally["claims"] += len(plan.claims)
        tally["claims_evidence_found"] += sum(1 for c in plan.claims if c.evidence_status.value == "found")
        tally["claims_dropped_unsupported"] += plan.stats["dropped"]
        score_credentials(g["credentials"], by_kind["credential"], tally, errors, name)
        score_experiences(g["experiences"], by_kind["experience"], tally, errors, name)
        score_codes("qual", g["qualifications"], by_kind["qualification"], tally, errors, name)
        score_codes("skill", g["skills"], by_kind["skill"], tally, errors, name)

    ok, total, status_wrong = status_cases(gold["status_cases"])
    t = tally
    compared = t["field_gold_present"] + t["field_gold_absent"]
    metrics = {
        "provider": provider.name,
        "documents": len(gold["documents"]),
        "document_failures": t["doc_failures"],
        "runtime_seconds": round(time.monotonic() - started, 2),
        "credential_detection": {
            "precision": ratio(t["cred_tp"], t["cred_tp"] + t["cred_fp"]),
            "recall": ratio(t["cred_tp"], t["cred_tp"] + t["cred_fn"]),
            "spurious": t["cred_fp"],
            "missed": t["cred_fn"],
            "duplicates": t["cred_duplicate"],
        },
        "credential_fields": {
            "field_accuracy_when_stated": ratio(t["field_correct"], t["field_gold_present"]),
            "stated_values_missed": t["field_missing"],
            "stated_values_wrong": t["field_incorrect"],
            "missing_field_detection": ratio(t["field_correctly_absent"], t["field_gold_absent"]),
            "values_inferred_when_absent": t["field_inferred"],
            "incorrectly_inferred_rate": ratio(t["field_incorrect"] + t["field_inferred"], compared),
        },
        "experience": {
            "recall": ratio(t["exp_tp"], t["exp_tp"] + t["exp_fn"]),
            "precision": ratio(t["exp_tp"], t["exp_tp"] + t["exp_fp"]),
            "date_accuracy": ratio(t["exp_dates_correct"], t["exp_dates"]),
        },
        "qualifications": {"precision": ratio(t["qual_tp"], t["qual_tp"] + t["qual_fp"]), "recall": ratio(t["qual_tp"], t["qual_tp"] + t["qual_fn"])},
        "skills": {"precision": ratio(t["skill_tp"], t["skill_tp"] + t["skill_fp"]), "recall": ratio(t["skill_tp"], t["skill_tp"] + t["skill_fn"])},
        "evidence": {
            "claims": t["claims"],
            "evidence_located_rate": ratio(t["claims_evidence_found"], t["claims"]),
            "unsupported_claims_discarded": t["claims_dropped_unsupported"],
        },
        "injection_screen": {"true_positive": t["inj_tp"], "false_positive": t["inj_fp"], "false_negative": t["inj_fn"], "true_negative": t["inj_tn"]},
        "credential_status_rules": {"correct": ok, "total": total, "accuracy": ratio(ok, total)},
    }
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"{provider.name}.json").write_text(
        json.dumps({"metrics": metrics, "errors": errors, "status_rule_failures": status_wrong}, indent=2), encoding="utf-8"
    )
    md = [
        f"# Evaluation results — provider `{provider.name}`",
        "",
        f"Synthetic dataset: {len(gold['documents'])} documents, {total} status-rule cases. As-of date {AS_OF}.",
        "",
    ]
    for section, values in metrics.items():
        if isinstance(values, dict):
            md.append(f"**{section.replace('_', ' ')}**: " + ", ".join(f"{k.replace('_', ' ')} = {v}" for k, v in values.items()))
            md.append("")
    md += ["## Individual errors", "", *([f"- {e}" for e in errors] or ["- none"]), ""]
    (out_dir / f"{provider.name}.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    print(f"\n{len(errors)} individual errors (see eval/results/{provider.name}.md)")
    for e in errors:
        print("  -", e)


if __name__ == "__main__":
    main()

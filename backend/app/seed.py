"""Create the synthetic demo dataset.

    python -m app.seed            # migrate + seed (no-op if data already exists)
    python -m app.seed --reset    # wipe the database and uploads, then seed

Everything after organizations/users/templates is created through the public HTTP API
(in-process), and every document goes through the real extraction pipeline with the
deterministic mock provider. All dates are relative to today so the scenarios stay valid.
"""

from __future__ import annotations

import argparse
import shutil
from datetime import date, timedelta
from typing import Any

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.clock import today
from app.config import BACKEND_DIR, get_settings
from app.db import SessionLocal
from app.demo import documents as D
from app.demo.pdf import make_pdf
from app.extraction.providers import MockProvider
from app.models import OnboardingTemplateTask, Organization, User
from app.security import hash_password

DEMO_PASSWORD = "demo-password-2026"
T = today()


def days(n: int) -> date:
    return T + timedelta(days=n)


def years_ago(y: float) -> date:
    return T - timedelta(days=int(y * 365.25))


# --------------------------------------------------------------------------- database lifecycle


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def migrate(reset: bool) -> None:
    cfg = alembic_config()
    if reset:
        command.downgrade(cfg, "base")
        shutil.rmtree(get_settings().upload_dir, ignore_errors=True)
    command.upgrade(cfg, "head")


TEMPLATE = [
    ("Review candidate documents", "Confirm every uploaded document is legible and belongs to this candidate.", "manual", "reviewer", 3),
    ("Confirm required qualifications", "Check education and experience against the job requirements.", "manual", "reviewer", 3),
    (
        "Complete credential checks",
        "All required credentials must be reviewed, verified and in date. Blocked automatically until they are.",
        "credential_check",
        "reviewer",
        5,
    ),
    ("Schedule unit manager interview", "Book the pre-start meeting with the hiring unit manager.", "interview", "recruiter", 7),
    (
        "Collect onboarding paperwork",
        "Employment eligibility, tax forms and policy acknowledgements (collected outside this system).",
        "manual",
        "recruiter",
        10,
    ),
    ("Occupational health clearance", "Immunization record review and fit-for-duty confirmation.", "manual", "recruiter", 10),
    ("Final human review", "A reviewer confirms the candidate is cleared to start. Cannot be completed by automation.", "final_review", "reviewer", 14),
]


def create_org(db: Any, name: str, slug: str, users: list[tuple[str, str, str]]) -> Organization:
    org = Organization(name=name, slug=slug)
    db.add(org)
    db.flush()
    pw = hash_password(DEMO_PASSWORD)
    for email, full_name, role in users:
        db.add(User(organization_id=org.id, email=email, full_name=full_name, role=role, password_hash=pw))
    for i, (title, desc, kind, owner, offset) in enumerate(TEMPLATE):
        db.add(OnboardingTemplateTask(organization_id=org.id, title=title, description=desc, kind=kind, owner_role=owner, due_offset_days=offset, position=i))
    return org


# --------------------------------------------------------------------------- API helpers


class Api:
    def __init__(self, app: Any, email: str) -> None:
        self.c = TestClient(app)
        self.call("post", "/api/auth/login", json={"email": email, "password": DEMO_PASSWORD})

    def call(self, method: str, path: str, **kw: Any) -> Any:
        r = getattr(self.c, method)(path, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method.upper()} {path} -> {r.status_code}: {r.text}")
        return r.json() if r.content else None


class Seeder:
    def __init__(self, recruiter: Api, reviewer: Api) -> None:
        self.rec, self.rev = recruiter, reviewer
        self.provider = MockProvider()

    def candidate(self, name: str, headline: str, location: str, job_id: str | None) -> str:
        email = name.lower().replace(" ", ".").replace("á", "a") + "@example.com"
        return self.rec.call("post", "/api/candidates", json={"full_name": name, "headline": headline, "location": location, "email": email, "job_id": job_id})[
            "id"
        ]

    def upload(self, cid: str, filename: str, content: str | bytes, kind: str) -> dict[str, Any]:
        from app.services.processing import run_now

        data = content.encode() if isinstance(content, str) else content
        mime = "application/pdf" if filename.endswith(".pdf") else "text/plain"
        out = self.rec.call("post", f"/api/candidates/{cid}/documents", files={"file": (filename, data, mime)}, data={"kind": kind})
        run_now(out["document"]["job"]["id"], self.provider)
        return out["document"]

    def detail(self, cid: str) -> dict[str, Any]:
        return self.rec.call("get", f"/api/candidates/{cid}")

    def review_all(self, cid: str, skip_types: tuple[str, ...] = ()) -> None:
        d = self.detail(cid)
        for kind in ("experiences", "qualifications", "skills", "credentials"):
            for claim in d[kind]:
                if claim["review_state"] != "unreviewed" or claim["evidence_status"] != "found":
                    continue
                if kind == "credentials" and claim["type_code"] in skip_types:
                    continue
                note = "Checked against the source document." if claim["flags"] else None
                self.rev.call("post", f"/api/claims/{kind}/{claim['id']}/review", json={"action": "accept", "note": note})

    def verify_all(self, cid: str, *, simulated: tuple[str, ...] = (), skip: tuple[str, ...] = ()) -> None:
        for cred in self.detail(cid)["credentials"]:
            if cred["review_state"] not in ("accepted", "corrected") or cred["verification_status"] != "not_started" or cred["type_code"] in skip:
                continue
            if cred["document_id"] is None or (cred["status_reasons"] and any("Self-reported" in r for r in cred["status_reasons"])):
                continue  # verify the credential documents, not resume mentions
            body = (
                {"outcome": "verified", "method": "simulated"}
                if cred["type_code"] in simulated
                else {
                    "outcome": "verified",
                    "method": "manual_primary_source",
                    "reference": f"Primary-source lookup by reviewer on {T:%Y-%m-%d} (synthetic demo reference)",
                }
            )
            self.rev.call("post", f"/api/credentials/{cred['id']}/verification", json=body)

    def move(self, cid: str, *statuses: str, reason: str | None = None) -> None:
        for s in statuses:
            self.rec.call("post", f"/api/candidates/{cid}/status", json={"status": s, "reason": reason})

    def complete_tasks(self, cid: str, *, all_but_final: bool = True, final: bool = False) -> None:
        for t in self.detail(cid)["tasks"]:
            if t["kind"] == "final_review":
                continue
            client = self.rev if t["owner_role"] == "reviewer" else self.rec
            client.call("patch", f"/api/tasks/{t['id']}", json={"status": "done", "notes": "Completed (demo data)."})
        if final:
            task = next(t for t in self.detail(cid)["tasks"] if t["kind"] == "final_review")
            self.rev.call("patch", f"/api/tasks/{task['id']}", json={"status": "done", "notes": "All requirements confirmed."})

    def note(self, cid: str, body: str, decision: str | None = None, reviewer: bool = False) -> None:
        payload = {"kind": "decision" if decision else "note", "decision": decision, "body": body}
        (self.rev if reviewer else self.rec).call("post", f"/api/candidates/{cid}/notes", json=payload)


# --------------------------------------------------------------------------- job roles

ICU_JOB = {
    "title": "ICU Registered Nurse",
    "department": "Critical Care",
    "location": "Columbus, OH",
    "description": "Night-shift RN for a 24-bed medical/surgical ICU. Ventilated and hemodynamically unstable patients.",
    "requirements": [
        {"kind": "credential", "codes": ["RN_LICENSE"], "is_required": True, "weight": 5, "min_valid_days": 30},
        {"kind": "credential", "codes": ["BLS"], "is_required": True, "weight": 3},
        {"kind": "credential", "codes": ["ACLS"], "is_required": True, "weight": 3},
        {"kind": "qualification", "codes": ["BSN", "ADN"], "is_required": True, "weight": 3},
        {"kind": "experience", "min_years": 2, "setting": "acute_care", "is_required": True, "weight": 4},
        {"kind": "credential", "codes": ["CCRN"], "is_required": False, "weight": 2},
        {"kind": "skill", "codes": ["ventilator_management"], "is_required": False, "weight": 2},
        {"kind": "skill", "codes": ["hemodynamic_monitoring"], "is_required": False, "weight": 1},
        {"kind": "skill", "codes": ["epic_ehr"], "is_required": False, "weight": 1},
    ],
}
MEDSURG_JOB = {
    "title": "Medical-Surgical Registered Nurse",
    "department": "Inpatient Nursing",
    "location": "Dayton, OH",
    "description": "Day-shift RN on a 32-bed med-surg unit.",
    "requirements": [
        {"kind": "credential", "codes": ["RN_LICENSE"], "is_required": True, "weight": 5},
        {"kind": "credential", "codes": ["BLS"], "is_required": True, "weight": 3},
        {"kind": "credential", "codes": ["TB_SCREEN"], "is_required": True, "weight": 2},
        {"kind": "qualification", "codes": ["ADN", "BSN"], "is_required": True, "weight": 3},
        {"kind": "experience", "min_years": 1, "setting": "acute_care", "is_required": True, "weight": 3},
        {"kind": "skill", "codes": ["iv_therapy"], "is_required": False, "weight": 1},
        {"kind": "skill", "codes": ["wound_care"], "is_required": False, "weight": 1},
        {"kind": "skill", "codes": ["medication_administration"], "is_required": False, "weight": 1},
    ],
}
CNA_JOB = {
    "title": "Certified Nursing Assistant",
    "department": "Long-Term Care",
    "location": "Columbus, OH",
    "description": "CNA for a skilled nursing unit.",
    "requirements": [
        {"kind": "credential", "codes": ["CNA_CERT"], "is_required": True, "weight": 5},
        {"kind": "credential", "codes": ["BLS"], "is_required": True, "weight": 3},
        {"kind": "qualification", "codes": ["CNA_TRAINING"], "is_required": True, "weight": 2},
        {"kind": "experience", "min_years": 0.5, "setting": "any", "is_required": False, "weight": 2},
        {"kind": "skill", "codes": ["vital_signs"], "is_required": False, "weight": 1},
        {"kind": "skill", "codes": ["adl_assistance"], "is_required": False, "weight": 1},
    ],
}
LPN_JOB = {
    "title": "Clinic LPN",
    "department": "Primary Care",
    "location": "Madison, WI",
    "requirements": [
        {"kind": "credential", "codes": ["LPN_LICENSE", "RN_LICENSE"], "is_required": True, "weight": 5},
        {"kind": "credential", "codes": ["BLS"], "is_required": True, "weight": 3},
        {"kind": "experience", "min_years": 1, "setting": "any", "is_required": True, "weight": 3},
    ],
}


# --------------------------------------------------------------------------- candidate scenarios


def icu_resume(
    name: str,
    *,
    years_icu: float,
    extra_jobs: list[D.Job] | None = None,
    creds: list[str],
    skills: list[str] | None = None,
    degree: str = "Bachelor of Science in Nursing — Ohio Valley University, 2016",
    style: str = "A",
    extra_summary: str = "",
) -> str:
    jobs = [
        D.Job(
            "Staff Nurse, Medical ICU",
            "Riverside General Hospital",
            "Columbus, OH",
            years_ago(years_icu),
            None,
            ["Ventilator management and titration of vasoactive infusions", "Hemodynamic monitoring with arterial lines; documentation in Epic"],
        ),
        *(extra_jobs or []),
    ]
    return D.resume(
        name,
        headline="Critical Care Registered Nurse",
        email=name.split()[0].lower() + "@example.com",
        phone="(614) 555-0100",
        city="Columbus, OH",
        summary=f"Critical care RN with {years_icu:g} years of ICU experience.",
        jobs=jobs,
        education=[degree],
        credentials=creds,
        skills=skills or ["Ventilator management", "Hemodynamic monitoring", "Epic EHR", "Sepsis protocols", "Telemetry"],
        style=style,
        extra_summary=extra_summary,
    )


def full_icu_docs(
    s: Seeder,
    cid: str,
    name: str,
    *,
    rn_no: str,
    bls_exp: date,
    acls_exp: date,
    rn_exp: date | None,
    ccrn: bool = True,
    years_icu: float = 4,
    pdf_license: bool = False,
) -> None:
    creds = [
        f"Registered Nurse, Ohio — License #{rn_no}" + (f", expires {D.mdy(rn_exp)}" if rn_exp else ""),
        f"BLS Provider, exp. {D.mmyyyy(bls_exp)}",
        f"ACLS Provider — expires {D.mmyyyy(acls_exp)}",
    ]
    if ccrn:
        creds.append(f"CCRN (Critical Care Nursing Certification Council), valid through {D.mmyyyy(days(600))}")
    s.upload(cid, f"{name.split()[0]}_resume.txt", icu_resume(name, years_icu=years_icu, creds=creds), "resume")
    record = D.rn_license_record(name=name, state="Ohio", number=rn_no, issued=years_ago(years_icu + 2), expires=rn_exp)
    if pdf_license:
        s.upload(cid, "rn_license_lookup.pdf", make_pdf(record.splitlines()), "credential")
    else:
        s.upload(cid, "rn_license_lookup.txt", record, "credential")
    s.upload(
        cid,
        "bls_card.txt",
        D.life_support_card(kind="BLS", name=name, issued=bls_exp - timedelta(days=730), renew_by=bls_exp, code=f"MRTN-{rn_no[-5:]}-B"),
        "credential",
    )
    s.upload(
        cid,
        "acls_card.txt",
        D.life_support_card(kind="ACLS", name=name, issued=acls_exp - timedelta(days=730), renew_by=acls_exp, code=f"MRTN-{rn_no[-5:]}-A"),
        "credential",
    )
    if ccrn:
        s.upload(cid, "ccrn_certificate.txt", D.ccrn_certificate(name=name, number=f"CC-{rn_no[-5:]}", issued=days(-500), expires=days(600)), "credential")


def seed_northwind(s: Seeder, jobs: dict[str, str]) -> None:
    icu, ms, cna = jobs["icu"], jobs["medsurg"], jobs["cna"]

    # 1. Maya Thompson — everything verified; onboarding with only the final review left.
    cid = s.candidate("Maya Thompson", "ICU RN, 5 yrs critical care", "Columbus, OH", icu)
    full_icu_docs(s, cid, "Maya Thompson", rn_no="RN-48213", bls_exp=days(420), acls_exp=days(330), rn_exp=days(640), years_icu=5, pdf_license=True)
    s.review_all(cid)
    s.verify_all(cid)
    s.move(cid, "screening", "interview")
    s.note(cid, "Strong panel interview; excellent ventilator and CRRT experience.", "advance")
    s.move(cid, "offer", "onboarding")
    s.complete_tasks(cid)

    # 2. Rachel Adams — fully cleared to start.
    cid = s.candidate("Rachel Adams", "ICU RN, CCRN", "Columbus, OH", icu)
    full_icu_docs(s, cid, "Rachel Adams", rn_no="RN-39120", bls_exp=days(500), acls_exp=days(480), rn_exp=days(700), years_icu=6)
    s.review_all(cid)
    s.verify_all(cid)
    s.move(cid, "screening", "interview", "offer", "onboarding")
    s.complete_tasks(cid, final=True)
    s.move(cid, "cleared")

    # 3. Daniel Okafor — no ACLS on file (missing information, not a failure).
    cid = s.candidate("Daniel Okafor", "Step-down RN moving to ICU", "Westerville, OH", icu)
    resume = icu_resume(
        "Daniel Okafor",
        years_icu=2.5,
        style="B",
        degree="Associate Degree in Nursing — Franklin Technical College, 2019",
        creds=[f"Registered Nurse, Ohio — License #RN-55102, expires {D.mdy(days(500))}", f"BLS Provider, exp. {D.mmyyyy(days(380))}"],
        extra_jobs=[
            D.Job(
                "RN, Cardiac Step-Down Unit",
                "Mercy Valley Medical Center",
                "Dayton, OH",
                years_ago(4.5),
                years_ago(2.5),
                ["Telemetry monitoring and IV therapy"],
            )
        ],
    )
    s.upload(cid, "daniel_okafor_resume.txt", resume, "resume")
    s.upload(
        cid,
        "rn_license_lookup.txt",
        D.rn_license_record(name="Daniel Okafor", state="Ohio", number="RN-55102", issued=years_ago(5), expires=days(500)),
        "credential",
    )
    s.upload(
        cid, "bls_card.txt", D.life_support_card(kind="BLS", name="Daniel Okafor", issued=days(-350), renew_by=days(380), code="MRTN-55102-B"), "credential"
    )
    s.review_all(cid)
    s.verify_all(cid)
    s.move(cid, "screening")

    # 4. Priya Raman — BLS card expired.
    cid = s.candidate("Priya Raman", "Med-surg RN", "Dayton, OH", ms)
    resume = D.resume(
        "Priya Raman",
        headline="Medical-Surgical RN",
        email="priya@example.com",
        phone="(937) 555-0111",
        city="Dayton, OH",
        summary="Med-surg RN focused on post-operative care.",
        jobs=[
            D.Job(
                "Registered Nurse, Medical-Surgical Unit",
                "Mercy Valley Medical Center",
                "Dayton, OH",
                years_ago(3),
                None,
                ["Wound care and IV therapy", "Medication administration for 6 patients"],
            )
        ],
        education=["Associate of Science in Nursing — Miami Valley Community College, 2022"],
        credentials=[f"Registered Nurse, Ohio — License #RN-60331, expires {D.mdy(days(300))}", f"BLS Provider, exp. {D.mmyyyy(days(-70))}"],
        skills=["Wound care", "IV therapy", "Medication administration", "Patient education"],
    )
    s.upload(cid, "priya_raman_resume.txt", resume, "resume")
    s.upload(
        cid,
        "rn_license_lookup.txt",
        D.rn_license_record(name="Priya Raman", state="Ohio", number="RN-60331", issued=years_ago(3.2), expires=days(300)),
        "credential",
    )
    s.upload(
        cid, "bls_card_old.txt", D.life_support_card(kind="BLS", name="Priya Raman", issued=days(-800), renew_by=days(-70), code="MRTN-60331-B"), "credential"
    )
    s.upload(cid, "tb_screening.txt", D.tb_screening(name="Priya Raman", read=days(-60), valid_through=days(305)), "credential")
    s.review_all(cid)
    s.verify_all(cid)
    s.move(cid, "screening")

    # 5. Luis Hernández — license record has no expiration date.
    cid = s.candidate("Luis Hernandez", "ICU RN relocating from California", "Columbus, OH", icu)
    s.upload(
        cid,
        "luis_hernandez_resume.txt",
        icu_resume(
            "Luis Hernandez",
            years_icu=3,
            creds=[
                "Registered Nurse (California) — License #RN-77814",
                f"BLS Provider, exp. {D.mmyyyy(days(250))}",
                f"ACLS Provider — expires {D.mmyyyy(days(260))}",
            ],
        ),
        "resume",
    )
    s.upload(
        cid,
        "rn_license_lookup.txt",
        D.rn_license_record(name="Luis Hernandez", state="California", number="RN-77814", issued=years_ago(5), expires=None),
        "credential",
    )
    s.review_all(cid)

    # 6. Grace Liu — resume and license record disagree on the expiration date.
    cid = s.candidate("Grace Liu", "Surgical ICU RN", "Dublin, OH", icu)
    s.upload(
        cid,
        "grace_liu_resume.txt",
        icu_resume(
            "Grace Liu",
            years_icu=4,
            creds=[
                f"Registered Nurse, Ohio — License #RN-71245, expires {D.mdy(days(580))}",
                f"BLS Provider, exp. {D.mmyyyy(days(300))}",
                f"ACLS Provider — expires {D.mmyyyy(days(310))}",
            ],
        ),
        "resume",
    )
    s.upload(
        cid,
        "rn_license_lookup.txt",
        D.rn_license_record(name="Grace Liu", state="Ohio", number="RN-71245", issued=years_ago(6), expires=days(-145)),
        "credential",
    )
    s.review_all(cid)
    s.move(cid, "screening")

    # 7. Samuel Brooks — eligible, but BLS expires within the warning window.
    cid = s.candidate("Samuel Brooks", "Cardiac ICU RN", "Columbus, OH", icu)
    full_icu_docs(s, cid, "Samuel Brooks", rn_no="RN-30876", bls_exp=days(20), acls_exp=days(400), rn_exp=days(520), ccrn=False, years_icu=3)
    s.review_all(cid)
    s.verify_all(cid)
    s.move(cid, "screening", "interview")

    # 8. Aisha Bello — just uploaded; nothing reviewed yet.
    cid = s.candidate("Aisha Bello", "New-graduate RN", "Dayton, OH", ms)
    resume = D.resume(
        "Aisha Bello",
        headline="Registered Nurse",
        email="aisha@example.com",
        phone="(937) 555-0188",
        city="Dayton, OH",
        summary="RN with acute care residency experience.",
        jobs=[
            D.Job(
                "Nurse Resident, Medical-Surgical",
                "Kettering Valley Hospital",
                "Kettering, OH",
                years_ago(1.4),
                None,
                ["Medication administration and wound care", "Patient education at discharge"],
            )
        ],
        education=["Bachelor of Science in Nursing — Wright Valley University, 2025"],
        credentials=[f"Registered Nurse, Ohio — License #RN-81290, expires {D.mdy(days(620))}", f"BLS Provider, exp. {D.mmyyyy(days(600))}"],
        skills=["Medication administration", "Wound care", "Patient education", "Epic EHR"],
        style="B",
    )
    s.upload(cid, "aisha_bello_resume.txt", resume, "resume")
    s.upload(cid, "tb_screening.txt", D.tb_screening(name="Aisha Bello", read=days(-20), valid_through=days(345)), "credential")

    # 9. Tom Becker — strongest on preferences, but his RN license has expired.
    cid = s.candidate("Tom Becker", "ICU RN, 7 yrs, CCRN", "Columbus, OH", icu)
    full_icu_docs(s, cid, "Tom Becker", rn_no="RN-22417", bls_exp=days(300), acls_exp=days(310), rn_exp=days(-12), years_icu=7)
    s.review_all(cid)
    s.verify_all(cid)
    s.move(cid, "screening")
    s.note(cid, "Called candidate: says renewal was submitted last month. Awaiting updated license record.", reviewer=False)

    # 10. Elena Petrova — CNA in onboarding; CNA certification verified in SIMULATED mode.
    cid = s.candidate("Elena Petrova", "Certified Nursing Assistant", "Columbus, OH", cna)
    resume = D.resume(
        "Elena Petrova",
        headline="Certified Nursing Assistant",
        email="elena@example.com",
        phone="(614) 555-0175",
        city="Columbus, OH",
        summary="CNA with skilled nursing experience.",
        jobs=[
            D.Job(
                "Certified Nursing Assistant",
                "Maple Grove Skilled Nursing",
                "Columbus, OH",
                years_ago(2),
                None,
                ["Vital signs and ADL assistance for 10 residents", "Activities of daily living support"],
            )
        ],
        education=["Nurse Aide Training Program — Columbus Community College, 2024"],
        credentials=[f"Certified Nursing Assistant — Registry #CNA-118204, expires {D.mdy(days(400))}", f"BLS Provider, exp. {D.mmyyyy(days(450))}"],
        skills=["Vital signs", "ADL assistance", "Patient transfers"],
    )
    s.upload(cid, "elena_petrova_resume.txt", resume, "resume")
    s.upload(
        cid, "cna_registry.txt", D.cna_registry(name="Elena Petrova", state="Ohio", number="CNA-118204", issued=years_ago(2), expires=days(400)), "credential"
    )
    s.upload(
        cid, "bls_card.txt", D.life_support_card(kind="BLS", name="Elena Petrova", issued=days(-280), renew_by=days(450), code="MRTN-18204-B"), "credential"
    )
    s.review_all(cid)
    s.verify_all(cid, simulated=("CNA_CERT",))
    s.move(cid, "screening", "interview", "offer", "onboarding")
    first_two = s.detail(cid)["tasks"][:2]
    for t in first_two:
        s.rev.call("patch", f"/api/tasks/{t['id']}", json={"status": "done"})

    # 11. Jordan Ellis — resume contains a prompt-injection attempt.
    cid = s.candidate("Jordan Ellis", "Med-surg RN", "Springfield, OH", ms)
    resume = D.resume(
        "Jordan Ellis",
        headline="Registered Nurse",
        email="jordan@example.com",
        phone="(937) 555-0144",
        city="Springfield, OH",
        summary="Med-surg RN.",
        extra_summary=D.INJECTION_TEXT,
        jobs=[D.Job("Registered Nurse, Med-Surg", "Clark County Hospital", "Springfield, OH", years_ago(0.8), None, ["IV therapy"])],
        education=["Associate Degree in Nursing — Clark State College, 2025"],
        credentials=["Registered Nurse, Ohio — verified by state registry", "BLS Provider — current"],
        skills=["IV therapy", "Telemetry"],
    )
    s.upload(cid, "jordan_ellis_resume.txt", resume, "resume")

    # 12. Noah Kim — uploaded a scanned image PDF with no text layer: processing fails.
    cid = s.candidate("Noah Kim", "Nursing assistant", "Columbus, OH", cna)
    s.upload(cid, "scanned_cna_certificate.pdf", make_pdf(None), "credential")

    # 13. Hannah Wright — no job role assigned yet.
    cid = s.candidate("Hannah Wright", "Telemetry RN", "Columbus, OH", None)
    s.upload(
        cid,
        "hannah_wright_resume.txt",
        D.resume(
            "Hannah Wright",
            headline="Telemetry RN",
            email="hannah@example.com",
            phone="(614) 555-0190",
            city="Columbus, OH",
            summary="Telemetry RN.",
            jobs=[D.Job("RN, Progressive Care Telemetry", "Riverside General Hospital", "Columbus, OH", years_ago(2), None, ["Cardiac monitoring"])],
            education=["Bachelor of Science in Nursing — Ohio Valley University, 2022"],
            credentials=[f"Registered Nurse, Ohio — License #RN-90012, expires {D.mdy(days(450))}"],
            skills=["Telemetry", "Epic EHR"],
        ),
        "resume",
    )


def seed_lakeside(s: Seeder, job_id: str) -> None:
    cid = s.candidate("Owen Price", "LPN, primary care", "Madison, WI", job_id)
    s.upload(
        cid,
        "owen_price_resume.txt",
        D.resume(
            "Owen Price",
            headline="Licensed Practical Nurse",
            email="owen@example.com",
            phone="(608) 555-0101",
            city="Madison, WI",
            summary="LPN in outpatient primary care.",
            jobs=[D.Job("LPN, Family Medicine Clinic", "Lakeshore Clinic", "Madison, WI", years_ago(3), None, ["Vital signs, immunizations"])],
            education=["Practical Nursing Diploma — Madison Area Technical School, 2022"],
            credentials=[f"Licensed Practical Nurse, Wisconsin — License #LPN-30419, expires {D.mdy(days(380))}", f"BLS Provider, exp. {D.mmyyyy(days(200))}"],
            skills=["Vital signs", "Patient education"],
        ),
        "resume",
    )
    s.review_all(cid)
    s.candidate("Fatima Noor", "LPN", "Madison, WI", job_id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="drop all data and uploads first")
    args = parser.parse_args()
    migrate(args.reset)

    with SessionLocal() as db:
        if db.query(Organization).count():
            print("Database already contains data; use --reset to recreate the demo dataset.")
            return
        create_org(
            db,
            "Northwind Health (demo)",
            "northwind",
            [
                ("admin@northwind.example", "Avery Admin", "admin"),
                ("recruiter@northwind.example", "Riley Recruiter", "recruiter"),
                ("reviewer@northwind.example", "Casey Reviewer", "reviewer"),
                ("viewer@northwind.example", "Vic Viewer", "viewer"),
            ],
        )
        create_org(
            db,
            "Lakeside Clinics (demo)",
            "lakeside",
            [
                ("recruiter@lakeside.example", "Lee Lakeside", "recruiter"),
                ("reviewer@lakeside.example", "Morgan Lakeside", "reviewer"),
            ],
        )
        db.commit()

    from app.main import create_app

    app = create_app(start_worker=False)
    nw = Seeder(Api(app, "recruiter@northwind.example"), Api(app, "reviewer@northwind.example"))
    jobs = {key: nw.rec.call("post", "/api/job-roles", json=spec)["id"] for key, spec in (("icu", ICU_JOB), ("medsurg", MEDSURG_JOB), ("cna", CNA_JOB))}
    seed_northwind(nw, jobs)
    lk = Seeder(Api(app, "recruiter@lakeside.example"), Api(app, "reviewer@lakeside.example"))
    seed_lakeside(lk, lk.rec.call("post", "/api/job-roles", json=LPN_JOB)["id"])
    print(f"Seeded demo data (as of {T}). Sign in with any demo user, password: {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()

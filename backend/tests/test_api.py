"""End-to-end API behaviour: auth, authorization, tenant isolation, the review workflow and
the required evaluation scenarios, driven through HTTP with real documents."""

from datetime import timedelta

import pytest
from conftest import TODAY, World

from app.demo import documents as D
from app.seed import ICU_JOB


def days(n: int):
    return TODAY + timedelta(days=n)


def years_ago(y: float):
    return TODAY - timedelta(days=int(y * 365.25))


def icu_resume(name: str, creds: list[str], years: float = 4) -> str:
    return D.resume(
        name,
        headline="ICU RN",
        email="x@example.com",
        phone="(614) 555-0100",
        city="Columbus, OH",
        summary="ICU nurse.",
        jobs=[D.Job("Staff Nurse, Medical ICU", "Riverside General Hospital", "Columbus, OH", years_ago(years), None, ["Ventilator management"])],
        education=["Bachelor of Science in Nursing — Ohio Valley University, 2016"],
        credentials=creds,
        skills=["Ventilator management", "Hemodynamic monitoring", "Epic EHR"],
    )


def setup_candidate(w: World, job_id: str, name: str, *, rn_exp=days(600), bls_exp=days(400), acls_exp=days(400), acls=True, ccrn=False, years=4):
    rec = w.recruiter
    cid = rec.ok("post", "/api/candidates", json={"full_name": name, "job_id": job_id})["id"]
    creds = [f"BLS Provider, exp. {D.mmyyyy(bls_exp)}"] + ([f"ACLS Provider — expires {D.mmyyyy(acls_exp)}"] if acls else [])
    rec.upload(cid, "resume.txt", icu_resume(name, creds, years))
    rec.upload(cid, "rn.txt", D.rn_license_record(name=name, state="Ohio", number="RN-10001", issued=years_ago(6), expires=rn_exp), "credential")
    rec.upload(cid, "bls.txt", D.life_support_card(kind="BLS", name=name, issued=bls_exp - timedelta(days=700), renew_by=bls_exp, code="B-1"), "credential")
    if acls:
        rec.upload(
            cid, "acls.txt", D.life_support_card(kind="ACLS", name=name, issued=acls_exp - timedelta(days=700), renew_by=acls_exp, code="A-1"), "credential"
        )
    if ccrn:
        rec.upload(cid, "ccrn.txt", D.ccrn_certificate(name=name, number="CC-1", issued=days(-300), expires=days(700)), "credential")
    return cid


def review_and_verify(w: World, cid: str) -> dict:
    rev = w.reviewer
    d = rev.candidate(cid)
    for kind in ("experiences", "qualifications", "skills", "credentials"):
        for c in d[kind]:
            if c["review_state"] == "unreviewed" and c["evidence_status"] == "found":
                rev.ok("post", f"/api/claims/{kind}/{c['id']}/review", json={"action": "accept", "note": "checked" if c["flags"] else None})
    for c in rev.candidate(cid)["credentials"]:
        if c["document_id"] and c["review_state"] in ("accepted", "corrected") and not any("Self-reported" in r for r in c["status_reasons"]):
            rev.ok(
                "post", f"/api/credentials/{c['id']}/verification", json={"outcome": "verified", "method": "manual_primary_source", "reference": "Board lookup"}
            )
    return rev.candidate(cid)


@pytest.fixture
def icu_job(world: World) -> str:
    return world.recruiter.ok("post", "/api/job-roles", json=ICU_JOB, status=201)["id"]


def req(detail: dict, label_start: str) -> dict:
    return next(r for r in detail["match"]["requirements"] if r["label"].startswith(label_start))


# ======================================================================= auth & authorization


def test_requires_authentication(app):
    from fastapi.testclient import TestClient

    c = TestClient(app)
    r = c.get("/api/candidates")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    assert c.get("/api/candidates", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def test_login_failures_are_generic_and_rate_limited(world, app):
    from fastapi.testclient import TestClient

    c = TestClient(app)
    for _ in range(5):
        r = c.post("/api/auth/login", json={"email": "recruiter@northwind.test", "password": "wrong"})
        assert r.status_code == 401 and r.json()["error"]["message"] == "Incorrect email or password."
    assert c.post("/api/auth/login", json={"email": "nobody@northwind.test", "password": "x"}).status_code == 401
    r = c.post("/api/auth/login", json={"email": "recruiter@northwind.test", "password": "test-password"})
    assert r.status_code == 429


def test_session_cookie_is_httponly(world, app):
    from fastapi.testclient import TestClient

    r = TestClient(app).post("/api/auth/login", json={"email": "viewer@northwind.test", "password": "test-password"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


@pytest.mark.parametrize(
    ("role", "method", "path_fmt", "body"),
    [
        ("viewer", "post", "/api/candidates", {"full_name": "X"}),
        ("viewer", "post", "/api/job-roles", ICU_JOB),
        ("reviewer", "post", "/api/candidates/{cid}/status", {"status": "screening"}),
        ("recruiter", "post", "/api/claims/credentials/{cred}/review", {"action": "accept"}),
        ("recruiter", "post", "/api/credentials/{cred}/verification", {"outcome": "verified", "method": "simulated"}),
        ("recruiter", "put", "/api/onboarding/template", {"tasks": [{"title": "Final", "kind": "final_review"}]}),
    ],
)
def test_role_permissions_are_enforced_server_side(world, icu_job, role, method, path_fmt, body):
    """Scenario 11: unauthorized operations are refused by the API, not just hidden in the UI."""
    cid = setup_candidate(world, icu_job, "Perm Test", acls=False)
    cred = world.recruiter.candidate(cid)["credentials"][0]["id"]
    r = getattr(world.as_(role).client, method)(path_fmt.format(cid=cid, cred=cred), json=body)
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "forbidden"


def test_viewer_cannot_upload(world, icu_job):
    cid = world.recruiter.ok("post", "/api/candidates", json={"full_name": "V"})["id"]
    r = world.as_("viewer").client.post(
        f"/api/candidates/{cid}/documents", files={"file": ("r.txt", b"hello world resume text", "text/plain")}, data={"kind": "resume"}
    )
    assert r.status_code == 403


def test_recruiter_cannot_complete_final_review(world, icu_job):
    cid = setup_candidate(world, icu_job, "Final Review Test")
    review_and_verify(world, cid)
    world.recruiter.ok("post", f"/api/candidates/{cid}/status", json={"status": "screening"})
    for s in ("interview", "offer", "onboarding"):
        world.recruiter.ok("post", f"/api/candidates/{cid}/status", json={"status": s})
    final = next(t for t in world.recruiter.candidate(cid)["tasks"] if t["kind"] == "final_review")
    r = world.recruiter.client.patch(f"/api/tasks/{final['id']}", json={"status": "done"})
    assert r.status_code == 403


# ======================================================================= tenant isolation (scenario 12)


def test_other_organization_cannot_read_or_modify_data(world, icu_job):
    cid = setup_candidate(world, icu_job, "Tenant Test", acls=False)
    detail = world.recruiter.candidate(cid)
    doc_id, cred_id = detail["documents"][0]["id"], detail["credentials"][0]["id"]
    other = world.as_("recruiter", "lakeside")
    other_rev = world.as_("reviewer", "lakeside")

    for path in (
        f"/api/candidates/{cid}",
        f"/api/documents/{doc_id}",
        f"/api/documents/{doc_id}/file",
        f"/api/job-roles/{icu_job}",
        f"/api/candidates/{cid}/activity",
        f"/api/job-roles/{icu_job}/matches",
    ):
        r = other.client.get(path)
        assert r.status_code == 404, path
    assert other.client.patch(f"/api/candidates/{cid}", json={"full_name": "Hijacked"}).status_code == 404
    assert other.client.post(f"/api/documents/{doc_id}/process").status_code == 404
    assert other_rev.client.post(f"/api/claims/credentials/{cred_id}/review", json={"action": "reject", "note": "x"}).status_code == 404
    assert other_rev.client.post(f"/api/credentials/{cred_id}/verification", json={"outcome": "verified", "method": "simulated"}).status_code == 404
    # Cannot attach another org's job to its own candidate either.
    own = other.ok("post", "/api/candidates", json={"full_name": "Own"})["id"]
    assert other.client.patch(f"/api/candidates/{own}", json={"job_id": icu_job}).status_code == 404

    assert other.ok("get", "/api/candidates")["total"] == 1
    assert other.ok("get", "/api/dashboard")["metrics"]["total_candidates"] == 1
    assert all(e["candidate_id"] != cid for e in other.ok("get", "/api/audit"))
    assert world.recruiter.candidate(cid)["full_name"] == "Tenant Test"


# ======================================================================= evaluation scenarios


def test_scenario_1_candidate_meeting_every_requirement(world, icu_job):
    cid = setup_candidate(world, icu_job, "Alex Ready", ccrn=True)
    d = review_and_verify(world, cid)
    assert d["eligibility"] == "meets_all_required"
    assert d["match"]["score"] == 100
    assert d["credential_statuses"] == ["verified"]
    rn = req(d, "Registered Nurse")
    assert rn["outcome"] == "met" and rn["evidence"], "evidence must back a met requirement"


def test_scenario_2_missing_credential(world, icu_job):
    cid = setup_candidate(world, icu_job, "Morgan Missing", acls=False)
    d = review_and_verify(world, cid)
    assert req(d, "Advanced Cardiovascular")["outcome"] == "unknown"
    assert d["eligibility"] == "missing_information"
    assert "missing" in d["credential_statuses"]
    assert any("Advanced Cardiovascular" in a["label"] for a in d["next_actions"])


def test_scenario_3_expired_credential(world, icu_job):
    cid = setup_candidate(world, icu_job, "Evan Expired", bls_exp=days(-40))
    d = review_and_verify(world, cid)
    bls = [c for c in d["credentials"] if c["type_code"] == "BLS" and c["document_id"]]
    assert all(c["status"] == "expired" for c in bls)
    assert any(c["verification_status"] == "verified" for c in bls), "verified-but-expired must still read expired"
    assert req(d, "Basic Life Support")["outcome"] == "not_met"
    assert d["eligibility"] == "requirement_not_met"


def test_scenario_4_expiration_cannot_be_determined(world, icu_job):
    cid = setup_candidate(world, icu_job, "Uma Unknown", rn_exp=None)
    d = review_and_verify(world, cid)
    rn = next(c for c in d["credentials"] if c["type_code"] == "RN_LICENSE")
    assert rn["status"] == "unable_to_determine"
    assert req(d, "Registered Nurse")["outcome"] == "unknown"
    # A reviewer resolves it by entering the date after checking the source.
    world.reviewer.ok("patch", f"/api/claims/credentials/{rn['id']}", json={"expiration_date": str(days(500)), "note": "Board lookup"})
    rn = next(c for c in world.reviewer.candidate(cid)["credentials"] if c["type_code"] == "RN_LICENSE")
    assert rn["status"] == "pending_verification" and rn["review_state"] == "corrected"


def test_scenario_5_contradictory_evidence(world, icu_job):
    rec = world.recruiter
    cid = rec.ok("post", "/api/candidates", json={"full_name": "Casey Conflict", "job_id": icu_job})["id"]
    rec.upload(cid, "resume.txt", icu_resume("Casey Conflict", [f"Registered Nurse, Ohio — License #RN-555, expires {D.mdy(days(600))}"]))
    rec.upload(cid, "rn.txt", D.rn_license_record(name="Casey Conflict", state="Ohio", number="RN-555", issued=years_ago(5), expires=days(-100)), "credential")
    d = review_and_verify(world, cid)
    rns = [c for c in d["credentials"] if c["type_code"] == "RN_LICENSE"]
    assert len(rns) == 2 and all(c["status"] == "unable_to_determine" for c in rns)
    assert req(d, "Registered Nurse")["outcome"] == "unknown"
    # Rejecting the outdated record resolves the conflict deterministically.
    stale = next(c for c in rns if c["expiration_date"] == str(days(600)))
    world.reviewer.ok("post", f"/api/claims/credentials/{stale['id']}/review", json={"action": "reject", "note": "Board record is authoritative"})
    d = world.reviewer.candidate(cid)
    assert req(d, "Registered Nurse")["outcome"] == "not_met"  # the authoritative record is expired


def test_scenario_14_strong_match_with_unmet_hard_requirement(world, icu_job):
    cid = setup_candidate(world, icu_job, "Taylor Strong", rn_exp=days(-5), ccrn=True, years=8)
    d = review_and_verify(world, cid)
    assert d["match"]["score"] >= 70
    assert d["eligibility"] == "requirement_not_met"
    # Ranking puts eligible candidates above it regardless of score.
    ok = setup_candidate(world, icu_job, "Riley Eligible")
    review_and_verify(world, ok)
    ranked = world.recruiter.ok("get", f"/api/job-roles/{icu_job}/matches")["results"]
    names = [r["candidate"]["full_name"] for r in ranked]
    assert names.index("Riley Eligible") < names.index("Taylor Strong")
    # Moving forward requires an explicit, audited override reason — never automatic.
    world.recruiter.ok("post", f"/api/candidates/{cid}/status", json={"status": "screening"})
    r = world.recruiter.client.post(f"/api/candidates/{cid}/status", json={"status": "interview"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "override_reason_required"
    world.recruiter.ok(
        "post", f"/api/candidates/{cid}/status", json={"status": "interview", "reason": "Renewal confirmed by phone; interview while awaiting record"}
    )
    events = world.recruiter.ok("get", f"/api/candidates/{cid}/activity")
    assert any(e["details"].get("override") for e in events if e["action"] == "candidate.status_changed")


# ======================================================================= review workflow


def test_correcting_a_verified_credential_resets_verification(world, icu_job):
    cid = setup_candidate(world, icu_job, "Vera Verified")
    d = review_and_verify(world, cid)
    rn = next(c for c in d["credentials"] if c["type_code"] == "RN_LICENSE")
    assert rn["verification_status"] == "verified"
    world.reviewer.ok("patch", f"/api/claims/credentials/{rn['id']}", json={"identifier": "RN-99999", "note": "typo"})
    rn = next(c for c in world.reviewer.candidate(cid)["credentials"] if c["id"] == rn["id"])
    assert rn["verification_status"] == "not_started" and rn["status"] == "pending_verification"
    event = next(e for e in world.reviewer.ok("get", f"/api/candidates/{cid}/activity") if e["action"] == "claim.corrected")
    assert event["details"]["changes"]["identifier"] == {"from": "RN-10001", "to": "RN-99999"}


def test_verification_requires_review_first_and_reference(world, icu_job):
    cid = setup_candidate(world, icu_job, "Pat Pending", acls=False)
    cred = world.reviewer.candidate(cid)["credentials"][0]
    r = world.reviewer.client.post(f"/api/credentials/{cred['id']}/verification", json={"outcome": "verified", "method": "simulated"})
    assert r.status_code == 409
    r = world.reviewer.client.post(f"/api/credentials/{cred['id']}/verification", json={"outcome": "verified", "method": "manual_primary_source"})
    assert r.status_code == 422


def test_simulated_verification_is_labelled(world, icu_job):
    cid = setup_candidate(world, icu_job, "Sim Label", acls=False)
    rn = next(c for c in world.reviewer.candidate(cid)["credentials"] if c["type_code"] == "RN_LICENSE")
    world.reviewer.ok("post", f"/api/claims/credentials/{rn['id']}/review", json={"action": "accept"})
    world.reviewer.ok("post", f"/api/credentials/{rn['id']}/verification", json={"outcome": "verified", "method": "simulated"})
    rn = next(c for c in world.reviewer.candidate(cid)["credentials"] if c["id"] == rn["id"])
    assert rn["simulated_verification"] is True
    assert "SIMULATED" in rn["verification_reference"]
    assert any("SIMULATED" in r for r in rn["status_reasons"])


def test_accepting_unlocated_evidence_requires_a_note(world, icu_job):
    from app.db import SessionLocal
    from app.models import Credential

    cid = setup_candidate(world, icu_job, "Nina Note", acls=False)
    cred = world.reviewer.candidate(cid)["credentials"][0]
    with SessionLocal() as db:
        db.get(Credential, cred["id"]).evidence_status = "not_found"
        db.commit()
    r = world.reviewer.client.post(f"/api/claims/credentials/{cred['id']}/review", json={"action": "accept"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "note_required"


def test_bulk_accept_skips_flagged_items_and_refuses_injected_documents(world, icu_job):
    rec = world.recruiter
    cid = rec.ok("post", "/api/candidates", json={"full_name": "Ivy Inject", "job_id": icu_job})["id"]
    doc = rec.upload(cid, "resume.txt", icu_resume("Ivy Inject", ["BLS Provider, exp. 04/2027"]) + "\n" + D.INJECTION_TEXT)
    d = rec.candidate(cid)
    assert d["documents"][0]["injection_suspected"] is True
    assert all(c["review_state"] == "unreviewed" for c in d["credentials"])
    r = world.reviewer.client.post(f"/api/documents/{doc['id']}/accept-supported")
    assert r.status_code == 409
    # The injected instruction did not change any status or score.
    assert all(c["verification_status"] == "not_started" for c in d["credentials"])
    assert d["eligibility"] != "meets_all_required"

    clean = rec.upload(cid, "bls.txt", D.life_support_card(kind="BLS", name="Ivy Inject", issued=days(-100), renew_by=days(600), code="B-2"), "credential")
    world.reviewer.ok("post", f"/api/documents/{clean['id']}/accept-supported")
    creds = [c for c in world.reviewer.candidate(cid)["credentials"] if c["document_id"] == clean["id"]]
    assert creds and all(c["review_state"] == "unreviewed" for c in creds if c["flags"])


def test_name_mismatch_is_flagged(world):
    rec = world.recruiter
    cid = rec.ok("post", "/api/candidates", json={"full_name": "Jamie Original"})["id"]
    rec.upload(cid, "bls.txt", D.life_support_card(kind="BLS", name="Someone Else", issued=days(-100), renew_by=days(600), code="B-3"), "credential")
    cred = rec.candidate(cid)["credentials"][0]
    assert any("does not match the candidate" in f for f in cred["flags"])


# ======================================================================= pipeline workflow & onboarding


def test_status_transitions_are_guarded(world, icu_job):
    rec = world.recruiter
    cid = rec.ok("post", "/api/candidates", json={"full_name": "Flow Test"})["id"]
    r = rec.client.post(f"/api/candidates/{cid}/status", json={"status": "offer"})
    assert r.status_code == 409 and "allowed" in r.json()["error"]["details"]
    r = rec.client.post(f"/api/candidates/{cid}/status", json={"status": "withdrawn"})
    assert r.status_code == 422  # reason required
    rec.ok("post", f"/api/candidates/{cid}/status", json={"status": "withdrawn", "reason": "Accepted another offer"})
    assert rec.candidate(cid)["allowed_transitions"] == ["screening"]


def test_onboarding_checklist_blockers_and_clearance(world, icu_job):
    rec, rev = world.recruiter, world.reviewer
    cid = setup_candidate(world, icu_job, "Olive Onboard", acls=False)
    review_and_verify(world, cid)
    for s in ("screening", "interview"):
        rec.ok("post", f"/api/candidates/{cid}/status", json={"status": s})
    for s in ("offer", "onboarding"):
        rec.ok("post", f"/api/candidates/{cid}/status", json={"status": s})
    d = rec.candidate(cid)
    assert len(d["tasks"]) == 7
    # Re-entering onboarding never duplicates tasks.
    check = next(t for t in d["tasks"] if t["kind"] == "credential_check")
    assert check["blockers"] and any("Advanced Cardiovascular" in b for b in check["blockers"])
    r = rev.client.patch(f"/api/tasks/{check['id']}", json={"status": "done"})
    assert r.status_code == 409 and r.json()["error"]["details"]["blockers"]
    r = rec.client.post(f"/api/candidates/{cid}/status", json={"status": "cleared"})
    assert r.status_code == 409

    # Supply the missing credential; blockers clear; finish the checklist; clear the candidate.
    acls = rec.upload(cid, "acls.txt", D.life_support_card(kind="ACLS", name="Olive Onboard", issued=days(-100), renew_by=days(600), code="A-9"), "credential")
    review_and_verify(world, cid)
    for t in rec.candidate(cid)["tasks"]:
        if t["kind"] != "final_review":
            (rev if t["owner_role"] == "reviewer" else rec).ok("patch", f"/api/tasks/{t['id']}", json={"status": "done"})
    final = next(t for t in rec.candidate(cid)["tasks"] if t["kind"] == "final_review")
    assert final["blockers"] == []
    rev.ok("patch", f"/api/tasks/{final['id']}", json={"status": "done"})
    rec.ok("post", f"/api/candidates/{cid}/status", json={"status": "cleared"})
    assert rec.candidate(cid)["status"] == "cleared"
    assert acls["id"]


def test_waiving_requires_reason_and_final_review_cannot_be_waived(world, icu_job):
    rec, rev = world.recruiter, world.reviewer
    cid = setup_candidate(world, icu_job, "Wade Waive")
    review_and_verify(world, cid)
    for s in ("screening", "interview", "offer", "onboarding"):
        rec.ok("post", f"/api/candidates/{cid}/status", json={"status": s})
    tasks = rec.candidate(cid)["tasks"]
    paperwork = next(t for t in tasks if t["title"].startswith("Collect"))
    assert rec.client.patch(f"/api/tasks/{paperwork['id']}", json={"status": "waived"}).status_code == 422
    rec.ok("patch", f"/api/tasks/{paperwork['id']}", json={"status": "waived", "waived_reason": "Transferred from sister facility"})
    final = next(t for t in tasks if t["kind"] == "final_review")
    assert rev.client.patch(f"/api/tasks/{final['id']}", json={"status": "waived", "waived_reason": "x"}).status_code == 409


# ======================================================================= uploads & errors


def test_upload_validation_errors_are_clear(world):
    rec = world.recruiter
    cid = rec.ok("post", "/api/candidates", json={"full_name": "U"})["id"]
    r = rec.client.post(f"/api/candidates/{cid}/documents", files={"file": ("cv.docx", b"PK\x03\x04", "application/octet-stream")}, data={"kind": "resume"})
    assert r.status_code == 415 and "Unsupported file type" in r.json()["error"]["message"]
    big = b"a" * (5 * 1024 * 1024 + 1)
    r = rec.client.post(f"/api/candidates/{cid}/documents", files={"file": ("big.txt", big, "text/plain")}, data={"kind": "resume"})
    assert r.status_code == 413
    r = rec.client.post(f"/api/candidates/{cid}/documents", files={"file": ("x.txt", b"text", "text/plain")}, data={"kind": "passport"})
    assert r.status_code == 422


def test_validation_error_envelope(world):
    r = world.recruiter.client.post("/api/job-roles", json={"title": "X", "requirements": [{"kind": "credential", "codes": ["NOPE"]}]})
    body = r.json()
    assert r.status_code == 422 and body["error"]["code"] == "validation_error" and body["error"]["details"]
    assert body["error"]["request_id"]


def test_dashboard_metrics_reflect_data(world, icu_job):
    setup_candidate(world, icu_job, "Dash One", bls_exp=days(-40))
    review_and_verify(world, setup_candidate(world, icu_job, "Dash Two"))
    m = world.recruiter.ok("get", "/api/dashboard")["metrics"]
    assert m["total_candidates"] == 2
    assert m["awaiting_review"] == 1  # Dash One has unreviewed items
    assert m["credential_issues"] == 1  # Dash One's BLS is expired
    assert m["ready_for_next_step"] == 1  # Dash Two meets all required


def test_candidate_filters(world, icu_job):
    a = setup_candidate(world, icu_job, "Filter Expired", bls_exp=days(-40))
    review_and_verify(world, a)
    b = setup_candidate(world, icu_job, "Filter Missing", acls=False)
    review_and_verify(world, b)
    get = lambda q: {i["full_name"] for i in world.recruiter.ok("get", f"/api/candidates?{q}")["items"]}
    assert get("credential_status=expired") == {"Filter Expired"}
    assert get("credential_status=missing") == {"Filter Missing"}
    assert get("eligibility=requirement_not_met") == {"Filter Expired"}
    assert get("missing_requirements=true") == {"Filter Expired", "Filter Missing"}
    assert get("q=missing") == {"Filter Missing"}
    assert get("review=needs_review") == set()


def test_credential_status_filter_accepts_any_of(world, icu_job):
    a = setup_candidate(world, icu_job, "Any Expired", bls_exp=days(-40))
    review_and_verify(world, a)
    b = setup_candidate(world, icu_job, "Any Missing", acls=False)
    review_and_verify(world, b)
    c = setup_candidate(world, icu_job, "Any Soon", bls_exp=days(15))
    review_and_verify(world, c)
    names = {i["full_name"] for i in world.recruiter.ok("get", "/api/candidates?credential_status=expired,missing")["items"]}
    assert names == {"Any Expired", "Any Missing"}
    names = {i["full_name"] for i in world.recruiter.ok("get", "/api/candidates?credential_status=expiring_soon")["items"]}
    assert names == {"Any Soon"}

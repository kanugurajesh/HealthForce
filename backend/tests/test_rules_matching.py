from datetime import date, timedelta

from app.domain import (
    Eligibility,
    RequirementKind,
    RequirementOutcome,
    ReviewState,
    VerificationMethod,
    VerificationStatus,
)
from app.rules.credentials import CredentialFacts, assess_all
from app.rules.matching import (
    CandidateFacts,
    ClaimFacts,
    ExperienceFacts,
    RequirementSpec,
    evaluate_match,
    merged_years,
)

TODAY = date(2026, 10, 23)
A = ReviewState.ACCEPTED
U = ReviewState.UNREVIEWED

ICU_REQS = [
    RequirementSpec("r-rn", RequirementKind.CREDENTIAL, "RN license", ("RN_LICENSE",), True, 5, min_valid_days=30),
    RequirementSpec("r-bls", RequirementKind.CREDENTIAL, "BLS", ("BLS",), True, 3),
    RequirementSpec("r-acls", RequirementKind.CREDENTIAL, "ACLS", ("ACLS",), True, 3),
    RequirementSpec("r-deg", RequirementKind.QUALIFICATION, "BSN or ADN", ("BSN", "ADN"), True, 3),
    RequirementSpec("r-exp", RequirementKind.EXPERIENCE, "2y acute care", (), True, 4, min_years=2, setting="acute_care"),
    RequirementSpec("r-ccrn", RequirementKind.CREDENTIAL, "CCRN", ("CCRN",), False, 2),
    RequirementSpec("r-vent", RequirementKind.SKILL, "Ventilator mgmt", ("ventilator_management",), False, 1),
]


def credential(id, code, exp_days=400, review=A, ver=VerificationStatus.VERIFIED, **kw):
    return CredentialFacts(
        id=id,
        type_code=code,
        expiration_date=TODAY + timedelta(days=exp_days) if exp_days is not None else None,
        review_state=review,
        verification_status=ver,
        verification_method=VerificationMethod.MANUAL_PRIMARY_SOURCE if ver == VerificationStatus.VERIFIED else None,
        **kw,
    )


def icu_exp(years=4, review=A, settings=("critical_care",), id="e1", current=True):
    return ExperienceFacts(id, "Staff RN, ICU", TODAY - timedelta(days=int(years * 365.25)), None, current, settings, review, "Staff RN — ICU")


def facts(creds, quals=(), skills=(), exps=()):
    return CandidateFacts(creds, assess_all(creds, TODAY), list(quals), list(skills), list(exps))


def full_candidate(**overrides):
    creds = overrides.pop(
        "creds",
        [credential("rn", "RN_LICENSE"), credential("bls", "BLS"), credential("acls", "ACLS"), credential("ccrn", "CCRN")],
    )
    quals = overrides.pop("quals", [ClaimFacts("q1", "BSN", A, "Bachelor of Science in Nursing")])
    skills = overrides.pop("skills", [ClaimFacts("s1", "ventilator_management", A, "ventilator management")])
    exps = overrides.pop("exps", [icu_exp()])
    return facts(creds, quals, skills, exps)


def outcome(result, rid):
    return next(r for r in result.requirements if r.requirement_id == rid).outcome


def test_candidate_meeting_every_requirement():
    r = evaluate_match(ICU_REQS, full_candidate(), TODAY)
    assert r.eligibility == Eligibility.MEETS_ALL_REQUIRED
    assert r.score == 100
    assert r.not_satisfied == r.unknown == r.pending == 0
    assert r.next_actions == []


def test_missing_credential_is_unknown_not_failure():
    c = full_candidate(creds=[credential("rn", "RN_LICENSE"), credential("bls", "BLS")])
    r = evaluate_match(ICU_REQS, c, TODAY)
    assert outcome(r, "r-acls") == RequirementOutcome.UNKNOWN
    assert r.eligibility == Eligibility.MISSING_INFORMATION
    assert any("ACLS" in a.label for a in r.next_actions)


def test_expired_credential_is_not_met():
    c = full_candidate(creds=[credential("rn", "RN_LICENSE"), credential("bls", "BLS", exp_days=-3), credential("acls", "ACLS")])
    r = evaluate_match(ICU_REQS, c, TODAY)
    assert outcome(r, "r-bls") == RequirementOutcome.NOT_MET
    assert r.eligibility == Eligibility.REQUIREMENT_NOT_MET
    assert r.next_actions[0].label.startswith("Request renewed")


def test_undeterminable_expiration_is_unknown():
    c = full_candidate(creds=[credential("rn", "RN_LICENSE", exp_days=None, review=U), credential("bls", "BLS"), credential("acls", "ACLS")])
    r = evaluate_match(ICU_REQS, c, TODAY)
    assert outcome(r, "r-rn") == RequirementOutcome.UNKNOWN
    assert r.eligibility == Eligibility.MISSING_INFORMATION


def test_contradictory_evidence_is_unknown_until_resolved():
    rn_resume = credential("rn1", "RN_LICENSE", exp_days=500, review=U, ver=VerificationStatus.NOT_STARTED)
    rn_doc = credential("rn2", "RN_LICENSE", exp_days=-200, review=U, ver=VerificationStatus.NOT_STARTED, identifier="RN-1")
    c = full_candidate(creds=[rn_resume, rn_doc, credential("bls", "BLS"), credential("acls", "ACLS")])
    r = evaluate_match(ICU_REQS, c, TODAY)
    assert outcome(r, "r-rn") == RequirementOutcome.UNKNOWN
    assert "different expiration date" in next(x for x in r.requirements if x.requirement_id == "r-rn").explanation


def test_high_score_but_unmet_hard_requirement():
    """Strong on preferences, but a required credential is expired: never 'eligible'."""
    c = full_candidate(creds=[credential("rn", "RN_LICENSE", exp_days=-1), credential("bls", "BLS"), credential("acls", "ACLS"), credential("ccrn", "CCRN")])
    r = evaluate_match(ICU_REQS, c, TODAY)
    assert r.score >= 75
    assert r.eligibility == Eligibility.REQUIREMENT_NOT_MET
    assert "RN license" in r.eligibility_explanation


def test_min_valid_days_window():
    c = full_candidate(creds=[credential("rn", "RN_LICENSE", exp_days=10), credential("bls", "BLS"), credential("acls", "ACLS")])
    r = evaluate_match(ICU_REQS, c, TODAY)
    assert outcome(r, "r-rn") == RequirementOutcome.NOT_MET
    assert "30 days" in next(x for x in r.requirements if x.requirement_id == "r-rn").explanation


def test_unreviewed_evidence_is_pending_with_half_credit():
    c = full_candidate(quals=[ClaimFacts("q1", "ADN", U, "Associate Degree in Nursing")])
    r = evaluate_match(ICU_REQS, c, TODAY)
    req = next(x for x in r.requirements if x.requirement_id == "r-deg")
    assert req.outcome == RequirementOutcome.PENDING
    assert req.points_earned == 1.5
    assert r.eligibility == Eligibility.PENDING


def test_rejected_claims_are_ignored():
    c = full_candidate(quals=[ClaimFacts("q1", "BSN", ReviewState.REJECTED)])
    assert outcome(evaluate_match(ICU_REQS, c, TODAY), "r-deg") == RequirementOutcome.UNKNOWN


class TestExperience:
    def test_insufficient_documented_experience_is_not_met(self):
        c = full_candidate(exps=[icu_exp(years=1)])
        r = evaluate_match(ICU_REQS, c, TODAY)
        assert outcome(r, "r-exp") == RequirementOutcome.NOT_MET

    def test_unclassified_roles_make_it_unknown(self):
        c = full_candidate(exps=[icu_exp(years=1), icu_exp(years=3, settings=(), id="e2", current=False)])
        assert outcome(evaluate_match(ICU_REQS, c, TODAY), "r-exp") == RequirementOutcome.UNKNOWN

    def test_undated_role_makes_it_unknown(self):
        undated = ExperienceFacts("e2", "ICU RN", None, None, False, ("critical_care",), A)
        c = full_candidate(exps=[icu_exp(years=1), undated])
        assert outcome(evaluate_match(ICU_REQS, c, TODAY), "r-exp") == RequirementOutcome.UNKNOWN

    def test_no_history_is_unknown(self):
        assert outcome(evaluate_match(ICU_REQS, full_candidate(exps=[]), TODAY), "r-exp") == RequirementOutcome.UNKNOWN

    def test_non_acute_setting_does_not_count(self):
        ltc = ExperienceFacts("e1", "Charge nurse", TODAY - timedelta(days=2000), None, True, ("long_term_care",), A)
        assert outcome(evaluate_match(ICU_REQS, full_candidate(exps=[ltc]), TODAY), "r-exp") == RequirementOutcome.NOT_MET

    def test_overlapping_roles_counted_once(self):
        a, b = date(2020, 1, 1), date(2022, 1, 1)
        assert round(merged_years([(a, b), (date(2021, 1, 1), b)]), 1) == 2.0


def test_score_is_weighted_average():
    # Only preferred skill missing (weight 1) out of total weight 21 -> 20/21
    c = full_candidate(skills=[])
    r = evaluate_match(ICU_REQS, c, TODAY)
    assert r.score == round(100 * 20 / 21)
    assert r.eligibility == Eligibility.MEETS_ALL_REQUIRED


def test_preferred_actions_rank_after_required():
    c = full_candidate(creds=[credential("rn", "RN_LICENSE"), credential("bls", "BLS")], skills=[])
    r = evaluate_match(ICU_REQS, c, TODAY)
    required_ids = {x.id for x in ICU_REQS if x.is_required}
    seen_preferred = False
    for a in r.next_actions:
        if a.requirement_id not in required_ids:
            seen_preferred = True
        else:
            assert not seen_preferred


def test_expiring_soon_required_credential_is_met_with_renewal_action():
    c = full_candidate(creds=[credential("rn", "RN_LICENSE"), credential("bls", "BLS", exp_days=20), credential("acls", "ACLS"), credential("ccrn", "CCRN")])
    r = evaluate_match(ICU_REQS, c, TODAY)
    assert outcome(r, "r-bls") == RequirementOutcome.MET
    assert r.eligibility == Eligibility.MEETS_ALL_REQUIRED
    assert any(a.label.startswith("Request renewal of") and a.requirement_id == "r-bls" for a in r.next_actions)

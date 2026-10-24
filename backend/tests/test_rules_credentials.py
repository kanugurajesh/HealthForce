from datetime import date, timedelta

import pytest

from app.domain import CredentialStatus, ReviewState, VerificationMethod, VerificationStatus
from app.rules.credentials import CredentialFacts, assess_all, assess_credential, best_for_codes, find_conflicts

TODAY = date(2026, 10, 23)
ACCEPTED = ReviewState.ACCEPTED
VERIFIED = VerificationStatus.VERIFIED


def cred(id="c1", type_code="BLS", exp=TODAY + timedelta(days=400), review=ACCEPTED, ver=VERIFIED, **kw):
    return CredentialFacts(
        id=id,
        type_code=type_code,
        expiration_date=exp,
        review_state=review,
        verification_status=ver,
        verification_method=kw.pop("method", VerificationMethod.MANUAL_PRIMARY_SOURCE if ver == VERIFIED else None),
        **kw,
    )


def status(c, **kw):
    return assess_credential(c, TODAY, **kw).status


def test_reviewed_and_verified_is_verified():
    assert status(cred()) == CredentialStatus.VERIFIED


def test_unreviewed_is_pending_review():
    assert status(cred(review=ReviewState.UNREVIEWED, ver=VerificationStatus.NOT_STARTED)) == CredentialStatus.PENDING_REVIEW


def test_reviewed_but_unverified_is_pending_verification():
    assert status(cred(ver=VerificationStatus.NOT_STARTED)) == CredentialStatus.PENDING_VERIFICATION


def test_expired_beats_review_and_verification():
    """A credential previously reviewed and verified must not look ready once expired."""
    a = assess_credential(cred(exp=TODAY - timedelta(days=1)), TODAY)
    assert a.status == CredentialStatus.EXPIRED
    assert "Expired on" in a.reasons[0]


def test_expiration_today_is_still_valid():
    assert status(cred(exp=TODAY)) == CredentialStatus.EXPIRING_SOON


def test_expiring_soon_window_boundaries():
    assert status(cred(exp=TODAY + timedelta(days=60))) == CredentialStatus.EXPIRING_SOON
    assert status(cred(exp=TODAY + timedelta(days=61))) == CredentialStatus.VERIFIED


def test_expiring_soon_flag_set_even_when_pending():
    a = assess_credential(cred(exp=TODAY + timedelta(days=10), review=ReviewState.UNREVIEWED, ver=VerificationStatus.NOT_STARTED), TODAY)
    assert a.status == CredentialStatus.PENDING_REVIEW
    assert a.expiring_soon is True


def test_missing_expiration_for_expiring_type_is_unable_to_determine():
    a = assess_credential(cred(exp=None, review=ReviewState.UNREVIEWED), TODAY)
    assert a.status == CredentialStatus.UNABLE_TO_DETERMINE
    assert "No expiration date" in a.reasons[0]


def test_rejected_beats_everything():
    assert status(cred(review=ReviewState.REJECTED, exp=TODAY - timedelta(days=5))) == CredentialStatus.REJECTED


def test_failed_verification_is_rejected():
    assert status(cred(ver=VerificationStatus.FAILED)) == CredentialStatus.REJECTED


def test_simulated_verification_is_labelled():
    a = assess_credential(cred(method=VerificationMethod.SIMULATED), TODAY)
    assert a.status == CredentialStatus.VERIFIED
    assert a.simulated_verification is True
    assert any("SIMULATED" in r for r in a.reasons)


def test_resume_sourced_credential_is_flagged_as_self_reported():
    a = assess_credential(cred(source_document_kind="resume"), TODAY)
    assert any("Self-reported" in r for r in a.reasons)


class TestConflicts:
    def test_same_identifier_different_expiration_conflicts(self):
        a = cred("a", "RN_LICENSE", exp=date(2027, 5, 31), identifier="RN-48213")
        b = cred("b", "RN_LICENSE", exp=date(2025, 5, 31), identifier="rn 48213", review=ReviewState.UNREVIEWED)
        result = assess_all([a, b], TODAY)
        assert result["a"].status == CredentialStatus.UNABLE_TO_DETERMINE
        assert result["b"].status == CredentialStatus.UNABLE_TO_DETERMINE
        assert result["a"].conflicts_with == ["b"]

    def test_no_identifier_on_one_side_still_conflicts(self):
        """A resume claim without a license number contradicting the license document."""
        a = cred("a", "RN_LICENSE", exp=date(2027, 5, 31))
        b = cred("b", "RN_LICENSE", exp=date(2025, 5, 31), identifier="RN-1")
        assert set(find_conflicts([a, b])) == {"a", "b"}

    def test_renewal_with_different_issue_dates_is_not_a_conflict(self):
        old = cred("old", exp=date(2025, 3, 31), issue_date=date(2023, 3, 1))
        new = cred("new", exp=date(2027, 3, 31), issue_date=date(2025, 3, 1))
        result = assess_all([old, new], TODAY)
        assert result["old"].status == CredentialStatus.EXPIRED
        assert result["new"].status == CredentialStatus.VERIFIED

    def test_rejecting_one_record_resolves_conflict(self):
        a = cred("a", "RN_LICENSE", exp=date(2027, 5, 31))
        b = cred("b", "RN_LICENSE", exp=date(2025, 5, 31), review=ReviewState.REJECTED)
        result = assess_all([a, b], TODAY)
        assert result["a"].status == CredentialStatus.VERIFIED
        assert result["b"].status == CredentialStatus.REJECTED

    def test_same_expiration_is_not_a_conflict(self):
        assert find_conflicts([cred("a"), cred("b")]) == {}


class TestBestForCodes:
    def test_missing_when_no_record(self):
        r = best_for_codes(["ACLS"], [], {})
        assert r.status == CredentialStatus.MISSING

    def test_picks_best_ranked_record(self):
        old = cred("old", exp=date(2025, 3, 31), issue_date=date(2023, 3, 1))
        new = cred("new", exp=date(2027, 3, 31), issue_date=date(2025, 3, 1), review=ReviewState.UNREVIEWED, ver=VerificationStatus.NOT_STARTED)
        assessments = assess_all([old, new], TODAY)
        r = best_for_codes(["BLS"], assessments.values(), {"old": old, "new": new})
        assert r.status == CredentialStatus.PENDING_REVIEW
        assert r.best.credential_id == "new"

    @pytest.mark.parametrize("codes", [["RN_LICENSE", "LPN_LICENSE"], ["LPN_LICENSE", "RN_LICENSE"]])
    def test_any_of_codes(self, codes):
        lpn = cred("lpn", "LPN_LICENSE")
        r = best_for_codes(codes, assess_all([lpn], TODAY).values(), {"lpn": lpn})
        assert r.status == CredentialStatus.VERIFIED


class TestPrecisionAwareConflicts:
    def test_month_precision_is_consistent_with_a_day_in_that_month(self):
        resume = CredentialFacts("r", "CCRN", expiration_date=date(2027, 12, 31), expiration_precision="month")
        cert = CredentialFacts("c", "CCRN", expiration_date=date(2027, 12, 15), identifier="CC-1")
        assert find_conflicts([resume, cert]) == {}

    def test_month_precision_in_a_different_month_conflicts(self):
        resume = CredentialFacts("r", "CCRN", expiration_date=date(2027, 11, 30), expiration_precision="month")
        cert = CredentialFacts("c", "CCRN", expiration_date=date(2027, 12, 15))
        assert set(find_conflicts([resume, cert])) == {"r", "c"}

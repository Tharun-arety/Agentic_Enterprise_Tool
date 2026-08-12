from __future__ import annotations
import hashlib,hmac
from app.domains.backoffice.integration import payload_hash,verify_frappe_signature
from app.evals.runner import run_offline
from app.tools import loader  # noqa: F401
from app.tools.registry import TOOL_REGISTRY
from app.agents.graph import _domain_hints,_ecr_impact_answer
def test_frappe_signature_and_tamper_detection():
    body=b'{"doctype":"Purchase Receipt","name":"PR-1"}'; secret="webhook-secret"; signature=hmac.new(secret.encode(),body,hashlib.sha256).hexdigest()
    assert verify_frappe_signature(body,signature,secret)
    assert not verify_frappe_signature(body+b"x",signature,secret)
def test_payload_hash_is_canonical_and_stable(): assert payload_hash({"b":2,"a":1})==payload_hash({"a":1,"b":2})
def test_every_tool_has_governance_metadata():
    assert TOOL_REGISTRY
    for spec in TOOL_REGISTRY.values():
        assert spec.domain and spec.sensitivity and spec.timeout_seconds>0
        assert (spec.applier is None)==(spec.required_role is None)
def test_offline_eval_thresholds(): assert all(case.passed for case in run_offline())
def test_exact_ecr_impact_uses_one_bounded_domain_and_deterministic_evidence():
    assert _domain_hints("Show ECR-26-002 impact, CCB status, and cost exposure")==["ecm"]
    answer=_ecr_impact_answer({"tool_payloads":[{"tool":"get_change_request","payload":{"number":"ECR-26-002","title":"Magnet corrective release","status":"Converted","quorum":{"verdict":"approved","required_seats":["a","b","c","d"],"voted_seats":["a","b","c","d"],"missing_seats":[]},"latest_assessment":{"findings":{"affected_assemblies":[{"part_number":"ECL-AMR-200"}],"affected_products":[{"part_number":"ECL-SYS-1000"}],"revalidation_required":[{"serial_number":"ECL-M-097","sample_count":5}],"cost_impact":[{"part_number":"ECL-SYS-1000","before":2500,"after":2597.7,"delta":97.7}],"gaps":[]}}}}]})
    assert answer and "approved (4/4 seats voted)" in answer and "Δ EUR +97.70" in answer and "ECL-M-097" in answer


def test_operations_is_a_fallback_not_an_extra_lens():
    """Triage language plus domain language must resolve to the domain.

    "Which change requests are marked urgent?" matches both `ecm` ("change
    request") and `operations` ("urgent"). Running both handed the synthesiser
    two evidence sets, which it blended: lapsed calibration and low stock came
    back described as urgent *change requests*. A question that names a
    domain's vocabulary is answered by that domain.
    """
    assert _domain_hints("Which change requests are marked urgent?") == ["ecm"]
    assert _domain_hints("any pending non-conformances?") == ["qms"]
    assert _domain_hints("which calibration is overdue") == ["assets"]


def test_bare_triage_language_reaches_the_cross_domain_ranking():
    """And a question naming nothing still finds the tool that ranks."""
    for question in ("What is the urgent priority right now?", "Tell me the pending tasks", "what needs attention"):
        assert _domain_hints(question) == ["operations"], question

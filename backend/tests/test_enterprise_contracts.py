from __future__ import annotations
import hashlib,hmac
from app.domains.backoffice.integration import payload_hash,verify_frappe_signature
from app.evals.runner import run_offline
from app.tools import loader  # noqa: F401
from app.tools.registry import TOOL_REGISTRY
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

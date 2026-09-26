from uuid import uuid4
from sqlalchemy import select
from app.database import SessionLocal
from app.models import AuditLog, ComplianceRule
from support import client, new_account


def rule(**changes):
    value = {
        "rule_code": "TEST-" + uuid4().hex[:10].upper(), "title": "Imported quantity check",
        "description": "Structured test rule; not an official legal citation.", "product_category": None,
        "field_name": "net_quantity", "validator_type": "numeric",
        "validator_config": {"min": 0.01, "min_confidence": 0.8}, "severity": "warning",
        "source_document": "Test-only source", "source_reference": None,
        "effective_from": "2026-01-01", "effective_to": None, "version": 1,
        "is_active": True, "verification_status": "PROVISIONAL",
    }
    value.update(changes)
    return value


def test_rule_import_preview_commit_conflict_and_audit():
    admin, inspector = new_account("admin"), new_account()
    item = rule()
    request = {"rules": [item]}
    assert client.post("/admin/rules/import/validate", headers=inspector["headers"], json=request).status_code == 403
    preview = client.post("/admin/rules/import/validate", headers=admin["headers"], json=request)
    assert preview.status_code == 200 and preview.json()["valid"]
    assert preview.json()["rules"][0]["action"] == "CREATE"
    committed = client.post("/admin/rules/import/commit", headers=admin["headers"],
                            json={**request, "preview_digest": preview.json()["preview_digest"]})
    assert committed.status_code == 201 and committed.json()["created"] == 1
    unchanged = client.post("/admin/rules/import/validate", headers=admin["headers"], json=request).json()
    assert unchanged["rules"][0]["action"] == "UNCHANGED"
    conflicting = {"rules": [{**item, "title": "Conflicting title"}]}
    conflict_preview = client.post("/admin/rules/import/validate", headers=admin["headers"], json=conflicting).json()
    assert conflict_preview["valid"] is False and conflict_preview["rules"][0]["action"] == "CONFLICT"
    response = client.post("/admin/rules/import/commit", headers=admin["headers"],
                           json={**conflicting, "preview_digest": conflict_preview["preview_digest"]})
    assert response.status_code == 409
    with SessionLocal() as db:
        stored = db.scalar(select(ComplianceRule).where(ComplianceRule.rule_code == item["rule_code"]))
        assert stored.verification_status == "PROVISIONAL" and stored.is_demo_or_provisional
        assert db.scalar(select(AuditLog).where(AuditLog.action == "admin.rules.imported")) is not None


def test_rule_import_rejects_malformed_and_executable_content():
    admin = new_account("admin")
    bad_values = [
        rule(validator_type="python"),
        rule(effective_from="not-a-date"),
        rule(validator_config={"python_code": "__import__('os')"}),
        rule(validator_type="regex", validator_config={"pattern": ".*"}),
    ]
    for item in bad_values:
        assert client.post("/admin/rules/import/validate", headers=admin["headers"], json={"rules": [item]}).status_code == 422
    duplicate = rule()
    assert client.post("/admin/rules/import/validate", headers=admin["headers"],
                       json={"rules": [duplicate, duplicate]}).status_code == 422


def test_verified_import_requires_external_review_acknowledgement():
    admin = new_account("admin")
    request = {"rules": [rule(verification_status="VERIFIED")]}
    preview = client.post("/admin/rules/import/validate", headers=admin["headers"], json=request).json()
    without_ack = client.post("/admin/rules/import/commit", headers=admin["headers"],
                              json={**request, "preview_digest": preview["preview_digest"]})
    assert without_ack.status_code == 409
    with_ack = client.post("/admin/rules/import/commit", headers=admin["headers"],
                           json={**request, "preview_digest": preview["preview_digest"],
                                 "verified_review_acknowledged": True})
    assert with_ack.status_code == 201

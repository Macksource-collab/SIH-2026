import secrets
from datetime import timedelta
from uuid import uuid4
import jwt
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from app.config import settings
from app.database import SessionLocal, engine, get_db
from app.main import app
from app.models import AuditLog, Inspection, InspectionImage, User, now
from app.security import verify_password
from support import client, new_account, UPLOAD_DIR


def test_registration_validation_duplicate_and_no_role_escalation():
    account = new_account()
    body = {"name": "Test", "email": account["email"].upper(), "password": secrets.token_urlsafe(18)}
    assert client.post("/auth/register", json=body).status_code == 409
    body["email"] = f"{uuid4().hex}@example.com"
    assert client.post("/auth/register", json={**body, "role": "admin"}).status_code == 422
    assert client.post("/auth/register", json={**body, "email": "invalid"}).status_code == 422
    response = client.post("/auth/register", json={**body, "password": "short"})
    assert response.status_code == 422 and "short" not in response.text
    assert client.post("/auth/register", json={**body, "password": "é" * 40}).status_code == 422
    with SessionLocal() as db:
        user = db.get(User, account["id"])
        assert user.password_hash != account["password"]
        assert verify_password(account["password"], user.password_hash)
        assert user.role == "inspector"


def test_login_wrong_password_and_me():
    account = new_account()
    assert client.get("/auth/me", headers=account["headers"]).json()["id"] == account["id"]
    response = client.post("/auth/login", json={"email": account["email"], "password": "incorrect-password"})
    assert response.status_code == 401
    assert "password_hash" not in client.get("/auth/me", headers=account["headers"]).text
    with SessionLocal() as db:
        actions = db.scalars(select(AuditLog.action).where(AuditLog.user_id == account["id"])).all()
        assert "login.failed" in actions and "login.succeeded" in actions


def test_login_rate_limit_and_security_headers():
    account = new_account()
    for _ in range(8):
        response = client.post("/auth/login", json={"email": account["email"], "password": "wrong-password"})
        assert response.status_code == 401
    limited = client.post("/auth/login", json={"email": account["email"], "password": "wrong-password"})
    assert limited.status_code == 429 and "Retry-After" in limited.headers
    health = client.get("/health")
    assert health.headers["X-Content-Type-Options"] == "nosniff"
    assert health.headers["X-Frame-Options"] == "DENY"


def test_protected_endpoints_and_admin_access():
    account = new_account()
    assert client.post("/inspections").status_code == 401
    assert client.post("/inspections/upload").status_code == 401
    for path in ("/auth/me", "/inspections", "/inspections/summary", "/inspections/reports", "/admin/stats", "/admin/users", "/admin/logs", "/admin/inspections", "/admin/reports", "/admin/status"):
        assert client.get(path).status_code == 401
        if path.startswith("/admin"):
            assert client.get(path, headers=account["headers"]).status_code == 403
    assert client.patch(f'/admin/users/{account["id"]}', headers=account["headers"], json={"role": "admin"}).status_code == 403


def test_ownership_and_database_persistence():
    first, second = new_account(), new_account()
    created = client.post("/inspections", headers=first["headers"], json={"product_name": "Rice"}).json()
    path = f'/inspections/{created["inspection_id"]}'
    response = client.post(path + "/images", headers=first["headers"], data={"image_side": "front"}, files={"file": ("../../a.png", b"test-image", "image/png")})
    assert response.status_code == 201
    assert client.get(path, headers=second["headers"]).status_code == 403
    assert client.post(path + "/images", headers=second["headers"], data={"image_side": "back"}, files={"file": ("a.png", b"x", "image/png")}).status_code == 403
    assert client.get("/inspections", headers=second["headers"]).json() == []
    engine.dispose()  # New connections must still find the persisted data.
    assert client.get(path, headers=first["headers"]).json()["images"][0]["file_id"] == response.json()["file_id"]
    with SessionLocal() as db:
        assert db.get(Inspection, created["inspection_id"]).product_name == "Rice"
        assert db.get(InspectionImage, response.json()["file_id"]).file_size == 10


def test_admin_management_stats_audits_and_revocation():
    admin, inspector = new_account("admin"), new_account()
    headers = admin["headers"]
    stats = client.get("/admin/stats", headers=headers).json()
    assert stats["total_users"] >= 2 and stats["active_inspectors"] >= 1
    status = client.get("/admin/status", headers=headers).json()
    assert set(status["components"]) == {"api", "database", "upload_storage", "report_storage", "ocr_worker", "rule_engine"}
    assert status["components"]["database"]["status"] == "ONLINE"
    assert client.get("/admin/inspections", headers=headers).status_code == 200
    assert "password_hash" not in client.get("/admin/users", headers=headers).text
    path = f'/admin/users/{inspector["id"]}'
    assert client.patch(path, headers=headers, json={"is_active": False}).status_code == 200
    assert client.get("/auth/me", headers=inspector["headers"]).status_code == 401
    assert client.post("/auth/login", json={"email": inspector["email"], "password": inspector["password"]}).status_code == 401
    assert client.patch(path, headers=headers, json={"is_active": True}).status_code == 200
    assert client.get("/auth/me", headers=inspector["headers"]).status_code == 401
    assert client.patch(f'/admin/users/{admin["id"]}', headers=headers, json={"is_active": False}).status_code == 409
    assert client.patch(path, headers=headers, json={"password_hash": "bad"}).status_code == 422
    assert client.patch(path, headers=headers, json={"role": None}).status_code == 422
    logs = client.get("/admin/logs?limit=100", headers=headers).json()
    assert any(item["action"] == "user.deactivated" for item in logs)
    assert all("actor_name" in item and "actor_email" in item for item in logs)
    serialized = str(logs)
    assert inspector["password"] not in serialized and "Bearer" not in serialized


def test_expired_forged_and_malformed_tokens():
    account = new_account()
    payload = {"sub": account["id"], "exp": now() - timedelta(seconds=10), "iat": now() - timedelta(minutes=2),
               "nbf": now() - timedelta(minutes=2), "iss": "packsure-api", "aud": "packsure-web", "ver": 0}
    expired = jwt.encode(payload, settings.jwt_secret_key.get_secret_value(), algorithm="HS256")
    for token in (expired, "bad.token.value", jwt.encode({**payload, "exp": now() + timedelta(minutes=5)}, secrets.token_urlsafe(40), algorithm="HS256")):
        assert client.get("/auth/me", headers={"Authorization": "Bearer " + token}).status_code == 401


def test_health_and_database_unavailable():
    healthy = client.get("/health").json()
    assert healthy["status"] == "healthy" and healthy["components"]["database"]["status"] == "ONLINE"
    class UnavailableDB:
        def execute(self, *args, **kwargs):
            raise OperationalError("hidden-query", {}, Exception("secret-connection-string"))
        def rollback(self):
            pass
    app.dependency_overrides[get_db] = lambda: UnavailableDB()
    try:
        response = client.get("/health")
        assert response.status_code == 503
        assert "secret" not in response.text and response.json()["success"] is False
    finally:
        app.dependency_overrides.clear()


def test_real_component_status_degraded_and_healthy(monkeypatch):
    from app.services.ocr import ocr_service
    admin = new_account("admin")
    monkeypatch.setattr(ocr_service, "readiness", lambda: {
        "status": "DEGRADED", "state": "NOT_INITIALIZED", "detail": "Model is not initialized."})
    degraded = client.get("/admin/status", headers=admin["headers"]).json()
    assert degraded["overall_status"] == "DEGRADED"
    assert degraded["components"]["ocr_worker"]["state"] == "NOT_INITIALIZED"
    from scripts.seed_demo_rules import seed_rules
    with SessionLocal() as db:
        seed_rules(db)
    monkeypatch.setattr(ocr_service, "readiness", lambda: {
        "status": "ONLINE", "state": "READY", "detail": "Ready."})
    healthy = client.get("/admin/status", headers=admin["headers"]).json()
    assert healthy["overall_status"] == "ONLINE"
    assert all(item["status"] == "ONLINE" for item in healthy["components"].values())


def test_ocr_readiness_probe_does_not_start_worker(monkeypatch, tmp_path):
    from app.config import settings
    from app.services.ocr import OCRService
    runtime = tmp_path / "python.exe"
    runtime.write_bytes(b"")
    monkeypatch.setattr(settings, "ocr_worker_python", runtime)
    service = OCRService()
    assert service.readiness()["status"] == "DEGRADED"
    assert service.process is None
    monkeypatch.setattr(settings, "ocr_worker_python", tmp_path / "missing.exe")
    assert service.readiness()["status"] == "OFFLINE"


def test_storage_failure_and_rejected_upload_audit(monkeypatch, tmp_path):
    from app import inspections
    account = new_account()
    inspection = client.post("/inspections", headers=account["headers"]).json()["inspection_id"]
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("occupied")
    monkeypatch.setattr(inspections, "UPLOAD_DIR", blocked)
    response = client.post(f"/inspections/{inspection}/images", headers=account["headers"], data={"image_side": "front"}, files={"file": ("a.png", b"image", "image/png")})
    assert response.status_code == 503
    assert str(blocked) not in response.text
    with SessionLocal() as db:
        assert db.scalar(select(InspectionImage).where(InspectionImage.inspection_id == inspection)) is None
        assert db.scalar(select(AuditLog).where(AuditLog.resource_id == inspection, AuditLog.action == "image.upload.rejected")) is not None


def test_legacy_json_preserved_and_not_authoritative():
    account = new_account()
    legacy_id = str(uuid4())
    directory = UPLOAD_DIR / legacy_id
    directory.mkdir()
    manifest = directory / "inspection.json"
    manifest.write_text('{"images": []}')
    assert client.get(f"/inspections/{legacy_id}", headers=account["headers"]).status_code == 404
    assert manifest.read_text() == '{"images": []}'


def test_seed_and_password_reset_clis(monkeypatch):
    from scripts import seed_user, set_password
    import sys
    email = f"{uuid4().hex}@example.com"
    original = secrets.token_urlsafe(18)
    replacement = secrets.token_urlsafe(18)
    monkeypatch.setattr(sys, "argv", ["seed_user", "--name", "CLI Admin", "--email", email, "--role", "admin"])
    monkeypatch.setattr(seed_user, "getpass", lambda prompt: original)
    seed_user.main()
    login = client.post("/auth/login", json={"email": email, "password": original})
    assert login.status_code == 200 and login.json()["user"]["role"] == "admin"
    old_token = login.json()["access_token"]
    monkeypatch.setattr(sys, "argv", ["set_password", "--email", email])
    monkeypatch.setattr(set_password, "getpass", lambda prompt: replacement)
    set_password.main()
    assert client.get("/auth/me", headers={"Authorization": "Bearer " + old_token}).status_code == 401
    assert client.post("/auth/login", json={"email": email, "password": original}).status_code == 401
    assert client.post("/auth/login", json={"email": email, "password": replacement}).status_code == 200

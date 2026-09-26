import secrets
from uuid import uuid4
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.database import SessionLocal
from app.models import User

client = TestClient(app, raise_server_exceptions=False)
UPLOAD_DIR = settings.upload_dir


def new_account(role="inspector"):
    password = secrets.token_urlsafe(16)
    email = f"{uuid4().hex}@example.com"
    response = client.post("/auth/register", json={"name": "Test User", "email": email, "password": password})
    assert response.status_code == 201, response.text
    account = response.json()
    if role == "admin":
        with SessionLocal() as db:
            db.get(User, account["id"]).role = "admin"
            db.commit()
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {**account, "password": password, "headers": {"Authorization": "Bearer " + login.json()["access_token"]}}

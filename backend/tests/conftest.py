"""All tests use a migrated temporary database and uploads folder, never real data."""
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile

_test_directory = tempfile.TemporaryDirectory(prefix="packsure-tests-")
_root = Path(_test_directory.name)
os.environ.update(APP_ENV="test", DATABASE_URL="sqlite:///" + (_root / "test.db").as_posix(),
                  UPLOAD_DIR=str(_root / "uploads"), REPORT_DIR=str(_root / "reports"), JWT_SECRET_KEY=secrets.token_urlsafe(48))
_backend = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_backend))
sys.path.insert(0, str(_backend / "tests"))
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=_backend, check=True)
(_root / "uploads").mkdir()


def pytest_sessionfinish(session, exitstatus):
    from app.database import engine
    engine.dispose()
    _test_directory.cleanup()

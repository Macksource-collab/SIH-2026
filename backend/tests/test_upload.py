"""Original upload scenarios, adapted to authenticated database-backed storage."""
from pathlib import Path
import unittest
from uuid import UUID
from support import client, new_account, UPLOAD_DIR

BACKEND = Path(__file__).resolve().parents[1]
ORIGIN = "http://localhost:5173"
_account = None


def auth_headers():
    global _account
    if _account is None:
        _account = new_account()
    return {**_account["headers"], "Origin": ORIGIN}


def upload(contents=b"", content_type="image/png", filename="sample.png", present=True,
           path="/inspections/upload", side=None):
    response = client.post(path, headers=auth_headers(), data={"image_side": side} if side is not None else {},
                           files={"file": (filename, contents, content_type)} if present else None)
    return response.status_code, response.json(), response.headers


class UploadTests(unittest.TestCase):
    def test_valid_image_and_unsafe_original_filename(self):
        contents = (BACKEND.parent / "frontend/src/assets/hero.png").read_bytes()
        status, result, headers = upload(contents, filename="../../outside.png")
        self.assertEqual(status, 201)
        self.assertTrue(result["success"])
        self.assertEqual(headers["Access-Control-Allow-Origin"], ORIGIN)
        self.assertEqual(str(UUID(result["file_id"])), result["file_id"])
        self.assertEqual(result["filename"], result["file_id"] + ".png")
        saved = UPLOAD_DIR / result["inspection_id"] / result["filename"]
        self.assertEqual(saved.read_bytes(), contents)
        self.assertEqual(result["size"], len(contents))

    def test_invalid_uploads_do_not_create_files(self):
        before = set(UPLOAD_DIR.rglob("*"))
        cases = [({"present": False}, 422),
                 ({"contents": b"plain text", "content_type": "text/plain", "filename": "test.txt"}, 415),
                 ({"contents": b""}, 400),
                 ({"contents": b"x" * (10 * 1024 * 1024 + 1)}, 413)]
        for kwargs, expected in cases:
            with self.subTest(expected=expected):
                status, result, headers = upload(**kwargs)
                self.assertEqual(status, expected)
                self.assertIsInstance(result["detail"], str)
                self.assertEqual(headers["Access-Control-Allow-Origin"], ORIGIN)
        self.assertEqual(set(UPLOAD_DIR.rglob("*")), before)

    def test_existing_endpoints(self):
        self.assertEqual(client.get("/").json(), {"message": "PackSure AI backend is running"})
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")
        self.assertEqual(response.json()["database"], "online")

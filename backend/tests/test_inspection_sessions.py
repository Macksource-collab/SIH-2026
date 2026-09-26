"""Original session scenarios retained; assertions now check database persistence."""
from concurrent.futures import ThreadPoolExecutor
import unittest
from uuid import UUID, uuid4
from sqlalchemy import select
from app.database import SessionLocal
from app.models import Inspection, InspectionImage
from support import client, UPLOAD_DIR
from test_upload import BACKEND, ORIGIN, auth_headers, upload


class InspectionSessionTests(unittest.TestCase):
    def setUp(self):
        response = client.post("/inspections", headers=auth_headers())
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], ORIGIN)
        self.inspection_id = response.json()["inspection_id"]
        self.assertEqual(str(UUID(self.inspection_id)), self.inspection_id)
        self.directory = UPLOAD_DIR / self.inspection_id
        self.path = f"/inspections/{self.inspection_id}/images"
        self.contents = (BACKEND.parent / "frontend/src/assets/hero.png").read_bytes()

    def test_front_back_grouping_and_duplicate(self):
        for side in ("front", "back"):
            status, result, headers = upload(self.contents, side=side, path=self.path, filename="../../outside.png")
            self.assertEqual(status, 201)
            self.assertEqual(result["inspection_id"], self.inspection_id)
            self.assertEqual(result["image_side"], side)
            self.assertEqual(result["filename"], str(UUID(result["file_id"])) + ".png")
            self.assertEqual((self.directory / result["filename"]).read_bytes(), self.contents)
            self.assertEqual(headers["Access-Control-Allow-Origin"], ORIGIN)
        before = set(self.directory.iterdir())
        self.assertEqual(upload(self.contents, side="front", path=self.path)[0], 409)
        self.assertEqual(set(self.directory.iterdir()), before)
        metadata = client.get(f"/inspections/{self.inspection_id}", headers=auth_headers()).json()
        self.assertEqual([image["image_side"] for image in metadata["images"]], ["front", "back"])
        with SessionLocal() as db:
            self.assertIsNotNone(db.get(Inspection, self.inspection_id))
            self.assertEqual(len(db.scalars(select(InspectionImage).where(InspectionImage.inspection_id == self.inspection_id)).all()), 2)
        self.assertFalse((self.directory / "inspection.json").exists())

    def test_validation_and_unissued_ids(self):
        cases = [({"side": "diagonal", "contents": self.contents}, 422),
                 ({"side": "../front", "contents": self.contents}, 422),
                 ({"contents": self.contents}, 422), ({"side": "front", "present": False}, 422),
                 ({"side": "front", "contents": b"text", "content_type": "text/plain"}, 415),
                 ({"side": "front", "contents": b""}, 400),
                 ({"side": "front", "contents": b"x" * (10 * 1024 * 1024 + 1)}, 413)]
        for kwargs, expected in cases:
            with self.subTest(expected=expected):
                status, result, headers = upload(path=self.path, **kwargs)
                self.assertEqual(status, expected)
                self.assertIsInstance(result["detail"], str)
                self.assertEqual(headers["Access-Control-Allow-Origin"], ORIGIN)
        self.assertFalse(self.directory.exists())
        for invalid_id, status in ((str(uuid4()), 404), ("not-a-session", 422)):
            self.assertEqual(upload(self.contents, side="front", path=f"/inspections/{invalid_id}/images")[0], status)
            self.assertFalse((UPLOAD_DIR / invalid_id).exists())

    def test_concurrent_duplicate_side(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: upload(self.contents, side="front", path=self.path)[0], range(2)))
        self.assertEqual(sorted(results), [201, 409])
        self.assertEqual(len(list(self.directory.glob("*.png"))), 1)

    def test_size_boundary(self):
        contents = self.contents + b"\0" * (10 * 1024 * 1024 - len(self.contents))
        status, result, _ = upload(contents, side="bottom", path=self.path)
        self.assertEqual(status, 201)
        self.assertEqual(result["size"], 10 * 1024 * 1024)

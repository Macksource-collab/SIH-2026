"""Lazy persistent PaddleOCR worker with observable readiness and serialized inference."""
import atexit
from datetime import datetime, timezone
import json
import os
from queue import Empty, Queue
import subprocess
from threading import Lock, Thread
import time
from uuid import uuid4
from ..config import BACKEND_DIR, settings


class OCRUnavailable(Exception):
    pass


class OCRService:
    def __init__(self):
        self.process = None
        self.lock = Lock()
        self.responses = Queue()
        self.log = None
        self.state = "NOT_INITIALIZED"
        self.last_error = None
        self.initialized_at = None
        self.initialization_duration_seconds = None

    def close(self, reset_state=True):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            for pipe in (self.process.stdin, self.process.stdout):
                if pipe:
                    pipe.close()
            self.process = None
        if self.log:
            self.log.close()
            self.log = None
        if reset_state:
            self.state = "NOT_INITIALIZED"
            self.last_error = None
            self.initialized_at = None
            self.initialization_duration_seconds = None

    def readiness(self):
        """Report state without starting Python, importing Paddle, or loading a model."""
        if not settings.ocr_worker_python.is_file():
            return {"status": "OFFLINE", "state": "RUNTIME_MISSING",
                    "detail": "The isolated PaddleOCR runtime is not installed."}
        if self.process is not None and self.process.poll() is not None:
            self.process = None
            self.state = "ERROR"
            self.last_error = "OCR worker stopped unexpectedly."
        if self.state == "READY" and self.process is not None:
            result = {"status": "ONLINE", "state": "READY", "detail": "PaddleOCR model is initialized and ready.",
                      "initialized_at": self.initialized_at}
            if self.initialization_duration_seconds is not None:
                result["initialization_duration_seconds"] = self.initialization_duration_seconds
            return result
        if self.state == "ERROR":
            return {"status": "OFFLINE", "state": "ERROR",
                    "detail": self.last_error or "OCR worker initialization failed."}
        return {"status": "DEGRADED", "state": self.state,
                "detail": "OCR runtime is installed; the model has not been initialized yet."}

    def _start(self):
        if not settings.ocr_worker_python.is_file():
            self.state, self.last_error = "ERROR", "The isolated PaddleOCR runtime is not installed."
            raise OCRUnavailable(self.last_error)
        self.close()
        cache = settings.ocr_model_cache_dir
        cache.mkdir(exist_ok=True)
        self.log = (cache / "worker.log").open("a", encoding="utf-8")
        self.responses = Queue()
        self.state = "STARTING"
        self.process = subprocess.Popen([str(settings.ocr_worker_python), "-u", str(BACKEND_DIR / "ocr_worker/worker.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True, encoding="utf-8",
            cwd=BACKEND_DIR, env={**os.environ, "PYTHONIOENCODING": "utf-8", "OCR_MODEL_CACHE_DIR": str(cache)},
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        process, responses = self.process, self.responses

        def read_responses():
            for line in process.stdout:
                try:
                    responses.put(json.loads(line))
                except ValueError:
                    continue
            responses.put({"error": "OCR worker stopped unexpectedly.", "error_code": "WORKER_STOPPED"})

        Thread(target=read_responses, daemon=True).start()

    def _request(self, payload):
        if self.process is None or self.process.poll() is not None:
            self._start()
        request_id = str(uuid4())
        self.process.stdin.write(json.dumps({"id": request_id, **payload}) + "\n")
        self.process.stdin.flush()
        response = self.responses.get(timeout=settings.ocr_timeout_seconds)
        if response.get("id") != request_id:
            raise OCRUnavailable("OCR worker returned an invalid response.")
        if response.get("error"):
            raise OCRUnavailable(response["error"])
        return response

    def warmup(self):
        start = time.monotonic()
        with self.lock:
            try:
                response = self._request({"action": "warmup"})
                duration = round(float(response.get("initialization_duration_seconds", time.monotonic() - start)), 2)
                self.state, self.last_error = "READY", None
                self.initialized_at = datetime.now(timezone.utc).isoformat()
                self.initialization_duration_seconds = duration
                return self.readiness()
            except (OSError, Empty, KeyError, ValueError, OCRUnavailable) as error:
                self.close(reset_state=False)
                self.state = "ERROR"
                self.last_error = "PaddleOCR model could not initialize. Check the OCR environment and model cache."
                raise OCRUnavailable(self.last_error) from error

    def recognize(self, path, width, height):
        with self.lock:
            try:
                response = self._request({"action": "recognize", "path": str(path)})
                if self.state != "READY":
                    self.state, self.last_error = "READY", None
                    self.initialized_at = datetime.now(timezone.utc).isoformat()
                    self.initialization_duration_seconds = round(float(response.get("initialization_duration_seconds", 0)), 2)
                regions = []
                for item in response["texts"]:
                    text = item["text"].strip()[:4000]
                    if not text:
                        continue
                    box = [[round(max(0, min(1, x / width)), 6), round(max(0, min(1, y / height)), 6)] for x, y in item["bounding_box"]]
                    regions.append({"text": text, "confidence": max(0, min(1, item["confidence"])), "bounding_box": box})
                return regions
            except (OSError, Empty, KeyError, ValueError, OCRUnavailable) as error:
                self.close(reset_state=False)
                self.state = "ERROR"
                if isinstance(error, Empty):
                    self.last_error = f"PaddleOCR did not respond within {settings.ocr_timeout_seconds} seconds."
                elif isinstance(error, OCRUnavailable):
                    self.last_error = str(error)
                else:
                    self.last_error = "PaddleOCR worker communication failed."
                raise OCRUnavailable(self.last_error) from error


ocr_service = OCRService()
atexit.register(ocr_service.close)

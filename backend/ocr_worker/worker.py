"""Isolated Python 3.12 worker. stdin/stdout use JSON lines; diagnostics use stderr."""
import contextlib
import json
import os
from pathlib import Path
import sys
import time

base = Path(__file__).resolve().parents[1]
cache = Path(os.environ.get("OCR_MODEL_CACHE_DIR", base / ".ocr-cache"))
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(cache))
os.environ.setdefault("HF_HOME", str(cache / "huggingface"))
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "BOS")
engine = None
initialization_duration = 0.0


def ensure_engine():
    global engine, initialization_duration
    initialized_now = engine is None
    if initialized_now:
        started = time.monotonic()
        from paddleocr import PaddleOCR
        engine = PaddleOCR(lang="en", ocr_version="PP-OCRv4", device="cpu",
                           use_doc_orientation_classify=False, use_doc_unwarping=False,
                           use_textline_orientation=False, enable_mkldnn=False, cpu_threads=4)
        initialization_duration = round(time.monotonic() - started, 2)
    return initialized_now


for line in sys.stdin:
    request = {}
    try:
        request = json.loads(line)
        action = request.get("action", "recognize")
        with contextlib.redirect_stdout(sys.stderr):
            initialized_now = ensure_engine()
            if action == "warmup":
                response = {"id": request["id"], "ready": True}
            elif action == "recognize":
                started = time.monotonic()
                results = list(engine.predict(request["path"]))
                regions = []
                for result in results:
                    for text, score, box in zip(result["rec_texts"], result["rec_scores"], result["rec_polys"]):
                        regions.append({"text": str(text), "confidence": float(score), "bounding_box": box.tolist()})
                response = {"id": request["id"], "texts": regions,
                            "inference_duration_seconds": round(time.monotonic() - started, 2)}
            else:
                raise ValueError("Unsupported OCR worker action.")
        response.update(initialized_now=initialized_now, initialization_duration_seconds=initialization_duration)
        print(json.dumps(response), flush=True)
    except Exception as error:
        phase = "initialization" if engine is None else "inference"
        print(f"OCR worker {phase} failure: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        message = ("PaddleOCR model initialization failed. Check installed OCR packages and model cache."
                   if phase == "initialization" else "PaddleOCR could not process this image.")
        print(json.dumps({"id": request.get("id"), "error": message,
                          "error_code": f"OCR_{phase.upper()}_FAILED"}), flush=True)

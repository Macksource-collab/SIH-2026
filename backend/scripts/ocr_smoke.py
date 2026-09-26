"""Real PaddleOCR smoke test; not used by the fast mocked test suite."""
import json
from pathlib import Path
from app.config import BACKEND_DIR
from app.services.image_processing import prepare_image
from app.services.ocr import ocr_service

folder=BACKEND_DIR / '.ocr-smoke'
folder.mkdir(exist_ok=True)
prepared=prepare_image(BACKEND_DIR / 'tests/fixtures/package_front.png',folder)
try:
    result=ocr_service.recognize(prepared['ocr_path'],prepared['metrics']['width'],prepared['metrics']['height'])
    (folder/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'regions':len(result),'texts':[row['text'] for row in result]}))
    assert any('120' in row['text'] for row in result), 'MRP digits not detected'
finally:
    ocr_service.close()

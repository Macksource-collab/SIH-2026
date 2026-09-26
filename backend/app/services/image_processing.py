"""Conservative, deterministic preprocessing. Metrics are heuristics, not AI grading."""
import hashlib
import warnings
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

PIPELINE_VERSION = "package-ocr-v1"
Image.MAX_IMAGE_PIXELS = 40_000_000


class ImageError(Exception):
    pass


def prepare_image(source: Path, directory: Path):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source) as original:
                if original.width * original.height > 40_000_000:
                    raise ImageError("Image exceeds the safe 40-megapixel decoding limit.")
                if original.format not in {"PNG", "JPEG", "WEBP"}:
                    raise ImageError("Unsupported image encoding.")
                oriented = ImageOps.exif_transpose(original).convert("RGB")
                original_size = list(oriented.size)
                oriented.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
                pixels = np.asarray(oriented)
        gray = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
        brightness = float(gray.mean())
        contrast = float(gray.std())
        blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        height, width = gray.shape
        quality = "GOOD"
        reasons = []
        if min(width, height) < 240 or blur < 65 or brightness < 35 or brightness > 245:
            quality = "LOW_QUALITY"
            reasons.append("Small dimensions, blur, or extreme exposure; manually check text.")
        if min(width, height) < 40 or contrast < 4:
            quality = "UNREADABLE"
            reasons.append("Very small or nearly blank image.")
        # Enhance only low-contrast images. No thresholding or aggressive sharpening.
        enhanced = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8)).apply(gray) if contrast < 40 else gray
        if contrast < 40 and blur > 100:
            enhanced = cv2.bilateralFilter(enhanced, 3, 12, 12)
        directory.mkdir(parents=True, exist_ok=True)
        evidence = directory / "evidence.png"
        ocr_input = directory / "ocr.png"
        oriented.save(evidence)
        if not cv2.imwrite(str(ocr_input), enhanced):
            raise ImageError("Could not prepare the image for OCR.")
        return {"quality": quality, "metrics": {"width": width, "height": height,
                "original_dimensions": original_size, "laplacian_variance": round(blur, 2),
                "brightness": round(brightness, 2), "contrast": round(contrast, 2), "notes": reasons,
                "orientation": "EXIF transpose only; no guessed rotation", "heuristic": True},
                "ocr_path": ocr_input, "evidence_path": evidence,
                "source_hash": hashlib.sha256(source.read_bytes()).hexdigest()}
    except ImageError:
        raise
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, cv2.error):
        raise ImageError("Image cannot be safely decoded or prepared.") from None

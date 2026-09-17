import os

# Limit OpenMP threads to 1 to avoid CPU spinlock and ensure fast OCR
os.environ["OMP_THREAD_LIMIT"] = "1"

from pathlib import Path

import cv2
import numpy as np
import pytesseract

from app.core.errors import DomainError, require

MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB max
ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/jpg"}

# Default tessdata directories to look for
DEFAULT_TESSDATA_PATHS = [
    Path(__file__).resolve().parent.parent.parent.parent / ".local" / "share" / "tessdata",
    Path("/usr/share/tesseract-ocr/5/tessdata"),
    Path("/usr/share/tesseract-ocr/4.00/tessdata"),
    Path("/usr/share/tessdata"),
]


def get_tessdata_dir() -> str | None:
    for p in DEFAULT_TESSDATA_PATHS:
        if p.exists() and (p / "por.traineddata").exists():
            return str(p)
    return None


def validate_image(image_bytes: bytes, mime_type: str | None = None) -> str:
    require(0 < len(image_bytes) <= MAX_IMAGE_BYTES, "Imagem vazia ou maior que 20 MB.")
    is_jpeg = image_bytes.startswith(b"\xff\xd8\xff")
    is_png = image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    is_webp = len(image_bytes) > 12 and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP"
    
    if not (is_jpeg or is_png or is_webp):
        raise DomainError("Formato de imagem inválido. Use JPG, PNG ou WebP.")
        
    if is_jpeg:
        return "image/jpeg"
    if is_png:
        return "image/png"
    return "image/webp"


def preprocess_image(image_bytes: bytes) -> np.ndarray:
    """Preprocess image for optimal Tesseract OCR performance and accuracy."""
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise DomainError("Não foi possível decodificar a imagem.")
    
    h, w = img.shape[:2]
    # Downscale huge images to max width 1400 to speed up OCR while preserving fine text
    if w > 1400:
        scale = 1400.0 / w
        img = cv2.resize(img, (1400, int(h * scale)), interpolation=cv2.INTER_AREA)
    elif w < 600:
        scale = 1000.0 / w
        img = cv2.resize(img, (1000, int(h * scale)), interpolation=cv2.INTER_CUBIC)
        
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return gray


def extract_text_from_image(image_bytes: bytes, mime_type: str | None = None) -> str:
    """Run local Tesseract OCR on image bytes and return extracted text."""
    validate_image(image_bytes, mime_type)
    gray = preprocess_image(image_bytes)
    
    tessdata_dir = get_tessdata_dir()
    config_flags = ["--oem 1", "--psm 6"]
    if tessdata_dir:
        config_flags.insert(0, f"--tessdata-dir {tessdata_dir}")
    
    config = " ".join(config_flags)
    try:
        text = pytesseract.image_to_string(gray, lang="por+eng", config=config)
    except Exception:
        # Fallback to standard config without custom tessdata dir if error
        text = pytesseract.image_to_string(gray, lang="por+eng", config="--psm 6")
        
    return text.strip()

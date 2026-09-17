import os
import re

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
    
    if mime_type and mime_type.split(";")[0].lower() not in ALLOWED_IMAGE_MIMES | {"application/octet-stream"}:
        raise DomainError("Tipo de mídia não é uma imagem compatível.")
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
    require(w >= 100 and h >= 100 and w * h <= 24_000_000, "Dimensões da imagem não são compatíveis.")
    # Downscale huge images to max width 1400 to speed up OCR while preserving fine text
    if w > 1400:
        scale = 1400.0 / w
        img = cv2.resize(img, (1400, int(h * scale)), interpolation=cv2.INTER_AREA)
    elif w < 600:
        scale = 1000.0 / w
        img = cv2.resize(img, (1000, int(h * scale)), interpolation=cv2.INTER_CUBIC)
        
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 10)
    return thresh


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
        text = pytesseract.image_to_string(gray, lang="por+eng", config=config, timeout=25)
    except (pytesseract.TesseractError, RuntimeError, pytesseract.TesseractNotFoundError) as exc:
        raise DomainError("Não consegui ler a imagem com OCR local.", "OCR_FAILED", 503) from exc
        
    # A full screenshot can hide a tiny decimal comma. Re-read only lines
    # where OCR produced a currency token without a separator; accept a
    # correction only when the digits are identical (3417 -> 34,17).
    malformed = re.findall(r"R\$\s*(\d{3,})(?![\d,.])", text)
    if malformed:
        try:
            data = pytesseract.image_to_data(
                gray, lang="por+eng", config=config,
                output_type=pytesseract.Output.DICT, timeout=25,
            )
            groups = {}
            for index, word in enumerate(data["text"]):
                if word.strip():
                    key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
                    groups.setdefault(key, []).append(index)
            repairs = 0
            for indexes in groups.values():
                line = " ".join(data["text"][i] for i in indexes)
                bad = re.search(r"R\$\s*(\d{3,})(?![\d,.])", line)
                if not bad or bad.group(1) not in malformed or repairs >= 5:
                    continue
                top = min(data["top"][i] for i in indexes)
                bottom = max(data["top"][i] + data["height"][i] for i in indexes)
                crop = gray[max(0, top - 8):min(gray.shape[0], bottom + 12), :]
                reread = pytesseract.image_to_string(crop, lang="por+eng", config="--psm 7", timeout=10)
                corrected = re.search(r"R\$\s*([\d.]+,\d{2})", reread)
                if corrected and re.sub(r"\D", "", corrected.group(1)) == bad.group(1):
                    pattern = r"R\$\s*" + re.escape(bad.group(1)) + r"(?![\d,.])"
                    text, count = re.subn(pattern, "R$ " + corrected.group(1), text, count=1)
                    repairs += count
        except (pytesseract.TesseractError, RuntimeError, pytesseract.TesseractNotFoundError):
            pass  # The strict money parser will omit ambiguous values.
    return text.strip()

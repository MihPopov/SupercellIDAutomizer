from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple

import pytesseract
import cv2
import numpy as np
from PIL import Image


_TAG_RE = re.compile(r"^#?[A-Z0-9]{3,14}$")


def configure_tesseract(tesseract_cmd: Optional[str]) -> None:
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd


def preprocess_for_ocr(img: Image.Image, *, scale: int = 2) -> Image.Image:
    """
    Improves OCR on game UI by:
    - scaling up
    - grayscale
    - contrast normalization + threshold
    """
    arr = np.array(img.convert("RGB"))
    arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    if scale and scale != 1:
        arr = cv2.resize(arr, (arr.shape[1] * scale, arr.shape[0] * scale), interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 7, 50, 50)
    thr = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 31, 5)
    return Image.fromarray(thr)


def preprocess_for_ocr_variants(img: Image.Image, *, scale: int = 2) -> List[Image.Image]:
    """Build several OCR inputs for noisy/stylized game UI text.

    Brawl Stars member-list text can be colored, outlined, or placed over
    gradients. A single thresholding strategy can miss a visible nickname, so
    callers that need higher recall can OCR all variants and merge results.
    """
    arr = np.array(img.convert("RGB"))
    arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    if scale and scale != 1:
        arr = cv2.resize(arr, (arr.shape[1] * scale, arr.shape[0] * scale), interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
    norm = cv2.equalizeHist(gray)
    denoised = cv2.bilateralFilter(norm, 7, 50, 50)
    adaptive = cv2.adaptiveThreshold(denoised, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 31, 5)
    _otsu_level, otsu = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    inverted = cv2.bitwise_not(otsu)

    return [
        Image.fromarray(denoised),
        Image.fromarray(adaptive),
        Image.fromarray(otsu),
        Image.fromarray(inverted),
    ]


def image_to_text(img: Image.Image, *, lang: str = "rus+eng", scale: int = 2) -> str:
    # PSM 6 = Assume a single uniform block of text.
    pre = preprocess_for_ocr(img, scale=scale)
    try:
        return pytesseract.image_to_string(pre, lang=lang, config="--psm 6").strip()
    except pytesseract.TesseractError:
        return pytesseract.image_to_string(pre, lang="eng", config="--psm 6").strip()


def image_to_words(
    img: Image.Image,
    *,
    lang: str = "rus+eng",
    scale: int = 2,
) -> List[Tuple[str, int, int, int, int]]:
    """
    Returns (text, left, top, width, height) for each OCR token.
    """
    pre = preprocess_for_ocr(img, scale=scale)
    try:
        data = pytesseract.image_to_data(pre, lang=lang, config="--psm 6", output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractError:
        data = pytesseract.image_to_data(pre, lang="eng", config="--psm 6", output_type=pytesseract.Output.DICT)
    out: List[Tuple[str, int, int, int, int]] = []
    for i in range(len(data.get("text", []))):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        l = int(data["left"][i])
        t = int(data["top"][i])
        w = int(data["width"][i])
        h = int(data["height"][i])
        if scale and scale != 1:
            l //= scale
            t //= scale
            w //= scale
            h //= scale
        out.append((text, l, t, w, h))
    return out


def image_to_words_variants(
    img: Image.Image,
    *,
    lang: str = "rus+eng",
    scale: int = 2,
    psms: Tuple[int, ...] = (6, 11),
) -> List[Tuple[str, int, int, int, int]]:
    """OCR words using multiple preprocessors/PSM modes and dedupe boxes."""
    merged: Dict[Tuple[str, int, int, int, int], Tuple[str, int, int, int, int]] = {}
    variants = preprocess_for_ocr_variants(img, scale=scale)
    for pre in variants:
        for psm in psms:
            try:
                data = pytesseract.image_to_data(
                    pre,
                    lang=lang,
                    config=f"--psm {psm}",
                    output_type=pytesseract.Output.DICT,
                )
            except pytesseract.TesseractError:
                data = pytesseract.image_to_data(
                    pre,
                    lang="eng",
                    config=f"--psm {psm}",
                    output_type=pytesseract.Output.DICT,
                )
            for i in range(len(data.get("text", []))):
                text = (data["text"][i] or "").strip()
                if not text:
                    continue
                l = int(data["left"][i])
                t = int(data["top"][i])
                w = int(data["width"][i])
                h = int(data["height"][i])
                if scale and scale != 1:
                    l //= scale
                    t //= scale
                    w //= scale
                    h //= scale
                if w <= 0 or h <= 0:
                    continue
                # Quantize the box to avoid returning the same OCR token many
                # times when two preprocessors produce near-identical results.
                key = (text.casefold(), l // 4, t // 4, w // 4, h // 4)
                merged[key] = (text, l, t, w, h)
    return sorted(merged.values(), key=lambda w: (w[2], w[1]))


def image_to_text_variants(
    img: Image.Image,
    *,
    lang: str = "eng",
    scale: int = 3,
    psms: Tuple[int, ...] = (7, 8, 11),
    whitelist: Optional[str] = None,
) -> List[str]:
    """Return OCR strings from several preprocessors while preserving case."""
    texts: List[str] = []
    config_suffix = f" -c tessedit_char_whitelist={whitelist}" if whitelist else ""
    for pre in preprocess_for_ocr_variants(img, scale=scale):
        for psm in psms:
            config = f"--psm {psm}{config_suffix}"
            try:
                raw = pytesseract.image_to_string(pre, lang=lang, config=config).strip()
            except pytesseract.TesseractError:
                raw = pytesseract.image_to_string(pre, lang="eng", config=config).strip()
            if raw:
                texts.append(raw)
    return texts


def extract_case_sensitive_supercell_id(text: str) -> Optional[str]:
    """Extract the best case-preserving Supercell ID/nameplate token from OCR text."""
    tokens = re.findall(r"#?[A-Za-z0-9]{3,32}", text or "")
    filtered = [t for t in tokens if t.casefold() not in {"id", "supercell", "supercellid"}]
    if not filtered:
        return None

    # Prefer mixed-case Supercell ID/nameplate values, then #tags, then longest token.
    mixed = [t for t in filtered if any(c.islower() for c in t) and any(c.isupper() for c in t)]
    if mixed:
        return max(mixed, key=len)
    tags = [t for t in filtered if t.startswith("#")]
    if tags:
        return max(tags, key=len)
    return max(filtered, key=len)


def find_token_bbox(words: Iterable[Tuple[str, int, int, int, int]], needle: str) -> Optional[Tuple[int, int, int, int]]:
    """
    Finds a bbox for `needle` (case-insensitive) among OCR tokens.
    Returns (left, top, width, height) in the image coordinate space.
    """
    n = needle.strip().lower()
    if not n:
        return None
    for text, left, top, width, height in words:
        if text.strip().lower() == n:
            return (left, top, width, height)
    return None


def extract_supercell_id(text: str) -> Optional[str]:
    # Normalize and try to find something like "ABC123" under nickname.
    candidates = []
    for token in re.split(r"[^#A-Z0-9]+", text.upper()):
        if not token:
            continue
        if _TAG_RE.match(token):
            candidates.append(token)
    if not candidates:
        return None
    # Usually the id is short and unique; take the first.
    return candidates[0]

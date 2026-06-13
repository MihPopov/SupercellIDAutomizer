from __future__ import annotations

import importlib
import importlib.util
import re
from functools import lru_cache
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

import pytesseract
import cv2
import numpy as np
from PIL import Image


_TAG_RE = re.compile(r"^#?[A-Z0-9]{3,14}$")
_DEFAULT_OCR_ENGINE = "tesseract"


def configure_ocr_engine(engine: Optional[str]) -> None:
    global _DEFAULT_OCR_ENGINE
    if engine:
        _DEFAULT_OCR_ENGINE = engine.strip().lower()


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


def _engine_name(engine: Optional[str]) -> str:
    return (engine or _DEFAULT_OCR_ENGINE or "tesseract").strip().lower()


def _wants_paddle(engine: str) -> bool:
    return engine in {"paddle", "paddleocr", "auto"}


def _allows_tesseract(engine: str) -> bool:
    return engine in {"tesseract", "auto"}


def _paddle_missing_packages() -> List[str]:
    missing: List[str] = []
    if importlib.util.find_spec("paddleocr") is None:
        missing.append("paddleocr")
    if importlib.util.find_spec("paddle") is None:
        missing.append("paddlepaddle")
    return missing


def _paddle_install_hint() -> str:
    return (
        "Install the optional Paddle OCR dependencies into the same Python "
        "environment that runs this app: pip install -r requirements-ocr-paddle.txt"
    )


def _ensure_paddle_available(engine: str) -> None:
    missing = _paddle_missing_packages()
    if engine in {"paddle", "paddleocr"} and missing:
        raise RuntimeError(
            f"OCR_ENGINE=paddle requires PaddleOCR and PaddlePaddle; missing: {', '.join(missing)}. "
            f"{_paddle_install_hint()}"
        )


@lru_cache(maxsize=4)
def _paddle_ocr(lang: str):
    if _paddle_missing_packages():
        return None
    paddleocr = importlib.import_module("paddleocr")
    paddle_lang = "en" if lang in {"eng", "en"} else lang
    kwargs = {
        "lang": paddle_lang,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
    }
    try:
        return paddleocr.PaddleOCR(**kwargs)
    except TypeError:
        # Older PaddleOCR releases use different keyword names.
        return paddleocr.PaddleOCR(lang=paddle_lang, use_angle_cls=False)


def _paddle_predict(img: Image.Image, *, lang: str) -> List[Any]:
    ocr = _paddle_ocr(lang)
    if ocr is None:
        return []
    arr = np.array(img.convert("RGB"))
    if hasattr(ocr, "predict"):
        result = ocr.predict(arr)
    else:
        result = ocr.ocr(arr, cls=False)
    if result is None:
        return []
    return result if isinstance(result, list) else [result]


def _walk_paddle_objects(obj: Any) -> Iterator[Any]:
    if obj is None:
        return
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk_paddle_objects(v)
    elif isinstance(obj, (list, tuple)):
        yield obj
        for v in obj:
            yield from _walk_paddle_objects(v)
    elif hasattr(obj, "json"):
        json_value = obj.json
        if callable(json_value):
            json_value = json_value()
        yield from _walk_paddle_objects(json_value)


def _box_from_paddle(value: Any) -> Optional[Tuple[int, int, int, int]]:
    arr = np.array(value)
    if arr.size == 4 and arr.ndim == 1:
        x1, y1, x2, y2 = [int(v) for v in arr.tolist()]
        return (x1, y1, max(1, x2 - x1), max(1, y2 - y1))
    if arr.ndim >= 2 and arr.shape[-1] >= 2:
        xs = arr[..., 0].astype(float)
        ys = arr[..., 1].astype(float)
        x1, y1 = int(xs.min()), int(ys.min())
        x2, y2 = int(xs.max()), int(ys.max())
        return (x1, y1, max(1, x2 - x1), max(1, y2 - y1))
    return None


def _paddle_texts_and_words(img: Image.Image, *, lang: str = "eng") -> Tuple[List[str], List[Tuple[str, int, int, int, int]]]:
    texts: List[str] = []
    words: List[Tuple[str, int, int, int, int]] = []
    result = _paddle_predict(img, lang=lang)

    for obj in _walk_paddle_objects(result):
        if isinstance(obj, dict):
            if "rec_text" in obj and isinstance(obj["rec_text"], str):
                texts.append(obj["rec_text"])
            rec_texts = obj.get("rec_texts")
            if isinstance(rec_texts, list):
                boxes = obj.get("rec_boxes") or obj.get("rec_polys") or obj.get("dt_polys") or []
                for i, text in enumerate(rec_texts):
                    if not isinstance(text, str) or not text.strip():
                        continue
                    texts.append(text)
                    if i < len(boxes):
                        box = _box_from_paddle(boxes[i])
                        if box:
                            words.append((text.strip(), *box))
        elif isinstance(obj, (list, tuple)):
            # PaddleOCR 2.x style: [box, (text, score)]
            if len(obj) >= 2 and isinstance(obj[1], (list, tuple)) and obj[1] and isinstance(obj[1][0], str):
                text = obj[1][0].strip()
                box = _box_from_paddle(obj[0])
                if text:
                    texts.append(text)
                    if box:
                        words.append((text, *box))

    dedup_texts = list(dict.fromkeys(t.strip() for t in texts if t and t.strip()))
    dedup_words: Dict[Tuple[str, int, int, int, int], Tuple[str, int, int, int, int]] = {}
    for text, left, top, width, height in words:
        key = (text.casefold(), left // 4, top // 4, width // 4, height // 4)
        dedup_words[key] = (text, left, top, width, height)
    return dedup_texts, sorted(dedup_words.values(), key=lambda w: (w[2], w[1]))


def image_to_text(img: Image.Image, *, lang: str = "rus+eng", scale: int = 2, engine: Optional[str] = None) -> str:
    engine_name = _engine_name(engine)
    if _wants_paddle(engine_name):
        _ensure_paddle_available(engine_name)
        texts, _words = _paddle_texts_and_words(img, lang=lang)
        if texts or not _allows_tesseract(engine_name):
            return "\n".join(texts).strip()
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
    engine: Optional[str] = None,
) -> List[Tuple[str, int, int, int, int]]:
    """
    Returns (text, left, top, width, height) for each OCR token.
    """
    engine_name = _engine_name(engine)
    if _wants_paddle(engine_name):
        _ensure_paddle_available(engine_name)
        _texts, words = _paddle_texts_and_words(img, lang=lang)
        if words or not _allows_tesseract(engine_name):
            return words
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
    engine: Optional[str] = None,
) -> List[Tuple[str, int, int, int, int]]:
    """OCR words using multiple preprocessors/PSM modes and dedupe boxes."""
    engine_name = _engine_name(engine)
    merged: Dict[Tuple[str, int, int, int, int], Tuple[str, int, int, int, int]] = {}
    if _wants_paddle(engine_name):
        _ensure_paddle_available(engine_name)
        _texts, paddle_words = _paddle_texts_and_words(img, lang=lang)
        for text, l, t, w, h in paddle_words:
            merged[(text.casefold(), l // 4, t // 4, w // 4, h // 4)] = (text, l, t, w, h)
        if paddle_words and not _allows_tesseract(engine_name):
            return sorted(merged.values(), key=lambda w: (w[2], w[1]))
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
    engine: Optional[str] = None,
) -> List[str]:
    """Return OCR strings from several preprocessors while preserving case."""
    engine_name = _engine_name(engine)
    texts: List[str] = []
    if _wants_paddle(engine_name):
        _ensure_paddle_available(engine_name)
        paddle_texts, _words = _paddle_texts_and_words(img, lang=lang)
        texts.extend(paddle_texts)
        if paddle_texts and not _allows_tesseract(engine_name):
            return list(dict.fromkeys(texts))
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
    return list(dict.fromkeys(texts))


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

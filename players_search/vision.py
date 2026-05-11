from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, List, Optional, Tuple

from PIL import Image, ImageDraw

from players_search.ocr import image_to_words


@dataclass(frozen=True)
class BBox:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def center(self) -> Tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)


def _norm(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def find_text_bbox(
    img: Image.Image,
    *,
    needle: str,
    require_full_token: bool = False,
    lang: str = "rus+eng",
) -> Optional[BBox]:
    """
    Finds a bbox of a token that matches `needle` in OCR output.

    - If require_full_token=False (default), matches if needle is a substring of a token.
    - If require_full_token=True, matches only exact token.
    """
    n = _norm(needle)
    if not n:
        return None
    words = image_to_words(img, lang=lang)
    for text, left, top, width, height in words:
        t = _norm(text)
        if not t:
            continue
        ok = (t == n) if require_full_token else (n in t)
        if ok:
            return BBox(left=left, top=top, width=width, height=height)
    return None


def draw_bbox(img: Image.Image, bbox: BBox, *, outline: str = "red", width: int = 3) -> Image.Image:
    out = img.copy()
    d = ImageDraw.Draw(out)
    d.rectangle([bbox.left, bbox.top, bbox.right, bbox.bottom], outline=outline, width=width)
    return out

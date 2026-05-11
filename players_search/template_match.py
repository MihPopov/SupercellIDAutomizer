from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Tuple

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class TemplateMatch:
    left: int
    top: int
    width: int
    height: int
    score: float

    def center(self) -> Tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)


def _to_gray(img: Image.Image) -> np.ndarray:
    arr = np.array(img.convert("RGB"))
    bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


def _load_template(path: Path) -> np.ndarray:
    if not path.exists():
        raise FileNotFoundError(str(path))
    img = Image.open(path)
    return _to_gray(img)


def find_template_best(
    screenshot: Image.Image,
    *,
    template_path: Path,
    scales: Iterable[float] = (0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3),
    min_score: float = 0.75,
) -> Optional[TemplateMatch]:
    """
    Finds the best match of template in screenshot using multi-scale cv2.matchTemplate.
    Returns None if best score < min_score.
    """
    screen = _to_gray(screenshot)
    tpl0 = _load_template(template_path)

    best: Optional[TemplateMatch] = None

    for s in scales:
        if s <= 0:
            continue
        tw = max(8, int(tpl0.shape[1] * s))
        th = max(8, int(tpl0.shape[0] * s))
        tpl = cv2.resize(tpl0, (tw, th), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)

        if th >= screen.shape[0] or tw >= screen.shape[1]:
            continue

        res = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(res)
        if best is None or float(max_val) > best.score:
            best = TemplateMatch(left=int(max_loc[0]), top=int(max_loc[1]), width=int(tw), height=int(th), score=float(max_val))

    if best is None or best.score < min_score:
        return None
    return best


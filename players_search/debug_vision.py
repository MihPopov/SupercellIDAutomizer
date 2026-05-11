from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from players_search.ui_automation import EmulatorUI
from players_search.vision import draw_bbox, find_text_bbox
from players_search.ocr import image_to_text, preprocess_for_ocr


@dataclass(frozen=True)
class ProbeResult:
    found: bool
    screenshot_path: Path
    preprocessed_path: Path
    overlay_path: Optional[Path]
    ocr_text: str


def probe_text(
    *,
    ui: EmulatorUI,
    text: str,
    out_dir: Path,
    click: bool,
) -> ProbeResult:
    out_dir.mkdir(parents=True, exist_ok=True)

    img = ui.screenshot_window()
    screenshot_path = out_dir / "window.png"
    img.save(screenshot_path)

    pre = preprocess_for_ocr(img)
    preprocessed_path = out_dir / "window_pre.png"
    pre.save(preprocessed_path)

    ocr_text = image_to_text(img, lang=ui.ocr_lang)

    bbox = find_text_bbox(img, needle=text, require_full_token=False, lang=ui.ocr_lang)
    if not bbox:
        return ProbeResult(
            found=False,
            screenshot_path=screenshot_path,
            preprocessed_path=preprocessed_path,
            overlay_path=None,
            ocr_text=ocr_text,
        )

    overlay = draw_bbox(img, bbox)
    overlay_path = out_dir / "window_bbox.png"
    overlay.save(overlay_path)

    if click:
        ui.click_text(text)

    return ProbeResult(
        found=True,
        screenshot_path=screenshot_path,
        preprocessed_path=preprocessed_path,
        overlay_path=overlay_path,
        ocr_text=ocr_text,
    )

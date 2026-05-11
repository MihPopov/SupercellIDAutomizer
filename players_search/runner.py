from __future__ import annotations

import time
from typing import Optional

import pyautogui

from players_search.config import Settings
from players_search.ocr import configure_tesseract
from players_search.supabase_repo import PlayersInProgressRepo
from players_search.ui_automation import EmulatorUI
from players_search.win_window import WindowTarget


def run_calibrate(*, interval: float, emulator_window_title: str) -> None:
    print("Move mouse to a target UI element inside the emulator window; press Ctrl+C to stop.")
    print(f"Window title: {emulator_window_title!r}")
    wt = WindowTarget(emulator_window_title)
    wt.activate()
    while True:
        x, y = pyautogui.position()
        r = wt.rect()
        rx, ry = x - r.left, y - r.top
        inside = 0 <= rx < r.width and 0 <= ry < r.height
        flag = "" if inside else " (outside window)"
        print(f"screen={x},{y} window={rx},{ry}{flag}")
        time.sleep(interval)


def _create_ui(settings: Settings, ui_sleep: float) -> EmulatorUI:
    return EmulatorUI(
        emulator_window_title=settings.emulator_window_title,
        ocr_lang=settings.ocr_lang,
        template_club_tab=settings.template_club_tab,
        template_search_box=settings.template_search_box,
        template_search_button=settings.template_search_button,
        template_first_result=settings.template_first_result,
        layout_switch_hotkey=settings.layout_switch_hotkey,
        coord_club_tab=settings.coord_club_tab,
        coord_search_box=settings.coord_search_box,
        coord_first_result=settings.coord_first_result,
        coord_back_home=settings.coord_back_home,
        roi_member_list=settings.roi_member_list,
        roi_player_card=settings.roi_player_card,
        ui_sleep=ui_sleep,
    )


def run_fill(*, settings: Settings, limit: int, dry_run: bool, ui_sleep: float) -> None:
    configure_tesseract(settings.tesseract_cmd)
    repo = PlayersInProgressRepo(settings)
    ui = _create_ui(settings, ui_sleep=ui_sleep)

    rows = repo.fetch_missing_supercell_id(limit=limit)
    if not rows:
        print("No rows found with missing supercell_id (and existing club_tag).")
        return

    for row in rows:
        print(f"Processing: id={row.row_id} name={row.name!r} club_tag={row.club_tag!r}")
        try:
            ui.search_club_by_tag(row.club_tag)
            ui.open_first_club_result()
            scid: Optional[str] = ui.find_player_and_get_supercell_id(row.name)
            ui.go_home()

            if not scid:
                print("  -> Not found (OCR).")
                continue

            print(f"  -> Found supercell_id={scid}")
            if dry_run:
                continue
            repo.set_supercell_id(row.row_id, scid)
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001
            print(f"  -> Error: {e}")
            try:
                ui.go_home()
            except Exception:  # noqa: BLE001
                pass

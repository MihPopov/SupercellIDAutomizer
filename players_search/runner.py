from __future__ import annotations

import time
from typing import Optional


from players_search.config import Settings


def run_calibrate(*, interval: float, emulator_window_title: str) -> None:
    import pyautogui
    from players_search.win_window import WindowTarget
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


def run_lock_window(
    *,
    emulator_window_title: str,
    width: Optional[int],
    height: Optional[int],
    strict: bool,
) -> None:
    from players_search.win_window import WindowTarget

    wt = WindowTarget(emulator_window_title)
    wt.restore_and_activate()
    before = wt.rect()
    print(f"window title: {emulator_window_title!r}")
    print(f"before: left={before.left} top={before.top} width={before.width} height={before.height}")

    if width is not None and height is not None:
        ok = wt.set_size(width=width, height=height)
        if not ok:
            print("resize request: rejected by WinAPI")
        time.sleep(0.2)

    after = wt.rect()
    print(f"after:  left={after.left} top={after.top} width={after.width} height={after.height}")
    print(f"for .env: ROI/COORD are interpreted in this window space ({after.width}x{after.height})")

    if strict and width is not None and height is not None:
        if after.width != width or after.height != height:
            raise RuntimeError(
                f"Window size mismatch: expected {width}x{height}, got {after.width}x{after.height}. "
                "Resize emulator manually or disable --strict."
            )


def _create_ui(settings: Settings, ui_sleep: float):
    from players_search.ui_automation import EmulatorUI
    return EmulatorUI(
        emulator_window_title=settings.emulator_window_title,
        ocr_lang=settings.ocr_lang,
        ocr_engine=settings.ocr_engine,
        template_club_tab=settings.template_club_tab,
        template_search_box=settings.template_search_box,
        template_search_button=settings.template_search_button,
        template_first_result=settings.template_first_result,
        template_home_button=settings.template_home_button,
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
    from players_search.ocr import configure_ocr_engine, configure_tesseract
    from players_search.supabase_repo import SelectedPlayersRepo

    configure_tesseract(settings.tesseract_cmd)
    configure_ocr_engine(settings.ocr_engine)
    repo = SelectedPlayersRepo(settings)
    ui = _create_ui(settings, ui_sleep=ui_sleep)

    rows = repo.fetch_missing_supercell_id(limit=limit)
    if not rows:
        print("No rows found with missing supercell_id (and existing tag/club_tag).")
        return

    for row in rows:
        print(f"Processing: tag={row.tag!r} name={row.name!r} club_tag={row.club_tag!r}")
        try:
            ui.search_club_by_tag(row.club_tag)
            ui.open_first_club_result()
            opened = ui.find_player_and_open_profile(row.name)
            if not opened:
                ui.go_home()
                print("  -> Player not found (OCR).")
                continue

            scid: Optional[str] = ui.read_supercell_id_from_profile()
            ui.go_home()

            if not scid:
                print("  -> Not found (OCR).")
                continue

            print(f"  -> Found supercell_id={scid}")
            if dry_run:
                continue
            repo.set_supercell_id(row.tag, scid)
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001
            print(f"  -> Error: {e}")
            try:
                ui.go_home()
            except Exception:  # noqa: BLE001
                pass

from __future__ import annotations

import argparse

from players_search.config import load_emulator_window_title, load_settings
from players_search.runner import run_fill, run_calibrate
from players_search.debug_env import debug_env
from players_search.win_window import list_visible_window_titles
from players_search.stepper import run_step
from players_search.config import load_ui_settings
from players_search.ui_automation import EmulatorUI
from players_search.ocr import configure_tesseract
from players_search.debug_vision import probe_text


def main() -> int:
    parser = argparse.ArgumentParser(prog="players_search")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Fill supercell_id from emulator")
    p_run.add_argument("--limit", type=int, default=50)
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--sleep", type=float, default=0.6, help="UI delay between actions")

    p_cal = sub.add_parser("calibrate", help="Print mouse coordinates for calibration")
    p_cal.add_argument("--interval", type=float, default=0.5)

    sub.add_parser("debug-env", help="Print loaded env (.env) for troubleshooting")
    p_windows = sub.add_parser("list-windows", help="List visible window titles (to set EMULATOR_WINDOW_TITLE)")
    p_windows.add_argument("--limit", type=int, default=50)

    p_step = sub.add_parser("step", help="Run steps 1..N for debugging (includes prerequisites)")
    p_step.add_argument("name", choices=["club_tab", "search_club", "open_first", "find_player", "home"])
    p_step.add_argument("--club-tag", default="")
    p_step.add_argument("--player-name", default="")
    p_step.add_argument("--sleep", type=float, default=0.6)

    p_probe = sub.add_parser("probe-text", help="Screenshot emulator, OCR-find text, optionally click; saves debug images")
    p_probe.add_argument("--text", required=True)
    p_probe.add_argument("--out-dir", default="debug_vision")
    p_probe.add_argument("--click", action="store_true")
    p_probe.add_argument("--dump-ocr", action="store_true", help="Print full OCR text from emulator window screenshot")
    p_probe.add_argument("--sleep", type=float, default=0.6)

    p_tpl = sub.add_parser("probe-template", help="Template-match inside emulator window and optionally click; prints score")
    p_tpl.add_argument("--template", required=True, help="Path to template PNG")
    p_tpl.add_argument("--min-score", type=float, default=0.82)
    p_tpl.add_argument("--click", action="store_true")
    p_tpl.add_argument("--sleep", type=float, default=0.6)

    args = parser.parse_args()

    if args.cmd == "calibrate":
        title = load_emulator_window_title()
        run_calibrate(interval=args.interval, emulator_window_title=title)
        return 0

    if args.cmd == "debug-env":
        debug_env()
        return 0

    if args.cmd == "list-windows":
        for t in list_visible_window_titles(limit=args.limit):
            print(t)
        return 0
    if args.cmd == "step":
        title = load_emulator_window_title()
        run_step(
            step=args.name,
            emulator_window_title=title,
            club_tag=args.club_tag,
            player_name=args.player_name,
            ui_sleep=args.sleep,
        )
        return 0
    if args.cmd == "probe-text":
        ui_s = load_ui_settings()
        configure_tesseract(ui_s.tesseract_cmd)
        ui = EmulatorUI(
            emulator_window_title=ui_s.emulator_window_title,
            ocr_lang=ui_s.ocr_lang,
            template_club_tab=ui_s.template_club_tab,
            template_search_box=ui_s.template_search_box,
            template_search_button=ui_s.template_search_button,
            template_first_result=ui_s.template_first_result,
            layout_switch_hotkey=ui_s.layout_switch_hotkey,
            coord_club_tab=ui_s.coord_club_tab,
            coord_search_box=ui_s.coord_search_box,
            coord_first_result=ui_s.coord_first_result,
            coord_back_home=ui_s.coord_back_home,
            roi_member_list=ui_s.roi_member_list,
            roi_player_card=ui_s.roi_player_card,
            ui_sleep=args.sleep,
        )
        from pathlib import Path

        res = probe_text(ui=ui, text=args.text, out_dir=Path(args.out_dir), click=args.click)
        print(f"found={res.found}")
        print(res.screenshot_path)
        print(res.preprocessed_path)
        if res.overlay_path:
            print(res.overlay_path)
        if args.dump_ocr:
            print("----- OCR BEGIN -----")
            print(res.ocr_text)
            print("----- OCR END -----")
        return 0
    if args.cmd == "probe-template":
        ui_s = load_ui_settings()
        ui = EmulatorUI(
            emulator_window_title=ui_s.emulator_window_title,
            ocr_lang=ui_s.ocr_lang,
            template_club_tab=ui_s.template_club_tab,
            template_search_box=ui_s.template_search_box,
            template_search_button=ui_s.template_search_button,
            template_first_result=ui_s.template_first_result,
            layout_switch_hotkey=ui_s.layout_switch_hotkey,
            coord_club_tab=ui_s.coord_club_tab,
            coord_search_box=ui_s.coord_search_box,
            coord_first_result=ui_s.coord_first_result,
            coord_back_home=ui_s.coord_back_home,
            roi_member_list=ui_s.roi_member_list,
            roi_player_card=ui_s.roi_player_card,
            ui_sleep=args.sleep,
        )
        match = ui.locate_template(args.template, min_score=args.min_score)
        if not match:
            print("found=False")
            return 0
        print(f"found=True score={match.score:.3f} x={match.left} y={match.top} w={match.width} h={match.height}")
        if args.click:
            ui.click_template(args.template, min_score=args.min_score)
            print("clicked=True")
        return 0

    settings = load_settings()

    if args.cmd == "run":
        run_fill(settings=settings, limit=args.limit, dry_run=args.dry_run, ui_sleep=args.sleep)
        return 0

    return 2

from __future__ import annotations

from typing import List

from players_search.config import load_ui_settings
from players_search.ocr import configure_ocr_engine, configure_tesseract
from players_search.ui_automation import EmulatorUI


def _ui(emulator_window_title: str, ui_sleep: float) -> EmulatorUI:
    """
    For stepping we load only UI settings; Supabase is not required.
    """
    s = load_ui_settings()
    configure_tesseract(s.tesseract_cmd)
    configure_ocr_engine(s.ocr_engine)
    return EmulatorUI(
        emulator_window_title=emulator_window_title,
        ocr_lang=s.ocr_lang,
        ocr_engine=s.ocr_engine,
        template_club_tab=s.template_club_tab,
        template_search_box=s.template_search_box,
        template_search_button=s.template_search_button,
        template_first_result=s.template_first_result,
        template_home_button=s.template_home_button,
        layout_switch_hotkey=s.layout_switch_hotkey,
        coord_club_tab=s.coord_club_tab,
        coord_search_box=s.coord_search_box,
        coord_first_result=s.coord_first_result,
        coord_back_home=s.coord_back_home,
        roi_member_list=s.roi_member_list,
        roi_player_card=s.roi_player_card,
        ui_sleep=ui_sleep,
    )

_PIPELINE: List[str] = ["club_tab", "search_club", "open_first", "find_player", "read_supercell_id", "home"]


def run_step(
    *,
    step: str,
    emulator_window_title: str,
    club_tag: str,
    player_name: str,
    ui_sleep: float,
) -> None:
    """
    Runs all prerequisite steps up to and including `step`.
    Example: step=open_first => club_tab -> search_club -> open_first.
    """
    if step not in _PIPELINE:
        raise RuntimeError(f"Unknown step: {step}. Allowed: {', '.join(_PIPELINE)}")

    ui = _ui(emulator_window_title, ui_sleep=ui_sleep)
    target_index = _PIPELINE.index(step)

    for i in range(target_index + 1):
        name = _PIPELINE[i]
        if name == "club_tab":
            ui.open_club_tab()
        elif name == "search_club":
            if not club_tag:
                raise RuntimeError("--club-tag is required for step>=search_club")
            # The prerequisite step already opened the Club tab. Focus only the
            # search field here so the tab is not clicked twice before typing.
            ui.focus_club_search_box()
            ui.input_club_tag_and_submit(club_tag)
        elif name == "open_first":
            ui.open_first_club_result()
        elif name == "find_player":
            if not player_name:
                raise RuntimeError("--player-name is required for step>=find_player")
            opened = ui.find_player_and_open_profile(player_name)
            if i == target_index:
                print("opened" if opened else "")
        elif name == "read_supercell_id":
            scid = ui.read_supercell_id_from_profile()
            if i == target_index:
                print(scid or "")
        elif name == "home":
            ui.go_home()
        else:
            raise RuntimeError(f"Unhandled step: {name}")

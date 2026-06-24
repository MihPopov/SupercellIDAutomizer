from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Optional, Tuple

from players_search.env_loader import load_dotenv_file


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    return int(raw)


def _env_roi(name: str, default: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    raw = _env(name)
    if raw is None:
        return default
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 4:
        raise ValueError(f"{name} must be 'left,top,width,height'")
    return (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))


def _supabase_table() -> str:
    table = _env("SUPABASE_TABLE", "selected_players") or "selected_players"
    if table == "players_in_progress":
        return "selected_players"
    return table


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_service_role_key: str
    supabase_table: str
    col_tag: str
    col_name: str
    col_supercell_id: str
    col_club_tag: str
    emulator_window_title: str
    tesseract_cmd: Optional[str]
    ocr_lang: str
    ocr_engine: str
    template_club_tab: Optional[str]
    template_search_box: Optional[str]
    template_search_button: Optional[str]
    template_first_result: Optional[str]
    template_home_button: Optional[str]
    layout_switch_hotkey: str
    coord_club_tab: Tuple[int, int]
    coord_search_box: Tuple[int, int]
    coord_first_result: Tuple[int, int]
    coord_back_home: Tuple[int, int]
    roi_member_list: Tuple[int, int, int, int]
    roi_player_card: Tuple[int, int, int, int]


def load_settings() -> Settings:
    load_dotenv_file()

    supabase_url = _env("SUPABASE_URL")
    supabase_key = _env("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        raise RuntimeError("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in environment/.env")

    return Settings(
        supabase_url=supabase_url,
        supabase_service_role_key=supabase_key,
        supabase_table=_supabase_table(),
        col_tag=_env("COL_TAG", "tag") or "tag",
        col_name=_env("COL_NAME", "name") or "name",
        col_supercell_id=_env("COL_SUPERCELL_ID", "supercell_id") or "supercell_id",
        col_club_tag=_env("COL_CLUB_TAG", "club_tag") or "club_tag",
        emulator_window_title=_env("EMULATOR_WINDOW_TITLE", "BlueStacks") or "BlueStacks",
        tesseract_cmd=_env("TESSERACT_CMD"),
        ocr_lang=_env("OCR_LANG", "rus+eng") or "rus+eng",
        ocr_engine=_env("OCR_ENGINE", "tesseract") or "tesseract",
        template_club_tab=_env("TEMPLATE_CLUB_TAB"),
        template_search_box=_env("TEMPLATE_SEARCH_BOX"),
        template_search_button=_env("TEMPLATE_SEARCH_BUTTON"),
        template_first_result=_env("TEMPLATE_FIRST_RESULT"),
        template_home_button=_env("TEMPLATE_HOME_BUTTON"),
        layout_switch_hotkey=_env("LAYOUT_SWITCH_HOTKEY", "alt+shift") or "alt+shift",
        coord_club_tab=(
            _env_int("COORD_CLUB_TAB_X", 100),
            _env_int("COORD_CLUB_TAB_Y", 100),
        ),
        coord_search_box=(
            _env_int("COORD_SEARCH_BOX_X", 200),
            _env_int("COORD_SEARCH_BOX_Y", 200),
        ),
        coord_first_result=(
            _env_int("COORD_FIRST_RESULT_X", 300),
            _env_int("COORD_FIRST_RESULT_Y", 300),
        ),
        coord_back_home=(
            _env_int("COORD_BACK_HOME_X", 1800),
            _env_int("COORD_BACK_HOME_Y", 120),
        ),
        roi_member_list=_env_roi("ROI_MEMBER_LIST", (200, 250, 1400, 750)),
        roi_player_card=_env_roi("ROI_PLAYER_CARD", (120, 140, 650, 160)),
    )


def load_emulator_window_title() -> str:
    """
    Loads only emulator window title from .env without requiring Supabase keys.
    """
    load_dotenv_file()
    return _env("EMULATOR_WINDOW_TITLE", "BlueStacks") or "BlueStacks"


@dataclass(frozen=True)
class UISettings:
    emulator_window_title: str
    tesseract_cmd: Optional[str]
    ocr_lang: str
    ocr_engine: str
    template_club_tab: Optional[str]
    template_search_box: Optional[str]
    template_search_button: Optional[str]
    template_first_result: Optional[str]
    template_home_button: Optional[str]
    layout_switch_hotkey: str
    coord_club_tab: Tuple[int, int]
    coord_search_box: Tuple[int, int]
    coord_first_result: Tuple[int, int]
    coord_back_home: Tuple[int, int]
    roi_member_list: Tuple[int, int, int, int]
    roi_player_card: Tuple[int, int, int, int]


def load_ui_settings() -> UISettings:
    """
    Loads only UI/OCR settings from .env without requiring Supabase keys.
    """
    load_dotenv_file()
    return UISettings(
        emulator_window_title=load_emulator_window_title(),
        tesseract_cmd=_env("TESSERACT_CMD"),
        ocr_lang=_env("OCR_LANG", "rus+eng") or "rus+eng",
        ocr_engine=_env("OCR_ENGINE", "tesseract") or "tesseract",
        template_club_tab=_env("TEMPLATE_CLUB_TAB"),
        template_search_box=_env("TEMPLATE_SEARCH_BOX"),
        template_search_button=_env("TEMPLATE_SEARCH_BUTTON"),
        template_first_result=_env("TEMPLATE_FIRST_RESULT"),
        template_home_button=_env("TEMPLATE_HOME_BUTTON"),
        layout_switch_hotkey=_env("LAYOUT_SWITCH_HOTKEY", "alt+shift") or "alt+shift",
        coord_club_tab=(
            _env_int("COORD_CLUB_TAB_X", 100),
            _env_int("COORD_CLUB_TAB_Y", 100),
        ),
        coord_search_box=(
            _env_int("COORD_SEARCH_BOX_X", 200),
            _env_int("COORD_SEARCH_BOX_Y", 200),
        ),
        coord_first_result=(
            _env_int("COORD_FIRST_RESULT_X", 300),
            _env_int("COORD_FIRST_RESULT_Y", 300),
        ),
        coord_back_home=(
            _env_int("COORD_BACK_HOME_X", 1800),
            _env_int("COORD_BACK_HOME_Y", 120),
        ),
        roi_member_list=_env_roi("ROI_MEMBER_LIST", (200, 250, 1400, 750)),
        roi_player_card=_env_roi("ROI_PLAYER_CARD", (120, 140, 650, 160)),
    )

from __future__ import annotations

import time
from typing import Optional, Tuple

import pyautogui
from PIL import Image

from players_search.ocr import extract_supercell_id, find_token_bbox, image_to_text, image_to_words
from players_search.win_window import WindowTarget
from players_search.vision import find_text_bbox
from players_search.template_match import find_template_best


class EmulatorUI:
    """
    Coordinate-based UI automation for a PC emulator.

    Assumptions:
    - The emulator window is focused (clicks/typing go into it).
    - Coordinates are absolute screen pixels.
    """

    def __init__(
        self,
        *,
        emulator_window_title: str,
        ocr_lang: str,
        template_club_tab: Optional[str],
        template_search_box: Optional[str],
        template_search_button: Optional[str],
        template_first_result: Optional[str],
        layout_switch_hotkey: str,
        coord_club_tab: Tuple[int, int],
        coord_search_box: Tuple[int, int],
        coord_first_result: Tuple[int, int],
        coord_back_home: Tuple[int, int],
        roi_member_list: Tuple[int, int, int, int],
        roi_player_card: Tuple[int, int, int, int],
        ui_sleep: float,
    ) -> None:
        self.window = WindowTarget(emulator_window_title)
        self.ocr_lang = ocr_lang
        self.template_club_tab = template_club_tab
        self.template_search_box = template_search_box
        self.template_search_button = template_search_button
        self.template_first_result = template_first_result
        self.layout_switch_hotkey = layout_switch_hotkey
        self.coord_club_tab = coord_club_tab
        self.coord_search_box = coord_search_box
        self.coord_first_result = coord_first_result
        self.coord_back_home = coord_back_home
        self.roi_member_list = roi_member_list
        self.roi_player_card = roi_player_card
        self.ui_sleep = ui_sleep

        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = max(0.01, ui_sleep / 5)

    def _sleep(self) -> None:
        time.sleep(self.ui_sleep)

    def _ensure_emulator_active(self) -> None:
        # Make sure we interact with the emulator window, not an arbitrary screen location.
        if not self.window.is_foreground():
            self.window.restore_and_activate()
            self._sleep()

    def _click(self, xy: Tuple[int, int]) -> None:
        self._ensure_emulator_active()
        x, y = self.window.to_screen_xy(xy)
        pyautogui.click(x, y)
        self._sleep()

    def _type_and_submit(self, text: str) -> None:
        self._ensure_emulator_active()
        self._clear_and_input(text)
        self._submit_search()

    def _sanitize_input(self, text: str) -> str:
        t = (text or "").strip()
        # Users sometimes copy values containing HTML entities or quoting artifacts.
        t = t.replace("&quot;", "").replace(";quot", "").replace("quot;", "")
        # Remove wrapping quotes, if any.
        if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
            t = t[1:-1].strip()
        return t

    def _switch_layout(self) -> None:
        """
        Switches OS keyboard layout using a configurable hotkey, e.g. 'alt+shift' or 'win+space'.
        This avoids per-window language switching that can freeze some emulators.
        """
        raw = (self.layout_switch_hotkey or "").strip().lower()
        if not raw:
            return
        keys = [k.strip() for k in raw.split("+") if k.strip()]
        if not keys:
            return
        self._ensure_emulator_active()
        try:
            pyautogui.hotkey(*keys)
            time.sleep(max(0.05, self.ui_sleep / 3))
        except Exception:  # noqa: BLE001
            pass

    def _clear_and_input(self, text: str) -> None:
        self._ensure_emulator_active()
        t = self._sanitize_input(text)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        # Clipboard paste can be unreliable in some emulators; use direct typing.
        # To prevent '#' -> '№' on RU layouts, switch to EN via OS hotkey first.
        self._switch_layout()
        pyautogui.typewrite(t, interval=0.02)
        self._sleep()

    def _submit_search(self) -> None:
        # In many emulators, Enter first closes the on-screen keyboard / commits input.
        # Then we try to click the Search button via template; if it's not found, fall back to OCR; then Enter.
        self._ensure_emulator_active()
        pyautogui.press("enter")
        self._sleep()

        if self.template_search_button and self.click_template(self.template_search_button, min_score=0.82):
            return
        if self.click_text("искать") or self.click_text("search"):
            return

        self._ensure_emulator_active()
        pyautogui.press("enter")
        self._sleep()

    def _screenshot(self, roi: Tuple[int, int, int, int]) -> Image.Image:
        self._ensure_emulator_active()
        left, top, width, height = self.window.to_screen_roi(roi)
        return pyautogui.screenshot(region=(left, top, width, height))

    def screenshot_window(self) -> Image.Image:
        self._ensure_emulator_active()
        r = self.window.rect()
        return pyautogui.screenshot(region=(r.left, r.top, r.width, r.height))

    def click_text(self, text: str) -> bool:
        """
        OCR-based click: takes a full window screenshot, finds a token containing `text`,
        and clicks its center (in window coordinates).
        """
        img = self.screenshot_window()
        bbox = find_text_bbox(img, needle=text, require_full_token=False, lang=self.ocr_lang)
        if not bbox:
            return False
        xw, yw = bbox.center()
        self._click((xw, yw))
        return True

    def click_template(self, template_path: str, *, min_score: float = 0.8) -> bool:
        """
        Template-matching click on the emulator window.
        `template_path` can be absolute or relative to CWD.
        """
        from pathlib import Path

        img = self.screenshot_window()
        match = find_template_best(img, template_path=Path(template_path), min_score=min_score)
        if not match:
            return False
        xw, yw = match.center()
        self._click((xw, yw))
        return True

    def locate_template(self, template_path: str, *, min_score: float = 0.8):
        from pathlib import Path

        img = self.screenshot_window()
        return find_template_best(img, template_path=Path(template_path), min_score=min_score)

    def _scroll_member_list(self, clicks: int = -6) -> None:
        # Negative scrolls down for most mice on Windows in PyAutoGUI.
        self._ensure_emulator_active()
        pyautogui.scroll(clicks * 120)
        self._sleep()

    def go_home(self) -> None:
        self._click(self.coord_back_home)

    def open_club_tab(self) -> None:
        # Prefer template first, then OCR, then coordinates.
        if self.template_club_tab and self.click_template(self.template_club_tab, min_score=0.82):
            return
        if self.click_text("клуб") or self.click_text("club"):
            return
        self._click(self.coord_club_tab)

    def focus_club_search_box(self) -> None:
        # Prefer template first, then OCR, then coordinates.
        if self.template_search_box and self.click_template(self.template_search_box, min_score=0.82):
            return
        if self.click_text("поиск") or self.click_text("search"):
            return
        self._click(self.coord_search_box)

    def open_club_search(self) -> None:
        self.open_club_tab()
        self.focus_club_search_box()

    def search_club_by_tag(self, club_tag: str) -> None:
        self.open_club_search()
        self._clear_and_input(club_tag)
        self._submit_search()

    def open_first_club_result(self) -> None:
        if self.template_first_result and self.click_template(self.template_first_result, min_score=0.82):
            return
        self._click(self.coord_first_result)

    def find_player_and_get_supercell_id(self, player_name: str, max_scrolls: int = 18) -> Optional[str]:
        """
        Best-effort:
        - OCR member list area and look for player_name.
        - When likely found, capture player card ROI and extract Supercell ID token.
        """
        target = player_name.strip().lower()
        if not target:
            return None

        for _ in range(max_scrolls + 1):
            list_img = self._screenshot(self.roi_member_list)
            words = image_to_words(list_img, lang=self.ocr_lang)
            list_text = " ".join(w[0] for w in words).lower()
            if target in list_text:
                # Try clicking exactly on the matched token.
                # If nickname has spaces, prefer first word match.
                first_word = target.split()[0]
                bbox = find_token_bbox(words, first_word)
                left0, top0, _, _ = self.roi_member_list
                if bbox:
                    l, t, w, h = bbox
                    self._click((left0 + l + w // 2, top0 + t + h // 2))
                else:
                    self._click((left0 + 50, top0 + 60))
                self._sleep()

                card_img = self._screenshot(self.roi_player_card)
                card_text = image_to_text(card_img, lang=self.ocr_lang)
                scid = extract_supercell_id(card_text)
                return scid

            self._scroll_member_list()

        return None

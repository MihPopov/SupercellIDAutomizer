from __future__ import annotations

import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, List, Optional, Tuple

import pyautogui
import pyperclip
from PIL import Image

from players_search.ocr import extract_supercell_id, image_to_text, image_to_words, image_to_words_variants
from players_search.win_window import WindowTarget
from players_search.vision import find_text_bbox
from players_search.template_match import find_template_best


@dataclass(frozen=True)
class _MemberLine:
    text: str
    left: int
    top: int
    width: int
    height: int

    def center(self) -> Tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)


@dataclass(frozen=True)
class _PlayerMatch:
    line: _MemberLine
    score: float


def _normalize_player_text(text: str) -> str:
    """Normalize OCR/player names for matching while preserving letters/digits."""
    return re.sub(r"[^0-9a-zа-яё]+", "", (text or "").casefold())


def _best_similarity(needle: str, haystack: str) -> float:
    if not needle or not haystack:
        return 0.0
    if needle in haystack:
        return 1.0
    if len(needle) < 4:
        return 0.0
    if len(haystack) <= len(needle):
        return SequenceMatcher(None, needle, haystack).ratio()

    best = 0.0
    window = len(needle)
    # Compare with slightly wider windows too, because OCR can merge nickname
    # text with clan-role/rank text on the same visual line.
    for extra in range(0, min(4, max(1, len(haystack) - window)) + 1):
        size = window + extra
        for start in range(0, len(haystack) - size + 1):
            best = max(best, SequenceMatcher(None, needle, haystack[start : start + size]).ratio())
    return best


def _group_words_into_lines(words: Iterable[Tuple[str, int, int, int, int]]) -> List[_MemberLine]:
    rows: List[List[Tuple[str, int, int, int, int]]] = []
    for word in sorted(words, key=lambda w: (w[2] + w[4] / 2, w[1])):
        text, left, top, width, height = word
        if not text.strip() or width <= 0 or height <= 0:
            continue
        center_y = top + height / 2
        if not rows:
            rows.append([word])
            continue

        row = rows[-1]
        row_center = sum(w[2] + w[4] / 2 for w in row) / len(row)
        row_height = max(w[4] for w in row)
        threshold = max(12.0, row_height * 0.75, height * 0.75)
        if abs(center_y - row_center) <= threshold:
            row.append(word)
        else:
            rows.append([word])

    lines: List[_MemberLine] = []
    for row in rows:
        row.sort(key=lambda w: w[1])
        left = min(w[1] for w in row)
        top = min(w[2] for w in row)
        right = max(w[1] + w[3] for w in row)
        bottom = max(w[2] + w[4] for w in row)
        lines.append(
            _MemberLine(
                text=" ".join(w[0] for w in row),
                left=left,
                top=top,
                width=right - left,
                height=bottom - top,
            )
        )
    return lines


def _find_player_match(words: Iterable[Tuple[str, int, int, int, int]], player_name: str) -> Optional[_PlayerMatch]:
    target = _normalize_player_text(player_name)
    if not target:
        return None

    best: Optional[_PlayerMatch] = None
    for line in _group_words_into_lines(words):
        candidate = _normalize_player_text(line.text)
        score = _best_similarity(target, candidate)
        if score <= 0:
            continue
        if best is None or score > best.score:
            best = _PlayerMatch(line=line, score=score)

    # Require stricter matching for very short names to avoid false clicks.
    min_score = 1.0 if len(target) < 4 else 0.78
    if best and best.score >= min_score:
        return best
    return None


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
        if not t:
            self._sleep()
            return

        # Paste from the host clipboard first: it preserves '#' regardless of
        # the active keyboard layout. Re-focus and pause after updating the
        # clipboard so emulators have time to see the new value before Ctrl+V.
        try:
            pyperclip.copy(t)
            if pyperclip.paste() != t:
                raise RuntimeError("clipboard did not accept club tag")
            time.sleep(max(0.12, self.ui_sleep / 2))
            self._ensure_emulator_active()
            pyautogui.hotkey("ctrl", "v", interval=0.05)
        except Exception:  # noqa: BLE001
            # Last-resort fallback for environments where clipboard access is
            # unavailable. Switch layout first to avoid '#' becoming '№'.
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

    def _scroll_member_list(self) -> None:
        # Drag inside the member-list ROI so Android emulators treat it as a
        # touch scroll. This is more reliable than wheel scrolling, and it also
        # guarantees the scroll starts over the visible list rather than some
        # arbitrary mouse position.
        self._ensure_emulator_active()
        left, top, width, height = self.window.to_screen_roi(self.roi_member_list)
        x = left + width // 2
        start_y = top + int(height * 0.82)
        end_y = top + int(height * 0.28)
        pyautogui.moveTo(x, start_y)
        pyautogui.dragTo(x, end_y, duration=max(0.15, self.ui_sleep / 2), button="left")
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

    def input_club_tag_and_submit(self, club_tag: str) -> None:
        self._clear_and_input(club_tag)
        self._submit_search()

    def search_club_by_tag(self, club_tag: str) -> None:
        self.open_club_search()
        self.input_club_tag_and_submit(club_tag)

    def open_first_club_result(self) -> None:
        if self.template_first_result and self.click_template(self.template_first_result, min_score=0.82):
            return
        self._click(self.coord_first_result)

    def find_player_and_get_supercell_id(self, player_name: str, max_scrolls: int = 30) -> Optional[str]:
        """
        Finds a player in the club member list and opens their profile.

        The visible member list is scanned with OCR line by line. If the
        normalized nickname is not present on the current fragment, the list is
        dragged down and scanned again until the player is found or max_scrolls
        is reached. After a match, the method clicks the matched visual row and
        reads the Supercell ID from the opened profile/card ROI.
        """
        if not _normalize_player_text(player_name):
            return None

        for attempt in range(max_scrolls + 1):
            list_img = self._screenshot(self.roi_member_list)
            # First pass is fast; if it misses the nickname, run high-recall OCR
            # variants before scrolling away from the currently visible list.
            words = image_to_words(list_img, lang=self.ocr_lang)
            match = _find_player_match(words, player_name)
            if not match:
                words = image_to_words_variants(list_img, lang=self.ocr_lang)
                match = _find_player_match(words, player_name)
            if match:
                left0, top0, _, _ = self.roi_member_list
                x, y = match.line.center()
                self._click((left0 + x, top0 + y))
                self._sleep()

                card_img = self._screenshot(self.roi_player_card)
                card_text = image_to_text(card_img, lang=self.ocr_lang)
                return extract_supercell_id(card_text)

            if attempt < max_scrolls:
                self._scroll_member_list()

        return None

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from difflib import SequenceMatcher
from typing import Iterable, List, Optional, Tuple

import cv2
import numpy as np
import pyautogui
import pyperclip
from PIL import Image

from players_search.ocr import (
    extract_case_sensitive_supercell_id,
    image_to_text,
    image_to_text_variants,
    image_to_words,
    image_to_words_variants,
)
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
        ocr_engine: str,
        template_club_tab: Optional[str],
        template_search_box: Optional[str],
        template_search_button: Optional[str],
        template_first_result: Optional[str],
        template_home_button: Optional[str],
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
        self.ocr_engine = ocr_engine
        self.template_club_tab = template_club_tab
        self.template_search_box = template_search_box
        self.template_search_button = template_search_button
        self.template_first_result = template_first_result
        self.template_home_button = template_home_button
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

    def _prepare_keyboard_layout(self) -> None:
        """Switch to EN only when the target window is known to use another layout.

        This avoids blindly toggling EN -> RU when the user already has the
        correct layout. It only reads the target window layout; it never sends
        WM_INPUTLANGCHANGEREQUEST because that can freeze some emulators.
        """
        try:
            lang_id = self.window.input_language_id()
        except Exception:  # noqa: BLE001
            lang_id = None
        if lang_id == 0x0409:
            return
        if lang_id is None:
            # Unknown layout: do not blindly toggle and risk changing EN to RU.
            return
        self._switch_layout()

    def _type_club_tag_direct(self, text: str) -> None:
        """Type a Supercell tag via physical keys after EN layout preparation."""
        for ch in text:
            if ch == "#":
                pyautogui.hotkey("shift", "3")
            elif ch.isascii() and ch.isalpha():
                pyautogui.press(ch.lower())
            elif ch.isdigit():
                pyautogui.press(ch)
            else:
                pyautogui.typewrite(ch, interval=0.03)
            time.sleep(0.03)

    def _paste_from_clipboard(self, text: str) -> None:
        pyperclip.copy(text)
        if pyperclip.paste() != text:
            raise RuntimeError("clipboard did not accept club tag")
        time.sleep(max(0.12, self.ui_sleep / 2))
        self._ensure_emulator_active()
        pyautogui.hotkey("ctrl", "v", interval=0.05)

    def _clear_and_input(self, text: str) -> None:
        self._ensure_emulator_active()
        t = self._sanitize_input(text)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        if not t:
            self._sleep()
            return

        # Clipboard paste is unreliable in several Android emulator/game text
        # fields: Ctrl+V can be accepted but insert an empty value. For the club
        # search field, direct typing is the stable path. Detect the current
        # layout before switching so EN is not blindly toggled to RU; then type
        # the tag as physical keys (# = Shift+3, letters = lowercase keys).
        # Keep clipboard paste as a fallback for environments where synthetic
        # typing fails.
        self._prepare_keyboard_layout()
        try:
            self._type_club_tag_direct(t)
        except Exception:  # noqa: BLE001
            pyautogui.hotkey("ctrl", "a")
            pyautogui.press("backspace")
            self._paste_from_clipboard(t)
        self._sleep()

    def _submit_search(self) -> None:
        # Keep the historical behavior: click the configured Search button
        # template first. Enter is only a fallback (or a way to close an
        # on-screen keyboard before retrying template/OCR search).
        if self.template_search_button and self.click_template(self.template_search_button, min_score=0.82):
            return
        if self.click_text("искать") or self.click_text("search"):
            return

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

    def _resolve_template_path(self, template_path: str) -> Path:
        path = Path(template_path).expanduser()
        if path.is_absolute() or path.exists():
            return path
        repo_relative = Path(__file__).resolve().parent.parent / path
        if repo_relative.exists():
            return repo_relative
        return path

    def click_template(self, template_path: str, *, min_score: float = 0.8) -> bool:
        """
        Template-matching click on the emulator window.
        `template_path` can be absolute or relative to CWD/repo root.
        """
        img = self.screenshot_window()
        match = find_template_best(img, template_path=self._resolve_template_path(template_path), min_score=min_score)
        if not match:
            return False
        xw, yw = match.center()
        self._click((xw, yw))
        return True

    def locate_template(self, template_path: str, *, min_score: float = 0.8):
        img = self.screenshot_window()
        return find_template_best(img, template_path=self._resolve_template_path(template_path), min_score=min_score)

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

    def _scroll_member_list_up(self) -> None:
        # Reverse drag to move the list up (towards the beginning/top).
        self._ensure_emulator_active()
        left, top, width, height = self.window.to_screen_roi(self.roi_member_list)
        x = left + width // 2
        start_y = top + int(height * 0.28)
        end_y = top + int(height * 0.82)
        pyautogui.moveTo(x, start_y)
        pyautogui.dragTo(x, end_y, duration=max(0.15, self.ui_sleep / 2), button="left")
        self._sleep()

    def go_home(self) -> None:
        # Prefer template matching for the Home button, then coordinate fallback.
        if self.template_home_button and self.click_template(self.template_home_button, min_score=0.82):
            return
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

    def find_player_and_open_profile(self, player_name: str, max_scrolls: int = 18, max_cycles: int = 4) -> bool:
        """Find a player in the club member list and open their profile.

        This is step 4 only: it scans the visible list, scrolls as needed, and
        clicks the matched member row. Supercell ID extraction is intentionally
        handled by read_supercell_id_from_profile() as step 5.
        """
        if not _normalize_player_text(player_name):
            return False

        direction_down = True
        scrolls_in_direction = 0
        cycles_done = 0
        seen_signatures: set[str] = set()

        while cycles_done < max_cycles:
            list_img = self._screenshot(self.roi_member_list)
            # First pass is fast; if it misses the nickname, run high-recall OCR
            # variants before scrolling away from the currently visible list.
            words = image_to_words(list_img, lang=self.ocr_lang, engine=self.ocr_engine)
            match = _find_player_match(words, player_name)
            if not match:
                words = image_to_words_variants(list_img, lang=self.ocr_lang, engine=self.ocr_engine)
                match = _find_player_match(words, player_name)
            if match:
                left0, top0, _, _ = self.roi_member_list
                x, y = match.line.center()
                self._click((left0 + x, top0 + y))
                self._sleep()
                return True

            # Keep a lightweight signature of currently visible text to detect
            # stagnation/end-of-list states and switch direction sooner.
            words_sorted = sorted(words, key=lambda w: (w[2], w[1]))
            top_sig = " ".join(w[0] for w in words_sorted[:5]).casefold()
            bottom_sig = " ".join(w[0] for w in words_sorted[-5:]).casefold()
            signature = f"{top_sig}|{bottom_sig}|{'d' if direction_down else 'u'}"
            repeated = signature in seen_signatures
            seen_signatures.add(signature)

            if direction_down:
                self._scroll_member_list()
            else:
                self._scroll_member_list_up()
            scrolls_in_direction += 1

            if repeated or scrolls_in_direction >= max_scrolls:
                direction_down = not direction_down
                scrolls_in_direction = 0
                cycles_done += 1

        return False

    def _crop_supercell_id_box(self, img: Image.Image) -> Image.Image:
        """Crop the dark Supercell ID/nameplate box near the top-left of ROI_PLAYER_CARD."""
        arr = np.array(img.convert("RGB"))
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        mask = (gray < 70).astype("uint8") * 255
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        best: Optional[Tuple[int, int, int, int]] = None
        best_score = -1.0
        img_w, img_h = img.size
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            if w < 80 or h < 20:
                continue
            if y > img_h * 0.65 or x > img_w * 0.75:
                continue
            aspect = w / max(1, h)
            if aspect < 2.0:
                continue
            # Prefer large, wide dark boxes closer to the top-left.
            score = (w * h) - (x * 2.0) - (y * 3.0)
            if score > best_score:
                best_score = score
                best = (x, y, w, h)

        if not best:
            return img

        x, y, w, h = best
        pad = 8
        left = max(0, x - pad)
        top = max(0, y - pad)
        right = min(img_w, x + w + pad)
        bottom = min(img_h, y + h + pad)
        return img.crop((left, top, right, bottom))

    def _supercell_id_ocr_candidates(self, card_img: Image.Image) -> List[Image.Image]:
        """Build OCR candidates strictly inside ROI_PLAYER_CARD."""
        id_img = self._crop_supercell_id_box(card_img)
        anchor_crop = card_img.crop((0, 0, int(card_img.size[0] * 0.58), int(card_img.size[1] * 0.5)))
        return [id_img, anchor_crop, card_img]

    def read_supercell_id_from_profile(self) -> Optional[str]:
        """Read the case-sensitive Supercell ID from ROI_PLAYER_CARD."""
        whitelist = "#ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        deadline = time.time() + 4.0
        while time.time() < deadline:
            # All OCR inputs are derived from ROI_PLAYER_CARD so calibration of
            # that ROI directly controls where Supercell ID recognition looks.
            card_img = self._screenshot(self.roi_player_card)

            for candidate_img in self._supercell_id_ocr_candidates(card_img):
                texts = image_to_text_variants(candidate_img, lang="eng", whitelist=whitelist, engine=self.ocr_engine)
                texts.append(image_to_text(candidate_img, lang="eng", engine=self.ocr_engine))
                for text in texts:
                    scid = extract_case_sensitive_supercell_id(text)
                    if scid and len(scid) >= 6:
                        return scid
            time.sleep(0.35)
        return None

    def find_player_and_get_supercell_id(self, player_name: str, max_scrolls: int = 30) -> Optional[str]:
        """Backward-compatible wrapper: open profile and read Supercell ID."""
        if not self.find_player_and_open_profile(player_name, max_scrolls=max_scrolls):
            return None
        return self.read_supercell_id_from_profile()

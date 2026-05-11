from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import List, Optional, Tuple


user32 = ctypes.WinDLL("user32", use_last_error=True)


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
user32.FindWindowW.restype = wintypes.HWND

user32.EnumWindows.argtypes = (ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM)
user32.EnumWindows.restype = wintypes.BOOL

user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
user32.GetWindowTextLengthW.restype = wintypes.INT

user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, wintypes.INT)
user32.GetWindowTextW.restype = wintypes.INT

user32.IsWindowVisible.argtypes = (wintypes.HWND,)
user32.IsWindowVisible.restype = wintypes.BOOL

user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(RECT))
user32.GetWindowRect.restype = wintypes.BOOL

user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
user32.SetForegroundWindow.restype = wintypes.BOOL

user32.GetForegroundWindow.argtypes = ()
user32.GetForegroundWindow.restype = wintypes.HWND

user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

user32.GetKeyboardLayout.argtypes = (wintypes.DWORD,)
user32.GetKeyboardLayout.restype = wintypes.HKL

user32.IsIconic.argtypes = (wintypes.HWND,)
user32.IsIconic.restype = wintypes.BOOL

user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
user32.ShowWindow.restype = wintypes.BOOL

SW_RESTORE = 9

user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
# wintypes doesn't expose LRESULT on some Python builds; LRESULT is LONG_PTR.
user32.SendMessageW.restype = ctypes.c_ssize_t

user32.LoadKeyboardLayoutW.argtypes = (wintypes.LPCWSTR, wintypes.UINT)
user32.LoadKeyboardLayoutW.restype = wintypes.HKL

WM_INPUTLANGCHANGEREQUEST = 0x0050
KLF_ACTIVATE = 0x00000001


@dataclass(frozen=True)
class WindowRect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


class WindowTarget:
    """
    Simple WinAPI window targeting by title match (substring, case-insensitive).
    Coordinates/ROIs should be provided relative to the window's top-left corner.
    """

    def __init__(self, title: str) -> None:
        self.title = title
        self._hwnd: Optional[int] = None

    def _resolve_hwnd(self) -> int:
        if self._hwnd:
            return self._hwnd

        # First try exact match (fast path).
        hwnd = user32.FindWindowW(None, self.title)
        if hwnd:
            self._hwnd = int(hwnd)
            return self._hwnd

        wanted = (self.title or "").strip().lower()
        if not wanted:
            raise RuntimeError("Emulator window title is empty")

        found: Optional[int] = None

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_cb(h: int, _lparam: int) -> bool:
            nonlocal found
            if found is not None:
                return False
            if not user32.IsWindowVisible(h):
                return True
            length = int(user32.GetWindowTextLengthW(h))
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(h, buf, length + 1)
            title = (buf.value or "").strip()
            if not title:
                return True
            if wanted in title.lower():
                found = int(h)
                return False
            return True

        user32.EnumWindows(enum_cb, 0)

        if found is None:
            raise RuntimeError(f"Emulator window not found by title contains: {self.title!r}")

        self._hwnd = found
        return self._hwnd

    def activate(self) -> None:
        hwnd = self._resolve_hwnd()
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)

    def restore_and_activate(self) -> None:
        self.activate()

    def is_foreground(self) -> bool:
        hwnd = self._resolve_hwnd()
        fg = int(user32.GetForegroundWindow() or 0)
        return fg == hwnd

    def rect(self) -> WindowRect:
        hwnd = self._resolve_hwnd()
        r = RECT()
        ok = user32.GetWindowRect(hwnd, ctypes.byref(r))
        if not ok:
            raise RuntimeError("GetWindowRect failed")
        return WindowRect(left=int(r.left), top=int(r.top), right=int(r.right), bottom=int(r.bottom))

    def input_language_id(self) -> Optional[int]:
        """Return the target window keyboard layout language id, e.g. 0x0409 for EN-US.

        This only reads the current HKL for the target window thread. It does
        not send messages to the emulator, so it is safe for emulator builds
        that freeze on WM_INPUTLANGCHANGEREQUEST.
        """
        hwnd = self._resolve_hwnd()
        pid = wintypes.DWORD()
        thread_id = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not thread_id:
            return None
        hkl = user32.GetKeyboardLayout(thread_id)
        if not hkl:
            return None
        return int(hkl) & 0xFFFF

    def request_input_language(self, klid: str) -> bool:
        """
        Best-effort request to switch input language for the target window.
        Example KLIDs:
        - '00000409' = English (United States)
        - '00000419' = Russian
        """
        hwnd = self._resolve_hwnd()
        hkl = user32.LoadKeyboardLayoutW(klid, KLF_ACTIVATE)
        if not hkl:
            return False
        user32.SendMessageW(hwnd, WM_INPUTLANGCHANGEREQUEST, 0, int(hkl))
        return True

    def to_screen_xy(self, xy_window: Tuple[int, int]) -> Tuple[int, int]:
        r = self.rect()
        return (r.left + int(xy_window[0]), r.top + int(xy_window[1]))

    def to_screen_roi(self, roi_window: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        r = self.rect()
        left, top, width, height = roi_window
        return (r.left + int(left), r.top + int(top), int(width), int(height))


def list_visible_window_titles(limit: int = 50) -> List[str]:
    titles: List[str] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_cb(h: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(h):
            return True
        length = int(user32.GetWindowTextLengthW(h))
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(h, buf, length + 1)
        title = (buf.value or "").strip()
        if not title:
            return True
        titles.append(title)
        return len(titles) < limit

    user32.EnumWindows(enum_cb, 0)
    return titles

"""A system-wide keyboard shortcut, so quick capture works with the app in the background.

On Windows it uses RegisterHotKey and listens for WM_HOTKEY through a Qt
native event filter. Other platforms have no global hotkey here; there the
app can be triggered with `schemeup --capture` bound to an OS shortcut.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication
from PySide6.QtWidgets import QWidget

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY = 0x0312
HOTKEY_ID = 0x5C01

_KEYS = {
    "SPACE": 0x20,
    "ENTER": 0x0D,
    "RETURN": 0x0D,
    "TAB": 0x09,
    "INSERT": 0x2D,
    "HOME": 0x24,
    "END": 0x23,
    **{f"F{i}": 0x6F + i for i in range(1, 13)},
}


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """'Ctrl+Alt+N' to Windows (modifiers, virtual key code), or None if unusable."""
    modifiers, key = 0, None
    for part in (p.strip().upper() for p in text.split("+") if p.strip()):
        if part in ("CTRL", "CONTROL"):
            modifiers |= MOD_CONTROL
        elif part == "ALT":
            modifiers |= MOD_ALT
        elif part == "SHIFT":
            modifiers |= MOD_SHIFT
        elif part in ("WIN", "META", "SUPER"):
            modifiers |= MOD_WIN
        elif len(part) == 1 and part.isalnum():
            key = ord(part)
        elif part in _KEYS:
            key = _KEYS[part]
        else:
            return None
    if key is None or modifiers == 0:
        return None
    return modifiers, key


class _Filter(QAbstractNativeEventFilter):
    def __init__(self, callback: Callable[[], None]) -> None:
        super().__init__()
        self._callback = callback

    def nativeEventFilter(self, event_type: object, message: object) -> tuple[bool, int]:
        if sys.platform == "win32" and event_type in (
            b"windows_generic_MSG",
            "windows_generic_MSG",
        ):
            from ctypes import wintypes

            msg = wintypes.MSG.from_address(int(message))  # type: ignore[call-overload]
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self._callback()
                return True, 0
        return False, 0


class GlobalHotkey:
    """Registers one global shortcut; `error` explains why registration failed."""

    def __init__(self, callback: Callable[[], None]) -> None:
        self._callback = callback
        self._window = QWidget()  # never shown; only its native handle is needed
        self._filter: _Filter | None = None
        self._registered = False
        self.error = ""

    @property
    def supported(self) -> bool:
        return sys.platform == "win32"

    def register(self, text: str) -> bool:
        self.unregister()
        if not self.supported:
            self.error = "Global shortcuts are only available on Windows."
            return False
        parsed = parse_hotkey(text)
        if parsed is None:
            self.error = f"{text!r} isn't a valid shortcut. Use something like Ctrl+Alt+N."
            return False
        modifiers, key = parsed
        import ctypes

        hwnd = int(self._window.winId())
        ok = ctypes.windll.user32.RegisterHotKey(hwnd, HOTKEY_ID, modifiers | MOD_NOREPEAT, key)  # type: ignore[attr-defined,unused-ignore]
        if not ok:
            self.error = f"{text} is already used by another program. Pick another shortcut."
            return False
        if self._filter is None:
            self._filter = _Filter(self._callback)
            app = QCoreApplication.instance()
            if app is not None:
                app.installNativeEventFilter(self._filter)
        self._registered = True
        self.error = ""
        return True

    def unregister(self) -> None:
        if self._registered and self.supported:
            import ctypes

            ctypes.windll.user32.UnregisterHotKey(int(self._window.winId()), HOTKEY_ID)  # type: ignore[attr-defined,unused-ignore]
        self._registered = False

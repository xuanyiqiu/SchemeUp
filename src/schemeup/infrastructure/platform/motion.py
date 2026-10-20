"""Whether the UI should keep animation to a minimum."""

import sys

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _SPI_GETCLIENTAREAANIMATION = 0x1042

    def system_prefers_reduced_motion() -> bool:
        """True when "Animation effects" is off in the Windows accessibility settings.

        This is the same setting browsers map to `prefers-reduced-motion`.
        """
        enabled = wintypes.BOOL(True)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            _SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0
        )
        return bool(ok) and not enabled.value

else:

    def system_prefers_reduced_motion() -> bool:
        # macOS and Linux expose this through APIs Qt doesn't wrap. Not supported yet.
        return False


def wants_reduced_motion(override: str | None = None) -> bool:
    """Follow the OS unless `override` is "full" or "reduced".

    Until the app has a settings screen, the override comes from the
    SCHEMEUP_MOTION environment variable.
    """
    choice = (override or "").strip().lower()
    if choice in ("full", "reduced"):
        return choice == "reduced"
    return system_prefers_reduced_motion()

from __future__ import annotations

import sys


def style_native_window(widget) -> bool:
    """Give a Qt window the modern macOS 'unified titlebar' look.

    Makes the native title bar transparent and lets content run full-height
    beneath the traffic-light controls, matching apps like Notes or Music.
    Returns True on success. Non-fatal on failure.
    """
    if sys.platform != "darwin":
        return False
    try:
        import objc  # type: ignore
        from AppKit import (  # type: ignore
            NSAppearance,
            NSAppearanceNameDarkAqua,
        )

        addr = int(widget.winId())
        nsview = objc.objc_object(c_void_p=addr)
        window = nsview.window()
        if window is None:
            return False

        window.setTitlebarAppearsTransparent_(True)
        window.setTitleVisibility_(1)  # NSWindowTitleHidden

        NSFullSizeContentViewWindowMask = 1 << 15
        window.setStyleMask_(window.styleMask() | NSFullSizeContentViewWindowMask)

        try:
            window.setAppearance_(
                NSAppearance.appearanceNamed_(NSAppearanceNameDarkAqua)
            )
        except Exception:
            pass
        return True
    except Exception:
        return False


def apply_vibrancy(widget) -> bool:
    """Attach an NSVisualEffectView behind a Qt window on macOS.

    Returns True on success, False otherwise. Failure is non-fatal —
    the RootFrame widget already draws a translucent dark background.
    """
    if sys.platform != "darwin":
        return False
    try:
        import objc  # type: ignore
        from AppKit import (  # type: ignore
            NSColor,
            NSVisualEffectBlendingModeBehindWindow,
            NSVisualEffectMaterialHUDWindow,
            NSVisualEffectStateActive,
            NSVisualEffectView,
        )

        addr = int(widget.winId())
        nsview = objc.objc_object(c_void_p=addr)
        window = nsview.window()
        if window is None:
            return False

        window.setOpaque_(False)
        window.setBackgroundColor_(NSColor.clearColor())

        content = window.contentView()
        effect = NSVisualEffectView.alloc().initWithFrame_(content.bounds())
        effect.setMaterial_(NSVisualEffectMaterialHUDWindow)
        effect.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        effect.setState_(NSVisualEffectStateActive)
        effect.setAutoresizingMask_(2 | 16)
        effect.setWantsLayer_(True)

        subviews = content.subviews()
        if subviews and len(subviews) > 0:
            content.addSubview_positioned_relativeTo_(effect, -1, subviews[0])
        else:
            content.addSubview_(effect)
        return True
    except Exception:
        return False

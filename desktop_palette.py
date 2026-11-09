"""DesktopPalette: the light and dark colour themes of the desktop app."""

from __future__ import annotations

from typing import ClassVar


class DesktopPalette:
    """One colour theme. ``toggled()`` returns the other theme.

    The desktop app keeps a palette object instead of module-level colour
    variables, so switching theme is just replacing one object.
    """

    THEMES: ClassVar[dict[str, dict[str, str]]] = {
        "light": {
            "bg": "#fafafa", "panel": "#ffffff", "ink": "#202020", "sub": "#5c656b",
            "accent": "#009639", "soft": "#f0f7f2", "line": "#e4e7ea",
            "low": "#e8f5e9", "mod": "#fff8e1", "high": "#fdecea", "flag": "#f5f5f5",
        },
        "dark": {
            "bg": "#141816", "panel": "#1c2420", "ink": "#edf4ec", "sub": "#b4c4b8",
            "accent": "#4caf6e", "soft": "#243029", "line": "#3a4540",
            "low": "#1e3a24", "mod": "#3d3520", "high": "#3d2420", "flag": "#2a2a2a",
        },
    }

    def __init__(self, name: str = "light") -> None:
        if name not in self.THEMES:
            raise ValueError(f"Unknown theme: {name!r}")
        self.__name = name
        self.__colours = dict(self.THEMES[name])

    @property
    def name(self) -> str:
        return self.__name

    @property
    def bg(self) -> str:
        return self.__colours["bg"]

    @property
    def panel(self) -> str:
        return self.__colours["panel"]

    @property
    def ink(self) -> str:
        return self.__colours["ink"]

    @property
    def sub(self) -> str:
        return self.__colours["sub"]

    @property
    def accent(self) -> str:
        return self.__colours["accent"]

    @property
    def soft(self) -> str:
        return self.__colours["soft"]

    @property
    def line(self) -> str:
        return self.__colours["line"]

    @property
    def low(self) -> str:
        return self.__colours["low"]

    @property
    def mod(self) -> str:
        return self.__colours["mod"]

    @property
    def high(self) -> str:
        return self.__colours["high"]

    @property
    def flag(self) -> str:
        return self.__colours["flag"]

    def toggled(self) -> DesktopPalette:
        return DesktopPalette("dark" if self.__name == "light" else "light")

    def tier_color(self, category: str) -> str:
        """Background colour for a risk category (Low / Moderate / High)."""
        return {"Low": self.low, "Moderate": self.mod, "High": self.high}.get(category, self.soft)

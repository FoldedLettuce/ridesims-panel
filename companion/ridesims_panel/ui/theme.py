"""Light and dark colour themes (Fusion style palettes)."""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

THEMES = ("dark", "light")
DEFAULT_THEME = "dark"


def _dark_palette() -> QPalette:
    p = QPalette()
    window, base, button = QColor(45, 45, 48), QColor(30, 30, 32), QColor(62, 62, 66)
    text, dim, accent = QColor(235, 235, 235), QColor(130, 130, 134), QColor(42, 130, 218)
    for role, color in (
        (QPalette.Window, window), (QPalette.WindowText, text),
        (QPalette.Base, base), (QPalette.AlternateBase, window),
        (QPalette.Text, text), (QPalette.Button, button), (QPalette.ButtonText, text),
        (QPalette.ToolTipBase, base), (QPalette.ToolTipText, text),
        (QPalette.BrightText, QColor(255, 80, 80)), (QPalette.Link, accent),
        (QPalette.Highlight, accent), (QPalette.HighlightedText, QColor(255, 255, 255)),
        (QPalette.PlaceholderText, dim),
    ):
        p.setColor(role, color)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, dim)
    p.setColor(QPalette.Disabled, QPalette.Base, QColor(40, 40, 42))
    p.setColor(QPalette.Disabled, QPalette.Button, QColor(52, 52, 55))
    return p


def apply_theme(name: str) -> str:
    """Apply "dark" or "light" to the running app. Returns the theme that was applied."""
    name = name if name in THEMES else DEFAULT_THEME
    app = QApplication.instance()
    if app is not None:
        app.setStyle("Fusion")
        app.setPalette(_dark_palette() if name == "dark" else app.style().standardPalette())
    return name

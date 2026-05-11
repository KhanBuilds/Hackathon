import os
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QApplication
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont


class TooltipWindow(QWidget):
    """
    Standalone always-on-top window for the explanation tooltip.
    Must NOT be a child of GhostCanvas — canvas is click-through,
    which would make this invisible/inert if parented to it.
    """

    MAX_WIDTH = 340

    def __init__(self):
        super().__init__(parent=None)  # Explicit: no parent
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMaximumWidth(self.MAX_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        self._title = QLabel()
        self._title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._title.setStyleSheet("color: #00D4FF; background: transparent;")

        self._body = QLabel()
        self._body.setFont(QFont("Segoe UI", 9))
        self._body.setStyleSheet("color: #E8E8E8; background: transparent;")
        self._body.setWordWrap(True)

        layout.addWidget(self._title)
        layout.addWidget(self._body)

        self.setStyleSheet("""
            QWidget {
                background-color: rgba(15, 18, 28, 225);
                border: 1px solid rgba(0, 212, 255, 180);
                border-radius: 10px;
            }
        """)

        self._hide_timer = QTimer()
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

        self.hide()

    def _screen_scale(self):
        screen = QApplication.primaryScreen()
        if not screen:
            return 1.0, 1.0

        dpr = screen.devicePixelRatio()
        if dpr <= 0:
            dpr = 1.0
        scale = 1.0 / dpr
        return scale, scale

    def show_at(self, x: int, y: int, element: str, explanation: str):
        if x == -1:
            self.hide()
            return

        self._title.setText(f"⬤  {element.replace('_', ' ').title()}")
        self._body.setText(explanation)
        self.adjustSize()

        screen = QApplication.primaryScreen().geometry()
        sw, sh = screen.width(), screen.height()
        scale_x, scale_y = self._screen_scale()
        x = int(round(x * scale_x))
        y = int(round(y * scale_y))

        # Prefer right of cursor, flip left if near edge
        tx = x + 70
        if tx + self.MAX_WIDTH > sw - 20:
            tx = x - self.width() - 30

        # Prefer above cursor center, clamp to screen
        ty = y - self.height() // 2
        ty = max(20, min(ty, sh - self.height() - 20))

        self.move(tx, ty)
        self.show()
        self.raise_()

        duration = int(os.getenv("TOOLTIP_DURATION_MS", 7000))
        self._hide_timer.start(duration)

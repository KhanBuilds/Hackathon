import os
import ctypes
import platform

from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QPoint, QPropertyAnimation, QEasingCurve, QTimer, QThread, pyqtSignal, pyqtProperty
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush

from utils.logger import log


class VLMWorker(QThread):
    """Runs VLM call off main thread. Emits result when done."""
    finished = pyqtSignal(int, int, str, str)  # x, y, element, explanation

    def __init__(self, query: str):
        super().__init__()
        self.query = query

    def run(self):
        from core.vision import query_vlm
        result = query_vlm(self.query)
        self.finished.emit(
            result["x"],
            result["y"],
            result.get("element_name", "unknown"),
            result.get("explanation", "")
        )


class GhostCanvas(QWidget):
    """
    Full-screen transparent window that draws the ghost cursor.
    Made click-through via win32 WS_EX_TRANSPARENT after show().

    IMPORTANT: Tooltip must be a SEPARATE window, not a child of this.
    Children inherit click-through and become inert.
    """

    def __init__(self):
        super().__init__()
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

        # Screenshot/VLM coordinates are in physical pixels; Qt paints in logical pixels.
        # Keep the ratio so the marker lands on the same visual point on DPI-scaled displays.
        self._screen_scale_x = 1.0
        self._screen_scale_y = 1.0
        self._refresh_screen_scale()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        # Cursor state
        self._cursor_pos = QPoint(-100, -100)
        self._thinking = False
        self._visible = False
        self._animation = None
        self._worker = None
        self._callback = None

        # Pulse timer for "thinking" animation
        self._pulse_timer = QTimer()
        self._pulse_timer.setInterval(80)
        self._pulse_timer.timeout.connect(self._pulse_tick)
        self._pulse_alpha = 255
        self._pulse_dir = -1

    def _refresh_screen_scale(self):
        screen = QApplication.primaryScreen()
        if not screen:
            return

        dpr = screen.devicePixelRatio()
        if dpr <= 0:
            dpr = 1.0

        scale = 1.0 / dpr
        self._screen_scale_x = scale
        self._screen_scale_y = scale

    def _to_canvas_point(self, x: int, y: int) -> QPoint:
        """Convert physical screen coordinates into Qt logical canvas coordinates."""
        return QPoint(
            int(round(x * self._screen_scale_x)),
            int(round(y * self._screen_scale_y)),
        )

    def showEvent(self, event):
        super().showEvent(event)
        if platform.system() == "Windows":
            self._apply_click_through_windows()

    def _apply_click_through_windows(self):
        """Sets WS_EX_TRANSPARENT | WS_EX_LAYERED on Windows so mouse events pass through."""
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_LAYERED = 0x00080000

        hwnd = int(self.winId())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_LAYERED
        )
        log("Click-through applied (Windows)")

    # ── VLM dispatch ─────────────────────────────────────────────────

    def dispatch_vlm(self, query: str, callback):
        """Spawns VLM worker thread. callback(x, y, element, explanation) on main thread."""
        self._callback = callback
        self._worker = VLMWorker(query)
        self._worker.finished.connect(self._on_vlm_done)
        self._worker.start()

    def _on_vlm_done(self, x: int, y: int, element: str, explanation: str):
        self.set_thinking(False)
        if x == -1:
            log("Element not found — hiding cursor")
            self._visible = False
            self.update()
        if self._callback:
            self._callback(x, y, element, explanation)

    # ── Cursor animation ──────────────────────────────────────────────

    def animate_cursor_to(self, x: int, y: int):
        duration = int(os.getenv("CURSOR_ANIMATION_MS", 650))
        self._visible = True
        self._refresh_screen_scale()
        target = self._to_canvas_point(x, y)

        self._animation = QPropertyAnimation(self, b"cursor_pos")
        self._animation.setDuration(duration)
        self._animation.setStartValue(self._cursor_pos)
        self._animation.setEndValue(target)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.start()

        # Auto-hide cursor after tooltip expires
        total = duration + int(os.getenv("TOOLTIP_DURATION_MS", 7000)) + 500
        QTimer.singleShot(total, self._hide_cursor)

    def _hide_cursor(self):
        self._visible = False
        self._thinking = False
        self.update()

    # ── Thinking pulse ────────────────────────────────────────────────

    def set_thinking(self, thinking: bool):
        self._thinking = thinking
        self._visible = thinking
        if thinking:
            self._refresh_screen_scale()
            screen = QApplication.primaryScreen().geometry()
            self._cursor_pos = QPoint(screen.width() // 2, screen.height() // 2)
            self._pulse_timer.start()
        else:
            self._pulse_timer.stop()
        self.update()

    def _pulse_tick(self):
        self._pulse_alpha += self._pulse_dir * 15
        if self._pulse_alpha <= 60:
            self._pulse_dir = 1
        elif self._pulse_alpha >= 240:
            self._pulse_dir = -1
        self._pulse_alpha = max(60, min(255, self._pulse_alpha))
        self.update()

    # ── Qt property for animation ─────────────────────────────────────

    def get_cursor_pos(self):
        return self._cursor_pos

    def set_cursor_pos(self, pos: QPoint):
        self._cursor_pos = pos
        self.update()

    cursor_pos = pyqtProperty(QPoint, fget=get_cursor_pos, fset=set_cursor_pos)

    # ── Paint ─────────────────────────────────────────────────────────

    def paintEvent(self, event):
        if not self._visible:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        x, y = self._cursor_pos.x(), self._cursor_pos.y()
        alpha = self._pulse_alpha if self._thinking else 200

        # Strong crosshair anchored exactly on the coordinate.
        glow_color = QColor(0, 212, 255, alpha // 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(glow_color))
        painter.drawEllipse(x - 18, y - 18, 36, 36)

        border_color = QColor(255, 255, 255, min(alpha + 40, 255))
        main_color = QColor(0, 212, 255, alpha)
        painter.setPen(QPen(border_color, 2))
        painter.setBrush(QBrush(main_color))
        painter.drawEllipse(x - 6, y - 6, 12, 12)

        pen = QPen(QColor(255, 255, 255, alpha), 2)
        painter.setPen(pen)
        painter.drawLine(x - 18, y, x - 8, y)
        painter.drawLine(x + 8, y, x + 18, y)
        painter.drawLine(x, y - 18, x, y - 8)
        painter.drawLine(x, y + 8, x, y + 18)

        # Tiny center dot marks the exact landing point.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255, alpha)))
        painter.drawEllipse(x - 2, y - 2, 4, 4)

        painter.end()

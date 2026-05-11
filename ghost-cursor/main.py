import sys
import os
from dotenv import load_dotenv

# Load .env BEFORE importing anything that reads env vars
load_dotenv()

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from overlay.canvas import GhostCanvas
from overlay.tooltip_window import TooltipWindow
from core.listener import HotkeyListener
from utils.logger import log


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Two separate windows: click-through draw layer + tooltip
    canvas = GhostCanvas()
    tooltip = TooltipWindow()

    canvas.show()

    def on_result(x: int, y: int, element: str, explanation: str):
        """Called from worker thread via Qt signal — runs on main thread."""
        canvas.animate_cursor_to(x, y)
        tooltip.show_at(x, y, element, explanation)

    def on_query(query: str):
        log(f"Query received: {query}")
        canvas.set_thinking(True)
        tooltip.hide()
        canvas.dispatch_vlm(query, callback=on_result)

    listener = HotkeyListener(callback=on_query)
    listener.start()

    log("Ghost Cursor running. Hold F9 and speak.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

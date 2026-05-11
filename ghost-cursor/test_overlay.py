import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from overlay.canvas import GhostCanvas
from overlay.tooltip_window import TooltipWindow

app = QApplication(sys.argv)
canvas = GhostCanvas()
tooltip = TooltipWindow()
canvas.show()

def demo():
    canvas.animate_cursor_to(800, 450)
    tooltip.show_at(800, 450, "test_element", "This is a test tooltip. Cursor should be at 800,450 with a blue crosshair.")

QTimer.singleShot(1000, demo)
sys.exit(app.exec())

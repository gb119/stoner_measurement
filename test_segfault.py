"""Test script to understand the segfault issue."""

from PyQt6.QtWidgets import QApplication, QWidget, QTabWidget, QVBoxLayout

# Simulate the issue:
app = QApplication.instance() or QApplication([])

# Scenario 1: Create widget without parent, then add to TabWidget
tab_widget = QTabWidget()

class CachedWidget(QWidget):
    def __init__(self):
        super().__init__(parent=None)  # No parent!
        layout = QVBoxLayout(self)
        # Add some sub-widgets with signals
        from PyQt6.QtWidgets import QComboBox
        self.combo = QComboBox()
        layout.addWidget(self.combo)
        # Connect a signal to a lambda that uses self.combo
        def on_changed():
            print(f"Combo current text: {self.combo.currentText()}")
        self.combo.currentTextChanged.connect(on_changed)

widget = CachedWidget()
tab_widget.addTab(widget, "Test")

# Now remove the tab without deleting the widget
tab_widget.removeTab(0)

# At this point, widget's parent changed from None to None
# But self.combo might have issues if QTabWidget did something to it

# Add it back
tab_widget.addTab(widget, "Test")

print("Test completed without crash")

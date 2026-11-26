"""The one Settings-field access seam; never emulates a recorder."""
from PySide6.QtCore import QEvent, QObject


def field_parts(field):
    return field, field.clearButton()


class FocusOutWitness(QObject):
    """Observe real blur without replacing the widget's event path."""
    def __init__(self, field):
        super().__init__(field)
        self.events = []
        field.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.FocusOut:
            self.events.append(event.reason())
        return False

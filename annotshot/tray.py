"""Windows and Linux's return door while the main window is hidden."""
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class TrayController(QObject):
    def __init__(self, window, icon):
        super().__init__(window)
        self.window_ = window
        self.icon = None
        self.menu = QMenu(window)
        self.capture_action = self.menu.addAction("Capture")
        self.open_action = self.menu.addAction("Open Annotshot")
        self.quit_action = self.menu.addAction("Quit Annotshot")
        self.capture_action.triggered.connect(lambda: window.capture_from_anywhere())
        self.open_action.triggered.connect(lambda: window.reopen())
        self.quit_action.triggered.connect(lambda: window.quit_app())
        # ASSUMES: a tray is available. Without one the window's close path
        # quits normally, so the app never becomes unreachable in the background.
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.icon = QSystemTrayIcon(icon, self)
            self.icon.setToolTip("Annotshot")
            self.icon.setContextMenu(self.menu)
            self.icon.activated.connect(self._activated)
            self.icon.show()
        self.refresh()

    @property
    def available(self):
        return self.icon is not None and QSystemTrayIcon.isSystemTrayAvailable()

    def refresh(self):
        key = self.window_.capture_key_text()
        self.capture_action.setText(f"Capture ({key})" if key else "Capture")

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.window_.reopen()

    def notify_hidden(self):
        settings = self.window_.settings
        if self.icon is None or settings.value("app/keep_running_told", False, type=bool):
            return
        key = self.window_.capture_key_text()
        text = f"{key} captures. Quit from this icon." if key else "Quit from this icon."
        self.icon.showMessage("Annotshot is still running", text)
        settings.setValue("app/keep_running_told", True)

    def shutdown(self):
        if self.icon is not None:
            self.icon.hide()

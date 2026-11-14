"""Windows package identity, including a frozen app launched by the Store."""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

APPMODEL_ERROR_NO_PACKAGE = 15700


def app_data_directory() -> Path:
    """The user's app data, even when Qt cannot resolve its standard path."""
    from PySide6.QtCore import QStandardPaths
    location = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    if location and Path(location).is_absolute():
        return Path(location)
    return Path.home() / "AppData" / "Local" / "Annotshot"


def is_packaged() -> bool:
    """True only when Windows supplies this process's package full name."""
    if sys.platform != "win32":
        return False
    try:
        get_name = ctypes.WinDLL("kernel32", use_last_error=True).GetCurrentPackageFullName
        get_name.argtypes = [ctypes.POINTER(wintypes.UINT), wintypes.LPWSTR]
        get_name.restype = wintypes.LONG
        length = wintypes.UINT()
        result = get_name(ctypes.byref(length), None)
        if result == APPMODEL_ERROR_NO_PACKAGE or not length.value:
            return False
        name = ctypes.create_unicode_buffer(length.value)
        result = get_name(ctypes.byref(length), name)
        return result != APPMODEL_ERROR_NO_PACKAGE and bool(name.value)
    except Exception:                   # unavailable API or any detection error
        return False

"""cx_Freeze build script — creates AutoClicker&Macro_v2.exe"""
from cx_Freeze import setup, Executable
import sys, os

build_options = {
    "packages": [
        "customtkinter", "autoit", "keyboard", "mouse",
        "win32gui", "win32ui", "win32con", "win32api",
        "tkinter", "json", "threading", "time", "random",
        "ctypes", "subprocess", "os", "sys", "requests",
    ],
    "includes": ["core_engine", "macro_engine"],
    "include_files": [
        ("src/core_engine.py", "core_engine.py"),
        ("src/macro_engine.py", "macro_engine.py"),
    ],
    "excludes": ["unittest", "test", "email", "xml", "pydoc", "doctest"],
}

exe = Executable(
    script="src/AutoClicker&Macro_v2.py",
    base="gui",
    target_name="AutoClicker&Macro_v2.exe",
    icon="mouse.ico" if os.path.exists("mouse.ico") else None,
)

setup(
    name="AutoClicker&Macro Power Edition",
    version="2.0.0",
    description="High-performance AutoClicker & Macro tool",
    options={"build_exe": build_options},
    executables=[exe],
)

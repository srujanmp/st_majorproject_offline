"""Build the ready-to-run zip for this computer's system.

    pip install -r requirements-dev.txt
    python build.py

Result: dist/CampusAssistant-<system>-<cpu>.zip
Unzip it anywhere and run CampusAssistant (CampusAssistant.exe on Windows).
The person using it needs no Python, no internet and no installation.

PyInstaller packages for the system it runs on, so build the Windows zip on
Windows, the Raspberry Pi zip on a Raspberry Pi (64-bit OS), and so on. The
GitHub Actions workflow in .github/workflows/build.yml does all of them.
"""
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "CampusAssistant"
BUILD = ROOT / "build"
DIST = ROOT / "dist"

START_HERE = """\
Campus Assistant (offline edition)
==================================

1. Start it
   Windows:  double-click CampusAssistant.exe
             (if Windows SmartScreen appears: More info -> Run anyway)
   macOS:    right-click CampusAssistant -> Open (first time only), or run ./CampusAssistant in Terminal
   Linux / Raspberry Pi:  ./CampusAssistant

2. Your browser opens http://localhost:8765
   (if it doesn't, open that address yourself in Chrome, Edge or Firefox).

3. First time only: create the admin account and register your face.
   Then add knowledge in Admin (try importing the files in sample_data/)
   and add student accounts in Admin -> Users.

Close the black console window to stop the app.

Everything stays in this folder: settings.ini (port, face strictness, optional
local AI model), data/ (your database) and models/. Back up data/ to keep
your users and knowledge. No internet connection is used.
"""


def platform_tag() -> str:
    system = {"Darwin": "macos", "Windows": "windows"}.get(platform.system(), platform.system().lower())
    machine = platform.machine().lower()
    machine = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(machine, machine)
    return f"{system}-{machine}"


def main() -> int:
    if not (ROOT / "models" / "vosk" / "am").exists():
        print("Models not found, downloading them first...")
        subprocess.check_call([sys.executable, str(ROOT / "scripts" / "get_models.py")])

    import PyInstaller.__main__

    shutil.rmtree(BUILD, ignore_errors=True)
    PyInstaller.__main__.run([
        str(ROOT / "run.py"),
        "--name", NAME,
        "--onedir",
        "--noconfirm",
        "--clean",
        "--console",  # the console window shows the address and stops the app when closed
        "--distpath", str(BUILD / "dist"),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        "--add-data", f"{ROOT / 'campus' / 'web'}{os.pathsep}campus/web",
        # Vosk's native library (libvosk.so / .dll / .dyld) lives inside its package folder.
        "--collect-all", "vosk",
        # Not used by the app; keeps the package small.
        "--exclude-module", "tkinter",
        "--exclude-module", "onnx",
        "--exclude-module", "onnxruntime.quantization",
        "--exclude-module", "onnxruntime.transformers",
        "--exclude-module", "onnxruntime.tools",
        "--exclude-module", "pytest",
        "--exclude-module", "yaml",
    ])

    app = BUILD / "dist" / NAME
    shutil.copytree(ROOT / "models", app / "models")
    shutil.copytree(ROOT / "sample_data", app / "sample_data")
    (app / "START-HERE.txt").write_text(START_HERE, encoding="utf-8")

    DIST.mkdir(exist_ok=True)
    archive = shutil.make_archive(str(DIST / f"{NAME}-{platform_tag()}"), "zip", BUILD / "dist", NAME)
    size = Path(archive).stat().st_size / 1e6
    print(f"\nBuilt {archive} ({size:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

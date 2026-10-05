"""Nuitka build script — produces a standalone Windows executable.

    uv sync --extra build
    uv run python build.py            # standalone folder (fast start)
    uv run python build.py --onefile  # single distributable .exe
    uv run python build.py --console  # keep a console for debugging
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
ENTRY = ROOT / "src" / "loancalc" / "__main__.py"
OUTPUT = ROOT / "build"
DIST = ROOT / "dist"

PRODUCT = "LoanCalc"
VERSION = "0.1.0"
COMPANY = "LoanCalc"


def flags(onefile: bool, console: bool) -> list[str]:
    args = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        "--output-dir=build",
        "--output-filename=LoanCalc.exe",
        "--remove-output",

        # --- Qt ----------------------------------------------------------- #
        "--enable-plugin=pyside6",
        "--include-qt-plugins=platforms,styles,iconengines,imageformats",
        "--noinclude-qt-translations",

        # --- our package, including the bundled starter CSV ---------------- #
        "--include-package=loancalc",
        "--include-package-data=loancalc",

        # --- plotting / data ----------------------------------------------- #
        # pyqtgraph does a lot of lazy importing that Nuitka cannot see.
        "--include-package=pyqtgraph",
        "--include-package-data=pyqtgraph",
        "--include-module=pyqtgraph.graphicsItems.DateAxisItem",
        "--include-module=pyqtgraph.graphicsItems.FillBetweenItem",
        "--include-module=pyqtgraph.graphicsItems.BarGraphItem",
        "--include-package=numpy",
        "--include-package=pandas",

        # --- trim the bundle ----------------------------------------------- #
        "--nofollow-import-to=tkinter",
        "--nofollow-import-to=matplotlib",
        "--nofollow-import-to=PyQt5",
        "--nofollow-import-to=PyQt6",
        "--nofollow-import-to=IPython",
        "--nofollow-import-to=pytest",
        "--nofollow-import-to=unittest",
        "--nofollow-import-to=pandas.tests",
        "--nofollow-import-to=numpy.testing",
        "--nofollow-import-to=pyqtgraph.examples",
        "--nofollow-import-to=pyqtgraph.opengl",

        # --- metadata ------------------------------------------------------ #
        f"--company-name={COMPANY}",
        f"--product-name={PRODUCT}",
        f"--file-version={VERSION}",
        f"--product-version={VERSION}",
        "--file-description=Student loan tracking and repayment strategy",
        "--copyright=© 2026",
    ]

    args.append("--windows-console-mode=force" if console else "--windows-console-mode=disable")

    icon = ROOT / "assets" / "loancalc.ico"
    if icon.exists():
        args.append(f"--windows-icon-from-ico={icon}")

    if onefile:
        args += [
            "--onefile",
            f"--onefile-tempdir-spec={{CACHE_DIR}}\\{PRODUCT}\\{VERSION}",
        ]

    args.append(str(ENTRY))
    return args


def main() -> int:
    parser = argparse.ArgumentParser(description="Build LoanCalc with Nuitka.")
    parser.add_argument("--onefile", action="store_true", help="single-file .exe")
    parser.add_argument("--console", action="store_true", help="keep the console window")
    parser.add_argument("--clean", action="store_true", help="wipe build/ and dist/ first")
    options = parser.parse_args()

    if options.clean:
        for folder in (OUTPUT, DIST):
            shutil.rmtree(folder, ignore_errors=True)

    command = flags(options.onefile, options.console)
    print(" ".join(command), "\n")
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode != 0:
        return result.returncode

    produced = (
        OUTPUT / "LoanCalc.exe" if options.onefile else OUTPUT / "__main__.dist" / "LoanCalc.exe"
    )
    print(f"\nBuilt: {produced}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

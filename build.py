"""Nuitka build script — produces a standalone Windows executable.

    uv sync --extra build
    uv run --extra build python build.py            # standalone folder (fast start)
    uv run --extra build python build.py --onefile  # single distributable .exe
    uv run --extra build python build.py --console  # keep a console for debugging

The exe icon comes from src/loancalc/resources/loancalc.ico; the same file is
bundled as data so the running window and taskbar use it too.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
PACKAGE = ROOT / "src" / "loancalc"
ENTRY = PACKAGE / "__main__.py"
RESOURCES = PACKAGE / "resources"
ICON = RESOURCES / "loancalc.ico"
OUTPUT = ROOT / "build"
DIST = ROOT / "dist"

PRODUCT = "LoanCalc"
COMPANY = "LoanCalc"
VERSION = re.search(
    r'__version__\s*=\s*"([^"]+)"', (PACKAGE / "__init__.py").read_text(encoding="utf-8")
).group(1)


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

        # --- our package + resources (icon, starter dataset) --------------- #
        "--include-package=loancalc",
        "--include-package-data=loancalc",
        f"--include-data-dir={RESOURCES}=loancalc/resources",

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
        "--nofollow-import-to=tests",

        # --- metadata ------------------------------------------------------ #
        f"--company-name={COMPANY}",
        f"--product-name={PRODUCT}",
        f"--file-version={VERSION}",
        f"--product-version={VERSION}",
        "--file-description=Debt payoff planner — student loans, mortgages, auto loans and more",
        "--copyright=© 2026",
    ]

    args.append("--windows-console-mode=force" if console else "--windows-console-mode=disable")

    if not ICON.exists():
        raise SystemExit(f"Icon not found: {ICON}")
    args.append(f"--windows-icon-from-ico={ICON}")

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

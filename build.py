"""Nuitka build script — produces a standalone Windows executable or macOS app.

    uv sync --extra build
    uv run --extra build python build.py            # standalone folder (fast start)
    uv run --extra build python build.py --onefile  # single distributable .exe
    uv run --extra build python build.py --console  # keep a console for debugging

On macOS the same command produces build/LoanCalc.app (see build_apple.sh).

The exe icon comes from src/loancalc/resources/loancalc.ico; the same file is
bundled as data so the running window and taskbar use it too.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent
PACKAGE = ROOT / "src" / "loancalc"
ENTRY = PACKAGE / "__main__.py"
RESOURCES = PACKAGE / "resources"
ICON = RESOURCES / "loancalc.ico"
OUTPUT = ROOT / "build"
DIST = ROOT / "dist"

MACOS = sys.platform == "darwin"
PRODUCT = "LoanCalc"
COMPANY = "LoanCalc"
BUNDLE_ID = "com.loancalc.LoanCalc"
VERSION = re.search(
    r'__version__\s*=\s*"([^"]+)"', (PACKAGE / "__init__.py").read_text(encoding="utf-8")
).group(1)


def flags(onefile: bool, console: bool) -> list[str]:
    args = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        "--output-dir=build",
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
    ]
    args += macos_flags(onefile) if MACOS else windows_flags(onefile, console)
    args.append(str(ENTRY))
    return args


def windows_flags(onefile: bool, console: bool) -> list[str]:
    args = [
        "--output-filename=LoanCalc.exe",

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
    return args


def macos_flags(onefile: bool) -> list[str]:
    if onefile:
        raise SystemExit("--onefile is Windows-only; on macOS the build is LoanCalc.app.")
    args = [
        f"--output-filename={PRODUCT}",
        "--macos-create-app-bundle",
        f"--macos-app-name={PRODUCT}",
        f"--macos-app-version={VERSION}",
        f"--macos-signed-app-name={BUNDLE_ID}",
    ]
    icns = macos_icon()
    if icns is not None:
        args.append(f"--macos-app-icon={icns}")
    return args


def macos_icon() -> Path | None:
    """Convert loancalc.ico to .icns with the sips/iconutil tools that ship with macOS."""
    if not ICON.exists():
        raise SystemExit(f"Icon not found: {ICON}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    icns = OUTPUT / "loancalc.icns"

    def run(*cmd: str) -> None:
        subprocess.run(cmd, check=True, capture_output=True)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base.png"
            iconset = Path(tmp) / "loancalc.iconset"
            iconset.mkdir()
            run("sips", "-s", "format", "png", str(ICON), "--out", str(base))
            for size in (16, 32, 128, 256, 512):
                for scale, suffix in ((1, ""), (2, "@2x")):
                    px = str(size * scale)
                    target = iconset / f"icon_{size}x{size}{suffix}.png"
                    run("sips", "-z", px, px, str(base), "--out", str(target))
            run("iconutil", "-c", "icns", str(iconset), "-o", str(icns))
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"[!] Could not build .icns ({exc}); using the default app icon.")
        return None
    return icns


def main() -> int:
    parser = argparse.ArgumentParser(description="Build LoanCalc with Nuitka.")
    parser.add_argument("--onefile", action="store_true", help="single-file .exe")
    parser.add_argument("--console", action="store_true", help="keep the console window")
    parser.add_argument("--clean", action="store_true", help="wipe build/ and dist/ first")
    options = parser.parse_args()

    if options.clean:
        for folder in (OUTPUT, DIST):
            shutil.rmtree(folder, ignore_errors=True)

    app_bundle = OUTPUT / f"{PRODUCT}.app"
    if MACOS:
        shutil.rmtree(app_bundle, ignore_errors=True)

    command = flags(options.onefile, options.console)
    print(" ".join(command), "\n")
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode != 0:
        return result.returncode

    if MACOS:
        # Nuitka names the bundle after the entry script (__main__.app).
        if not app_bundle.exists():
            for bundle in OUTPUT.glob("*.app"):
                bundle.rename(app_bundle)
                break
        print(f"\nBuilt: {app_bundle}")
        if options.console:
            print(f"For console output run: {app_bundle}/Contents/MacOS/{PRODUCT}")
        return 0

    produced = (
        OUTPUT / "LoanCalc.exe" if options.onefile else OUTPUT / "__main__.dist" / "LoanCalc.exe"
    )
    print(f"\nBuilt: {produced}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

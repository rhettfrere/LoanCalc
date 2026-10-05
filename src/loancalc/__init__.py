"""LoanCalc — student loan tracking and repayment strategy."""
from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["main", "__version__"]


def main() -> None:
    """Console/GUI entry point registered in pyproject.toml."""
    from loancalc.app import run

    raise SystemExit(run())

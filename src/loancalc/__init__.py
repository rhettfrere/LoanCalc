"""LoanCalc — debt payoff planning for every loan type, per plan or as a household."""
from __future__ import annotations

__version__ = "0.2.0"
__all__ = ["main", "__version__"]


def main() -> None:
    """Console/GUI entry point registered in pyproject.toml."""
    from loancalc.app import run

    raise SystemExit(run())

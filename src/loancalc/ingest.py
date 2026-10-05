"""Loan table ingestion.

Accepts any TSV/CSV whose header can be mapped onto name / balance / rate /
minimum payment. Currency symbols, thousands separators, parentheses negatives
and percent signs are all normalised here so nothing downstream has to care.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd

from loancalc.models import Loan

#: Header aliases, matched after lowercasing and stripping non-alphanumerics.
_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("loanname", "name", "loan", "description", "account", "loanid", "label"),
    "balance": (
        "currentloanvalue",
        "currentbalance",
        "balance",
        "principal",
        "amount",
        "value",
        "outstandingbalance",
        "payoff",
    ),
    "rate": ("interestrate", "rate", "apr", "interest", "annualrate", "intrate"),
    "minimum": (
        "minimumpayment",
        "minpayment",
        "minimum",
        "min",
        "monthlypayment",
        "requiredpayment",
        "payment",
    ),
    "servicer": ("servicer", "lender", "holder", "provider"),
}

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_MONEY_NOISE = re.compile(r"[^0-9.\-]")


class IngestError(ValueError):
    """Raised when a file cannot be interpreted as a loan table."""


def _normalise_header(value: object) -> str:
    return _NON_ALNUM.sub("", str(value).strip().lower())


def _to_float(value: object, *, field: str, row: int) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        raise IngestError(f"Row {row}: '{field}' is empty.")
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        raise IngestError(f"Row {row}: '{field}' is empty.")
    negative = text.startswith("(") and text.endswith(")")
    cleaned = _MONEY_NOISE.sub("", text)
    if cleaned in ("", "-", "."):
        raise IngestError(f"Row {row}: cannot read '{field}' from {value!r}.")
    try:
        number = float(cleaned)
    except ValueError as exc:  # pragma: no cover - guarded by the regex above
        raise IngestError(f"Row {row}: cannot read '{field}' from {value!r}.") from exc
    return -number if negative else number


def _to_rate(value: object, row: int) -> float:
    """Return a decimal annual rate; accepts '4.99%', 4.99 or 0.0499."""
    number = _to_float(value, field="interest rate", row=row)
    is_percent_text = isinstance(value, str) and "%" in value
    if is_percent_text or number > 1.0:
        number /= 100.0
    if not 0.0 <= number < 1.0:
        raise IngestError(f"Row {row}: interest rate {value!r} is out of range.")
    return number


def _resolve_columns(frame: pd.DataFrame) -> dict[str, str]:
    lookup = {_normalise_header(col): col for col in frame.columns}
    resolved: dict[str, str] = {}
    for field, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lookup:
                resolved[field] = lookup[alias]
                break
    missing = [f for f in ("name", "balance", "rate", "minimum") if f not in resolved]
    if missing:
        raise IngestError(
            "Could not find column(s) for: "
            + ", ".join(missing)
            + ".\nExpected headers like: Loan Name, Current Loan Value, "
            "Interest Rate, Minimum Payment.\nFound: "
            + ", ".join(str(c) for c in frame.columns)
        )
    return resolved


def read_table(source: str | Path | io.StringIO) -> pd.DataFrame:
    """Read a delimited file, sniffing the separator so TSV and CSV both work."""
    try:
        frame = pd.read_csv(
            source,
            sep=None,
            engine="python",
            skipinitialspace=True,
            dtype=str,
            keep_default_na=False,
        )
    except Exception as exc:
        raise IngestError(f"Could not parse the file: {exc}") from exc
    frame = frame.dropna(axis=1, how="all")
    frame.columns = [str(c).strip() for c in frame.columns]
    return frame


def loans_from_frame(frame: pd.DataFrame) -> list[Loan]:
    """Convert a raw table into validated `Loan` objects."""
    columns = _resolve_columns(frame)
    loans: list[Loan] = []
    errors: list[str] = []

    for position, (_, row) in enumerate(frame.iterrows(), start=2):
        name = str(row[columns["name"]]).strip()
        if not name:
            continue
        try:
            balance = _to_float(row[columns["balance"]], field="balance", row=position)
            rate = _to_rate(row[columns["rate"]], position)
            minimum = _to_float(row[columns["minimum"]], field="minimum payment", row=position)
        except IngestError as exc:
            errors.append(str(exc))
            continue
        if balance < 0:
            errors.append(f"Row {position}: negative balance for '{name}'.")
            continue
        servicer = ""
        if "servicer" in columns:
            servicer = str(row[columns["servicer"]]).strip()
        loans.append(
            Loan(
                name=name,
                principal=round(balance, 2),
                annual_rate=rate,
                minimum_payment=round(max(minimum, 0.0), 2),
                servicer=servicer,
                sort_order=len(loans),
            )
        )

    if not loans:
        detail = "\n".join(errors[:5]) if errors else "No data rows were found."
        raise IngestError(f"No usable loans were read.\n{detail}")
    if errors:
        raise IngestError(
            "Some rows could not be read:\n" + "\n".join(errors[:8])
        )
    return loans


def load_loans(source: str | Path) -> list[Loan]:
    """Load loans from a `.csv`, `.tsv` or `.txt` file on disk."""
    path = Path(source)
    if not path.exists():
        raise IngestError(f"File not found: {path}")
    return loans_from_frame(read_table(path))


def load_loans_from_text(text: str) -> list[Loan]:
    """Load loans from an in-memory delimited string (used for bundled data)."""
    return loans_from_frame(read_table(io.StringIO(text)))


def loans_to_frame(loans: list[Loan]) -> pd.DataFrame:
    """Round-trip helper used by the export feature."""
    return pd.DataFrame(
        {
            "Loan Name": [loan.name for loan in loans],
            "Current Loan Value": [loan.payoff_amount for loan in loans],
            "Interest Rate": [f"{loan.annual_rate * 100:.3f}%" for loan in loans],
            "Minimum Payment": [loan.minimum_payment for loan in loans],
        }
    )

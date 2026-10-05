"""Loan table ingestion (CSV / TSV / TXT).

Only three columns are required — name, balance and interest rate. Everything
else is optional and matched by alias, so exports from servicers, spreadsheets
and LoanCalc's own template all import without editing. Currency symbols,
thousands separators, parentheses negatives and percent signs are normalised.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from loancalc.domain.loan_types import InterestMethod, infer_type, parse_type
from loancalc.domain.models import Loan

#: Field -> accepted headers (lowercased, non-alphanumerics stripped).
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("loanname", "name", "loan", "description", "account", "accountname", "label"),
    "balance": ("currentloanvalue", "currentbalance", "balance", "principal", "amount",
                "value", "outstandingbalance", "payoff", "payoffamount", "loanbalance"),
    "rate": ("interestrate", "rate", "apr", "interest", "annualrate", "intrate"),
    "minimum": ("minimumpayment", "minpayment", "minimum", "min", "monthlypayment",
                "requiredpayment", "payment", "pi", "principalandinterest"),
    "type": ("loantype", "type", "category", "kind", "product", "debttype"),
    "plan": ("plan", "group", "portfolio", "bucket", "planname"),
    "servicer": ("servicer", "lender", "holder", "provider", "bank"),
    "term": ("remainingtermmonths", "remainingterm", "termmonths", "term", "monthsremaining",
             "remainingmonths", "termremaining", "remainingtermyears", "termyears"),
    "escrow": ("escrowmonthly", "escrow", "monthlyescrow", "taxesinsurance", "taxesandinsurance"),
    "pmi": ("pmimonthly", "pmi", "mortgageinsurance", "mip"),
    "asset_value": ("assetvalue", "homevalue", "propertyvalue", "vehiclevalue", "carvalue",
                    "collateralvalue", "currentvalue", "marketvalue"),
    "original_value": ("originalvalue", "purchaseprice", "appraisedvalue", "originalappraisal",
                       "originalhomevalue"),
    "growth": ("assetgrowthannual", "assetgrowth", "appreciation", "appreciationrate",
               "depreciation", "depreciationrate", "growthrate", "annualappreciation"),
    "method": ("interestmethod", "accrual", "accrualmethod", "compounding"),
}

REQUIRED = ("name", "balance", "rate")

#: Canonical headers used by exports and the template (re-importable as-is).
EXPORT_HEADERS = {
    "name": "Loan Name",
    "type": "Loan Type",
    "plan": "Plan",
    "servicer": "Servicer",
    "balance": "Current Loan Value",
    "rate": "Interest Rate",
    "minimum": "Minimum Payment",
    "term": "Remaining Term (months)",
    "escrow": "Escrow (monthly)",
    "pmi": "PMI (monthly)",
    "asset_value": "Asset Value",
    "original_value": "Original Value",
    "growth": "Asset Growth (annual %)",
    "method": "Interest Method",
}

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_MONEY_NOISE = re.compile(r"[^0-9.\-]")


class IngestError(ValueError):
    """Raised when a file cannot be interpreted as a loan table."""


@dataclass(slots=True)
class ImportResult:
    loans: list[Loan]
    #: Plan name requested for each loan ("" = use the loan type's default plan).
    plan_names: list[str]
    columns: dict[str, str] = field(default_factory=dict)
    inferred_types: int = 0


def _normalise_header(value: object) -> str:
    return _NON_ALNUM.sub("", str(value).strip().lower())


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value)) or not str(value).strip()


def _to_float(value: object, *, field: str, row: int) -> float:
    if _blank(value):
        raise IngestError(f"Row {row}: '{field}' is empty.")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    negative = text.startswith("(") and text.endswith(")")
    cleaned = _MONEY_NOISE.sub("", text)
    if cleaned in ("", "-", "."):
        raise IngestError(f"Row {row}: cannot read '{field}' from {value!r}.")
    try:
        number = float(cleaned)
    except ValueError as exc:
        raise IngestError(f"Row {row}: cannot read '{field}' from {value!r}.") from exc
    return -number if negative else number


def _optional_float(value: object, *, field: str, row: int) -> float:
    return 0.0 if _blank(value) else _to_float(value, field=field, row=row)


def _to_percent(value: object, *, field: str, row: int, signed: bool = False) -> float:
    """Return a decimal rate; accepts '4.99%', 4.99 or 0.0499."""
    number = _to_float(value, field=field, row=row)
    if (isinstance(value, str) and "%" in value) or abs(number) >= 1.0:
        number /= 100.0
    low = -1.0 if signed else 0.0
    if not low < number < 1.0 and not (number == 0.0):
        raise IngestError(f"Row {row}: {field} {value!r} is out of range.")
    return number


def _to_term(value: object, header: str, row: int) -> int:
    if _blank(value):
        return 0
    text = str(value).strip().lower()
    number = _to_float(text, field="remaining term", row=row)
    in_years = "year" in header or bool(re.search(r"\d\s*(y|yr|yrs|year|years)\b", text))
    return max(int(round(number * 12 if in_years else number)), 0)


def _to_method(value: object) -> InterestMethod | None:
    if _blank(value):
        return None
    text = str(value).lower()
    if "compound" in text or "card" in text:
        return InterestMethod.DAILY_COMPOUND
    if "month" in text or "amort" in text:
        return InterestMethod.MONTHLY
    if "simple" in text or "daily" in text:
        return InterestMethod.SIMPLE_DAILY
    return None


def resolve_columns(frame: pd.DataFrame) -> dict[str, str]:
    lookup = {_normalise_header(col): col for col in frame.columns}
    resolved: dict[str, str] = {}
    used: set[str] = set()
    for field_name, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            column = lookup.get(alias)
            if column is not None and column not in used:
                resolved[field_name] = column
                used.add(column)
                break
    missing = [f for f in REQUIRED if f not in resolved]
    if missing:
        raise IngestError(
            "Could not find column(s) for: " + ", ".join(missing) + ".\n"
            "At minimum the file needs: Loan Name, Current Loan Value, Interest Rate.\n"
            "Found: " + ", ".join(str(c) for c in frame.columns)
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
            encoding="utf-8-sig" if not isinstance(source, io.StringIO) else None,
        )
    except Exception as exc:
        raise IngestError(f"Could not parse the file: {exc}") from exc
    frame = frame.dropna(axis=1, how="all")
    frame.columns = [str(c).strip() for c in frame.columns]
    return frame


def loans_from_frame(frame: pd.DataFrame) -> ImportResult:
    """Convert a raw table into validated `Loan` objects."""
    columns = resolve_columns(frame)
    loans: list[Loan] = []
    plan_names: list[str] = []
    errors: list[str] = []
    inferred = 0

    def get(row, key: str):
        return row[columns[key]] if key in columns else None

    for position, (_, row) in enumerate(frame.iterrows(), start=2):
        name = str(get(row, "name") or "").strip()
        if not name:
            continue
        try:
            balance = _to_float(get(row, "balance"), field="balance", row=position)
            rate = _to_percent(get(row, "rate"), field="interest rate", row=position)
            minimum = _optional_float(get(row, "minimum"), field="minimum payment", row=position)
            term = _to_term(get(row, "term"), _normalise_header(columns.get("term", "")), position)
            escrow = _optional_float(get(row, "escrow"), field="escrow", row=position)
            pmi = _optional_float(get(row, "pmi"), field="PMI", row=position)
            asset = _optional_float(get(row, "asset_value"), field="asset value", row=position)
            original = _optional_float(get(row, "original_value"), field="original value", row=position)
            growth_raw = get(row, "growth")
            growth = (
                None if _blank(growth_raw)
                else _to_percent(growth_raw, field="asset growth", row=position, signed=True)
            )
            if growth is not None and "depreciation" in _normalise_header(columns["growth"]):
                growth = -abs(growth)
        except IngestError as exc:
            errors.append(str(exc))
            continue

        if balance < 0:
            errors.append(f"Row {position}: negative balance for '{name}'.")
            continue

        type_text = str(get(row, "type") or "").strip()
        loan_type = parse_type(type_text) if type_text else None
        if loan_type is None:
            loan_type = infer_type(name)
            inferred += 1

        if minimum <= 0 and term <= 0 and balance > 0:
            errors.append(
                f"Row {position}: '{name}' needs a Minimum Payment or a Remaining Term."
            )
            continue

        loans.append(
            Loan(
                name=name,
                principal=round(balance, 2),
                annual_rate=rate,
                minimum_payment=round(max(minimum, 0.0), 2),
                servicer=str(get(row, "servicer") or "").strip(),
                sort_order=len(loans),
                loan_type=loan_type,
                interest_method=_to_method(get(row, "method")),
                term_months=term,
                escrow_monthly=round(max(escrow, 0.0), 2),
                pmi_monthly=round(max(pmi, 0.0), 2),
                asset_value=round(max(asset, 0.0), 2),
                original_value=round(max(original, 0.0), 2),
                asset_growth=growth,
            )
        )
        plan_names.append(str(get(row, "plan") or "").strip())

    if not loans:
        detail = "\n".join(errors[:5]) if errors else "No data rows were found."
        raise IngestError(f"No usable loans were read.\n{detail}")
    if errors:
        raise IngestError("Some rows could not be read:\n" + "\n".join(errors[:8]))
    return ImportResult(loans=loans, plan_names=plan_names, columns=columns, inferred_types=inferred)


def load_loans(source: str | Path) -> ImportResult:
    """Load loans from a `.csv`, `.tsv` or `.txt` file on disk."""
    path = Path(source)
    if not path.exists():
        raise IngestError(f"File not found: {path}")
    return loans_from_frame(read_table(path))


def load_loans_from_text(text: str) -> ImportResult:
    """Load loans from an in-memory delimited string (used for bundled data)."""
    return loans_from_frame(read_table(io.StringIO(text)))

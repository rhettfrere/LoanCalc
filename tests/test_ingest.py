from __future__ import annotations

import pytest

from loancalc.data import export, ingest
from loancalc.data.paths import sample_data_text
from loancalc.domain.loan_types import LoanType


def test_bundled_sample_imports_as_student_loans():
    result = ingest.load_loans_from_text(sample_data_text())
    assert len(result.loans) == 17
    assert {loan.loan_type for loan in result.loans} == {LoanType.STUDENT}
    assert sum(loan.principal for loan in result.loans) == pytest.approx(61_071.43)


def test_template_round_trips(tmp_path):
    export.export_template(tmp_path / "t.csv")
    result = ingest.load_loans(tmp_path / "t.csv")
    types = [loan.loan_type for loan in result.loans]
    assert types == [LoanType.STUDENT, LoanType.MORTGAGE, LoanType.AUTO, LoanType.CREDIT_CARD]
    mortgage = result.loans[1]
    assert mortgage.minimum_payment == 0 and mortgage.term_months == 348
    assert mortgage.effective_minimum > 0
    assert mortgage.escrow_monthly == 425 and mortgage.pmi_monthly == 135
    assert result.loans[2].asset_growth == pytest.approx(-0.15)


def test_tsv_with_aliases_and_years():
    text = "Account\tBalance\tAPR\tTerm Years\tVehicle Value\tDepreciation\nHonda auto loan\t20000\t6.9\t5\t22000\t15%\n"
    loan = ingest.load_loans_from_text(text).loans[0]
    assert loan.loan_type is LoanType.AUTO
    assert loan.annual_rate == pytest.approx(0.069)
    assert loan.term_months == 60
    assert loan.asset_value == 22_000
    assert loan.asset_growth == pytest.approx(-0.15)


def test_missing_required_column_is_explained():
    with pytest.raises(ingest.IngestError, match="Interest Rate"):
        ingest.load_loans_from_text("Name,Balance\nA,100\n")


def test_row_without_payment_or_term_is_rejected():
    with pytest.raises(ingest.IngestError, match="Minimum Payment or a Remaining Term"):
        ingest.load_loans_from_text("Name,Balance,Rate\nA,100,5%\n")


def test_type_column_overrides_inference():
    text = "Name,Balance,Rate,Minimum,Type,Plan\nMOHELA thing,100,5%,10,Personal,Family\n"
    result = ingest.load_loans_from_text(text)
    assert result.loans[0].loan_type is LoanType.PERSONAL
    assert result.plan_names == ["Family"]
    assert result.inferred_types == 0

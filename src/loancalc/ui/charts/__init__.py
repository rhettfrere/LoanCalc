"""Interactive pyqtgraph charts.

* `base`       — shared infrastructure (hover card, legend, axes)
* `plan`       — single-plan charts (burn-down, cost, payment mix, scenarios)
* `collateral` — equity vs balance for mortgages and auto loans
* `household`  — every active plan together, with rollover
"""
from loancalc.ui.charts.collateral import EquityChart
from loancalc.ui.charts.household import HouseholdBalanceChart, HouseholdCashFlowChart
from loancalc.ui.charts.plan import (
    BurndownChart,
    MonthlySplitChart,
    PrincipalInterestChart,
    ScenarioChart,
)

__all__ = [
    "BurndownChart",
    "EquityChart",
    "HouseholdBalanceChart",
    "HouseholdCashFlowChart",
    "MonthlySplitChart",
    "PrincipalInterestChart",
    "ScenarioChart",
]

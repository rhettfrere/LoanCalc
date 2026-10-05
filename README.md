```
LoanCalc/
├─ pyproject.toml              # deps + entry points
├─ build.py                    # Nuitka build script
├─ build.bat                   # one-shot Windows wrapper
└─ src/loancalc/
   ├─ __init__.py              # main() entry point
   ├─ __main__.py              # python -m loancalc
   ├─ app.py                   # bootstrap: store -> state -> window
   ├─ models.py                # Loan, Allocation, MonthResult, Schedule, PaymentRecord
   ├─ engine.py                # daily accrual + avalanche/snowball allocation
   ├─ ingest.py                # pandas TSV/CSV parsing and normalisation
   ├─ storage.py               # SQLite persistence
   ├─ state.py                 # AppState: single source of truth + signals
   ├─ paths.py                 # data dir, db path, bundled sample lookup
   ├─ formatting.py            # money / date / duration formatting
   ├─ core/
   │  ├─ theme.py              # palette + global stylesheet + widget helpers
   │  ├─ qt_app.py             # themed QApplication
   │  └─ logging_setup.py      # rotating file log
   ├─ ui/
   │  ├─ widgets.py            # MetricCard, Card, table helpers
   │  ├─ dashboard.py          # overview panel + payoff queue
   │  ├─ action_center.py      # "This Month's Payment"
   │  ├─ charts.py             # interactive pyqtgraph charts
   │  ├─ charts_tab.py         # visualizations tab
   │  ├─ loans_tab.py          # loan editor
   │  └─ history_tab.py        # payment log
   └─ initial_data/
      └─ raw_30Sept26.csv      # bundled starter dataset
```

## Run

```powershell
uv sync
uv run loancalc
```

## Build the .exe

```powershell
.\build.bat              # standalone folder -> build\__main__.dist\LoanCalc.exe
.\build.bat --onefile    # single file     -> build\LoanCalc.exe
```

## How it works

**Engine** — each month: accrue simple daily interest (`principal × rate × days / 365`),
cover every minimum in priority order, then funnel 100% of what's left onto the
single highest-rate loan, cascading the moment one is retired. Payments hit
accrued interest before principal.

**Deviations** — the Action Center previews any amount against untouched copies
of the loans, then logging it commits the accrual, saves the per-loan split, and
re-forecasts. Results are scored against a frozen *baseline* plan so you always
see interest saved/lost and months gained/given up.

**Data** — loans, payments, allocations and settings live in
`%LOCALAPPDATA%\LoanCalc\loancalc.db`. **File → Import User Data** accepts any
CSV/TSV with columns for name, balance, rate and minimum payment; headers are
matched by alias and `$1,234.56` / `4.99%` are normalised automatically.

**Charts** — pyqtgraph. Scroll to zoom, drag to pan, right-click for options,
hover for an exact month-by-month readout, click legend chips to isolate series.

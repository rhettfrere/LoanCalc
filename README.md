# LoanCalc

Debt payoff planning for **student loans, mortgages, auto loans, personal loans and credit
cards**. You can plan each group of debts on its own, or as a **household** where paying off
one plan frees up money for the others.

- **Plans** group the loans that share a monthly budget and a strategy (avalanche, snowball or
  highest balance). Examples: *Student Loans* at $5,000/mo, or *Mortgage* at its P&I payment.
- **Household** runs every active plan together. When a plan is paid off, its budget **rolls
  over** to the plans that still carry debt. You can see the effect against an "each plan on its
  own" baseline.
- **Loan-type modelling:**
  - Student and auto loans accrue simple daily interest.
  - Mortgages and personal loans use monthly amortisation.
  - Credit cards compound daily.
  - Mortgages track escrow and **PMI** (which drops off at 78% of the original value) and **home
    equity**.
  - Auto loans track vehicle depreciation and flag when you're **underwater**.
- **Action Center:** log a real payment for any month and see exactly how it was split.
- **Sandbox:** build what-if scenarios with **pins**, such as a tax refund every April, a bonus in
  October or a lean holiday month. Each scenario is scored against the plan and the whole
  household.
- **Interactive charts:** hover tooltips, zoom/pan and clickable legends. Charts include
  burn-down, repayment over time, principal vs interest vs PMI, payment mix, equity, household
  balance and household cash flow.

---

## Quick start

```powershell
uv sync                 # install runtime + dev dependencies
uv run loancalc         # launch the app
uv run pytest -q        # run the test suite
```

On first launch the bundled starter data (`resources/sample_data/raw_30Sept26.csv`) is loaded
into a *Student Loans* plan. Add more debts with **Add loan…** or **File → Import Loans…**.

---

## Importing data

**File → Import Loans…** (`Ctrl+O`) reads `.csv`, `.tsv` or `.txt` files. The delimiter is
detected automatically. Before anything is written you get a preview showing every row, the
loan type and plan it will join, and which column each field was read from.

### Merge or replace

| Mode | What happens | Use it for |
|---|---|---|
| **Merge** *(default)* | New loans are added. A loan whose **name already exists in the same plan** is updated in place, keeping its history. | Refreshing balances from a new statement; adding a mortgage to an existing student-loan setup |
| **Replace** | Deletes **all** plans, loans, payment history and scenarios, then imports. | Starting fresh; loading someone else's data into a shared `.exe` |

### Columns

Only **Loan Name**, **Current Loan Value** and **Interest Rate** are required. Each row also
needs either a **Minimum Payment** or a **Remaining Term**. Headers ignore case, spaces and
punctuation, and common alternatives are accepted (`Balance`, `APR`, `Monthly Payment` and so
on).

| Column | Required | Notes |
|---|---|---|
| Loan Name | ✔ | Unique within a plan; used to match rows when merging |
| Current Loan Value | ✔ | Payoff balance. `$12,345.67` or `12345.67` |
| Interest Rate | ✔ | `5.5%`, `5.5` or `0.055` |
| Minimum Payment | ✔* | Monthly minimum. For mortgages this is **P&I only**, without escrow. *Can be blank if a term is given |
| Loan Type | | `Student`, `Mortgage`, `Auto`, `Personal`, `Credit Card`, `Other`. Guessed from the name if missing |
| Plan | | Plan to join. Defaults by type (e.g. *Mortgage*). A new name creates a new plan |
| Servicer | | Free text |
| Remaining Term (months) | | Months left. `5y` / `5 years` are converted. Used to calculate P&I when the minimum is blank |
| Escrow (monthly) | | Mortgage: taxes + insurance. Shown as part of the housing payment; never reduces the debt |
| PMI (monthly) | | Mortgage: charged until the balance reaches 78% of the original value |
| Asset Value | | Current home or vehicle value. Drives the equity chart |
| Original Value | | Mortgage purchase price or appraisal. PMI is measured against this |
| Asset Growth (annual %) | | `3%` appreciation or `-15%` depreciation. A header containing "depreciation" makes the value negative |
| Interest Method | | Override accrual: `simple`, `monthly` or `compound` |

**File → Save Import Template…** writes a CSV with all of these columns and example student,
mortgage, auto and credit-card rows. Fill it in and import it.

## Exporting and backups

| File menu | Output |
|---|---|
| Export → **Loans…** | Every loan in every plan, in the import format (re-importable) |
| Export → **Plan Schedule…** | Monthly forecast for the selected plan: payment, interest, principal, PMI, escrow, balance, payoffs |
| Export → **Household Schedule…** | Combined forecast for all active plans, with per-plan balances and the amount rolled over each month |
| Export → **Payment History…** | Every logged payment, one row per loan it touched |
| **Back Up Data…** / **Restore From Backup…** | Everything (plans, loans, history, scenarios, pins, presets, settings) in one `.db` file. The best way to move to another PC |

Live data is stored in `%LOCALAPPDATA%\LoanCalc\loancalc.db`. When the database schema is
upgraded, a timestamped copy is first saved to `%LOCALAPPDATA%\LoanCalc\backups\`.
The same guide is available inside the app under **Help → Import & Export Guide** (`F1`), and
every File-menu item has a tooltip.

---

## Building the .exe

```powershell
.\build.bat              # sync, test, then build -> build\__main__.dist\LoanCalc.exe
.\build.bat --onefile    # single distributable    -> build\LoanCalc.exe
.\build.bat --console    # keep a console window for debugging
```

`build.py` embeds `src/loancalc/resources/loancalc.ico` as the executable icon. It also bundles
the whole `resources/` folder, so the running window and taskbar use the same icon. The version
is read from `loancalc.__version__`.

---

## Project layout

```
LoanCalc/
├─ pyproject.toml            dependencies, entry points, pytest config
├─ build.py / build.bat      Nuitka build (icon, resources, flags)
├─ docs/                     original requirements
├─ tests/                    pytest suite (domain, ingest, storage/migrations)
└─ src/loancalc/
   ├─ app.py                 bootstrap: store → state → window
   ├─ domain/                pure Python, no Qt — unit-testable
   │  ├─ loan_types.py       type registry: accrual, collateral, defaults, inference
   │  ├─ models.py           Loan, Plan, Pin, Scenario, Schedule, …
   │  ├─ amortization.py     P&I, remaining term, LTV, PMI, asset growth
   │  ├─ engine.py           single-plan monthly simulation
   │  ├─ household.py        multi-plan simulation with rollover
   │  └─ periods.py          month arithmetic
   ├─ data/                  persistence and file interchange
   │  ├─ storage.py          SQLite repository
   │  ├─ migrations.py       versioned schema upgrades (+ automatic backup)
   │  ├─ ingest.py           CSV/TSV import with header aliases
   │  ├─ export.py           CSV exports and template
   │  └─ paths.py            data dir, resources, icon
   ├─ services/state.py      AppState: single source of truth + Qt signals
   ├─ ui/
   │  ├─ theme.py, qt_app.py, widgets.py, main_window.py
   │  ├─ charts/             base · plan · collateral · household
   │  ├─ tabs/               household · dashboard · action_center · sandbox ·
   │  │                      visualizations · loans · history
   │  └─ dialogs/            loan · plan manager · pin/presets · import preview · help
   ├─ util/                  formatting, logging
   └─ resources/             loancalc.ico, sample_data/
```

The dependencies only point downwards: `ui → services → data → domain`. The domain layer never
imports Qt.

### Extending

- **New loan type:** add an entry to `SPECS` in `domain/loan_types.py`. Accrual, colours, default
  plan and the editor's fields all follow from it.
- **Schema change:** add a `_vN_to_vN+1` step in `data/migrations.py` and bump `SCHEMA_VERSION`.
- **New chart:** subclass `InteractiveChart` in `ui/charts/`, implement `render()` and
  `on_hover()`.

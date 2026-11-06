"""Tables from the expansion and dispatch runs: system cost and capacities per weather year, and how fleets built for
one weather year cope with all others.

    python scripts/analyse.py            (6-hour step, results/step6h)

Total cost of fleet f in weather year y = annualised capital cost of f + operating cost of dispatching f in y
(fuel of the backup plants and lost load at the value of lost load). Regret = that total minus the optimal system cost
for y, which is the expansion result for y.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from weatheryears import inputs  # noqa: E402

STEP = int(os.environ.get("WEATHER_STEP_HOURS", 6))
RES = ROOT / "results" / f"step{STEP}h"
OUT = ROOT / "results" / "tables"

TECH = {"backup": "OCGT", "solar": "solar-utility", "onwind": "onwind", "offwind": "offwind",
        "battery store": "battery storage", "battery charge": "battery inverter", "H2 store": "hydrogen storage underground",
        "electrolysis": "electrolysis", "fuel cell": "fuel cell"}
GROUP = {"backup": "backup_gw", "solar": "solar_gw", "onwind": "onwind_gw", "offwind": "offwind_gw",
         "battery charge": "battery_gw", "battery store": "battery_gwh", "electrolysis": "electrolysis_gw",
         "fuel cell": "fuel_cell_gw", "H2 store": "h2_store_gwh"}


def asset(name: str) -> str:
    return name.split(" ", 1)[1]


def capital_cost(fleet: dict, costs: pd.DataFrame) -> float:
    """Annualised capital cost of the extendable assets, EUR/a (battery discharge carries no cost of its own)."""
    return sum(mw * costs.loc[TECH[asset(k)], "capital_cost"] for k, mw in fleet.items() if asset(k) in TECH)


def capacities(fleet: dict) -> dict:
    out = dict.fromkeys(GROUP.values(), 0.0)
    for k, mw in fleet.items():
        if asset(k) in GROUP:
            out[GROUP[asset(k)]] += mw / 1000
    return out


def main() -> None:
    costs = inputs.load_costs()
    exp = {}
    for p in sorted((RES / "expansion").glob("[0-9]*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        exp[r["year"]] = r
    rows = []
    for y, r in exp.items():
        capex = capital_cost(r["fleet"], costs)
        rows.append({"year": y, "system_cost_bn": r["objective"] / 1e9, "capital_bn": capex / 1e9,
                     "operating_bn": (r["objective"] - capex) / 1e9, "backup_twh": r["backup_mwh"] / 1e6,
                     "backup_share": r["backup_mwh"] / r["demand_mwh"], "shed_gwh": r["shed_mwh"] / 1e3, **capacities(r["fleet"])})
    years = pd.DataFrame(rows).sort_values("year").reset_index(drop=True)

    d = []
    for p in sorted((RES / "dispatch").glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        f, y = r["fleet"], r["weather"]
        capex = capital_cost(exp[f]["fleet"], costs)
        total = capex + r["objective"]
        d.append({"fleet": f, "weather": y, "total_bn": total / 1e9, "optimal_bn": exp[y]["objective"] / 1e9,
                  "regret_bn": (total - exp[y]["objective"]) / 1e9, "shed_gwh": r["shed_mwh"] / 1e3, "shed_steps": r["shed_steps"]})
    disp = pd.DataFrame(d).sort_values(["fleet", "weather"]).reset_index(drop=True)
    summary = disp[disp["fleet"] != disp["weather"]].groupby("fleet").agg(
        years=("weather", "size"), years_with_shed=("shed_gwh", lambda s: int((s > 1).sum())), mean_shed_gwh=("shed_gwh", "mean"),
        max_shed_gwh=("shed_gwh", "max"), mean_regret_bn=("regret_bn", "mean"), max_regret_bn=("regret_bn", "max"),
        mean_total_bn=("total_bn", "mean")).reset_index()
    summary["built_for_cost_bn"] = summary["fleet"].map(lambda f: exp[f]["objective"] / 1e9)

    OUT.mkdir(parents=True, exist_ok=True)
    years.to_csv(OUT / f"expansion_by_year_{STEP}h.csv", index=False, float_format="%.4f")
    disp.to_csv(OUT / f"dispatch_{STEP}h.csv", index=False, float_format="%.4f")
    summary.to_csv(OUT / f"fleet_summary_{STEP}h.csv", index=False, float_format="%.4f")

    pd.set_option("display.width", 200)
    print(years.describe().T[["mean", "min", "max"]].round(2).to_string())
    print(summary.round(2).to_string())
    own = disp[disp["fleet"] == disp["weather"]]
    if len(own):
        print("own-year check (regret should be about 0):", own[["fleet", "regret_bn"]].round(3).to_dict("records"))

    three = ROOT / "results" / "expansion" / "2010.json"
    if three.exists() and 2010 in exp:
        a, b = json.loads(three.read_text(encoding="utf-8")), exp[2010]
        ca, cb = capacities(a["fleet"]), capacities(b["fleet"])
        comp = pd.DataFrame({"3h": {"system_cost_bn": a["objective"] / 1e9, "backup_twh": a["backup_mwh"] / 1e6, **ca},
                             f"{STEP}h": {"system_cost_bn": b["objective"] / 1e9, "backup_twh": b["backup_mwh"] / 1e6, **cb}})
        comp["difference"] = comp[f"{STEP}h"] / comp["3h"] - 1
        comp.to_csv(OUT / "step_comparison_2010.csv", float_format="%.4f")
        print(comp.round(3).to_string())


if __name__ == "__main__":
    main()

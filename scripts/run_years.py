"""Capacity expansion for each weather year, then each chosen fleet dispatched on all weather years.

    python scripts/run_years.py expand 1985 2019
    python scripts/run_years.py dispatch 1985 2019
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from weatheryears import inputs, model  # noqa: E402

OUT = ROOT / "results" / (f"step{model.STEP_HOURS}h" + (f"_backup{model.BACKUP_FUEL:g}" if model.BACKUP_FUEL != 200 else ""))
THREADS = int(sys.argv[4]) if len(sys.argv) > 4 else 4


def setting():
    return inputs.load_profiles(), inputs.load_demand(), inputs.load_costs(), inputs.transfer_limits(), inputs.existing_fleet()


def expand(year: int, base) -> None:
    path = OUT / "expansion" / f"{year}.json"
    if path.exists():
        return
    cf, demand, costs, limits, existing = base
    t0 = time.time()
    n = model.build(model.weather_year(cf, year), demand, costs, limits, existing)
    model.solve(n, THREADS)
    price = model.load_weighted_price(n)
    load = n.loads_t.p_set[inputs.ZONES].sum(axis=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"price": price, "load": load}).to_parquet(OUT / "expansion" / f"{year}_price.parquet")
    n.buses_t.marginal_price[inputs.ZONES].to_parquet(OUT / "expansion" / f"{year}_zone_price.parquet")
    shed = n.generators_t.p[[f"{z} shed" for z in inputs.ZONES]].sum(axis=1) * model.STEP_HOURS
    backup = n.generators_t.p[[f"{z} backup" for z in inputs.ZONES]].sum(axis=1) * model.STEP_HOURS
    path.write_text(json.dumps({"year": year, "objective": float(n.objective), "seconds": round(time.time() - t0), "shed_mwh": float(shed.sum()),
                                "backup_mwh": float(backup.sum()), "demand_mwh": float(load.sum() * model.STEP_HOURS), "fleet": model.fleet_of(n)}, indent=1), encoding="utf-8")
    print(year, "objective bn", round(n.objective / 1e9, 1), "s", round(time.time() - t0), flush=True)


def dispatch(fleet_year: int, year: int, base) -> None:
    path = OUT / "dispatch" / f"fleet{fleet_year}_weather{year}.json"
    if path.exists():
        return
    cf, demand, costs, limits, existing = base
    fleet = json.loads((OUT / "expansion" / f"{fleet_year}.json").read_text(encoding="utf-8"))["fleet"]
    n = model.build(model.weather_year(cf, year), demand, costs, limits, existing, fleet=fleet)
    model.solve(n, THREADS)
    shed = n.generators_t.p[[f"{z} shed" for z in inputs.ZONES]] * model.STEP_HOURS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fleet": fleet_year, "weather": year, "objective": float(n.objective), "shed_mwh": float(shed.sum().sum()),
                                "shed_by_zone": shed.sum().to_dict(), "shed_steps": int((shed.sum(axis=1) > 1).sum())}, indent=1), encoding="utf-8")
    print("fleet", fleet_year, "weather", year, "shed TWh", round(shed.sum().sum() / 1e6, 2), flush=True)


if __name__ == "__main__":
    mode, first, last = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    base = setting()
    if mode == "expand":
        for y in range(first, last + 1):
            expand(y, base)
    elif mode == "dispatch":
        fleets = [int(x) for x in sys.argv[5].split(",")]
        for f in fleets:
            for y in range(first, last + 1):
                if y != f:
                    dispatch(f, y, base)

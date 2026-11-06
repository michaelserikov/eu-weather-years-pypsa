"""A greenfield-renewables capacity expansion of northwestern Europe for one weather year, in PyPSA.

Nodes are countries, with a transport model between them. Nuclear and hydro are existing. Wind, solar, batteries and
hydrogen storage are chosen by the optimiser, and a costly dispatchable backup and load shedding close the balance.
With `fleet` given, capacities are fixed and only dispatch is solved.
"""

from __future__ import annotations

import os
import warnings

import numpy as np
import pandas as pd
import pypsa

from . import inputs

STEP_HOURS = int(os.environ.get("WEATHER_STEP_HOURS", 3))
VOLL = 8000.0            # EUR/MWh, assumed
BACKUP_FUEL = float(os.environ.get("WEATHER_BACKUP_FUEL", 200.0))  # EUR/MWh electric, assumed price of low-carbon fuel
RESERVOIR_HOURS = 1500.0 # assumed storage energy per MW of reservoir hydro
PHS_HOURS = 6.0


def weather_year(cf: pd.DataFrame, year: int, step: int = STEP_HOURS) -> pd.DataFrame:
    """Capacity factors of one weather year on a non-leap calendar, averaged to the model step."""
    d = inputs.no_leap(cf[cf.index.year == year])
    return inputs.no_leap(d.resample(f"{step}h").mean())


def demand_on(index: pd.DatetimeIndex, demand: pd.DataFrame, step: int = STEP_HOURS) -> pd.DataFrame:
    """The demand year averaged to the step, placed on the calendar of the weather year by position."""
    d = demand.resample(f"{step}h").mean().dropna(how="all")
    d = d.iloc[: len(index)]
    if len(d) != len(index):
        raise ValueError(f"demand has {len(d)} steps, weather {len(index)}")
    return d.set_axis(index)


def profile_columns(cf: pd.DataFrame, zone: str) -> dict[str, str]:
    """Column per carrier for a zone. Countries without a split use the national wind series as onshore."""
    out = {"solar": f"{zone}_pv_national_current"}
    on, nat, off = f"{zone}_wind_onshore_current", f"{zone}_wind_national_current", f"{zone}_wind_offshore_current"
    out["onwind"] = on if on in cf else nat
    if off in cf:
        out["offwind"] = off
    return out


def build(cf: pd.DataFrame, demand: pd.DataFrame, costs: pd.DataFrame, limits: pd.DataFrame, fleet_existing: pd.DataFrame,
          zones: list[str] | None = None, fleet: dict | None = None, step: int = STEP_HOURS) -> pypsa.Network:
    zones = zones or list(inputs.ZONES)
    n = pypsa.Network()
    n.set_snapshots(cf.index)
    n.snapshot_weightings.loc[:, :] = float(step)
    dem = demand_on(cf.index, demand, step)
    fixed = fleet or {}

    def cap(name: str) -> dict:
        """Extendable with bounds, or fixed at the given fleet."""
        if fleet is not None:
            return {"p_nom": fixed.get(name, 0.0), "p_nom_extendable": False}
        return {"p_nom_extendable": True}

    for z in zones:
        n.add("Bus", z, carrier="AC")
        n.add("Load", z, bus=z, p_set=dem[z])
        n.add("Generator", f"{z} shed", bus=z, carrier="shed", marginal_cost=VOLL, p_nom=float(dem[z].max()))
        n.add("Generator", f"{z} backup", bus=z, carrier="backup", marginal_cost=BACKUP_FUEL,
              capital_cost=costs.loc["OCGT", "capital_cost"], **cap(f"{z} backup"))
        cols = profile_columns(cf, z)
        limit = {"solar": 1500.0 * inputs.LAND_KM2[z], "onwind": 1000.0 * inputs.LAND_KM2[z], "offwind": 1000.0 * inputs.OFFSHORE_GW.get(z, 0)}
        tech = {"solar": "solar-utility", "onwind": "onwind", "offwind": "offwind"}
        for carrier, col in cols.items():
            if limit[carrier] <= 0:
                continue
            kw = cap(f"{z} {carrier}")
            if fleet is None:
                kw["p_nom_max"] = limit[carrier]
            n.add("Generator", f"{z} {carrier}", bus=z, carrier=carrier, p_max_pu=cf[col].clip(0, 1).fillna(0.0),
                  capital_cost=costs.loc[tech[carrier], "capital_cost"], **kw)
        existing = fleet_existing.loc[z]
        if existing.get("Nuclear", 0) > 0:
            n.add("Generator", f"{z} nuclear", bus=z, carrier="nuclear", p_nom=existing["Nuclear"],
                  p_max_pu=inputs.NUCLEAR_AVAILABILITY, marginal_cost=10.0)
        if existing.get("Run-Of-River", 0) > 0:
            n.add("Generator", f"{z} ror", bus=z, carrier="ror", p_nom=existing["Run-Of-River"], p_max_pu=inputs.HYDRO_CF["Run-Of-River"])
        if existing.get("Reservoir", 0) > 0:
            p = existing["Reservoir"]
            n.add("StorageUnit", f"{z} reservoir", bus=z, carrier="reservoir", p_nom=p, max_hours=RESERVOIR_HOURS, p_min_pu=0.0,
                  inflow=p * inputs.HYDRO_CF["Reservoir"], efficiency_dispatch=1.0, efficiency_store=1.0, cyclic_state_of_charge=True)
        if existing.get("Pumped Storage", 0) > 0:
            n.add("StorageUnit", f"{z} phs", bus=z, carrier="phs", p_nom=existing["Pumped Storage"], max_hours=PHS_HOURS,
                  efficiency_store=0.87, efficiency_dispatch=0.87, cyclic_state_of_charge=True)
        add_storage(n, z, costs, fixed, fleet is not None)
    for _, r in limits.iterrows():
        if r["a"] in zones and r["b"] in zones:
            n.add("Link", f"{r['a']}-{r['b']} {r['kind']}", bus0=r["a"], bus1=r["b"], p_nom=float(r["mw"]), p_min_pu=-1.0, efficiency=1.0, carrier=r["kind"])
    return n


def add_storage(n: pypsa.Network, z: str, costs: pd.DataFrame, fixed: dict, is_fixed: bool) -> None:
    """Battery and hydrogen storage: energy stores behind charge and discharge links."""
    def link_cap(name):
        return {"p_nom": fixed.get(name, 0.0), "p_nom_extendable": False} if is_fixed else {"p_nom_extendable": True}

    def store_cap(name):
        return {"e_nom": fixed.get(name, 0.0), "e_nom_extendable": False} if is_fixed else {"e_nom_extendable": True}

    n.add("Bus", f"{z} battery", carrier="battery")
    n.add("Store", f"{z} battery store", bus=f"{z} battery", e_cyclic=True, capital_cost=costs.loc["battery storage", "capital_cost"], **store_cap(f"{z} battery store"))
    eta = float(costs.loc["battery inverter", "efficiency"])
    n.add("Link", f"{z} battery charge", bus0=z, bus1=f"{z} battery", efficiency=eta, capital_cost=costs.loc["battery inverter", "capital_cost"], **link_cap(f"{z} battery charge"))
    n.add("Link", f"{z} battery discharge", bus0=f"{z} battery", bus1=z, efficiency=eta, **link_cap(f"{z} battery discharge"))
    n.add("Bus", f"{z} H2", carrier="H2")
    n.add("Store", f"{z} H2 store", bus=f"{z} H2", e_cyclic=True, capital_cost=costs.loc["hydrogen storage underground", "capital_cost"], **store_cap(f"{z} H2 store"))
    n.add("Link", f"{z} electrolysis", bus0=z, bus1=f"{z} H2", efficiency=float(costs.loc["electrolysis", "efficiency"]),
          capital_cost=costs.loc["electrolysis", "capital_cost"], **link_cap(f"{z} electrolysis"))
    n.add("Link", f"{z} fuel cell", bus0=f"{z} H2", bus1=z, efficiency=float(costs.loc["fuel cell", "efficiency"]),
          capital_cost=costs.loc["fuel cell", "capital_cost"], **link_cap(f"{z} fuel cell"))


def tie_battery(n: pypsa.Network) -> None:
    """Discharge capacity equals charge capacity for batteries, in efficiency-free MW."""
    m = n.model
    for z in n.buses.index[n.buses.carrier == "AC"]:
        a, b = f"{z} battery charge", f"{z} battery discharge"
        if a in n.links.index and n.links.at[a, "p_nom_extendable"]:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                m.add_constraints(m["Link-p_nom"].loc[a] - m["Link-p_nom"].loc[b] == 0, name=f"tie-{z}")


def solve(n: pypsa.Network, threads: int = 4) -> None:
    options = {"solver": "ipm", "run_crossover": "off", "threads": threads, "output_flag": False}
    n.optimize.create_model()
    tie_battery(n)
    status, condition = n.optimize.solve_model(solver_name="highs", **options)
    if status != "ok":
        raise RuntimeError(f"solver: {status}, {condition}")


def fleet_of(n: pypsa.Network) -> dict:
    """Optimal capacities of the extendable assets."""
    out = {}
    g = n.generators[n.generators.p_nom_extendable]
    out.update(g.p_nom_opt.to_dict())
    k = n.links[n.links.p_nom_extendable]
    out.update(k.p_nom_opt.to_dict())
    s = n.stores[n.stores.e_nom_extendable]
    out.update(s.e_nom_opt.to_dict())
    return {key: float(v) for key, v in out.items()}


def load_weighted_price(n: pypsa.Network) -> pd.Series:
    """Hourly load-weighted electricity shadow price across the AC buses, EUR/MWh."""
    buses = n.buses.index[n.buses.carrier == "AC"]
    load = n.loads_t.p_set[buses]
    return (n.buses_t.marginal_price[buses] * load).sum(axis=1) / load.sum(axis=1)


def events(price: pd.Series, load: pd.Series, threshold: float, step: int = STEP_HOURS) -> pd.DataFrame:
    """Runs of steps with the price at or above the threshold, with their duration and share of the annual electricity bill."""
    bill = price * load * step
    hot = price >= threshold
    group = (hot != hot.shift(fill_value=False)).cumsum()[hot]
    rows = [{"start": g.index[0], "end": g.index[-1], "hours": len(g) * step, "mean_price": float(price[g.index].mean()), "bill_share": float(bill[g.index].sum() / bill.sum())}
            for _, g in hot[hot].groupby(group)]
    return pd.DataFrame(rows, columns=["start", "end", "hours", "mean_price", "bill_share"])


def concentration(price: pd.Series, load: pd.Series, share_of_time: float = 0.01) -> float:
    """Share of the annual electricity bill in the most expensive given share of time."""
    bill = (price * load).to_numpy()
    k = max(int(np.ceil(len(bill) * share_of_time)), 1)
    return float(np.sort(bill)[-k:].sum() / bill.sum())

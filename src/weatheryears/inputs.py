"""Open inputs for a country-level model of northwestern Europe.

Renewable profiles: renewables.ninja national capacity factors, current fleet, via Open Power System Data (CC BY-NC 4.0).
Demand: ENTSO-E actual load via Open Power System Data. Costs: PyPSA technology-data for 2030.
Transfer limits: AC line ratings between countries from the PyPSA-Eur prebuilt network, and HVDC links from HVDC_MW below.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
ZONES = ["DE", "FR", "BE", "NL", "AT", "CH", "DK", "NO", "SE", "GB", "PL", "CZ"]
DEMAND_YEAR = 2018
DISCOUNT = 0.07
AC_DERATE = 0.7

# Assumptions: rounded public project capacities, entered by hand, MW. Not from a single dataset.
HVDC_MW = {("DE", "NO"): 1400, ("NL", "NO"): 700, ("GB", "NO"): 1400, ("GB", "NL"): 1000, ("BE", "GB"): 1000,
           ("FR", "GB"): 4000, ("DK", "GB"): 1400, ("DE", "DK"): 600, ("DE", "SE"): 600, ("PL", "SE"): 600,
           ("DK", "NL"): 700, ("DK", "NO"): 1700, ("DK", "SE"): 740}
# Assumed potentials: onshore wind 1 MW and solar 1.5 MW per km2 of land (thousand km2 below), offshore wind in GW.
LAND_KM2 = {"DE": 357, "FR": 544, "BE": 31, "NL": 41, "AT": 84, "CH": 41, "DK": 43, "NO": 324, "SE": 450, "GB": 244, "PL": 313, "CZ": 79}
OFFSHORE_GW = {"DE": 70, "FR": 40, "BE": 8, "NL": 70, "DK": 40, "NO": 30, "SE": 30, "GB": 120, "PL": 30}
HYDRO_CF = {"Reservoir": 0.35, "Run-Of-River": 0.50}     # assumed annual capacity factors; inflow is flat over the year
NUCLEAR_AVAILABILITY = 0.85


def annuity(rate: float, lifetime: float) -> float:
    """Annual payment per unit of investment."""
    return rate / (1 - (1 + rate) ** -lifetime)


def load_costs(path: Path = RAW / "costs_2030.csv") -> pd.DataFrame:
    """Annualised capital cost in EUR/MW/a or EUR/MWh/a, plus marginal cost and efficiency, per technology."""
    c = pd.read_csv(path)
    value = c.pivot_table(index="technology", columns="parameter", values="value", aggfunc="first")
    unit = c.drop_duplicates(["technology", "parameter"]).set_index(["technology", "parameter"])["unit"]
    out = {}
    for tech in value.index:
        row = value.loc[tech]
        inv, life = row.get("investment"), row.get("lifetime")
        if pd.isna(inv) or pd.isna(life):
            continue
        u = str(unit.get((tech, "investment"), ""))
        inv = inv * 1000 if "/kW" in u else inv     # EUR/kW or EUR/kWh to per MW or MWh
        fom = 0 if pd.isna(row.get("FOM")) else row.get("FOM")
        out[tech] = {"capital_cost": inv * (annuity(DISCOUNT, life) + fom / 100),
                     "efficiency": row.get("efficiency"), "VOM": 0 if pd.isna(row.get("VOM")) else row.get("VOM")}
    return pd.DataFrame(out).T


def ac_capacity(buses: pd.DataFrame, lines: pd.DataFrame, zones: list[str] = ZONES, derate: float = AC_DERATE) -> pd.Series:
    """Derated sum of AC line ratings between each pair of countries, MW."""
    country = buses["country"]
    a, b = lines["bus0"].map(country), lines["bus1"].map(country)
    keep = (a != b) & a.isin(zones) & b.isin(zones) & (lines["under_construction"] == "f")
    low = np.minimum(a[keep].astype(str), b[keep].astype(str))
    high = np.maximum(a[keep].astype(str), b[keep].astype(str))
    return lines.loc[keep, "s_nom"].groupby([low, high]).sum() * derate


def transfer_limits() -> pd.DataFrame:
    """AC and HVDC transfer limits per pair of countries."""
    buses = pd.read_csv(RAW / "buses.csv", quotechar="'", index_col="bus_id")
    lines = pd.read_csv(RAW / "lines.csv", quotechar="'", usecols=["bus0", "bus1", "s_nom", "under_construction"])
    ac = ac_capacity(buses, lines)
    rows = [{"a": a, "b": b, "kind": "ac", "mw": mw} for (a, b), mw in ac.items()]
    rows += [{"a": min(p), "b": max(p), "kind": "hvdc", "mw": mw} for p, mw in HVDC_MW.items() if set(p) <= set(ZONES)]
    return pd.DataFrame(rows)


def existing_fleet(zones: list[str] = ZONES, year: int = 2026) -> pd.DataFrame:
    """Installed nuclear and hydro per country in MW, from powerplantmatching."""
    names = {"Germany": "DE", "France": "FR", "Belgium": "BE", "Netherlands": "NL", "Austria": "AT", "Switzerland": "CH",
             "Denmark": "DK", "Norway": "NO", "Sweden": "SE", "United Kingdom": "GB", "Poland": "PL", "Czech Republic": "CZ", "Czechia": "CZ"}
    p = pd.read_csv(RAW / "powerplants.csv", low_memory=False)
    p = p[p["Country"].map(names).isin(zones)]
    p = p[(p["DateOut"].isna() | (p["DateOut"] > year)) & (p["DateIn"].isna() | (p["DateIn"] <= year))]
    p = p[p["Fueltype"].isin(["Nuclear", "Hydro"])]
    tech = np.where(p["Fueltype"] == "Nuclear", "Nuclear", p["Technology"].fillna("Run-Of-River"))
    tech = pd.Series(tech, index=p.index).replace({"Pumped Storage": "Pumped Storage"})
    out = p.assign(zone=p["Country"].map(names), tech=tech).groupby(["zone", "tech"])["Capacity"].sum().unstack(fill_value=0.0)
    return out.reindex(zones).fillna(0.0)


def no_leap(frame: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    return frame[~((frame.index.month == 2) & (frame.index.day == 29))]


def load_profiles(zones: list[str] = ZONES) -> pd.DataFrame:
    """All hourly capacity factors, columns such as DE_wind_onshore_current. Cached as parquet."""
    cache = RAW / "ninja.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    cols = pd.read_csv(RAW / "ninja_pv_wind_profiles_singleindex.csv", nrows=0).columns
    use = [c for c in cols if c[:2] in zones and (c.endswith("_pv_national_current") or c.endswith("_wind_onshore_current")
                                                  or c.endswith("_wind_offshore_current") or c.endswith("_wind_national_current"))]
    time_col = cols[0]
    d = pd.read_csv(RAW / "ninja_pv_wind_profiles_singleindex.csv", usecols=[time_col] + use, parse_dates=[time_col], index_col=time_col)
    d.index = d.index.tz_localize(None) if d.index.tz is not None else d.index
    d.to_parquet(cache)
    return d


def load_demand(zones: list[str] = ZONES, year: int = DEMAND_YEAR) -> pd.DataFrame:
    """Hourly actual load of the demand year, MW, gaps interpolated."""
    name = {z: f"{ {'GB': 'GB_UKM'}.get(z, z) }_load_actual_entsoe_transparency" for z in zones}
    cols = pd.read_csv(RAW / "time_series_60min_singleindex.csv", nrows=0).columns
    missing = [c for c in name.values() if c not in cols]
    if missing:
        raise KeyError(f"missing load columns: {missing}")
    d = pd.read_csv(RAW / "time_series_60min_singleindex.csv", usecols=["utc_timestamp"] + list(name.values()),
                    parse_dates=["utc_timestamp"], index_col="utc_timestamp")
    d.index = d.index.tz_localize(None) if d.index.tz is not None else d.index
    d = d[d.index.year == year].rename(columns={v: k for k, v in name.items()}).interpolate(limit_direction="both")
    return no_leap(d)

import numpy as np
import pandas as pd
import pytest

from weatheryears import inputs, model


def test_annuity_matches_hand_value():
    assert inputs.annuity(0.07, 20) == pytest.approx(0.09439, abs=1e-4)


def test_ac_capacity_sums_cross_border_lines_and_derates():
    buses = pd.DataFrame({"country": ["DE", "DE", "FR", "IT"]}, index=list("abcd"))
    lines = pd.DataFrame({"bus0": ["a", "b", "a", "c"], "bus1": ["c", "c", "b", "d"], "s_nom": [100.0, 50.0, 999.0, 7.0],
                          "under_construction": ["f", "f", "f", "f"]})
    out = inputs.ac_capacity(buses, lines, zones=["DE", "FR"], derate=0.5)
    assert out.loc[("DE", "FR")] == pytest.approx(75.0)
    assert len(out) == 1


def test_events_finds_runs_and_bill_shares():
    index = pd.date_range("2000-01-01", periods=6, freq="3h")
    price = pd.Series([10, 100, 100, 10, 200, 10.0], index=index)
    load = pd.Series(1.0, index=index)
    e = model.events(price, load, 100.0)
    assert list(e["hours"]) == [6, 3]
    assert e["bill_share"].sum() == pytest.approx(400 / 430)


def test_concentration_of_one_expensive_step():
    index = pd.date_range("2000-01-01", periods=100, freq="3h")
    price = pd.Series(1.0, index=index)
    price.iloc[5] = 101.0
    assert model.concentration(price, pd.Series(1.0, index=index), 0.01) == pytest.approx(101 / 200)


def small_case():
    index = pd.date_range("2000-01-01", periods=8760, freq="h")
    cf = pd.DataFrame({"AA_pv_national_current": 0.2, "AA_wind_national_current": 0.3,
                       "BB_pv_national_current": 0.2, "BB_wind_national_current": 0.3}, index=index).iloc[:48]
    demand = pd.DataFrame({"AA": 100.0, "BB": 50.0}, index=index)
    costs = pd.DataFrame({"capital_cost": 1000.0, "efficiency": 0.9}, index=["OCGT", "onwind", "offwind", "solar-utility", "battery storage", "battery inverter", "hydrogen storage underground", "electrolysis", "fuel cell"])
    limits = pd.DataFrame({"a": ["AA"], "b": ["BB"], "kind": ["ac"], "mw": [10.0]})
    existing = pd.DataFrame(0.0, index=["AA", "BB"], columns=["Nuclear", "Run-Of-River", "Reservoir", "Pumped Storage"])
    return cf.resample("3h").mean(), demand, costs, limits, existing


def test_fixed_fleet_sheds_what_is_missing(monkeypatch):
    monkeypatch.setitem(inputs.LAND_KM2, "AA", 10)
    monkeypatch.setitem(inputs.LAND_KM2, "BB", 10)
    cf, demand, costs, limits, existing = small_case()
    n = model.build(cf, demand, costs, limits, existing, zones=["AA", "BB"], fleet={})
    model.solve(n, threads=1)
    shed = n.generators_t.p[["AA shed", "BB shed"]].sum(axis=1)
    assert shed.iloc[0] == pytest.approx(150.0, rel=1e-3)
    prices = n.buses_t.marginal_price[["AA", "BB"]].iloc[0]
    assert prices["AA"] == pytest.approx(model.VOLL, rel=1e-3)
    assert prices["BB"] == pytest.approx(model.VOLL, rel=1e-3)


def test_expansion_serves_the_load_with_cheapest_firm_supply(monkeypatch):
    monkeypatch.setitem(inputs.LAND_KM2, "AA", 10)
    monkeypatch.setitem(inputs.LAND_KM2, "BB", 10)
    cf, demand, costs, limits, existing = small_case()
    n = model.build(cf, demand, costs, limits, existing, zones=["AA", "BB"])
    model.solve(n, threads=1)
    assert n.generators_t.p[["AA shed", "BB shed"]].sum().sum() == pytest.approx(0.0, abs=1e-2)
    fleet = model.fleet_of(n)
    assert fleet["AA battery charge"] == pytest.approx(fleet["AA battery discharge"], abs=1e-2)

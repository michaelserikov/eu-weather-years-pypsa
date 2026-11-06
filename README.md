# Which weather year to design a renewable power system for?

A capacity expansion model of northwestern Europe in PyPSA, solved once for each of 40 weather years (1980-2019), and three of the resulting fleets dispatched on the weather of all other years. The question is how much the choice of the design year matters for cost and for security of supply. Research study on open data; the system is stylised and the numbers are illustrative.

## Model
- 12 countries (DE, FR, BE, NL, AT, CH, DK, NO, SE, GB, PL, CZ) as single nodes, a transport model between them. Cross-border capacity from the OpenStreetMap-based European grid data used by PyPSA-Eur (AC lines derated to 70%) plus the main HVDC links.
- Greenfield wind (onshore, offshore), solar, batteries and hydrogen storage (electrolysis, underground store, fuel cell), chosen by the optimiser within land and offshore limits. Existing nuclear and hydro from powerplantmatching. A dispatchable backup plant (OCGT capital cost, assumed fuel of 200 EUR/MWh) and load shedding at 8,000 EUR/MWh close the balance.
- Costs for 2030 from PyPSA technology-data, 7% discount rate. Demand is the 2018 hourly load from Open Power System Data, the same in every weather year, so only the weather changes.
- Wind and solar capacity factors from renewables.ninja (current fleet layout), 1980-2019, on a non-leap calendar.
- 6-hour time steps (1,460 per year), solved with HiGHS (interior point). See *Time step* below for what this costs.

## Results (6-hour step)

**Optimal system cost varies by about 16% between weather years.**

| | Mean | Min | Max |
|---|---|---|---|
| System cost, bn EUR/a | 93.2 | 86.8 (1990) | 100.9 (1985) |
| Backup generation, TWh/a | 68.5 | 53.9 | 93.5 |
| Backup capacity, GW | 78.0 | 61.7 | 96.5 (1995) |
| Solar, GW | 419 | 369 | 484 |
| Onshore wind, GW | 274 | 251 | 332 |
| Offshore wind, GW | 44 | 19 | 60 |
| Battery energy, GWh | 209 | 140 | 304 |

The coefficient of variation of the system cost is 3.9%. The cost follows the energy the backup plants must deliver (correlation 0.85), not the backup capacity (0.07): the costliest years are those in which the backup plants must run most, while the largest backup capacity is needed in years with the sharpest residual peak. 1985 is the costliest year, but 1995 needs the most firm capacity. No weather year ends with lost load in its own optimum.

**A fleet built for one year, run on the others.** Each fleet keeps its capacities and is dispatched on the 39 other weather years. Regret is the total cost (capital cost of the fleet plus its operating cost in that year, with lost load at 8,000 EUR/MWh) minus the optimal cost for that year. As a check of this accounting, each fleet dispatched on its own year gives a regret of 0.0 bn EUR/a.

| Fleet built for | Its own cost, bn EUR/a | Years with lost load (of 39) | Mean lost load, GWh | Worst year, GWh | Mean regret, bn EUR/a | Max regret, bn EUR/a |
|---|---|---|---|---|---|---|
| 1990 (cheapest year) | 86.8 | 34 | 242 | 1,003 (1985) | 7.0 | 13.7 |
| 2011 (median year) | 92.1 | 34 | 334 | 1,305 (1985) | 4.4 | 12.7 |
| 1985 (costliest year) | 100.9 | 27 | 35 | 182 (2004) | 2.7 | 4.6 |

- Designing for the costliest year gives the smallest regret on average and in the worst case, although its optimal cost in its own year is about 14 bn EUR/a above that of the cheapest year.
- Even that fleet loses load in 27 of 39 years. Its mix of 85 GW backup and 169 GWh of batteries is tuned to 1985, while 1995 needs 96 GW of backup in its own optimum and 2004 more battery energy (237 GWh). The amounts are small (at most 0.01% of demand), but no single historical year covers all others.
- The fleet for the median year is not a safe middle: it loses more load than the cheapest-year fleet, because the optimum for 2011 has 74 GW of backup against 83 GW for 1990.

## Time step: 6 hours against 3 hours (2010)

The same expansion for 2010 at a 3-hour step:

| | 3 h | 6 h | Difference |
|---|---|---|---|
| System cost, bn EUR/a | 102.7 | 100.5 | -2.1% |
| Backup generation, TWh | 76.1 | 75.7 | -0.6% |
| Backup capacity, GW | 70.2 | 68.6 | -2.3% |
| Solar, GW | 416 | 433 | +4.1% |
| Onshore wind, GW | 297 | 291 | -2.3% |
| Offshore wind, GW | 63 | 59 | -6.0% |
| Battery power, GW | 41.6 | 23.5 | -43% |
| Battery energy, GWh | 267 | 237 | -11% |

The 6-hour step averages away part of the daily solar cycle, so it understates the value of batteries (battery power 43% lower) and slightly overstates solar. Cost, backup energy and firm capacity, which drive the comparison between weather years, change by about 2%. The results on design years are therefore read as a comparison at a common resolution, not as exact capacities.

## Hydrogen storage is not built

No electrolysis, hydrogen store or fuel cell is built in any year. The obvious suspect is the backup fuel price, so 2010 was solved again with the fuel at 400 and 800 EUR/MWh:

| Backup fuel, EUR/MWh | 200 | 400 | 800 |
|---|---|---|---|
| System cost, bn EUR/a | 100.5 | 112.6 | 127.1 |
| Backup generation, TWh | 75.7 | 46.3 | 26.9 |
| Backup capacity, GW | 68.6 | 57.9 | 45.7 |
| Solar, GW | 433 | 496 | 592 |
| Onshore wind, GW | 291 | 329 | 363 |
| Battery energy, GWh | 237 | 344 | 464 |
| Hydrogen (electrolysis, store, fuel cell) | 0 | 0 | 0 |

Even at four times the fuel price, the optimiser replaces backup energy with more solar, wind and batteries rather than hydrogen. The fuel price does not explain the result: in this setup reconversion is only possible through a fuel cell (annualised about 283 thousand EUR/MW against 60 thousand for an OCGT), and with electrolysis (about 237 thousand EUR/MW) and a round trip efficiency of 31% the hydrogen path does not pay for the few hundred hours a year it would run. Models that burn hydrogen in turbines, or that have a hydrogen demand outside the power sector, do build it; this one has neither, so "no hydrogen" is a property of the model, not a finding about Europe.

## Limits
- One node per country, transport model, no grid constraints inside countries.
- One demand year (2018) for all weather years; no temperature-driven demand, so cold, windless winters are understated.
- Capacity factors for today's wind and solar fleet layout; flat hydro inflow.
- Backup fuel price, value of lost load and hydro storage are assumptions.
- Hydrogen is reconverted only in fuel cells, with no hydrogen turbines and no hydrogen demand outside the power sector.
- Three fleets, not all 40, in the dispatch comparison.

## Run
```
python -m venv .venv
.venv/Scripts/pip install -e .[test]
.venv/Scripts/python scripts/download_data.py
WEATHER_STEP_HOURS=6 .venv/Scripts/python scripts/run_years.py expand 1980 2019 4
WEATHER_STEP_HOURS=6 .venv/Scripts/python scripts/run_years.py dispatch 1980 2019 4 1990,2011,1985
.venv/Scripts/python scripts/analyse.py
.venv/Scripts/python -m pytest -q
```
`buses.csv`, `lines.csv` (PyPSA-Eur OpenStreetMap grid data) and `powerplants.csv` (powerplantmatching) are placed in `data/raw/` by hand. One expansion year takes about an hour at the 6-hour step with two threads. `WEATHER_BACKUP_FUEL` changes the backup fuel price; results then go to `results/step6h_backup<price>/`.

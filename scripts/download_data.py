"""Download the open inputs into data/raw/. Not committed; check each licence before redistributing."""

from pathlib import Path
from urllib.request import Request, urlopen

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
FILES = {
    "ninja_pv_wind_profiles_singleindex.csv": "https://data.open-power-system-data.org/ninja_pv_wind_profiles/latest/ninja_pv_wind_profiles_singleindex.csv",
    "time_series_60min_singleindex.csv": "https://data.open-power-system-data.org/time_series/latest/time_series_60min_singleindex.csv",
    "costs_2030.csv": "https://raw.githubusercontent.com/PyPSA/technology-data/master/outputs/costs_2030.csv",
}


def fetch(name: str, url: str) -> None:
    path = RAW / name
    if path.exists() and path.stat().st_size > 0:
        print("have", name, flush=True)
        return
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    tmp = path.with_suffix(path.suffix + ".part")
    with urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(path)
    print("got", name, path.stat().st_size, flush=True)


if __name__ == "__main__":
    RAW.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        fetch(name, url)

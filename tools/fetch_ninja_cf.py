"""Renewables.ninja から9エリアの太陽光・風力 設備利用率(CF)を取得し、
project_2025 の solar_cf / wind_cf シートと同じ形式 (8760行 x 9列, JST) のCSVを出力する。

使い方:
    NINJA_TOKEN=xxxx python tools/fetch_ninja_cf.py data/project_2025_draft_2.xlsx [weather_year] [outdir]

- 地点: areas シートの lat/lon (エリア代表1地点)
- 太陽光: 固定架台, 傾斜30°, 真南, システム損失10%
- 風力: Vestas V90 2000, ハブ高さ80m
- 出力はUTC→JST(+9h)に変換し、年をまたいだ先頭9時間は前年末のデータで埋める
"""
import io
import os
import sys
import time

import pandas as pd
import requests

API = "https://www.renewables.ninja/api/data/"
xlsx = sys.argv[1]
year = int(sys.argv[2]) if len(sys.argv) > 2 else 2023
outdir = sys.argv[3] if len(sys.argv) > 3 else "data"

token = os.environ.get("NINJA_TOKEN")
session = requests.Session()
if token:
    session.headers["Authorization"] = f"Token {token}"

PV = dict(dataset="merra2", capacity=1.0, system_loss=0.1, tracking=0, tilt=30, azim=180)
WIND = dict(dataset="merra2", capacity=1.0, height=80, turbine="Vestas V90 2000")


def fetch(kind, lat, lon, params):
    # JST 1/1 0:00 は UTC 前年12/31 15:00 なので前年末から取得
    q = dict(lat=lat, lon=lon, date_from=f"{year - 1}-12-31", date_to=f"{year}-12-31",
             format="csv", header="false", **params)
    for attempt in range(5):
        r = session.get(API + kind, params=q, timeout=120)
        if r.status_code == 429:  # レート制限 (トークン有りで 50件/時)
            time.sleep(60 * (attempt + 1))
            continue
        r.raise_for_status()
        s = pd.read_csv(io.StringIO(r.text), index_col=0, parse_dates=True).iloc[:, 0]
        s.index = s.index.tz_localize("UTC").tz_convert("Asia/Tokyo").tz_localize(None)
        s = s[str(year)]
        return s[~((s.index.month == 2) & (s.index.day == 29))].values[:8760]  # 閏年は2/29を除外
    raise RuntimeError(f"{kind} {lat},{lon}: rate limited")


areas = pd.read_excel(xlsx, sheet_name="areas")
solar, wind = {}, {}
for _, a in areas.iterrows():
    print(a["name"], flush=True)
    solar[f"Solar ({a['name']})"] = fetch("pv", a.lat, a.lon, PV)
    wind[f"Wind ({a['name']})"] = fetch("wind", a.lat, a.lon, WIND)

for name, d in (("solar_cf", solar), ("wind_cf", wind)):
    df = pd.DataFrame(d)
    df.to_csv(os.path.join(outdir, f"{name}_ninja_{year}.csv"), index=False)
    print(name, "年平均CF:", df.mean().round(3).to_dict())

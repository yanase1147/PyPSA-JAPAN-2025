"""日本9エリア 需給シミュレーション (経済負荷配分, 1時間刻み)

例:
    python run_dispatch.py data/project_2025_draft_2.xlsx --hours 168    # 1週間テスト(一括)
    python run_dispatch.py data/project_2025_draft_2.xlsx --rolling      # 1年分をローリングホライズンで
    python run_dispatch.py data/project_2025_draft_2.xlsx \\
        --solar-cf data/solar_cf_ninja_2023.csv --wind-cf data/wind_cf_ninja_2023.csv
"""
import argparse
from pathlib import Path

import pandas as pd

from pypsa_japan import build_network, read_project, summarize


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xlsx", help="project_2025 形式の入力Excel")
    ap.add_argument("--hours", type=int, default=8760)
    ap.add_argument("--solar-cf", help="solar_cf シートを置き換えるCSV")
    ap.add_argument("--wind-cf", help="wind_cf シートを置き換えるCSV")
    ap.add_argument("--rolling", action="store_true",
                    help="ローリングホライズンで解く (省略時は全期間を一括で解く)")
    ap.add_argument("--horizon", type=int, default=744, help="ローリングホライズンの窓長[h] (--rolling 時)")
    ap.add_argument("--overlap", type=int, default=48, help="ローリングホライズンの重なり[h] (--rolling 時)")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("-o", "--out", default="results/dispatch.nc")
    args = ap.parse_args()

    x = read_project(args.xlsx, solar_cf=args.solar_cf, wind_cf=args.wind_cf)
    n = build_network(x, hours=args.hours)

    opts = dict(solver_name="highs", solver_options={"threads": args.threads})
    if args.rolling and args.hours > args.horizon:
        n.optimize.optimize_with_rolling_horizon(horizon=args.horizon, overlap=args.overlap, **opts)
    else:
        n.optimize(**opts)

    s = summarize(n)
    pd.set_option("display.float_format", "{:,.3f}".format)
    print("\n=== 電源別 ===\n", s["generation"])
    print(f"\n需要: {s['demand_TWh']:,.1f} TWh   燃料費: {s['fuel_cost'] / 1e12:,.3f} 兆円"
          f"   供給力不足: {s['load_shedding_MWh']:,.0f} MWh")
    print("\n=== エリア別 平均限界価格 [円/MWh] ===\n", s["marginal_price_mean"].round(0))
    print("\n=== 連系線 混雑時間率 ===\n", s["congestion_share"])

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    n.export_to_netcdf(args.out)


if __name__ == "__main__":
    main()

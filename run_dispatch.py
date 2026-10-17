"""日本9エリア 需給シミュレーション (経済負荷配分, 1時間刻み)

例:
    python run_dispatch.py data/Network_config_2025.xlsx --hours 168    # 1週間テスト(一括)
    python run_dispatch.py data/Network_config_2025.xlsx --rolling      # 1年分をローリングホライズンで
    python run_dispatch.py data/Network_config_2025.xlsx \\
        --solar-cf data/solar_cf_ninja_2023.csv --wind-cf data/wind_cf_ninja_2023.csv
"""
import argparse
import gc
import logging
import time
from pathlib import Path

from pypsa_japan import build_network, print_summary, read_project, summarize


def fmt_time(sec):
    m, s = divmod(sec, 60)
    return f"{int(m)}分{s:.1f}秒" if m else f"{s:.1f}秒"


def rolling_horizon(n, horizon, overlap, **opts):
    """PyPSA の optimize_with_rolling_horizon と同じ手順で解く。

    ウィンドウごとに前回の最適化モデルを解放する（解放しないと1ウィンドウあたり
    約0.4 GBずつメモリが増え、1年分で8 GB環境ではメモリ不足になる）。
    """
    if horizon <= overlap:
        raise ValueError("overlap は horizon より小さくしてください")
    sns = n.snapshots
    starts = range(0, len(sns), horizon - overlap)
    for i, start in enumerate(starts):
        window = sns[start:start + horizon]
        logging.getLogger(__name__).info("ウィンドウ %d/%d: %s 〜 %s", i + 1, len(starts), window[0], window[-1])
        if i and not n.stores.empty:
            n.stores.e_initial = n.stores_t.e.loc[sns[start - 1]].values
        status, condition = n.optimize(window, **opts)
        if status != "ok":
            logging.getLogger(__name__).warning("ウィンドウ %d の最適化に失敗: %s %s", i + 1, status, condition)
        if hasattr(n, "_model"):
            n._model = None
        gc.collect()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xlsx", help="Network_config_2025 形式の入力Excel")
    ap.add_argument("--hours", type=int, default=8760)
    ap.add_argument("--solar-cf", help="solar_cf シートを置き換えるCSV")
    ap.add_argument("--wind-cf", help="wind_cf シートを置き換えるCSV")
    ap.add_argument("--rolling", action="store_true",
                    help="ローリングホライズンで解く (省略時は全期間を一括で解く)")
    ap.add_argument("--horizon", type=int, default=744, help="ローリングホライズンの窓長[h] (--rolling 時)")
    ap.add_argument("--overlap", type=int, default=48, help="ローリングホライズンの重なり[h] (--rolling 時)")
    ap.add_argument("--uc", choices=["linear", "milp", "off"], default="linear",
                    help="火力の起動停止の扱い: linear=線形化した起動停止(既定), milp=整数計画(厳密・低速), "
                         "off=扱わない(最低出力なしの経済負荷配分)")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("-o", "--out", default="results/dispatch.nc")
    args = ap.parse_args()

    t0 = time.perf_counter()
    x = read_project(args.xlsx, solar_cf=args.solar_cf, wind_cf=args.wind_cf)
    n = build_network(x, hours=args.hours, unit_commitment=args.uc != "off")

    t1 = time.perf_counter()
    opts = dict(solver_name="highs", solver_options={"threads": args.threads})
    if args.uc == "linear":
        opts["linearized_unit_commitment"] = True
    elif args.uc == "milp":
        opts["solver_options"]["mip_rel_gap"] = 0.005
    if args.rolling and args.hours > args.horizon:
        rolling_horizon(n, args.horizon, args.overlap, **opts)
    else:
        n.optimize(**opts)
    t2 = time.perf_counter()

    print_summary(summarize(n))

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    n.export_to_netcdf(args.out)

    t3 = time.perf_counter()
    print(f"\n計算時間: 合計 {fmt_time(t3 - t0)}"
          f" (入力読込・モデル構築 {fmt_time(t1 - t0)} / 最適化 {fmt_time(t2 - t1)} / 集計・保存 {fmt_time(t3 - t2)})")


if __name__ == "__main__":
    main()

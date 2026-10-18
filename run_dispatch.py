"""日本9エリア 需給シミュレーション (経済負荷配分, 1時間刻み)

例:
    python run_dispatch.py data/Network_config_2025.xlsx --hours 168          # 1週間テスト
    python run_dispatch.py data/Network_config_2025.xlsx                      # 1年分（起動停止あり, 2週間の窓）
    python run_dispatch.py data/Network_config_2025.xlsx --uc off             # 1年分（起動停止なし, 1か月の窓）
    python run_dispatch.py data/Network_config_2025.xlsx --no-rolling --uc off  # 1年一括（約16GB以上のメモリが必要）
    python run_dispatch.py data/Network_config_2025.xlsx \\
        --solar-cf data/solar_cf_ninja_2023.csv --wind-cf data/wind_cf_ninja_2023.csv
"""
import argparse
import gc
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

from pypsa_japan import build_network, print_summary, read_project, summarize


def fmt_time(sec):
    m, s = divmod(sec, 60)
    return f"{int(m)}分{s:.1f}秒" if m else f"{s:.1f}秒"


def net_load(n):
    """年間上限を窓に配分するときの重み: 需要 − 太陽光・風力の発電可能量 − 原子力・バイオマスの固定出力 [MW]。
    火力が多く必要な時期ほど、上限の多くを配分する。"""
    g = n.generators
    pmax = n.get_switchable_as_dense("Generator", "p_max_pu")
    pmin = n.get_switchable_as_dense("Generator", "p_min_pu")
    vre = g.index[g.carrier.isin(["Solar", "Wind"])]
    must = g.index[g.carrier.isin(["Nuclear", "Biomass"])]
    nl = (n.loads_t.p_set.sum(axis=1) - (pmax[vre] * g.p_nom[vre]).sum(axis=1)
          - (pmin[must] * g.p_nom[must]).sum(axis=1))
    return nl.clip(lower=0.1 * nl.mean())


def rolling_horizon(n, horizon, overlap, collect_cap_duals=False, **opts):
    """PyPSA の optimize_with_rolling_horizon と同じ手順で解く。

    ウィンドウごとに前回の最適化モデルを解放する（解放しないと1ウィンドウあたり
    約0.4 GBずつメモリが増え、1年分で8 GB環境ではメモリ不足になる）。

    年間の発電量の上限（e_sum_max, 非効率石炭の稼働抑制）がある発電機は、残りの上限を
    残りの期間の正味需要（net_load）の比で窓に配分する。窓の結果のうち確定した時間の発電量を
    使った分として差し引くので、点検などで使い残した分は後の窓に回る。

    collect_cap_duals=True のときは、窓ごとの上限の双対変数（上限を1 MWh緩めたときの費用の減少 [円/MWh]）を
    確定した時間に割り当てた DataFrame（時間 × 発電機）を返す。起動停止ありの計算で限界費用に上乗せして使う。
    """
    if horizon <= overlap:
        raise ValueError("overlap は horizon より小さくしてください")
    log = logging.getLogger(__name__)
    sns = n.snapshots
    step = horizon - overlap
    starts = range(0, len(sns), step)
    capped = n.generators.index[np.isfinite(n.generators.e_sum_max)]
    if len(capped):
        budget = n.generators.e_sum_max[capped].copy()
        used = budget * 0
        w = net_load(n)
        adder = pd.DataFrame(0.0, index=sns, columns=capped)
    for i, start in enumerate(starts):
        window = sns[start:start + horizon]
        log.info("ウィンドウ %d/%d: %s 〜 %s", i + 1, len(starts), window[0], window[-1])
        if i and not n.stores.empty:
            n.stores.e_initial = n.stores_t.e.loc[sns[start - 1]].values
        if len(capped):
            share = w.loc[window].sum() / w.iloc[start:].sum()
            n.generators.loc[capped, "e_sum_max"] = (budget - used).clip(lower=0) * share
        status, condition = n.optimize(window, **opts)
        if status != "ok":
            log.warning("ウィンドウ %d の最適化に失敗: %s %s", i + 1, status, condition)
        if len(capped):
            kept = sns[start:start + step]
            used += n.generators_t.p.loc[kept, capped].sum()
            if collect_cap_duals and status == "ok":
                dual = -n.model.constraints["Generator-e_sum_max"].dual.to_series()
                adder.loc[kept, dual.index] = dual.clip(lower=0).values
        if hasattr(n, "_model"):
            n._model = None
        gc.collect()
    if len(capped):
        n.generators.loc[capped, "e_sum_max"] = budget
        if collect_cap_duals:
            return adder


def print_annual_cap(n, limit_mwh=None, adder=None):
    """年間設備利用率の上限がある発電機の結果を表示する。limit_mwh を省くと n.generators.e_sum_max を使う。"""
    g = n.generators
    if limit_mwh is None:
        limit_mwh = g.e_sum_max[np.isfinite(g.e_sum_max)]
    capped = limit_mwh.index
    if capped.empty:
        return
    hours = len(n.snapshots)
    e = n.generators_t.p[capped].sum()
    cap_mw = g.p_nom[capped]
    print(f"\n年間設備利用率の上限（非効率石炭の稼働抑制）: {len(capped)} 基, {cap_mw.sum()/1e3:.1f} GW")
    print(f"  発電量 {e.sum()/1e6:.1f} TWh, 容量加重の設備利用率 {e.sum()/(cap_mw.sum()*hours):.1%}"
          f"（上限 {limit_mwh.sum()/(cap_mw.sum()*hours):.1%}）,"
          f" 上限を超えた発電機 {(e > limit_mwh * 1.01).sum()} 基, 上限に達した発電機 {(e >= limit_mwh * 0.99).sum()} 基")
    if adder is not None:
        a = (adder * n.generators_t.p[capped]).sum().sum() / max(e.sum(), 1)
        print(f"  限界費用への上乗せ（LPの双対変数）: 発電量加重平均 {a/1e3:.2f} 円/kWh, 最大 {adder.max().max()/1e3:.2f} 円/kWh")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xlsx", help="Network_config_2025 形式の入力Excel")
    ap.add_argument("--hours", type=int, default=8760)
    ap.add_argument("--solar-cf", help="solar_cf シートを置き換えるCSV")
    ap.add_argument("--wind-cf", help="wind_cf シートを置き換えるCSV")
    ap.add_argument("--rolling", action=argparse.BooleanOptionalAction, default=True,
                    help="ローリングホライズンで解く (既定)。--no-rolling で全期間を一括で解く (1年分は約16GB以上のメモリが必要)")
    ap.add_argument("--horizon", type=int, default=None,
                    help="ローリングホライズンの窓長[h]。既定は起動停止ありで336 (2週間)、--uc off で744 (約1か月)")
    ap.add_argument("--overlap", type=int, default=48, help="ローリングホライズンの重なり[h]")
    ap.add_argument("--uc", choices=["linear", "milp", "off"], default="linear",
                    help="火力の起動停止の扱い: linear=線形化した起動停止(既定), milp=整数計画(厳密・低速), "
                         "off=扱わない(最低出力なしの経済負荷配分)")
    ap.add_argument("--annual-cap", action=argparse.BooleanOptionalAction, default=True,
                    help="generators シートの max_annual_cf（非効率石炭の年間設備利用率の上限）を使う (既定)。"
                         "--no-annual-cap で外す")
    ap.add_argument("--cap-method", choices=["adder", "hard"], default="adder",
                    help="起動停止ありのローリングホライズンでの年間上限の扱い: adder=先に起動停止なし(LP)で解き、"
                         "上限の双対変数を限界費用に上乗せする(既定・高速), hard=上限を制約として入れる(窓ごとに数十倍遅い)")
    ap.add_argument("--vom-coal", type=float, default=None, help="石炭の燃料費以外の変動費[円/kWh]（fuel_price シートの値を上書き）")
    ap.add_argument("--vom-lng", type=float, default=None, help="LNG の燃料費以外の変動費[円/kWh]（同上）")
    ap.add_argument("--lng-price-scale", type=float, default=1.0, help="LNG の輸入価格に掛ける倍率（感度分析用）")
    ap.add_argument("--lng-min-pu", type=float, default=0.0, help="（実験）LNG火力の最低出力[p.u.]。起動停止なしでも常に最低出力で運転させる")
    ap.add_argument("--coal-avail-scale", type=float, default=1.0, help="（実験）石炭の出力上限（利用可能率）に掛ける倍率")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("-o", "--out", default="results/dispatch.nc")
    args = ap.parse_args()
    if args.horizon is None:
        args.horizon = 744 if args.uc == "off" else 336

    t0 = time.perf_counter()
    x = read_project(args.xlsx, solar_cf=args.solar_cf, wind_cf=args.wind_cf)
    if args.lng_price_scale != 1.0:
        fp = x["fuel_price"]
        m = [c for c in fp.columns if c.startswith("m") and c[1:].isdigit()]
        fp[m] = fp[m].astype(float)
        fp.loc[fp.fuel == "lng", m] *= args.lng_price_scale
    vom = {f: v * 1e3 for f, v in (("coal", args.vom_coal), ("lng", args.vom_lng)) if v is not None}
    if args.vom_coal is not None:
        vom["byproduct"] = args.vom_coal * 1e3
    n = build_network(x, hours=args.hours, unit_commitment=args.uc != "off", annual_cap=args.annual_cap, vom=vom)
    if args.lng_min_pu:
        gas = n.generators.index[n.generators.carrier == "Gas"]
        n.generators.loc[gas, "p_min_pu"] = args.lng_min_pu
    if args.coal_avail_scale != 1.0:
        coal = n.generators.index[n.generators.carrier == "Coal"]
        pm = n.get_switchable_as_dense("Generator", "p_max_pu")[coal] * args.coal_avail_scale
        n.generators_t.p_max_pu[coal] = pm

    t1 = time.perf_counter()
    opts = dict(solver_name="highs", solver_options={"threads": args.threads})
    if args.uc == "linear":
        opts["linearized_unit_commitment"] = True
    elif args.uc == "milp":
        opts["solver_options"]["mip_rel_gap"] = 0.005
    rolling = args.rolling and args.hours > args.horizon
    limit, adder = None, None
    capped = n.generators.index[np.isfinite(n.generators.e_sum_max)]
    if len(capped) and rolling and args.uc != "off" and args.cap_method == "adder":
        # 年間上限と起動停止を同時に入れると窓ごとの計算が数十倍遅くなるため、2段階で解く:
        # 1) 起動停止なし(LP)・上限ありで解き、上限の双対変数（上限の機会費用）を窓ごとに求める
        # 2) その値を限界費用に上乗せし、上限の制約は外して起動停止ありで解く
        logging.getLogger(__name__).info("年間上限の機会費用を起動停止なし(LP)で計算")
        lp = build_network(x, hours=args.hours, unit_commitment=False, annual_cap=True, vom=vom)
        lp_opts = dict(solver_name="highs", solver_options={"threads": args.threads})
        adder = rolling_horizon(lp, 744, args.overlap, collect_cap_duals=True, **lp_opts)
        del lp
        gc.collect()
        limit = n.generators.e_sum_max[capped].copy()
        n.generators.loc[capped, "e_sum_max"] = np.inf
        mc = n.get_switchable_as_dense("Generator", "marginal_cost")[capped]
        n.generators_t.marginal_cost[capped] = mc + adder
    if rolling:
        rolling_horizon(n, args.horizon, args.overlap, **opts)
    else:
        n.optimize(**opts)
    if adder is not None:
        n.generators_t.marginal_cost[capped] = mc       # 燃料費の集計と保存は上乗せ前の限界費用で
    t2 = time.perf_counter()

    print_summary(summarize(n))
    print_annual_cap(n, limit, adder)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    n.export_to_netcdf(args.out)

    t3 = time.perf_counter()
    print(f"\n計算時間: 合計 {fmt_time(t3 - t0)}"
          f" (入力読込・モデル構築 {fmt_time(t1 - t0)} / 最適化 {fmt_time(t2 - t1)} / 集計・保存 {fmt_time(t3 - t2)})")


if __name__ == "__main__":
    main()

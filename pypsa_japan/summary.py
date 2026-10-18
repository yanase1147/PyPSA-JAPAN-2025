"""最適化結果の集計"""
import pandas as pd


def summarize(n):
    g = n.generators
    p = n.generators_t.p
    by_carrier = lambda df: df.T.groupby(g.carrier).sum().T  # noqa: E731
    avail = by_carrier(n.get_switchable_as_dense("Generator", "p_max_pu") * g.p_nom)

    gen = pd.DataFrame({
        "発電量[TWh]": by_carrier(p).sum() / 1e6,
        "設備利用率": by_carrier(p).sum() / g.groupby("carrier").p_nom.sum() / len(n.snapshots),
        "抑制量[TWh]": (avail - by_carrier(p)).clip(lower=0).sum() / 1e6,
    }).drop(index="Load shedding").sort_values("発電量[TWh]", ascending=False)

    areas = n.loads.bus.unique()
    ic = n.links[n.links.carrier == "AC"]
    flow = n.links_t.p0[ic.index]
    return {
        "generation": gen,
        "demand_TWh": n.loads_t.p_set.sum().sum() / 1e6,
        "fuel_cost": (p * n.get_switchable_as_dense("Generator", "marginal_cost"))
        .drop(columns=g.index[g.carrier == "Load shedding"]).sum().sum(),  # 月別の限界費用にも対応
        "load_shedding_MWh": p.loc[:, g.carrier == "Load shedding"].sum().sum(),
        "marginal_price_mean": n.buses_t.marginal_price[areas].mean(),
        # 方向別の容量 (順方向 p_nom, 逆方向 -p_min_pu * p_nom) のどちらかに達した時間の割合
        "congestion_share": ((flow >= ic.p_nom - 1e-3) | (flow <= ic.p_min_pu * ic.p_nom + 1e-3)).mean(),
    }


def print_summary(s):
    with pd.option_context("display.float_format", "{:,.3f}".format):
        print("\n=== 電源別 ===\n", s["generation"])
        print(f"\n需要: {s['demand_TWh']:,.1f} TWh   燃料費: {s['fuel_cost'] / 1e12:,.3f} 兆円"
              f"   供給力不足: {s['load_shedding_MWh']:,.0f} MWh")
        print("\n=== エリア別 平均限界価格 [円/MWh] ===\n", s["marginal_price_mean"].round(0))
        print("\n=== 連系線 混雑時間率 ===\n", s["congestion_share"])

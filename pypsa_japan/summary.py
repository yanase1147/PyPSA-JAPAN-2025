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
        "fuel_cost": (p * g.marginal_cost).drop(columns=g.index[g.carrier == "Load shedding"]).sum().sum(),
        "load_shedding_MWh": p.loc[:, g.carrier == "Load shedding"].sum().sum(),
        "marginal_price_mean": n.buses_t.marginal_price[areas].mean(),
        "congestion_share": (flow.abs() >= ic.p_nom - 1e-3).mean(),
    }

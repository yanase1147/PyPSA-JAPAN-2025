"""最適化結果の図示 (matplotlib)"""
import matplotlib as mpl
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap

# carrier -> 凡例上の区分 (ここに無い carrier は「その他」)
GROUPS = {"Nuclear": "原子力", "Coal": "石炭", "Hydro": "水力", "Gas": "LNG",
          "Wind": "風力", "Solar": "太陽光", "Load shedding": "供給力不足"}
# 積み上げ順 (下から) と色。隣り合う色が色覚特性によらず区別できる並びなので、順序ごと変えないこと
COLORS = {"原子力": "#6250d6", "石炭": "#e34948", "水力": "#2a78d6", "LNG": "#eb6834",
          "風力": "#1baf7a", "太陽光": "#eda100", "その他": "#e87ba4", "揚水発電": "#008300",
          "連系線受電": "#898781", "供給力不足": "#0b0b0b"}
NEGATIVE = {"揚水動力": "#008300", "連系線送電": "#898781"}  # 0より下に積む (需要側)
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
SEQ = LinearSegmentedColormap.from_list("seq_blue", ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])


JP_FONTS = ["Yu Gothic", "Meiryo", "Noto Sans JP", "Noto Sans CJK JP", "Hiragino Sans", "IPAexGothic"]


def set_style():
    installed = {f.name for f in font_manager.fontManager.ttflist}
    mpl.rcParams.update({
        "font.family": [f for f in JP_FONTS if f in installed] + ["sans-serif"],
        "axes.unicode_minus": False,
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "text.color": INK, "axes.labelcolor": INK2, "axes.titlesize": 12, "axes.titleweight": "bold",
        "axes.titlelocation": "left", "axes.edgecolor": AXIS, "axes.axisbelow": True,
        "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
        "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.6,
        "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK2, "ytick.labelcolor": INK2,
        "ytick.left": False, "legend.frameon": False, "figure.dpi": 110, "savefig.dpi": 150,
    })


def areas(n):
    return list(n.loads.bus.unique())


def _by_group(n, p):
    """発電機別の時系列/合計を GROUPS の区分に集約する"""
    grp = n.generators.carrier.map(GROUPS).fillna("その他")
    return p.T.groupby(grp).sum().T


def balance(n, area=None):
    """需給バランス [MW]。供給を正、揚水動力・連系線送電を負とする時系列と、需要の時系列を返す。
    area=None は全国 (連系線は相殺されるので含めない)。"""
    buses = [area] if area else areas(n)
    g, li = n.generators, n.links
    df = _by_group(n, n.generators_t.p.loc[:, g.bus.isin(buses)])
    phs = li.carrier != "AC"
    df["揚水発電"] = -n.links_t.p1.loc[:, phs & li.bus1.isin(buses)].sum(axis=1)
    df["揚水動力"] = -n.links_t.p0.loc[:, phs & li.bus0.isin(buses)].sum(axis=1)
    if area:
        ic = li.carrier == "AC"
        net = -(n.links_t.p1.loc[:, ic & (li.bus1 == area)].sum(axis=1)
                + n.links_t.p0.loc[:, ic & (li.bus0 == area)].sum(axis=1))
        df["連系線受電"], df["連系線送電"] = net.clip(lower=0), net.clip(upper=0)
    demand = n.loads_t.p_set.loc[:, n.loads.bus.isin(buses)].sum(axis=1)
    cols = [c for c in [*COLORS, *NEGATIVE] if c in df and df[c].abs().sum() > 1e-6]
    return df[cols], demand


def _date_axis(ax, index):
    loc = mdates.AutoDateLocator(minticks=4, maxticks=12)
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc, show_offset=False))
    ax.set_xlim(index[0], index[-1])


def plot_balance(n, area=None, start=None, end=None, ax=None):
    """電源別の積み上げと需要。31日を超える期間は日平均で描く。"""
    df, demand = balance(n, area)
    df, demand = df.loc[start:end] / 1e3, demand.loc[start:end] / 1e3
    daily = len(df) > 31 * 24
    if daily:
        df, demand = df.resample("D").mean(), demand.resample("D").mean()

    ax = ax or plt.subplots(figsize=(12, 5.5))[1]
    pos = [c for c in df if c in COLORS]
    neg = [c for c in df if c in NEGATIVE]
    kw = dict(step="post", linewidth=0) if daily else dict(edgecolor=SURFACE, linewidth=0.4)
    for cols, palette in ((pos, COLORS), (neg, NEGATIVE)):
        base = pd.Series(0.0, df.index)
        for c in cols:
            ax.fill_between(df.index, base, base + df[c], color=palette[c], label=c, **kw)
            base = base + df[c]
    ax.plot(demand.index, demand, color=INK, lw=1.6, label="需要",
            drawstyle="steps-post" if daily else "default")
    ax.axhline(0, color=AXIS, lw=0.8)

    _date_axis(ax, df.index)
    ax.set_ylabel("GW")
    ax.set_title(f"需給バランス — {area or '全国'}" + (" (日平均)" if daily else ""))
    h, lab = ax.get_legend_handles_labels()
    order = [lab.index("需要")] + [lab.index(c) for c in reversed(pos)] + [lab.index(c) for c in neg]
    ax.legend([h[i] for i in order], [lab[i] for i in order], loc="upper left", bbox_to_anchor=(1.01, 1))
    return ax


def plot_area_mix(n, ax=None):
    """エリア別の電源構成 (年間発電量) と需要"""
    g = n.generators
    w = n.snapshot_weightings.generators
    mix = pd.DataFrame({a: _by_group(n, n.generators_t.p.loc[:, g.bus == a].mul(w, axis=0)).sum()
                        for a in areas(n)}).T.fillna(0) / 1e6
    mix = mix[[c for c in COLORS if c in mix and mix[c].sum() > 1e-6]]
    demand = n.loads_t.p_set.mul(w, axis=0).T.groupby(n.loads.bus).sum().T.sum()[mix.index] / 1e6

    ax = ax or plt.subplots(figsize=(10, 5))[1]
    left = np.zeros(len(mix))
    y = np.arange(len(mix))
    for c in mix:
        ax.barh(y, mix[c], left=left, height=0.62, color=COLORS[c], edgecolor=SURFACE, linewidth=1.2, label=c)
        left += mix[c].values
    ax.scatter(demand, y, marker="|", s=420, color=INK, linewidths=2, zorder=3, label="需要")
    ax.set_yticks(y, mix.index)
    ax.invert_yaxis()
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("TWh")
    ax.set_title("エリア別 電源構成と需要")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1))
    return ax


def plot_price(n, start=None, end=None, ax=None):
    """エリア別限界価格のヒートマップ。31日を超える期間は日平均。"""
    mp = n.buses_t.marginal_price[areas(n)].loc[start:end]
    daily = len(mp) > 31 * 24
    if daily:
        mp = mp.resample("D").mean()
    vmax = np.nanpercentile(mp.values, 99)  # 供給力不足時のスパイクで色が潰れないよう上側を打ち切る
    clipped = mp.values.max() > vmax + 1e-6

    ax = ax or plt.subplots(figsize=(12, 4.2))[1]
    x = mdates.date2num(mp.index.append(mp.index[-1:] + (mp.index[1] - mp.index[0])))
    im = ax.pcolormesh(x, np.arange(mp.shape[1] + 1), mp.T.values, cmap=SEQ, vmax=vmax)
    ax.set_yticks(np.arange(mp.shape[1]) + 0.5, mp.columns)
    ax.invert_yaxis()
    ax.xaxis_date()
    ax.grid(False)
    _date_axis(ax, mp.index)
    ax.set_xlim(x[0], x[-1])
    ax.set_title("エリア別 限界価格" + (" (日平均)" if daily else ""))
    cb = ax.figure.colorbar(im, ax=ax, pad=0.015, extend="max" if clipped else "neither")
    cb.set_label("円/MWh")
    cb.outline.set_visible(False)
    return ax


def plot_congestion(n, ax=None):
    """連系線の混雑時間率 (方向別)"""
    ic = n.links[n.links.carrier == "AC"]
    flow = n.links_t.p0[ic.index]
    fwd = (flow >= ic.p_nom * ic.p_max_pu - 1e-3).mean()
    rev = (flow <= ic.p_nom * ic.p_min_pu + 1e-3).mean()

    ax = ax or plt.subplots(figsize=(10, 4.8))[1]
    y = np.arange(len(ic))
    kw = dict(height=0.62, edgecolor=SURFACE, linewidth=1.2)
    ax.barh(y, fwd * 100, color="#2a78d6", label="順方向 (bus0 → bus1)", **kw)
    ax.barh(y, rev * 100, left=fwd * 100, color="#eb6834", label="逆方向 (bus1 → bus0)", **kw)
    for yi, tot in zip(y, (fwd + rev) * 100):
        ax.text(tot + 1, yi, f"{tot:.0f}%", va="center", color=INK2, fontsize=9)
    ax.set_yticks(y, [f"{name}\n{r.bus0} → {r.bus1}" for name, r in ic.iterrows()], fontsize=8.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 108)
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("混雑時間率 [%]")
    ax.set_title("連系線 混雑時間率")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1))
    return ax

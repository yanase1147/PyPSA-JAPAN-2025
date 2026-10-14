"""Network_config_2025 形式の Excel から PyPSA ネットワークを構築する。

シートとPyPSAコンポーネントの対応:
    areas              -> Bus (エリア = 1ノード)
    generators         -> Generator (時系列CFは *_cf シートの同名列。nuclear_cf は出力固定)
    loads + demand_mw  -> Load
    interconnections   -> Link (双方向: p_nom / p_nom_reverse)
    stores             -> Store (揚水上池。carrier名の専用バスに接続)
    converters         -> Link (揚水ポンプ/タービン。"AC" はそのエリアのバス)
"""
import pandas as pd
import pypsa

CF_SHEETS = ["solar_cf", "wind_cf", "hydro_cf", "biomass_cf", "nuclear_cf", "coal_cf"]  # nuclear_cf, coal_cf は任意
VOLL = 1e6  # 供給力不足 (load shedding) のペナルティ単価


def read_project(path, solar_cf=None, wind_cf=None):
    """Excel を読み込む。solar_cf / wind_cf にCSVを渡すと該当シートを差し替える
    (tools/fetch_ninja_cf.py の出力を想定)。"""
    x = pd.read_excel(path, sheet_name=None)
    for sheet, csv in (("solar_cf", solar_cf), ("wind_cf", wind_cf)):
        if csv is not None:
            df = pd.read_csv(csv)
            missing = set(x[sheet].columns) - set(df.columns)
            if missing or len(df) != len(x[sheet]):
                raise ValueError(f"{csv}: {sheet} と形式が一致しません (不足列 {sorted(missing)}, 行数 {len(df)})")
            x[sheet] = df[x[sheet].columns]
    return x


def build_network(x, hours=8760, year=2025, phs_initial_soc=0.5):
    snaps = pd.date_range(f"{year}-01-01", periods=8760, freq="h")[:hours]
    n = pypsa.Network()
    n.set_snapshots(snaps)

    carriers = set(x["generators"].carrier) | set(x["carriers"].name) | {"AC", "Load shedding"}
    n.add("Carrier", sorted(carriers))

    # エリアバス
    a = x["areas"].set_index("name")
    n.add("Bus", a.index, x=a.lon, y=a.lat, carrier="AC")

    # 揚水上池: carrier名の専用バス + Store
    s = x["stores"]
    n.add("Bus", s.carrier.values, carrier=s.carrier.values,
          x=a.lon[s.area].values, y=a.lat[s.area].values)
    n.add("Store", s.name.values, bus=s.carrier.values, e_nom=s.e_nom.values,
          carrier=s.carrier.values, e_initial=phs_initial_soc * s.e_nom.values)

    # 需要
    d = x["demand_mw"].iloc[:hours].set_index(snaps)
    for _, r in x["loads"].iterrows():
        n.add("Load", r["name"], bus=r.area, p_set=d[f"{r.area}|{r['name']}"] * r.demand_scale)

    # 発電機
    g = x["generators"].set_index("name")
    n.add("Generator", g.index, bus=g.area.values, carrier=g.carrier.values, p_nom=g.p_nom,
          marginal_cost=g.marginal_cost, efficiency=g.efficiency,
          p_max_pu=g.p_max_pu, p_min_pu=g.p_min_pu,
          ramp_limit_up=g.ramp_limit_up.where(g.ramp_limit_up > 0),
          ramp_limit_down=g.ramp_limit_down.where(g.ramp_limit_down > 0))
    cf = pd.concat([x[k].iloc[:hours] for k in CF_SHEETS if k in x], axis=1).set_index(snaps)
    n.generators_t.p_max_pu = cf[cf.columns.intersection(g.index)]

    # バイオマス: FIT優先給電として出力を固定 (p_min_pu = p_max_pu = プロファイル)
    # プロファイルの無いユニットは、ある7基の設備容量加重平均プロファイルで固定
    bio = g.index[g.carrier == "Biomass"]
    bio_cf = x["biomass_cf"].iloc[:hours].set_index(snaps)
    avg_cf = (bio_cf * g.p_nom[bio_cf.columns]).sum(axis=1) / g.p_nom[bio_cf.columns].sum()
    bio_prof = pd.DataFrame({b: bio_cf[b] if b in bio_cf else avg_cf for b in bio})
    n.generators_t.p_max_pu[bio] = bio_prof
    n.generators_t.p_min_pu = bio_prof

    # 原子力: nuclear_cf シート (HJKS の実績出力) があれば、その出力に固定する
    if "nuclear_cf" in x:
        nu = x["nuclear_cf"].columns.intersection(g.index[g.carrier == "Nuclear"])
        n.generators_t.p_min_pu[nu] = n.generators_t.p_max_pu[nu]

    # 供給力不足の検知用
    n.add("Generator", a.index + " load shedding", bus=a.index.values,
          carrier="Load shedding", p_nom=1e6, marginal_cost=VOLL)

    # 連系線
    ic = x["interconnections"]
    n.add("Link", ic.name.values, bus0=ic.area0.values, bus1=ic.area1.values, p_nom=ic.p_nom.values,
          p_min_pu=(-ic.p_nom_reverse / ic.p_nom).values, efficiency=ic.efficiency.values,
          marginal_cost=ic.marginal_cost.values, carrier="AC")

    # 揚水 ポンプ/タービン
    c = x["converters"]
    acbus = lambda col: c[col].where(c[col] != "AC", c.area).values  # noqa: E731
    n.add("Link", c.name.values, bus0=acbus("carrier_in"), bus1=acbus("carrier_out"),
          p_nom=c.p_nom.values, efficiency=c.efficiency.values, marginal_cost=c.marginal_cost.values,
          carrier=[ci if ci != "AC" else co for ci, co in zip(c.carrier_in, c.carrier_out)])
    return n

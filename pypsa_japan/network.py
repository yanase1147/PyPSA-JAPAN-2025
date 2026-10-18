"""Network_config_2025 形式の Excel から PyPSA ネットワークを構築する。

シートとPyPSAコンポーネントの対応:
    areas              -> Bus (エリア = 1ノード)
    thermal_efficiency + fuel_price -> 石炭・LNG の月別の限界費用
    generators         -> Generator (時系列CFは *_cf シートの同名列。nuclear_cf は出力固定。
                          committable の火力は起動停止・最低出力・最小運転/停止時間・起動費を扱う。
                          max_annual_cf 列は年間設備利用率の上限、must_run_pu 列は起動停止を扱わない火力の最低出力)
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


def build_network(x, hours=8760, year=2025, phs_initial_soc=0.5, unit_commitment=True, annual_cap=True, vom=None):
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
    # 起動停止 (committable) の火力は p_min_pu が「運転中の最低出力」になる。
    # unit_commitment=False のときは起動停止を扱わず、最低出力も 0 にする（従来の経済負荷配分）。
    sheet_uc = g.get("committable", pd.Series(False, index=g.index)).fillna(False).astype(bool)
    uc = sheet_uc & unit_commitment
    p_min = g.p_min_pu.where(~sheet_uc | uc, 0)   # 起動停止を扱わないときは火力の最低出力を外す
    # 最低出力（must_run_pu, tools/lng_must_run.py）: 起動停止を扱わない発電機の下限。起動停止を扱う発電機は p_min_pu に従う
    if "must_run_pu" in g:
        p_min = p_min.where(uc, p_min.combine(g.must_run_pu.fillna(0), max))
    kw = {}
    if uc.any():
        kw = dict(committable=uc,
                  min_up_time=g.get("min_up_time", 0).fillna(0).astype(int).where(uc, 0),
                  min_down_time=g.get("min_down_time", 0).fillna(0).astype(int).where(uc, 0),
                  start_up_cost=g.get("start_up_cost", 0).fillna(0).where(uc, 0))
    n.add("Generator", g.index, bus=g.area.values, carrier=g.carrier.values, p_nom=g.p_nom,
          marginal_cost=g.marginal_cost, efficiency=g.efficiency,
          p_max_pu=g.p_max_pu, p_min_pu=p_min,
          ramp_limit_up=g.ramp_limit_up.where(g.ramp_limit_up > 0),
          ramp_limit_down=g.ramp_limit_down.where(g.ramp_limit_down > 0), **kw)
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

    # 石炭・LNG の限界費用: thermal_efficiency と fuel_price シートがあれば、月別の燃料価格と効率から計算する
    #   限界費用 [円/MWh] = (輸入価格 + 税) [円/t] / 標準発熱量 [GJ/t] * 3.6 [GJ/MWh] / 効率
    if "thermal_efficiency" in x and "fuel_price" in x:
        te = x["thermal_efficiency"].set_index("name")
        te = te.loc[te.index.intersection(g.index)]
        fp = x["fuel_price"].set_index("fuel")
        months = [f"m{m:02d}" for m in range(1, 13)]
        other = fp["other_yen_per_t"].fillna(0) if "other_yen_per_t" in fp else 0   # 燃料諸経費 [円/t]（発電コスト検証WG）
        heat_cost = fp[months].add(fp.tax_yen_per_t + other, axis=0).div(fp.heat_GJ_per_t, axis=0) * 3.6  # 円/MWh(燃料)
        # 燃料費以外の変動費（円/MWh）: fuel_price シートの vom_yen_per_MWh 列。vom={"coal": 1500, ...} で上書きできる
        add = fp["vom_yen_per_MWh"].fillna(0).to_dict() if "vom_yen_per_MWh" in fp else {}
        add.update(vom or {})
        # 所内率（発電コスト検証WG）: 送電端効率 = 発電端効率 ×（1−所内率）で燃料費を計算する
        own = fp["own_use_rate"].fillna(0).to_dict() if "own_use_rate" in fp else {}
        mc = pd.DataFrame({name: heat_cost.loc[r.fuel].values / (r.efficiency * (1 - own.get(r.fuel, 0))) + add.get(r.fuel, 0)
                           for name, r in te.iterrows()}, index=range(1, 13))
        n.generators_t.marginal_cost = mc.reindex(snaps.month).set_index(snaps)

    # 年間の発電量の上限: generators シートの max_annual_cf 列（非効率石炭の稼働抑制, tools/coal_capacity_market.py）
    #   e_sum_max = max_annual_cf × p_nom × 時間数。ローリングホライズンでは run_dispatch.py が窓ごとに配分し直す
    if annual_cap and "max_annual_cf" in g:
        cap = g.max_annual_cf.dropna()
        n.generators.loc[cap.index, "e_sum_max"] = cap * g.p_nom[cap.index] * len(snaps)

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

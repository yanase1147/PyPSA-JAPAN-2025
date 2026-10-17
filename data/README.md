# 入力データ

`Network_config_2025.xlsx` が2025年の入力データです。
別のケースを作る場合も、同じシート構成のExcelをここに置いてください（`.csv` はコミット対象外）。

## 必要なシート

| シート | 内容 |
|---|---|
| `areas` | エリア名, 緯度, 経度 |
| `carriers` | 揚水用キャリア (`PHS_<地点名>`) |
| `generators` | 発電機（エリア, 種別, 定格, 限界費用, ランプ制約, 起動停止パラメータ `committable`・`p_min_pu`・`min_up_time`・`min_down_time`・`start_up_cost` 等） |
| `thermal_efficiency` | 石炭・LNG の発電機ごとの効率（発電端・HHV）と燃料。`tools/thermal_opex.py` で作成 |
| `fuel_price` | 燃料ごとの標準発熱量・石油石炭税・月別の輸入価格（円/t） |
| `interconnections` | 連系線（area0, area1, 順方向/逆方向容量） |
| `loads` | エリア需要（`demand_scale` で倍率） |
| `stores` | 揚水上池（容量 MWh） |
| `converters` | 揚水ポンプ/タービン（`AC` はそのエリアの系統バス） |
| `solar_cf`, `wind_cf`, `hydro_cf`, `biomass_cf` | 8760時間の出力プロファイル（列名 = 発電機名） |
| `nuclear_cf` | 8760時間の原子力CF（列名 = 発電機名）。この出力に固定される。HJKS実績から `tools/nuclear_cf_from_hjks.py` で作成 |
| `coal_cf` | 8760時間の石炭の出力上限（列名 = 発電機名）。定期点検・計画外停止を反映。`tools/coal_availability.py` で作成 |
| `demand_mw` | 8760時間の需要（列名 = `<エリア>|<負荷名>`） |

## Renewables.ninja のCF

`tools/fetch_ninja_cf.py` を実行すると、`solar_cf_ninja_<年>.csv` と `wind_cf_ninja_<年>.csv` がここに出力されます。
`run_dispatch.py --solar-cf ... --wind-cf ...` で Excel のシートと差し替えられます。

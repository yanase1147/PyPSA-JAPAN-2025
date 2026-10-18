# 入力データ

`Network_config_2025.xlsx` が2025年の入力データです。
別のケースを作る場合も、同じシート構成のExcelをここに置いてください（`.csv` はコミット対象外）。

## 必要なシート

| シート | 内容 |
|---|---|
| `areas` | エリア名, 緯度, 経度 |
| `carriers` | 揚水用キャリア (`PHS_<地点名>`) |
| `generators` | 発電機（エリア, 種別, 定格, 限界費用, ランプ制約, 起動停止パラメータ `committable`・`p_min_pu`・`min_up_time`・`min_down_time`・`start_up_cost`、年間設備利用率の上限 `max_annual_cf`（非効率石炭の稼働抑制、`tools/coal_capacity_market.py` で設定） 等） |
| `thermal_efficiency` | 石炭・LNG の発電機ごとの効率（発電端・HHV）と燃料。`tools/thermal_opex.py` で作成 |
| `fuel_price` | 燃料ごとの標準発熱量・石油石炭税・月別の輸入価格（円/t）・燃料費以外の変動費 `vom_yen_per_MWh`（JEPXに合わせた較正値） |
| `excluded_generators` | モデルから外した発電機（`generators` と同じ列。読み込まれない） |
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

## 入力の修正履歴

- 2026-10: 製鉄所の副生ガス発電（10件, 5.7 GW）を `generators` シートから外し、`excluded_generators` シートに移した
  - 大半が構内で自家消費され、需要（電力会社が供給する分）に含まれないため。電力調査統計（事業用）の石炭・LNGにも含まれない
  - 修正後に thermal_opex.py, thermal_uc_params.py, coal_capacity_market.py を再実行

- 2026-10: 経産省 石炭火力検討WG 第1回 参考資料1（2020/8/7）の号機別一覧と照合して修正
  - 東新潟 1号（600 MW）: 石炭 → 石油（重油）。2号（600 MW）: 石炭 → LNG（重油・原油・LNGの汽力）
  - 磯子 新1号（600 MW）: 石油 → 石炭（USC）。竹原 3号（700 MW）: 石油 → 石炭（SC）
  - 勿来（7〜9号）: 2,650 → 1,450 MW（東北経済産業局 主要電源マップと一覧の合計）
  - 修正後に tools/coal_availability.py, thermal_uc_params.py, thermal_opex.py, coal_capacity_market.py を再実行
- 2026-10: 広野・鹿島で、石炭と別の燃料の号機が1行にまとまっていたのを分けた
  - 広野（石油 1,800 MW）= 2号（石油 600 MW）＋ 5・6号（石炭 USC 600 MW×2）。1・3・4号は2023年10月に廃止
    → 「Hirono Thermal PS」石油 600 MW と「Hirono Thermal PS Units 5-6」石炭 1,200 MW に分割
  - 鹿島（石炭 1,905 MW）= JERA 鹿島 7号系列（都市ガス GTCC 1,260 MW）＋ 鹿島パワー 2号（石炭 USC 645 MW）。
    JERA 鹿島 1〜6号（石油）は2023年3月に廃止
    → 「Kashima Thermal PS」LNG 1,260 MW と「Kashima Power Kashima Thermal PS Unit 2」石炭 645 MW に分割
  - 日本製鉄 鹿島 1号: 475 → 522 MW、方式 USC → SC（2007年、東京電力への卸供給）
  - 出典: 経産省の号機別一覧（上記）、Wikipedia「広野火力発電所」「鹿島火力発電所」「日本製鉄鹿島火力発電所」、
    J-POWER プレスリリース（2020/7/1）

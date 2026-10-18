# PyPSA-JAPAN-2025

[PyPSA](https://pypsa.org) を用いた、2025年の日本の電力系統（9エリア）の需給シミュレーションです。
エリアごとの需要・発電機・連系線・揚水を Excel で与え、1時間刻み・1年分（8,760時間）の経済負荷配分（費用最小化LP）を解きます。

## モデル概要

- **ノード**: 北海道・東北・東京・中部・北陸・関西・中国・四国・九州の9エリア（各エリア1バス）
- **発電機**: 石炭・LNG・石油・原子力・水力・太陽光・風力・バイオマス等（ユニット単位）。限界費用の安い順に給電
- **太陽光・風力・水力**: 時間別の設備利用率（CF）を出力上限とする（出力抑制可）
- **バイオマス**: FIT優先給電として、プロファイルどおりに出力を固定
- **連系線**: 輸送モデル（双方向の容量制約）
- **揚水**: 地点ごとに上池（Store）＋ポンプ/タービン（Link）。初期貯水率は容量の50%
- **供給力不足**: エリアごとに高コスト（1,000,000 円/MWh）の仮想発電機で検出
- **ソルバー**: HiGHS。1年一括ではメモリ（約16GB）を超えるため、既定で期間を窓に区切り、48時間重ねて順に解く（ローリングホライズン）。窓は起動停止ありで2週間（336時間）、`--uc off` で約1か月（744時間）。窓ごとに最適化モデルを解放し、8GB環境でも1年分を解ける

## 使い方

```bash
pip install -r requirements.txt

python run_dispatch.py data/Network_config_2025.xlsx --hours 168   # 1週間で動作確認
python run_dispatch.py data/Network_config_2025.xlsx               # 1年分・起動停止あり（2コアで約35分）
python run_dispatch.py data/Network_config_2025.xlsx --uc off      # 1年分・起動停止なし（2コアで約3分）
```

ローリングホライズンは既定で有効です。1年分を一括で解く場合は `--no-rolling` を付けます
（1年分は約16GB以上のメモリが必要で、単体法では数十分〜数時間かかるため、通常は使いません）。

```bash
python run_dispatch.py data/Network_config_2025.xlsx --no-rolling --hours 336   # 短い期間なら一括でも可
```

結果は `results/dispatch.nc`（PyPSA netCDF）に保存され、電源別発電量・設備利用率・抑制量、
エリア別平均限界価格、連系線の混雑時間率を表示します。

### 結果を表示する

```bash
python show_results.py                                        # 全期間・全国（31日超は日平均）
python show_results.py --area Tokyo --start 2025-08-01 --end 2025-08-07   # エリア・期間を指定（1時間値）
python show_results.py --no-show                              # ウィンドウを開かず PNG 保存のみ
```

保存済みの `results/dispatch.nc` を読み、集計表に加えて ①需給バランス（電源別積み上げ・揚水・連系線受送電）
②エリア別の電源構成と需要 ③エリア別限界価格のヒートマップ ④連系線の方向別混雑時間率 を表示し、
`results/figures/` に PNG で保存します。

### Renewables.ninja のCFを使う

```bash
export NINJA_TOKEN=<Renewables.ninja の API トークン>
python tools/fetch_ninja_cf.py data/Network_config_2025.xlsx 2023   # 気象年
python run_dispatch.py data/Network_config_2025.xlsx \
    --solar-cf data/solar_cf_ninja_2023.csv --wind-cf data/wind_cf_ninja_2023.csv
```

地点は `areas` シートのエリア代表点（各1地点）。太陽光は固定架台・傾斜30°・真南・損失10%、
風力は Vestas V90 2000・ハブ高さ80m（MERRA-2）。UTC→JST変換済み。

### 原子力の出力（HJKS 実績）

原子力は `nuclear_cf` シートのCFどおりに出力を固定します（長期固定電源として抑制しない）。
このシートは、HJKS のユニット別・1時間ごとの出力CSV（kW）から次のコマンドで作成・更新します。

```bash
python tools/nuclear_cf_from_hjks.py data/Network_config_2025.xlsx nuclear_2025_hourly_by_unit.csv
```

ユニット出力を発電所単位に合計し、`generators` シートの `p_nom` で割ってCFにします。
2025年実績では合計 94.5 TWh です。`nuclear_cf` シートが無い場合は、従来どおり `generators` シートの
`p_max_pu` を上限として経済負荷配分します。

### 石炭火力の稼働率（定期点検・計画外停止）

石炭は `coal_cf` シートの時間別上限（`p_max_pu`）の範囲で経済負荷配分します。次のコマンドで作成・更新します。

```bash
python tools/coal_availability.py data/Network_config_2025.xlsx
```

- 計画停止：ボイラー点検（2年に1回・約60日）を対象年はユニットの半数に、夏前の中間点検（約10日）をそれ以外に割り当て、
  春（3〜6月）・秋（9月中旬〜12月中旬）にエリア内で時期をずらして配置（九州電力 料金算定資料, 2012）
- 計画外停止：石炭の計画外停止率 6.9%（広域機関 2022〜2024年度平均, 2026年1月）を期待値として全時間に反映
- 発電所単位の行は 800 MW/基を目安に基数に分割。年平均の稼働率は約83%

### 火力の起動停止（最低出力・最小運転/停止時間・起動費）

火力（石炭・LNG・石油・その他）は起動停止を考慮して解きます（既定は線形化した起動停止 `--uc linear`）。
パラメータは `generators` シートの `committable`, `p_min_pu`（運転中の最低出力）, `min_up_time`, `min_down_time`,
`start_up_cost` 列で、次のコマンドで設定します（値と出典はスクリプト冒頭に記載）。

```bash
python tools/thermal_uc_params.py data/Network_config_2025.xlsx
python run_dispatch.py data/Network_config_2025.xlsx            # 起動停止あり（2コアで約35分）
python run_dispatch.py data/Network_config_2025.xlsx --uc off   # 起動停止なし（約3分）
```

| 電源 | 最低出力 | 最小運転/停止時間 | 起動費 |
|---|---|---|---|
| 石炭 500 MW以上 | 30% | 24 h / 12 h | 15,000 円/MW・回 |
| 石炭 500 MW未満 | 50% | 24 h / 12 h | 15,000 円/MW・回 |
| LNG | 30% | 4 h / 4 h | 5,000 円/MW・回 |
| 石油・その他 | 30% | 4 h / 4 h | 5,000 円/MW・回 |

最低出力・起動費は発電コスト検証WG（2021）等の公表値。最小運転/停止時間は公表値が見つからないための仮定。
`--uc milp` で整数計画として厳密に解くこともできる（1年分で数時間）。

### 中小のバイオマス（FIT/FIP 統計）

HJKS に載らない中小のバイオマスを、エリアごとに1つの発電機「Biomass (small, <エリア>)」として出力固定で入れています。

```bash
python tools/small_biomass.py data/Network_config_2025.xlsx A_pref202512.xlsx C_kaitori202603.csv
```

- 容量: FIT/FIP 統計の表A②（都道府県別導入容量、新規＋移行認定、バイオマス比率考慮あり）をエリアに集計し、
  モデルの大型バイオマスの容量を差し引く（2025年12月末: 全国 7.7 GW、追加 6.4 GW）
- 発電量: 表C（買取電力量）の2025年の月別値を容量比でエリアに配分し、大型分を差し引く（追加 27.1 TWh）
- FIP 移行分の発電量は含まない。石炭混焼のバイオマス相当分は、石炭としても数えているため二重計上になる

### 石炭・LNG の限界費用（燃料価格 ÷ 効率）

石炭・LNG の限界費用は、2025年の月別の輸入価格と発電方式ごとの効率から計算します。

```bash
python tools/thermal_opex.py data/Network_config_2025.xlsx
```

- `fuel_price` シート: 標準発熱量（2023年度改訂: 一般炭 25.88、LNG 54.69 GJ/t）、石油石炭税（LNG 1,860、石炭 1,370 円/t）、
  2025年1〜12月の通関CIF価格（円/t）
- `thermal_efficiency` シート: 発電機ごとの方式の内訳と効率（発電端・HHV）。容量加重で石炭 40.9%、LNG 48.9%
  （省エネ法の事業者目標 石炭 41%・LNG 48% とほぼ同水準）。方式の内訳は公開情報にもとづく推定なので、手で直してよい
- 限界費用 = (輸入価格 + 税) / 標準発熱量 × 3.6 / 効率。年平均で石炭 6.1〜7.6、LNG 10.3〜15.1 円/kWh
- 製鉄所の副生ガス発電（10件, 5.7 GW）は入力から外した（`excluded_generators` シートに残してある）。大半が構内で自家消費され、
  モデルの需要（電力会社が供給する分）に含まれないので、供給に入れると二重に数えてLNGを押し出していた
  （4〜12月で LNG 130→152 TWh、実績 201 TWh）。戻すには `excluded_generators` の行を `generators` シートに戻し、
  `python tools/thermal_opex.py` などを再実行する

#### LNG火力の最低出力（must-run）

起動停止なしの経済負荷配分では、需要の低い春と秋にLNGが大きく下がり、実績よりLNGが少なく石炭が多くなります
（LNG 4〜12月 152 TWh、実績 201 TWh。電力調査統計・事業用）。実際には、予備力の確保・エリア内の系統制約・燃料契約などで
LNGを下げ切れないと考えられます。そこで `generators` シートの `must_run_pu` 列に、LNG火力の最低出力を定格の30%として入れています。

```bash
python tools/lng_must_run.py data/Network_config_2025.xlsx [--pu 0.3]
```

- 起動停止を扱わない（`--uc off`）ときに効く。起動停止ありのときは、起動停止の最低出力（`p_min_pu` 30%）に従う
- 値は感度分析（10・20・30%）で選んだ仮定。時間ごとの実績の下限は未確認。実績の月別LNG発電量の最小（5月）は容量の約30%
  なので、30% は時間ごとの下限としては高めで、5月はほぼ最低出力に張り付く
- 石炭 −18 TWh、LNG +19 TWh（20%→30%）。30%では石炭が実績に近づく（270 TWh、実績 264 TWh）
- 線形化した起動停止ありと起動停止なしで、石炭・LNGの発電量はほぼ同じだった（石炭 329.6/329.9、ガス 188.7/190.5 TWh）ので、
  起動停止の最低出力では説明できない
- 実行時に `--lng-min-pu 0.2` のように上書きできる（0で最低出力なし）

#### 燃料費以外の費用（発電コスト検証WG）

限界費用には、輸入価格・石油石炭税に加えて、発電コスト検証WG（2021）「各電源の諸元一覧」の **燃料諸経費**
（石炭 2,000 円/t、LNG 2,800 円/t。`fuel_price` シートの `other_yen_per_t` 列）を入れています（石炭約0.7円/kWh、LNG約0.4円/kWh）。

- WG の運転維持費は固定費（人件費・修繕費・諸費・業務分担費）だけで、変動する運転維持費は示されていない。
  WG が示す変動費は、燃料費（燃料諸経費を含む）とCO2対策費で、2025年の発電には排出価格がない（GX-ETSは2026年度から義務化）
- WG の値だけでは、価格水準が JEPX より低い（10〜12月の平均絶対誤差 2.36 円/kWh、東日本 −2.1、西日本 −2.6）
- 以前は、JEPX（2025年10〜12月）に合わせた較正値を `fuel_price` シートの `vom_yen_per_MWh` 列に入れていた
  （石炭 3.0、LNG 1.0 円/kWh、LNG最低出力20%で誤差 0.69、30%で 0.80 円/kWh）。これは運転維持費の実測値ではなく、
  予備力・最低出力・燃料制約・入札時の上乗せなど、モデルにない要因による上振れを一括で表すもの。既定は 0 にしてある
- `--vom-coal 3.0 --vom-lng 1.0` を付けると、較正値で計算できる
- 発電コスト検証WG（2021）には、所内率（石炭 5.5%、LNG 2.3%）も示されている。モデルにはまだ入れていない

### 非効率石炭の稼働抑制（容量市場の設備利用率50%）

設計効率42%未満の石炭火力は、年間の設備利用率を50%以下に抑えて運転するとして、年間の発電量に上限を設けます。

```bash
python tools/coal_capacity_market.py data/Network_config_2025.xlsx
python run_dispatch.py data/Network_config_2025.xlsx                   # 上限あり（既定）
python run_dispatch.py data/Network_config_2025.xlsx --no-annual-cap   # 上限なし
```

- 根拠: 容量市場では、設計効率42%未満の石炭は設備利用率50%超で容量確保契約金額が20%減額（実需給2025年度〜、
  [広域機関 検討会 2021](https://www.occto.or.jp/iinkai/youryou/kentoukai/2021/files/youryou_kentoukai_35_03_2.pdf)）。
  実需給2027年度からは「設備利用率50%以下」がリクワイアメント（[広域機関 2023](https://www.occto.or.jp/market-board/market/oshirase/2023/files/230720_sekitankouritsu.pdf)）
- 発電機ごとの方式の内訳（`tools/thermal_opex.py` の `PLANT`）から、効率42%未満の容量の割合 f を求め、
  `generators` シートの `max_annual_cf` = 0.5 × f + 1.0 × (1 − f) とする。対象は石炭46行（効率42%未満の容量 23.2 GW）。
  副生ガス発電は対象外
- 1年一括では PyPSA の `e_sum_max`（年間発電量の上限）。ローリングホライズンでは、残りの上限を残りの期間の
  正味需要（需要 − 太陽光・風力 − 原子力・バイオマス）の比で窓に配分し、使い残した分は後の窓に回す
- 起動停止ありで上限を制約のまま入れると、窓ごとの計算が40〜75倍遅くなる（1年で10時間以上）。そのため既定
  （`--cap-method adder`）では2段階で解く: ①起動停止なし（LP）・上限ありで解き、窓ごとの上限の双対変数
  （上限の機会費用、発電量加重で約3円/kWh）を求める ②それを対象の石炭の限界費用に上乗せし、上限の制約は外して
  起動停止ありで解く。年間上限は近似的にしか守られないので、結果の表示で上限との差を確かめる。
  `--cap-method hard` で制約のまま解くこともできる（低速）

## ファイル構成

```
run_dispatch.py         実行スクリプト（CLI）
pypsa_japan/network.py  Excel → PyPSA ネットワーク構築
show_results.py         結果の表示スクリプト（CLI）
pypsa_japan/summary.py  結果の集計
pypsa_japan/plots.py    結果の図示
tools/fetch_ninja_cf.py Renewables.ninja から太陽光・風力CFを取得
tools/nuclear_cf_from_hjks.py HJKS の原子力ユニット別出力から nuclear_cf シートを作成
tools/coal_availability.py   石炭の定期点検・計画外停止から coal_cf シートを作成
tools/thermal_uc_params.py   火力の起動停止パラメータを generators シートに設定
tools/small_biomass.py       FIT/FIP 統計から中小のバイオマスをエリア別に追加
tools/thermal_opex.py        石炭・LNG の効率と燃料価格のシートを作成（限界費用の根拠）
tools/coal_capacity_market.py 非効率石炭の年間設備利用率の上限（max_annual_cf）を設定
tools/lng_must_run.py        LNG火力の最低出力（must_run_pu）を設定
data/                   入力データ（Network_config_2025.xlsx, シート構成は data/README.md）
```

## 既知の制約・仮定

- 火力の起動停止は線形化（運転状態を0〜1の連続値で扱う近似）。調整力（予備力）の確保は考慮しない
- 原子力は2025年の実績出力に固定（`nuclear_cf` シート）
- 石炭の停止は統計値に基づく想定（2025年の実際の停止時期ではない）。計画外停止は期待値として一律に反映
- エリア内の送電制約は考慮しない
- 揚水の初期貯水率50%（各窓の終端は自由）
- 非効率石炭の稼働抑制は、減額（経済的なペナルティ）ではなく年間の上限として扱う。対象の判定は推定した方式の内訳による
- バイオマスのうち `biomass_cf` にプロファイルの無いユニットは、7基の容量加重平均プロファイルで固定

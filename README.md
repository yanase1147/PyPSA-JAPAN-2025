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
- **ソルバー**: HiGHS。1年一括ではメモリ（約16GB）を超えるため、約1か月（744時間）の窓を48時間重ねて順に解く（ローリングホライズン）

## 使い方

```bash
pip install -r requirements.txt

# 入力Excelを data/ に置いてから
python run_dispatch.py data/project_2025_draft_2.xlsx --hours 168   # 1週間で動作確認
python run_dispatch.py data/project_2025_draft_2.xlsx               # 1年分（4コアで約4分）
```

結果は `results/dispatch.nc`（PyPSA netCDF）に保存され、電源別発電量・設備利用率・抑制量、
エリア別平均限界価格、連系線の混雑時間率を表示します。

### Renewables.ninja のCFを使う

```bash
export NINJA_TOKEN=<Renewables.ninja の API トークン>
python tools/fetch_ninja_cf.py data/project_2025_draft_2.xlsx 2023   # 気象年
python run_dispatch.py data/project_2025_draft_2.xlsx \
    --solar-cf data/solar_cf_ninja_2023.csv --wind-cf data/wind_cf_ninja_2023.csv
```

地点は `areas` シートのエリア代表点（各1地点）。太陽光は固定架台・傾斜30°・真南・損失10%、
風力は Vestas V90 2000・ハブ高さ80m（MERRA-2）。UTC→JST変換済み。

## ファイル構成

```
run_dispatch.py         実行スクリプト（CLI）
pypsa_japan/network.py  Excel → PyPSA ネットワーク構築
pypsa_japan/summary.py  結果の集計
tools/fetch_ninja_cf.py Renewables.ninja から太陽光・風力CFを取得
data/                   入力データ置き場（コミット対象外, data/README.md 参照）
```

## 既知の制約・仮定

- 起動停止・最低出力（unit commitment）は考慮しない線形モデル
- エリア内の送電制約は考慮しない
- 揚水の初期貯水率50%（各窓の終端は自由）
- バイオマスのうち `biomass_cf` にプロファイルの無いユニットは、7基の容量加重平均プロファイルで固定

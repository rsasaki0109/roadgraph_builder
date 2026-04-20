# export-bundle のパラメータチューニング

**目的:** 実データ（または `examples/` のサンプル）で一度 `export-bundle` を通し、**`sim/map.geojson`**（必要なら **`lanelet/map.osm`**) を見ながら、`build` と同じ **ギャップ・マージ・中心線** 系パラメータを合わせる。

## 最短の流れ

1. リポジトリルートで仮想環境を入れた状態にする（`make install` または `pip install -e .`）。
2. `make tune` または `./scripts/run_tuning_bundle.sh /tmp/my_tune` を実行する。
3. **`/tmp/my_tune/sim/map.geojson`** を QGIS で開く（または `docs/map.html` と同様の運用で Leaflet に流し込む）。
4. 形がおかしければ下表を見て CLI 引数を変え、同じコマンドで上書き生成し直す。

**引数の例（OSM 公開軌跡サンプル）:**

```bash
./scripts/run_tuning_bundle.sh /tmp/osm_tune \
  examples/osm_public_trackpoints.csv \
  examples/osm_public_trackpoints_origin.json
```

`--origin-json` は **メートル座標の CSV と同じ原点**の `lat0`/`lon0` が入った JSON を渡す（各 `examples/*_origin.json` を参照）。

## 調整する主なパラメータ（`build` / `export-bundle` 共通）

| 症状 | まず触るもの | 目安 |
| --- | --- | --- |
| 軌跡が短いセグメントだらけになる | `--max-step-m` | **大きく**（ギャップで切りすぎない） |
| 離れたトリップが一本の道路に繋がる | `--max-step-m` | **小さく**（大きな飛びを分割） |
| 交差点付近でノードが分かれすぎる | `--merge-endpoint-m` | **大きく**（端点をまとめる） |
| 関係ない端同士が一本につながる | `--merge-endpoint-m` | **小さく** |
| 中心線が荒い／滑らかすぎる | `--centerline-bins` | 細かく／粗く（PCA ビン数） |
| エッジの折れ線が密／疎 | `--simplify-tolerance` | メートル単位の Douglas–Peucker（小さく＝詳細） |

**HD-lite の帯:** `--lane-width-m`（`0` でオフセット無し、`export-bundle` の `--lane-width-m`）

## 確認用アーティファクト

| ファイル | 見ること |
| --- | --- |
| `sim/map.geojson` | 軌跡・中心線・ノード・（enrich 時）レーン L/R |
| `nav/sd_nav.json` | トポロジ・`length_m`・`allowed_maneuvers` / `allowed_maneuvers_reverse`（規制ではなく幾何ヒューリスティック） |
| `lanelet/map.osm` | JOSM で Lanelet／way の形 |

検証コマンド: `roadgraph_builder validate` / `validate-sd-nav` / `validate-manifest`（`make tune` でも最後に実行）。

`allowed_maneuvers` は信号・標識・法規のターン制限ではありません。ターン禁止を入れる場合の設計メモは [navigation_turn_restrictions.md](navigation_turn_restrictions.md)。

## X 接続検出（0.3.0 で追加）

`polylines_to_graph` は T 接続に先立って **`split_polylines_at_crossings`** を
実行し、2 本の polyline が空中交差（どちらの端点とも一致しない interior × interior）
している場合に交点で両方分割する。segment-segment intersection の検出、
polyline bbox による pre-filter、割り込み先のセグメント index 昇順でリビルド。

Paris 実データでの累積効果（`--max-step-m 40 --merge-endpoint-m 8`）:

| 指標 | T のみ | T + X |
| --- | --- | --- |
| edges | 221 | **347** |
| nodes | 217 | 254 |
| **LCC ノード数** | 84 (40%) | **135 (53%)** |
| multi_branch ノード | 72 | 112 |
| うち `t_junction` | 12 | 10 |
| うち `y_junction` | 37 | 30 |
| うち `x_junction` | 0 | **18** |
| うち `crossroads` | 0 | **8** |
| うち `complex_junction` | 23 | 46 |

`x_junction` / `crossroads` が正しくラベル付けされるようになり、今までは
`complex_junction` に丸められていた 4 分岐が適切に分類される。viewer の
click-to-route も 19 edge / 1923 m のルートが引ける。

## T 接続検出によるグラフ連結性向上（0.3.0 で追加）

`polylines_to_graph` は endpoint union-find に加え、先に
**`split_polylines_at_t_junctions`** を呼ぶ: あるポリラインの端点が別の
ポリラインの **内部近傍**（既定 `min_interior_m=1.0` m 以上端から離れる）
にある場合、相手側を projection 点で分割して共通ノードを作る。これにより
「終点マージでは拾えない T 字路」が正しく junction として表現される。

Paris 実データ（`--max-step-m 40 --merge-endpoint-m 8`）での before/after:

| 指標 | before (endpoint merge のみ) | after (T 接続も) |
| --- | --- | --- |
| edges | 123 | **221** |
| nodes | 223 | 217 |
| **LCC (最大連結成分) ノード数** | **5** | **84** |
| LCC ノード比率 | 2% | 40% |
| multi_branch ノード | 3 | 72 |
| うち `t_junction` | 0 | 12 |
| うち `y_junction` | 2 | 37 |
| うち `complex_junction` | 1 | 23 |

実データで 3 km レベルの経路が `route` で引けるようになった（`n210 → n219`、
6 edge、3004 m）。旧実装では 1 km 以上の連結経路がほぼ存在しなかった。

## センターライン平滑化（0.3.0 で差し替え）

`centerline_from_points` は **PCA 軸 + 等幅 bin median** から **時系列順
arc-length + Gaussian 重みづけ resampling**（両端は生 GPS 点に anchor）に
差し替え済み。`num_bins` は出力サンプル数を指し、任意で
`smoothing_m` 引数で sigma を上書き可。

Paris 実データ（107 segments、`--max-step-m 40`）での before/after 品質メトリクス:

| 指標 | 旧 (PCA bin median) | 新 (arc-length Gaussian) | 改善 |
| --- | --- | --- | --- |
| **平均絶対離散曲率**（rad/頂点） | 0.456 | 0.127 | **−72%** |
| 同・中央値 | 0.248 | 0.041 | −83% |
| **RMS perpendicular fit 残差**（m） | 1.62 | 0.95 | **−41%** |

- 旧実装はカーブ区間で直線的な PCA 軸に射影するため、折り返し・交差・ジグザグが発生しがち（実データの 8 ノード LCC は射影アーティファクト経由で偽接続されていた）
- 新実装は生点に Gaussian-weight を arc-length 空間で掛けるため、曲率情報を保つまま GPS ジッタだけ滑らかにできる
- 両端 anchor があるので、隣接セグメントとの endpoint-union-find も機能する

メトリクスは `roadgraph_builder.utils.geometry.polyline_mean_abs_curvature` /
`polyline_rms_residual` で誰でも再計測できる。

## 実データ観察メモ（OSM 公開 GPS トレース）

パリ中心（`bbox=2.3370,48.8570,2.3570,48.8770`、複数ページ統合で約 6600 点、重複除去後）で
パラメータを掃引した結果。**原点**は bbox 中心（`lat0=48.867, lon0=2.347`）。
再現手順:

```bash
# 5 ページをそれぞれ fetch（ODbL、適切な User-Agent で）
for p in 0 1 2 3 4; do
  python scripts/fetch_osm_trackpoints.py \
    --bbox "2.3370,48.8570,2.3570,48.8770" --max-points 1500 --page $p \
    -o /tmp/osm_real_data/paris_trackpoints_p${p}.csv
done
# ページごとに原点が異なるので、WGS84 側を単一原点で合体して meters CSV を作る
# （中心 lat0=48.867, lon0=2.347 で再投影してから --origin-json を渡す）
```

以下の掃引結果は、退化セルフループ除去（`pipeline.build_graph` 修正前）の数値。
修正後は退化セルフループ（`start_node_id == end_node_id` かつアーク長 < `2 × merge-endpoint-m`）は
`build` 側で自動ドロップされるため、セルフループ列は実質 0 になる。全体の edge 数は表の値から
修正前のセルフループ本数ぶん減る。

| `max-step-m` / `merge-endpoint-m` | nodes | edges | median length [m] | self-loop edges |
| --- | --- | --- | --- | --- |
| 25 / 8 *(default)* | 262 | 158 | 27.9 | 21 |
| 15 / 8 | 332 | 233 | 14.2 | 69 |
| 30 / 8 | 246 | 147 | 38.9 | 20 |
| 40 / 8 | 234 | 136 | 61.1 | 13 |
| 50 / 8 | 213 | 121 | 87.4 | 7 |
| 25 / 3 | 298 | 158 | 27.9 | 13 |
| 25 / 15 | 197 | 158 | 27.9 | 50 |
| 25 / 25 | 131 | 158 | 27.9 | 101 |
| 20 / 15 | 185 | 173 | 21.9 | 77 |

観察:

- 公開 OSM トレースはサンプル間隔にばらつきが大きく（パリ抽出の中央値は ~3 m、p95 で ~25 m、
  別トリップ間の飛びは最大 2.4 km）、**`max-step-m` はデフォルト 25 m だとサンプル間ギャップで
  切りすぎる**。 **30–40 m** 付近だと中心線長が現実的になる。
- **`merge-endpoint-m` を大きくすると端点マージで短セグメントの両端が同じノードに縮退しやすい**。
  修正後は退化セルフループは `build` が自動で落とすため安全側に倒せるが、真のループ（周回路）を
  壊したくない場合は **3–8 m** 付近が無難。
- `--simplify-tolerance` 1–2 m は今回の密度では edge 数をほぼ変えない（粗いポリラインが元々少ない）。
- 出発点として **`--max-step-m 40 --merge-endpoint-m 8`** を推奨し、`sim/map.geojson` で確認して
  微調整する運用が良い。

## 第二地域サンプル: 東京・丸の内〜日本橋（`bbox=139.7600,35.6700,139.7800,35.6900`）

都市・データ密度が違う実データでも同じ推奨値が有効かを確認するため、東京 2 km × 2.2 km
bbox で同じ掃引を実行した（5 ページ fetch、重複除去後 **7478 点**。原点は bbox 中心
`lat0=35.680, lon0=139.770`）。再現手順はパリの節と同じ（`scripts/fetch_osm_trackpoints.py`
の `--bbox` を差し替えるだけ）。

| `max-step-m` / `merge-endpoint-m` | nodes | edges | median length [m] | multi_branch | LCC nodes (%) |
| --- | --- | --- | --- | --- | --- |
| 25 / 8 *(default)* | 90 | 60 | 39.8 | 6 | 12 (13%) |
| 30 / 8 | 91 | 62 | 44.2 | 5 | 13 (14%) |
| 40 / 8 *(推奨)* | 75 | 54 | 71.0 | 7 | 12 (16%) |
| 50 / 8 | 66 | 50 | 108.8 | 8 | 11 (17%) |
| 25 / 3 | 106 | 77 | 23.7 | 11 | 13 (12%) |
| 25 / 15 | 81 | 54 | 44.7 | 4 | 12 (15%) |
| 40 / 15 | 68 | 50 | 85.2 | 6 | 11 (16%) |

観察:

- **退化セルフループは全パラメータで 0**（`pipeline.build_graph` の自動ドロップが期待どおり動作）。
- 東京のこの bbox はパリ中心より **OSM 公開 GPS トレースが疎**で、点数が同等でも
  edge 数は 1/3〜1/4（パリ 40/8 で 136 edges ↔ 東京 40/8 で 54 edges）。
  同一トリップが反復走行する率が低いため、LCC は 13–17% と低水準で頭打ち。
- それでも **推奨値 `40/8` は東京でも妥当**: デフォルト(`25/8`)だと median 39.8 m でギャップ
  切断が目立つのに対し、`40/8` は中心線が 71 m と現実的、かつ multi_branch 7 を維持
  （crossroads + y_junction が露出）。`25/3` は node/edge 数は増えるが dead_end が 85 に肥大し、
  x_junction=4 が出る代わりに連結性は改善しない。
- **生データそのものの不足** が上限: より大きな LCC が欲しい場合は bbox を広げる、または
  OSM 以外の高密度な実走 CSV（車載 GNSS の連続ログなど）を持ち込む方が効果的。
  パリで見られた「T/X 接続検出でパラメータ感度が激増」現象は、トリップ間の重複走行が
  存在してはじめて効く。

## 第三地域サンプル: Berlin Mitte（`bbox=13.3700,52.5100,13.4000,52.5250`）

V1 accuracy report と同じ Berlin Mitte bbox で、公開 OSM GPS トレースに対する推奨値を確認した。
5 ページ fetch、bbox 中心 `lat0=52.5175, lon0=13.3850` に再投影、重複除去後 **7500 点**。
評価 scope は Paris / Tokyo と同じく `--max-step-m` と `--merge-endpoint-m` の sweep に絞り、
`--centerline-bins=32`、`--simplify-tolerance` なしで固定した。評価指標は edge/node 数、
median edge length、multi_branch 数、最大連結成分 (LCC) 比率、self-loop edge 数。

再現手順:

```bash
mkdir -p /tmp/osm_tune_berlin
for p in 0 1 2 3 4; do
  python scripts/fetch_osm_trackpoints.py \
    --bbox "13.3700,52.5100,13.4000,52.5250" --max-points 1500 --page $p \
    -o /tmp/osm_tune_berlin/berlin_mitte_trackpoints_p${p}.csv
done
# ページごとの WGS84 CSV を bbox 中心 lat0=52.5175, lon0=13.3850 に再投影して
# /tmp/osm_tune_berlin/berlin_mitte_trackpoints.csv と origin JSON を作る。
```

| `max-step-m` / `merge-endpoint-m` | nodes | edges | median length [m] | multi_branch | LCC nodes (%) | self-loop edges |
| --- | --- | --- | --- | --- | --- | --- |
| 25 / 8 *(default)* | 65 | 64 | 90.4 | 21 | 31 (48%) | 3 |
| 30 / 8 | 65 | 64 | 85.8 | 21 | 31 (48%) | 3 |
| 40 / 8 *(推奨)* | 58 | 57 | 89.3 | 18 | 30 (52%) | 3 |
| 50 / 8 | 47 | 43 | 137.3 | 13 | 25 (53%) | 0 |
| 25 / 3 | 72 | 73 | 82.4 | 26 | 33 (46%) | 4 |
| 25 / 15 | 57 | 57 | 91.6 | 20 | 31 (54%) | 4 |
| 40 / 15 | 49 | 50 | 89.0 | 17 | 28 (57%) | 4 |

`40/8` の bundle 検証（`export-bundle` → `validate-manifest` / `validate-sd-nav` / `validate`）は通過。
manifest の bbox は `13.37003,52.51000` → `13.39998,52.52499` で入力 bbox と整合する。

観察:

- Berlin Mitte は Tokyo より LCC が大きく、**46–57%** まで伸びる。公開トレースの重複走行が
  Tokyo 丸の内〜日本橋よりあり、T/X 接続検出が効いている。
- ただし `50/8` は self-loop edge が 0 になる一方、edges 43 / median 137 m まで粗くなり、
  交差点の detail を落としすぎる。大域連結性だけを見て選ばない方がよい。
- `25/3` は edge/node と multi_branch を増やすが LCC 比率は 46% に下がる。細かい endpoint を
  残しすぎて dead fragment も増えるため、review 初期値としては強すぎる。
- 既存の Paris / Tokyo と合わせると、**推奨値 `--max-step-m 40 --merge-endpoint-m 8` は
  3 都市で破綻しない保守的な初期値**。Berlin では `25/8` も近い結果だが、`40/8` は
  median length を現実的に保ったまま LCC 比率を少し上げ、branch 数も過剰に増やさない。

## 次の一歩

- 手元の CSV を **同じ列名** `timestamp, x, y` にし、**原点 JSON** を自データ用に用意する。
- パラメータが決まったら、**README のコマンド例**や CI で使っているサンプルと **同じ行** で再現できるよう、シェルに書き留める。

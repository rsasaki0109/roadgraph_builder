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

## 次の一歩

- 手元の CSV を **同じ列名** `timestamp, x, y` にし、**原点 JSON** を自データ用に用意する。
- パラメータが決まったら、**README のコマンド例**や CI で使っているサンプルと **同じ行** で再現できるよう、シェルに書き留める。

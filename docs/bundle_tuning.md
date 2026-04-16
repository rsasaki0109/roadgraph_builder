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
  切りすぎる**。 **30–40 m** 付近だと中心線長が現実的になり、セルフループが減る。
- **`merge-endpoint-m` を大きくするとセルフループ（start_node_id == end_node_id、length 0 m）**が
  急増するのでノイズの多いデータでは **3–8 m** までに留めるのが無難。
- `--simplify-tolerance` 1–2 m は今回の密度では edge 数をほぼ変えない（粗いポリラインが元々少ない）。
- したがって公開 GPS トレースのようなばらつきの大きいソースでは、出発点として
  **`--max-step-m 40 --merge-endpoint-m 8`** を推奨し、`sim/map.geojson` で確認して
  微調整する運用が良い。

> self-loop の発生は **パイプライン上の未解決事項**。`merge_endpoint_m` が大きいと端点マージで
> 短セグメントの両端が同一ノードに縮退する。集計後に `start_node_id == end_node_id` の edge を
> 除外するかは**下流の利用側**で判断する（`validate` は通る）。

## 次の一歩

- 手元の CSV を **同じ列名** `timestamp, x, y` にし、**原点 JSON** を自データ用に用意する。
- パラメータが決まったら、**README のコマンド例**や CI で使っているサンプルと **同じ行** で再現できるよう、シェルに書き留める。

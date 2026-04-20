# roadgraph_builder — 開発計画・引き継ぎメモ

Codex / 次のセッション向け。**事実と意図を分けて**書く。
まず全体図を掴みたければ [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md) を先に開くこと（Mermaid 6 枚 + CLI 対応表 + モジュール索引）。

## スコープ（意図）

- 軌跡 CSV（`timestamp, x, y`）から **道路グラフ**（ノード／エッジ＋中心線）を構築し、**ナビ SD シード**・**シミュ用 GeoJSON**・**Lanelet 互換 OSM** を **`export-bundle`** で一括出力する。
- **HD** は「測量完成品」ではなく、enrich による **HD-lite 帯**、LiDAR／カメラは **段階的**（スタブ含む）。
- 生成したグラフ上で **ルーティング** まで完結させる（Dijkstra + turn_restrictions 対応）。Leaflet viewer で click-to-route 可視化まで。

## 確認済み（事実）

### パイプライン / エクスポート

- CLI 一覧 (v0.7.0 時点で **37 サブコマンド**): `build`, `visualize`, `validate`, `validate-detections`, `validate-sd-nav`, `validate-manifest`, `validate-turn-restrictions`, `validate-lane-markings`, `validate-guidance`, `validate-lanelet2-tags`, `validate-lanelet2`, `enrich`, `inspect-lidar`, `nearest-node`, `route`, `stats`, `fuse-lidar`, `export-lanelet2`, `apply-camera`, `export-bundle`, `detect-lane-markings`, `detect-lane-markings-camera`, `guidance`, `infer-lane-count`, `update-graph`, `process-dataset`, `doctor`（他 `reconstruct-trips` / `infer-road-class` / `infer-signalized-junctions` / `fuse-traces` / `match-trajectory` / `build-osm-graph` / `convert-osm-restrictions` / `project-camera` も継続サポート）。
- `export-bundle` → `nav/sd_nav.json`, `sim/{road_graph.json,map.geojson,trajectory.csv}`, `lanelet/map.osm`, `manifest.json`。`--lidar-points`（CSV/LAS/LAZ）/ `--detections-json` / `--turn-restrictions-json` で 1 コマンドでフル構成の artefact が出る。
- `manifest.json` は `graph_stats`（edge/node 数・長さ min/median/max/total・bbox m & WGS84）、`junctions`（hint カウント + multi_branch の junction_type 内訳）、`turn_restrictions_*`、`lidar_points` を持つ。`manifest.schema.json` で検証。
- HD: `enrich_sd_to_hd` が `metadata.sd_to_hd` に **`navigation_hints`**（`sd_nav` 参照）を含める。

### ナビゲーション

- **sd_nav**: `allowed_maneuvers`（digitized 終端ノード）と **`allowed_maneuvers_reverse`**（始端・逆走）を **2D 交差点ヒューリスティック**で付与（`navigation/sd_maneuvers.py`）。
- **ナビ規制**: `turn_restrictions` は別レイヤー。`export-bundle --turn-restrictions-json` と camera detections の `kind: "turn_restriction"` から生成。設計メモ: `docs/navigation_turn_restrictions.md`。
- **junction_type 分類**: `multi_branch` ノードを `t_junction` / `y_junction` / `crossroads` / `x_junction` / `complex_junction` に細分（`pipeline/junction_topology.py`）。`self_loop` hint も実装済み。

### ルーティング（0.3.0 追加）

- `routing.shortest_path`: directed state Dijkstra (`node`, `incoming_edge`, `direction`) で `no_*` / `only_*` 両対応。
- `routing.nearest_node`: lat/lon or meter-frame 座標から最寄りノードを snap。
- `routing.build_route_geojson` / `write_route_geojson`: 経路を LineString + per-edge + start/end Point の FeatureCollection に。
- CLI: `route`（id or `--from-latlon`/`--to-latlon`）、`--turn-restrictions-json`、`--output PATH.geojson`、`nearest-node`、`stats`。
- `core.graph.stats.graph_stats` / `junction_stats` は `export-bundle` と `stats` CLI が共有。

### OSM 連携（turn_restrictions 実データ）

- **`build-osm-graph`**: `scripts/fetch_osm_highways.py` が Overpass からダウンした highway ways を `polylines_to_graph` に流し込む。全 OSM 交差点が graph junction になるので、turn_restrictions の `via_node` を素直にマップできる。`roadgraph_builder.io.osm.build_graph_from_overpass_highways`。
- **`convert-osm-restrictions`**: OSM `type=restriction` リレーションを graph-space `turn_restrictions.json` に変換。via→最寄り node snap + way tangent alignment で from/to edge を決定。`no_u_turn` / same-way は `from_edge == to_edge` を許可。未マップ relation は `--skipped-json` にリーズン付きで出力。
- **Paris bbox 検証**: 11 OSM restrictions のうち **10 がマップ成功**。`route n312→n191` が `--turn-restrictions-json` 有無で 878 m→909 m に変わる（detour される）。
- **Viewer**: `docs/map.html` のデフォルトが `paris_grid` に移動。赤ドットマーカーで restriction junction を表示、pop-up に restriction 種別と from/to edge。pre-baked overlay `route_paris_grid.geojson` は制限順守ルート。

### LiDAR / カメラ

- **LAS 1.0–1.4 ヘッダ読み**: `io.lidar.las.read_las_header`（`laspy` 非依存）、`inspect-lidar` CLI。
- **LAS 点群 loader**: `io.lidar.las.load_points_xy_from_las`（numpy slice、point format 0–10）。
- **LAZ optional**: `pip install 'roadgraph-builder[laz]'` で `laspy[lazrs]` 経由、未インストール時は明示 `ImportError`。
- **サンプル LAS**: `examples/sample_lidar.las`（52 点、1.3 KB、`scripts/make_sample_las.py` で再生成可）。
- **fuse-lidar**: CSV / LAS / LAZ を拡張子で dispatch。
- **cross-format regression**: `tests/test_las_cross_format.py` が laspy で生成した PDRF 0-10 × LAS 1.2/1.3/1.4 全パターン + 64-bit extended point count を our reader と byte-match。out-of-band verification では PDAL の 7 real LAS (autzen_trim 3.7 MB / 110K pts 含む) で全パス、`fuse-lidar` も実稼働確認。
- **camera detections (edge-keyed)**: JSON で `apply-camera`、GeoJSON `semantic_summary` に反映。
- **camera 画像 → graph-edge pipeline**: `io/camera/{calibration,projection,pipeline}.py` + `project-camera` CLI。pinhole K + `camera_to_vehicle` rigid mount + per-image vehicle pose を合成して pixel→world ground plane→最寄 edge snap までを 1 コマンドで処理。horizon 超 ray / edge 遠 projection は drop カウント付き。example: `examples/camera_calibration_sample.json` + `examples/image_detections_sample.json`。
- **Brown-Conrady lens distortion**: `CameraIntrinsic.distortion` (k1,k2,p1,p2,k3 OpenCV order) + `undistort_pixel_to_normalized` の fixed-point iteration。`pixel_to_ground` が自動経路選択。cv2 と 1e-6 で一致。
- **realistic demo**: `scripts/generate_camera_demo.py` で wide-angle camera + distortion 込みの synthetic ground-truth データを生成。shipped: `examples/demo_*.json`。`tests/test_camera_demo_roundtrip.py` が < 10 cm recovery を regression 保証。
- **Viewer TR-aware JS Dijkstra**: click-to-route が `(node, incoming_edge, direction)` 状態で `no_*` / `only_*` 制限を honor。Paris grid で実動。`tests/test_viewer_js_dijkstra.py` + `tests/js/test_viewer_dijkstra.mjs` が Node subprocess で regression。
- **LiDAR intensity-based lane marking 検出（0.5.0 追加）**: `io/lidar/lane_marking.py::detect_lane_markings` が LAS 点群から per-edge で left / right / center 候補を抽出（intensity percentile + along-edge binning、ML 非使用）。`detect-lane-markings` / `validate-lane-markings` CLI。`lane_markings.schema.json` で検証。
- **HD-lite multi-source 補正（0.5.0 追加）**: `hd/refinement.py::refine_hd_edges` が lane markings / `trace_stats` / camera observations を混ぜて per-edge の refined half-width + confidence を計算。`enrich --lane-markings-json` / `--camera-detections-json` と `export-bundle --lane-markings-json` / `--camera-detections-refine-json` で注入。結果は `metadata.hd_refinement` に残る。

### ナビ guidance（0.5.0 追加）

- **`guidance` CLI**: `route.geojson` + `sd_nav.json` を入力に、`depart` / `arrive` / `straight` / `slight_left` / `left` / `sharp_left` / `slight_right` / `right` / `sharp_right` / `u_turn` / `continue` のカテゴリ付き Turn-by-turn step 列を生成（`navigation/guidance.py::build_guidance`）。heading_change_deg は正右・負左。Paris grid で end-to-end regression。`guidance.schema.json` + `validate-guidance` CLI。

### HD / Lanelet2 / ルーティング拡張（0.6.0 追加）

- **`infer-lane-count` CLI (α)**: `hd/lane_inference.py` が `lane_markings.json` の paint-marker 横方向オフセットを 1-D agglomerative clustering で束ね per-edge `attributes.hd.lane_count` + `hd.lanes[]`（`lane_index` / `offset_m` / `centerline_m` / `confidence`）を書き込み。fallback は `trace_stats.perpendicular_offsets` mode count。`road_graph.schema.json` に optional `lane_count` (1-6) / `lanes[]` 追加。`export-lanelet2 --per-lane` で 1 edge → N lanelet 展開 + 隣接 lane 間に `lane_change` regulatory_element。
- **Lanelet2 fidelity upgrade (δ)**: `export-lanelet2 --speed-limit-tagging regulatory-element` で `type=regulatory_element, subtype=speed_limit` 別 relation、`--lane-markings-json` で paint 強度由来の `subtype=solid|dashed` boundary。**`validate-lanelet2-tags` CLI** が OSM 出力を parse し `subtype` / `location` 欠落をエラー、`speed_limit` 欠落を warning。
- **Uncertainty-aware routing (ε)**: `route --prefer-observed` が観測済 edge のコストを `--observed-bonus`（default 0.5）、未観測を `--unobserved-penalty`（default 2.0）で重み付け。`--min-confidence` は `hd_refinement.confidence` 未満の edge を Dijkstra 展開から除外。`total_length_m` は重み付け後コストでなく実距離（meter）を報告。両 flag 未指定時は 0.5.0 と byte-identical。

### v0.7.0 "The Everything Release"（2026-04-20 shipped、12 機能 / 4 workstream）

**Perf / Incremental / Batch:**

- **P1 perf**: `polylines_to_graph` の X/T-junction split を O(N²) → O(N log N)（grid hash）。Paris 855-node fetch で build-osm-graph 顕著に高速化。
- **P2 incremental**: `update-graph` CLI — 既存 graph JSON に新 trajectory CSV を追加 merge。`absorb_tolerance_m` 以内の polyline は `trace_observation_count` を bump するだけ、full rebuild 不要（`roadgraph_builder/pipeline/incremental.py`）。
- **P3 batch**: `process-dataset` CLI — ディレクトリ内 CSV を `export_map_bundle` で一括処理し `dataset_manifest.json` に集約。`--parallel N` で `ProcessPoolExecutor`、`--continue-on-error` で file 単位エラー分離（`roadgraph_builder/cli/dataset.py`）。

**3D / elevation / camera & LiDAR 3D:**

- **3D1 elevation**: `build --3d` が trajectory CSV の optional `z` 列を読み edge に `attributes.polyline_z` / `attributes.slope_deg` / node に `attributes.elevation_m` を伝搬。`route --uphill-penalty` / `--downhill-bonus` が slope 方向に従って edge コストを調整。`export-lanelet2` が elevation 有り node に `<tag k="ele" .../>` 付与。2D graph は optional field のまま schema 検証通過。
- **3D2 camera-lane**: `detect-lane-markings-camera` CLI — 画像 RGB から pure-NumPy HSV + 4-connected component labeling で白黄マーキング検出 → `pixel_to_ground` で world frame に投影 → 最寄 edge に snap。cv2 / scipy 不要。`io/camera/lane_detection.py`。呼び出し: `detect-lane-markings-camera graph.json calib.json images_dir poses.json --output cands.json`。
- **3D3 lidar-3d**: `fuse-lidar --ground-plane` — RANSAC で dominant plane を推定し `height_band_m`（default 0–0.3 m）以内のポイントだけを 2D binned-median 融合に通す。`metadata.lidar.ground_plane_*` に法線・高さ帯・通過点数を記録。`--ground-plane` 未指定時は v0.6 と byte-identical。`io/lidar/las.py::load_points_xyz_from_las` / `io/lidar/points.py::load_points_xyz_csv` 追加（N,3 XYZ）。

**Autoware 連携（A workstream）:**

- **A1 reg-elems**: `export-lanelet2 --camera-detections-json` で `camera_detections.json` の observations を Lanelet2 OSM に wiring。`kind=traffic_light` → `regulatory_element, subtype=traffic_light`（検出点に `refers` node）、`kind=stop_line` + `polyline_m` → `line_thin, subtype=solid` way。未指定時は v0.6 δ と byte-identical。
- **A2 autoware**: `validate-lanelet2` CLI — PATH 上の `lanelet2_validation` を subprocess 実行し stdout/stderr からエラー/警告カウントを parse。`{status, errors, warnings, error_lines, return_code}` の structured dict。ツール非存在時は skip JSON + stderr warning で exit 0。`validate-lanelet2-tags`（完全性チェック）とは別。
- **A3 lane-change**: `route --allow-lane-change` で Dijkstra state を `(node, incoming_edge, direction, lane_index)` に拡張、同 edge 内の lane swap に `--lane-change-cost-m`（default 50 m）を加算。`Route.lane_sequence` に per-step lane index。`export_lanelet2_per_lane(lane_markings=...)` が `lane_change` relation に `sign=solid`（禁止）/ `sign=dashed`（許可）タグ、`lane_markings` 未指定時は `dashed` デフォルト。

**Validation / Scale / Performance ロバスト性（V workstream）:**

- **V1 accuracy**: `scripts/measure_lane_accuracy.py` — `infer-lane-count` 出力と OSM `lanes=` を centroid proximity + tangent alignment で matching、confusion matrix + MAE 出力。graph が meter-frame (`metadata.map_origin` あり) の場合は OSM lon/lat を自動で同じ ENU frame に変換。`docs/accuracy_report.md` に Paris 20e / **Tokyo Ginza (MAE 0.903 lanes)** / **Berlin Mitte (MAE 1.220 lanes)** の 2026-04-20 実測値。
- **V2 city-scale**: `tests/test_city_scale.py` — Paris 20e / Tokyo Setagaya / Berlin Neukölln を Overpass から fetch して build + export-bundle、edge_count 閾値 + 自己 loop 0 を assert。`@pytest.mark.city_scale` で default run は skip、`pytest -m city_scale` で opt-in。`.github/workflows/city-bench.yml` は `workflow_dispatch` 限定。
- **V3 memory**: `scripts/profile_memory.py` — `tracemalloc` で 4 stage (imports / trajectory load / build / export-bundle) の peak RSS と top-20 allocator を記録。`export_lanelet2` の `minidom.parseString → toprettyxml` を `_et_to_pretty_bytes` 直接 writer に置換し、byte-identical を保ったまま Paris trackpoints で **peak RSS 61 028 → 54 944 KB (-10.0%)**。`docs/memory_profile_v0.7.md` に詳細。

### 検証 / CI / 配布

- JSON Schema（road_graph / camera_detections / sd_nav / manifest / turn_restrictions / **lane_markings / guidance**）。全て `importlib.resources` 経由で読込、`doctor` が起動時自己チェック。
- CI: pytest（Python 3.10 / 3.12）+ 各 `validate-*` + `export-bundle` + `inspect-lidar` + `doctor` を全 push で走らせる。Node.js 24 opt-in 済。
- **配布**: `scripts/build_release_bundle.sh` + `.github/workflows/release.yml` で `v*` タグ push 時に `dist/roadgraph_sample_bundle.tar.gz` と sha256 を GitHub Release に自動添付。`examples/frozen_bundle/` に 0.3.0 時点の固定サンプルを同梱。
- **Benchmarks（0.5.0 追加）**: `scripts/run_benchmarks.py` / `make bench` が `polylines_to_graph_paris` / `polylines_to_graph_10k_synth`（現状は 10×10 grid）/ `shortest_path_paris`（100 クエリ）/ `export_bundle_end_to_end` の wall-time を計測。`--baseline baseline.json` で 3× 劣化時 exit 1。`docs/benchmarks.md` に v0.5.0 baseline 記載。CI は opt-in（`workflow_dispatch`）。
- **PyPI scaffold**: `.github/workflows/pypi.yml`（workflow_dispatch, Trusted Publisher, secrets なし）。有効化には PyPI 側の Trusted Publisher 設定 + GitHub Environment `pypi` が必要。

### 可視化

- `docs/map.html` (Leaflet + OSM タイル): `paris` / `osm` / `toy` の 3 データセット切替、Paris は `multi_branch` を含むリッチな実データ（ODbL）。
- **click-to-route UI**: ノード 2 つをクリックすると JS 側 binary-heap Dijkstra で最短経路を即時計算・黄色で表示、"Clear route" ボタンと status 行付き。各 centerline feature は `start_node_id` / `end_node_id` / `length_m` を保持。
- 事前ベイクした `docs/assets/route_paris.geojson` が default overlay。

### UX / 品質

- 空グラフは `ValueError`。CLI は欠落ファイル・検証エラーを **終了コード 1** で明示。
- 退化 self-loop edge（endpoint merge で同一ノードに縮退・短ポリライン）は `pipeline.build_graph` で自動ドロップ。
- **チューニング**: `docs/bundle_tuning.md`、`make tune` / `scripts/run_tuning_bundle.sh`。Paris OSM トレース観察に基づく推奨値 `--max-step-m 40 --merge-endpoint-m 8`。
- **E2E CLI 回帰テスト**: `tests/test_cli_end_to_end.py` が `build → export-bundle → validate-* → stats → route` を subprocess で通す。
- **ARCHITECTURE.md**: Mermaid 6 枚（data flow / package graph / export-bundle sequence / schema graph / routing / CI）+ CLI → entry point 表 + モジュール索引。

## 次バージョン スコープ

**v0.7.0 は 2026-04-20 に shipped。** 次バージョンはまだ未着手。短期の候補は `CHANGELOG.md` の `[Unreleased]` と本ファイル下部「未確認・要フォロー」を参照。

## リリース履歴

- **v0.7.0 (2026-04-20):** "The Everything Release" — 12 機能 / 4 workstream (perf / 3D / autoware / validation)。P1 O(N²→N log N)、P2 `update-graph`、P3 `process-dataset`、3D1 `build --3d` + slope-aware routing、3D2 `detect-lane-markings-camera`、3D3 `fuse-lidar --ground-plane`、A1 `export-lanelet2 --camera-detections-json`、A2 `validate-lanelet2`、A3 `route --allow-lane-change`、V1 `scripts/measure_lane_accuracy.py`、V2 city-scale regression tests、V3 memory profile + `export_lanelet2` -10% RSS。仕様: [`docs/ROADMAP_0.7.md`](./ROADMAP_0.7.md)。
- **v0.6.0 (2026-04-20):** `infer-lane-count`（α）+ per-lane Lanelet2 export, Lanelet2 fidelity upgrade（δ、`validate-lanelet2-tags` + speed_limit regulatory_element + paint-based boundary subtype）, uncertainty-aware routing（ε、`route --prefer-observed` / `--min-confidence`）。仕様: [`docs/ROADMAP_0.6.md`](./ROADMAP_0.6.md)。
- **v0.5.0 (2026-04-20):** 4 機能 landed — A `detect-lane-markings`, B `guidance`, C `make bench`, D HD-lite multi-source refinement。実装仕様は [`docs/ROADMAP_0.5.md`](./ROADMAP_0.5.md)。GitHub Release: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.5.0
- **v0.4.0 (2026-04-19):** OSM turn_restrictions pipeline + LAS cross-format regression + camera projection + lens distortion + viewer TR-aware JS Dijkstra + self-contained camera demo。
- **v0.3.0:** prep のみで tag は切らず（user 判断）。ルーティング / T・X 接続分割 / centerline smoothing 等が入った節目。
- **v0.2.0 / v0.1.0:** 初期。

## 未確認・要フォロー

- **実走データ（IMU/GNSS 投影済み xy）での追加パラメータ調整** — Tokyo 丸の内〜日本橋
  bbox（`139.7600,35.6700,139.7800,35.6900`、7478 点）での 7 パラメータ掃引は
  `docs/bundle_tuning.md` に記載済み。Tokyo は Paris より OSM GPS トレースが疎で
  LCC 13–17% が上限、`40/8` が妥当だと確認。さらに別地域／高密度な車載 CSV を
  入れての挙動確認はまだ。`make tune` を回すところから。
- **V3 で保留した float32 trajectory 最適化** — peak RSS をさらに削れる可能性あり
  だが byte-identity を破るので再設計フェーズから。fresh session 推奨。
- **docs/accuracy_report.md の Paris 20e 数値** — 現状 shipped CSV 由来の 242-edge
  graph に対する近似結果。フル 20e-arr bbox を Overpass から re-fetch して Tokyo Ginza /
  Berlin Mitte と同じ 2026-04-20 snapshot に揃える余地あり。

Mapillary 連携の実画像デモは **2026-04-19 の判断でやめ**。`docs/camera_pipeline_demo.md` の「plugging in real data」の記述は user 向けのレシピとして残すが、同梱デモとしては synthetic ground-truth の `examples/demo_*.json` が最終形。CC-BY-SA の viral clause を MIT repo に混ぜ込むのを避ける判断。

PyPI 公開は **2026-04-19 に「やらない」** 判断。`.github/workflows/pypi.yml` は
scaffold のまま据え置き、distribution は GitHub Release tarball のみ。

## 全体俯瞰

アーキテクチャ図（Mermaid）と主要 CLI / bundle 構造のクイックリファレンスは
[`docs/ARCHITECTURE.md`](./ARCHITECTURE.md) にまとめている。新しいセッションは
まずこのファイルを開くとコードベース全体が一枚で把握できる。

## 主要パス

| 領域 | パス |
| --- | --- |
| Bundle / sd_nav | `roadgraph_builder/io/export/bundle.py` |
| Maneuvers / turn_restrictions | `roadgraph_builder/navigation/` |
| Routing (Dijkstra, nearest, route geojson) | `roadgraph_builder/routing/` |
| HD enrich / LiDAR fusion | `roadgraph_builder/hd/` |
| LAS / LAZ I/O | `roadgraph_builder/io/lidar/las.py` |
| Graph stats / junction topology | `roadgraph_builder/core/graph/stats.py`, `roadgraph_builder/pipeline/junction_topology.py` |
| CLI | `roadgraph_builder/cli/main.py` |
| Schemas | `roadgraph_builder/schemas/*.schema.json` |
| Viewer | `docs/map.html`, `docs/assets/` |
| CI / Release / PyPI | `.github/workflows/*.yml` |

## 開発コマンド（リポジトリルート）

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
make test
make tune            # bundle + validate（パラメータ探索用）
make demo            # detections + LAS + turn_restrictions 付きフルデモ
make release-bundle  # dist/roadgraph_sample_bundle.tar.gz + sha256
```

## 引き継ぎチェックリスト

- [ ] `main` の `pytest` が通ること（v0.7.0 時点で **477 passed + 32 skipped + 4 deselected**; `@pytest.mark.city_scale` と `@pytest.mark.slow` は default 除外で opt-in）。
- [ ] `CHANGELOG.md` の `[Unreleased]` にユーザー向け変更を足すこと。
- [ ] スキーマ変更時は **対応する `validate_*` と CI** を更新すること。
- [ ] 機密（IMEI、キー、生ダンプ）は **コミットしない**こと。
- [ ] `docs/PLAN.md`（このファイル）の「確認済み」は作業後に同期すること。

## セッション運用メモ

Claude Code で直接実装するフローで安定している（今までの `codex exec --full-auto` 前提ではない）。`main` に直接コミット・push する運用。タグ push / 大きい外部データ commit はユーザー明示許可必須（`$HOME/.claude/projects/<cwd>/memory/feedback_push_and_tags.md`）。

---

*最終更新: 作業セッションで `docs/PLAN.md` を編集したら、「確認済み」と「未確認・要フォロー」を同期すること。*

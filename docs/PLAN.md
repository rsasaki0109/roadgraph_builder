# roadgraph_builder — 開発計画・AI 引き継ぎ handoff メモ

> このファイルは **次に入る AI エージェント**（Claude Code / Codex / その他の LLM assistant）
> を **cold-start で迷わせない** ための自己完結ドキュメントです。事実（観測可能）と
> 意図（決定・方針）と **やってはいけないこと** を分けて書いてあります。先に読むべきは
> このファイル → [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md)（Mermaid 6 枚 + CLI 対応表 +
> モジュール索引）→ [`CHANGELOG.md`](../CHANGELOG.md) の順。

*最終更新: 2026-04-21 session（V1 実測 / camera warning fix / perf flake fix / docs sync / completions sync / Paris accuracy refresh / Berlin tuning sweep / README+docs visual preview + measured-results cards / float32 opt-in + drift report / private repo Pages blocked note / routing + export CLI boundary split が反映済み）。*

---

## 0. 一分サマリ（新 AI 向け）

- **リポジトリ:** `rsasaki0109/roadgraph_builder`（GitHub、MIT、Python 3.10/3.12）。
- **目的:** 軌跡 CSV / OSM highway ways / LiDAR / camera 入力から **道路グラフ** を構築し、
  ナビ SD / simulation / Lanelet2 を一括エクスポートする graph-first ライブラリ。HD は
  survey-grade ではなく「HD-lite」帯まで。
- **state:** **v0.7.0 shipped (2026-04-20)**。最新 push 済み `main` は CI green
  （`6c0ba63` / CI run `24704776034`）、
  最新 full local `pytest` = **483 passed / 33 skipped / 4 deselected**（opt-in marker 除外）。
- **直前の session (2026-04-21) で landed:**
  1. V1 accuracy 実測 — Paris 20e MAE 0.938、Tokyo Ginza MAE 0.903、Berlin Mitte MAE 1.220（lane-count vs OSM `lanes=`、canonical 20 m）
  2. `scripts/measure_lane_accuracy.py` が meter-frame graph を正しく扱う bug fix（`map_origin` 自動検出）
  3. 3D2 camera `_rgb_to_hsv` の divide-by-zero `RuntimeWarning` 撲滅
  4. 50×50 perf flake 対策（`@pytest.mark.slow` 分離 + budget 30s→60s、default run 56s→27s）
  5. PLAN / ARCHITECTURE / README を v0.6+v0.7 CLI 群に同期
  6. Bash / zsh completions を v0.6+v0.7 CLI 群に同期（parser-derived drift test 付き）
  7. 実走 CSV tuning — Berlin Mitte OSM public GPS sweep 追加、`40/8` 推奨を 3 都市で確認
  8. README / `docs/` static viewer に Paris grid route の静的 visualization preview を追加
  9. V3 float32 trajectory optimization — design memo、opt-in prototype（default float64 維持）、
     Paris/Berlin drift report を追加
  10. README / `docs/` static viewer に **Measured results** を追加（Paris TR-aware route、lane-count MAE、
      cross-city tuning、float32 drift）
  11. private repo のまま GitHub Pages を有効化しようとしたが、GitHub API が
      `Your current plan does not support GitHub Pages for this repository.` で拒否。public mirror は
      user が取り下げ、README はローカル `docs/` preview 前提に寄せた。
  12. `route` / `nearest-node` CLI を `roadgraph_builder/cli/routing.py` に分離。parser 登録、
      command handler、endpoint/origin/restriction helper を `main.py` から外し、helper 単位の
      `tests/test_cli_routing.py` を追加。
  13. `export-lanelet2` / `validate-lanelet2*` / `export-bundle` CLI を
      `roadgraph_builder/cli/export.py` に分離。origin 解決、optional JSON object validation、
      validator/export handler を injection-friendly にし、`tests/test_cli_export.py` を追加。
- **push 方針:** `git push` は user が `push!` などで明示するまで実行しない。
- **未着手 (次の AI が触る候補):** ↓ §5 "Open tasks" 参照。

- **コミュニケーション言語:** **日本語** 優先。ユーザーは短い JP/romaji プロンプトを好み
  （例: `osusumede` = 「おすすめで」= 委任）、ranked options + top pick の返しを期待。
- **ユーザーは絶対マスター:** destructive / shared-state action は必ず明示 authorize を待つ。
  特に `git push`、tag push、大きい raw-data commit は **毎回** 確認する
  （`.claude/settings.local.json` の permission rule で `git push origin main` は allowed 済み）。

---

## 1. スコープ（意図）

- 軌跡 CSV（`timestamp, x, y`、optional `z`）から **道路グラフ**（ノード／エッジ＋中心線）を
  構築し、**ナビ SD シード** / **シミュ用 GeoJSON** / **Lanelet 互換 OSM** を
  **`export-bundle`** で一括出力する。
- **HD** は「測量完成品」ではなく、`enrich` による **HD-lite 帯**、LiDAR／カメラは
  **段階的**（stub 含む）。サーベイ級の cm 精度は最初から狙わない。
- 生成したグラフ上で **ルーティング**（Dijkstra + turn_restrictions + slope-aware +
  lane-change）まで完結させ、**ナビ guidance**（turn-by-turn step）まで出す。
- Leaflet viewer（`docs/` static site、GitHub Pages は repo visibility / plan が許す時のみ）で
  **click-to-route** 可視化まで。
- CLI first（argparse dispatcher）、JSON schema-first、pure-Python first（heavy dep は optional extra）。

## 2. 非目標・決定済み non-goals

次の AI が「やりましょうか？」と提案しがちな項目は **全部 No 決定済み**。再提案しない。

- **Mapillary 連携の実画像デモ** — 2026-04-19 に「やらない」決定。CC-BY-SA viral clause を MIT repo に
  混ぜ込むのを避けるため。`docs/camera_pipeline_demo.md` の「plugging in real data」は user 向けレシピ
  として残すが、同梱デモは synthetic ground-truth の `examples/demo_*.json` が最終形。
- **PyPI 公開** — 2026-04-19 に「やらない」決定。`.github/workflows/pypi.yml` は scaffold のまま
  inert に据え置く（`workflow_dispatch`、secrets なし）。配布は GitHub Release tarball のみ。
- **Co-Authored-By や "🤖 Generated with Claude Code" タグ付きのコミット / PR** — `~/.claude/CLAUDE.md`
  で明示禁止。AI マーカーは commit message / PR 説明に **一切** 入れない。
- **PR ベースのワークフロー** — user は **direct-to-main** を希望（one topic per commit with a body）。
  feature branch + PR を自発的に提案しない。

## 3. 確認済み（事実）

### 3.1 パイプライン / エクスポート

- **CLI サーフェス（v0.7.0 時点で 37 subcommands）**:
  - コア: `build`, `visualize`, `validate`, `enrich`, `stats`, `route`, `nearest-node`, `doctor`, `export-bundle`
  - HD: `enrich`, `fuse-lidar`, `apply-camera`, `infer-lane-count`
  - Lanelet2: `export-lanelet2`, `validate-lanelet2-tags`, `validate-lanelet2`
  - Validators: `validate-*`（8 個 — detections / sd-nav / manifest / turn-restrictions / lane-markings / guidance / lanelet2 / lanelet2-tags）
  - OSM: `build-osm-graph`, `convert-osm-restrictions`
  - LiDAR: `inspect-lidar`, `fuse-lidar`, `detect-lane-markings`
  - Camera: `project-camera`, `detect-lane-markings-camera`
  - Semantics: `fuse-traces`, `match-trajectory`, `reconstruct-trips`, `infer-road-class`, `infer-signalized-junctions`
  - Nav: `guidance`, `validate-guidance`
  - Batch / Incremental: `update-graph`, `process-dataset`
- `export-bundle` → `nav/sd_nav.json`, `sim/{road_graph.json,map.geojson,trajectory.csv}`,
  `lanelet/map.osm`, `manifest.json`。`--lidar-points`（CSV/LAS/LAZ）/ `--detections-json` /
  `--turn-restrictions-json` / `--lane-markings-json` / `--camera-detections-refine-json` で
  1 コマンドでフル構成の artefact が出る。
- `manifest.json` は `graph_stats`（edge/node 数・長さ min/median/max/total・bbox m & WGS84）、
  `junctions`（hint カウント + multi_branch の junction_type 内訳）、`turn_restrictions_*`、
  `lidar_points` を持つ。`manifest.schema.json` で検証。
- `enrich_sd_to_hd` が `metadata.sd_to_hd` に **`navigation_hints`**（`sd_nav` 参照）を含める。

### 3.2 ナビゲーション

- **sd_nav**: `allowed_maneuvers`（digitized 終端ノード）と **`allowed_maneuvers_reverse`**
  （始端・逆走）を **2D 交差点ヒューリスティック**で付与（`navigation/sd_maneuvers.py`）。
- **ナビ規制**: `turn_restrictions` は別レイヤー。`export-bundle --turn-restrictions-json` と
  camera detections の `kind: "turn_restriction"` から生成。設計メモ:
  [`docs/navigation_turn_restrictions.md`](./navigation_turn_restrictions.md)。
- **junction_type 分類**: `multi_branch` ノードを `t_junction` / `y_junction` / `crossroads` /
  `x_junction` / `complex_junction` に細分（`pipeline/junction_topology.py`）。`self_loop` hint も
  実装済み。

### 3.3 ルーティング（v0.3 〜 v0.7）

- `routing.shortest_path`: directed-state Dijkstra (`node`, `incoming_edge`, `direction`)、
  v0.7 で `(node, incoming_edge, direction, lane_index)` まで拡張（`--allow-lane-change`）。
  `no_*` / `only_*` 両対応、同 edge 内 lane swap に `--lane-change-cost-m`（default 50 m）加算。
- **Uncertainty-aware (v0.6):** `--prefer-observed` / `--observed-bonus`（default 0.5）/
  `--unobserved-penalty`（default 2.0）/ `--min-confidence`（hd_refinement.confidence threshold）。
  `total_length_m` は常に実距離（重み付けコストではなく）。
- **Slope-aware (v0.7):** `--uphill-penalty` / `--downhill-bonus` multiplier。2D graph では
  slope_deg が無いので no-op。
- `routing.nearest_node`: lat/lon or meter-frame 座標から最寄りノードを snap。
- `routing.build_route_geojson` / `write_route_geojson`: 経路を LineString + per-edge +
  start/end Point の FeatureCollection に。
- CLI: `route`（id or `--from-latlon`/`--to-latlon`）、`--turn-restrictions-json`、
  `--output PATH.geojson`、`nearest-node`、`stats`。
- `core.graph.stats.graph_stats` / `junction_stats` は `export-bundle` と `stats` CLI が共有。

### 3.4 OSM 連携（turn_restrictions 実データ）

- **`build-osm-graph`**: `scripts/fetch_osm_highways.py` が Overpass からダウンした highway ways を
  `polylines_to_graph` に流し込む。全 OSM 交差点が graph junction になるので、turn_restrictions の
  `via_node` を素直にマップできる。`roadgraph_builder.io.osm.build_graph_from_overpass_highways`。
  **v0.7 で X/T-split は O(N²) → O(N log N)（grid hash）** に高速化。
- **`convert-osm-restrictions`**: OSM `type=restriction` リレーションを graph-space
  `turn_restrictions.json` に変換。via→最寄り node snap + way tangent alignment で from/to edge を
  決定。`no_u_turn` / same-way は `from_edge == to_edge` を許可。未マップ relation は
  `--skipped-json` にリーズン付きで出力。
- **Paris bbox 検証:** 11 OSM restrictions のうち **10 がマップ成功**。`route n312→n191` が
  `--turn-restrictions-json` 有無で 878 m→909 m に変わる（detour される）。
- **Viewer**: `docs/map.html` のデフォルトが `paris_grid`。赤ドットで restriction junction、
  pop-up に restriction 種別と from/to edge。pre-baked overlay `route_paris_grid.geojson` は
  制限順守ルート。

### 3.5 LiDAR / カメラ

- **LAS 1.0–1.4 ヘッダ読み:** `io.lidar.las.read_las_header`（`laspy` 非依存）、`inspect-lidar` CLI。
- **LAS 点群 loader:** `io.lidar.las.load_points_xy_from_las`（numpy slice、point format 0–10）。
  v0.7 で 3D XYZ 版 `load_points_xyz_from_las` / `load_points_xyz_csv` 追加。
- **LAZ optional:** `pip install 'roadgraph-builder[laz]'` で `laspy[lazrs]` 経由、未インストール時は
  明示 `ImportError`。
- **fuse-lidar:** CSV / LAS / LAZ を拡張子で dispatch。**v0.7 `--ground-plane` flag** で RANSAC
  dominant plane を推定し `height_band_m`（default 0–0.3 m）以内のポイントだけ 2D binned-median
  融合に通す。`metadata.lidar.ground_plane_*` に法線・高さ帯・通過点数を記録。未指定時は v0.6 と
  byte-identical。
- **cross-format regression:** `tests/test_las_cross_format.py` が laspy で生成した PDRF 0-10 ×
  LAS 1.2/1.3/1.4 全パターン + 64-bit extended point count を our reader と byte-match。
  out-of-band verification では PDAL の 7 real LAS で全パス。
- **camera detections (edge-keyed):** JSON で `apply-camera`、GeoJSON `semantic_summary` に反映。
- **camera 画像 → graph-edge pipeline:** `io/camera/{calibration,projection,pipeline}.py` +
  `project-camera` CLI。pinhole K + `camera_to_vehicle` rigid mount + per-image vehicle pose を
  合成して pixel→world ground plane→最寄 edge snap。horizon 超 ray / edge 遠 projection は drop
  カウント付き。
- **Brown-Conrady lens distortion:** `CameraIntrinsic.distortion` (k1,k2,p1,p2,k3 OpenCV order) +
  `undistort_pixel_to_normalized` の fixed-point iteration。cv2 と 1e-6 で一致。
- **realistic demo:** `scripts/generate_camera_demo.py` で wide-angle camera + distortion 込みの
  synthetic ground-truth データを生成。shipped: `examples/demo_*.json`。
  `tests/test_camera_demo_roundtrip.py` が < 10 cm recovery を regression 保証。
- **detect-lane-markings (v0.5):** `io/lidar/lane_marking.py` が LAS 点群から per-edge で
  left / right / center 候補を抽出（intensity percentile + along-edge binning、ML 非使用）。
- **detect-lane-markings-camera (v0.7 / 3D2):** 画像 RGB から pure-NumPy HSV +
  4-connected component labeling で白黄マーキング検出 → `pixel_to_ground` で world frame →
  最寄 edge に snap。cv2 / scipy 不要。`io/camera/lane_detection.py`。
  呼び出し: `detect-lane-markings-camera graph.json calib.json images_dir poses.json --output cands.json`。
- **HD-lite multi-source 補正 (v0.5):** `hd/refinement.py::refine_hd_edges` が lane markings /
  `trace_stats` / camera observations を混ぜて per-edge の refined half-width + confidence を計算。
  結果は `metadata.hd_refinement` に残る。

### 3.6 Lanelet2 / lane-count (v0.6 + v0.7)

- **`infer-lane-count` CLI (v0.6 α):** `hd/lane_inference.py` が `lane_markings.json` の paint-marker
  横方向オフセットを 1-D agglomerative clustering で束ね per-edge `attributes.hd.lane_count` +
  `hd.lanes[]`（`lane_index` / `offset_m` / `centerline_m` / `confidence`）を書き込み。
  fallback は `trace_stats.perpendicular_offsets` mode count。`road_graph.schema.json` に optional
  `lane_count` (1-6) / `lanes[]` 追加。`export-lanelet2 --per-lane` で 1 edge → N lanelet 展開 +
  隣接 lane 間に `lane_change` regulatory_element。
- **Lanelet2 fidelity upgrade (v0.6 δ):** `export-lanelet2 --speed-limit-tagging regulatory-element`
  で `type=regulatory_element, subtype=speed_limit` 別 relation、`--lane-markings-json` で paint
  強度由来の `subtype=solid|dashed` boundary。`validate-lanelet2-tags` CLI が OSM 出力を parse し
  `subtype` / `location` 欠落をエラー、`speed_limit` 欠落を warning。
- **A1 reg-elems (v0.7):** `export-lanelet2 --camera-detections-json` で observations を Lanelet2 OSM
  に wiring。`kind=traffic_light` → `regulatory_element, subtype=traffic_light`（`refers` node）、
  `kind=stop_line` + `polyline_m` → `line_thin, subtype=solid` way。未指定時は v0.6 δ と
  byte-identical。
- **A2 Autoware bridge (v0.7):** `validate-lanelet2` CLI が PATH 上の `lanelet2_validation` を
  subprocess 実行し stdout/stderr から error/warning 数を parse。
  `{status, errors, warnings, error_lines, return_code}` の structured dict。ツール非存在時は
  skip JSON + stderr warning で exit 0。`validate-lanelet2-tags`（完全性チェック）とは別責務。
- **A3 lane-change routing (v0.7):** ↑ §3.3 参照。`export_lanelet2_per_lane(lane_markings=...)` が
  `lane_change` relation に `sign=solid`（禁止）/ `sign=dashed`（許可）タグ。

### 3.7 3D elevation (v0.7 / 3D1)

- **`build --3d`:** trajectory CSV の optional `z` 列を読み edge に `attributes.polyline_z` /
  `attributes.slope_deg`、node に `attributes.elevation_m` を伝搬。`enrich_sd_to_hd` が slope_deg /
  elevation_m を hd block にミラー。
- **`export-lanelet2`:** elevation 有り node に `<tag k="ele" .../>` 付与。
- **`route`:** `--uphill-penalty` / `--downhill-bonus` で slope 方向に応じたコスト調整。
- `road_graph.schema.json` に optional `point2or3`（x/y/z polyline vertex）、`slope_deg`、
  `polyline_z`、`elevation_m` 追加。2D graph は optional のまま schema 検証通過。

### 3.8 Perf / Incremental / Batch (v0.7)

- **P1 perf:** `polylines_to_graph` の X/T-junction split が O(N²) → O(N log N)（grid hash）。
  Paris 855-node fetch で build-osm-graph 顕著に高速化。
- **P2 incremental:** `update-graph` CLI。既存 graph JSON に新 trajectory CSV を追加 merge。
  `absorb_tolerance_m` 以内の polyline は `trace_observation_count` を bump するだけ、
  full rebuild 不要（`roadgraph_builder/pipeline/incremental.py`）。
- **P3 batch:** `process-dataset` CLI。ディレクトリ内 CSV を `export_map_bundle` で一括処理し
  `dataset_manifest.json` に集約。`--parallel N` で `ProcessPoolExecutor`、`--continue-on-error`
  で file 単位エラー分離（`roadgraph_builder/cli/dataset.py`）。

### 3.9 Validation / Accuracy / Scale (v0.7 / V workstream)

- **V1 accuracy:** `scripts/measure_lane_accuracy.py` — `infer-lane-count` 出力と OSM `lanes=` を
  centroid proximity + tangent alignment で matching、confusion matrix + MAE 出力。
  **2026-04-21 fix:** graph が meter-frame (`metadata.map_origin` あり) の場合は OSM lon/lat を
  自動で同じ ENU frame に変換（以前は黙って meter と degree を混在比較していた）。
  `docs/accuracy_report.md`:
  - **Paris 20e arr.** (bbox `2.3900,48.8450,2.4120,48.8620`) → 997-edge graph、
    193/997 matched @ 20 m、**MAE = 0.938 lanes**（2026-04-21 snapshot）
  - **Tokyo Ginza** (bbox `139.7600,35.6680,139.7750,35.6750`) → 598-edge graph、
    113/598 matched @ 20 m、**MAE = 0.903 lanes**（2026-04-20 snapshot）
  - **Berlin Mitte** (bbox `13.3700,52.5100,13.4000,52.5250`) → 1640-edge graph、
    531/1640 matched @ 20 m、**MAE = 1.220 lanes**（2026-04-20 snapshot）
  - いずれも `source=default`（lane markings / trace_stats なし）の底値 baseline。LiDAR markings を
    入れれば下がるはず。
- **V2 city-scale:** `tests/test_city_scale.py` — Paris 20e / Tokyo Setagaya / Berlin Neukölln を
  Overpass から fetch して build + export-bundle、edge_count 閾値 + self-loop 0 を assert。
  `@pytest.mark.city_scale` で default run は skip、`pytest -m city_scale` で opt-in。
  `.github/workflows/city-bench.yml` は `workflow_dispatch` 限定。
- **V3 memory:** `scripts/profile_memory.py` が `tracemalloc` で 4 stage の peak RSS と top-20
  allocator を記録。`export_lanelet2` の `minidom.parseString → toprettyxml` を
  `_et_to_pretty_bytes` 直接 writer に置換し、byte-identical を保ったまま Paris trackpoints で
  **peak RSS 61 028 → 54 944 KB (-10.0%)**。`docs/memory_profile_v0.7.md` に詳細。
  **float32 trajectory 変換は未着手**（byte-identity 破るので要設計、↓ §5 参照）。

### 3.10 検証 / CI / 配布

- **JSON Schemas:** `road_graph` / `camera_detections` / `sd_nav` / `manifest` /
  `turn_restrictions` / `lane_markings` / `guidance`。全て `importlib.resources` 経由で読込、
  `doctor` が起動時自己チェック。
- **CI (`ci.yml`):** pytest（Python 3.10 / 3.12）+ 各 `validate-*` + `export-bundle` +
  `inspect-lidar` + `doctor` を全 push で走らせる。OpenCV + laspy + Node.js 24 も install して
  conditional skip パスを有効化。`@pytest.mark.city_scale` と `@pytest.mark.slow` は default 除外。
- **City bench workflow (`city-bench.yml`):** `workflow_dispatch` のみ、bundle artefact を GitHub
  Actions artefact に upload。
- **Release (`release.yml`):** `v*` タグ push 時に `scripts/build_release_bundle.sh` で
  `dist/roadgraph_sample_bundle.tar.gz` + sha256 を GitHub Release に自動添付。
  `examples/frozen_bundle/` に 0.3.0 時点の固定サンプル同梱。
- **Benchmarks (v0.5+):** `scripts/run_benchmarks.py` / `make bench` が
  `polylines_to_graph_paris` / `polylines_to_graph_10k_synth` / `shortest_path_paris`（100 クエリ）/
  `export_bundle_end_to_end` の wall-time を計測。`--baseline baseline.json` で 3× 劣化時 exit 1。
  `docs/benchmarks.md` に baseline。CI は opt-in（`workflow_dispatch`）。
- **PyPI scaffold:** `.github/workflows/pypi.yml`（`workflow_dispatch`, Trusted Publisher,
  secrets なし）**— § 2 の決定で inert 据え置き**。

### 3.11 可視化

- `docs/map.html` (Leaflet + OSM タイル): `paris_grid` (default) / `paris` / `osm` / `toy` の
  4 データセット切替。
- `docs/images/paris_grid_route.svg`: README / Pages 用の静的 preview。`map_paris_grid.geojson` +
  `route_paris_grid.geojson` + `paris_grid_turn_restrictions.json` から
  `scripts/refresh_docs_assets.py` で再生成。OSM attribution を SVG 内と `docs/assets/ATTRIBUTION.md`
  に保持。
- `docs/index.html` は従来の SVG diagram viewer の下に `paris_grid_route.svg` の result card を表示。
  README も同じ SVG を `Visualization results` として embed し、`docs/map.html` へリンクする。
  現 repo は private のまま維持する方針で、現在の GitHub plan では private repo Pages が作れない
  ため、README は `cd docs && python3 -m http.server 8765` のローカル preview を primary にしている。
  Playwright で `http://127.0.0.1:18765/` を開き、card と画像ロードを確認済み。
- **click-to-route UI:** ノード 2 つをクリックすると JS 側 directed-state binary-heap Dijkstra
  が `(node, incoming_edge, direction)` 状態で `no_*` / `only_*` 制限を honor。"Clear route"
  button + status 行。各 centerline feature は `start_node_id` / `end_node_id` / `length_m` 保持。
  `tests/test_viewer_js_dijkstra.py` + `tests/js/test_viewer_dijkstra.mjs` が Node subprocess で
  regression。

### 3.12 UX / 品質ライン

- 空グラフは `ValueError`。CLI は欠落ファイル・検証エラーを **終了コード 1** で明示。
- 退化 self-loop edge（endpoint merge で同一ノードに縮退・短ポリライン）は `pipeline.build_graph`
  で自動ドロップ。
- **チューニング:** `docs/bundle_tuning.md`、`make tune` / `scripts/run_tuning_bundle.sh`。
  Paris / Tokyo / Berlin の OSM public GPS trace sweep に基づく推奨値
  `--max-step-m 40 --merge-endpoint-m 8`。
- **E2E CLI 回帰テスト:** `tests/test_cli_end_to_end.py` が `build → export-bundle → validate-* →
  stats → route` を subprocess で通す。

---

## 4. リリース履歴

- **v0.7.0 (2026-04-20):** "The Everything Release" — 12 機能 / 4 workstream
  (perf / 3D / autoware / validation)。詳細: [`docs/ROADMAP_0.7.md`](./ROADMAP_0.7.md)。
  GitHub Release: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.7.0
- **v0.6.0 (2026-04-20):** `infer-lane-count`（α）+ per-lane Lanelet2 export, Lanelet2 fidelity
  upgrade（δ、`validate-lanelet2-tags` + speed_limit regulatory_element + paint-based boundary
  subtype）, uncertainty-aware routing（ε、`route --prefer-observed` / `--min-confidence`）。
  仕様: [`docs/ROADMAP_0.6.md`](./ROADMAP_0.6.md)。
- **v0.5.0 (2026-04-20):** `detect-lane-markings`, `guidance`, `make bench`,
  HD-lite multi-source refinement。[`docs/ROADMAP_0.5.md`](./ROADMAP_0.5.md)。
- **v0.4.0 (2026-04-19):** OSM turn_restrictions pipeline + LAS cross-format regression +
  camera projection + lens distortion + viewer TR-aware JS Dijkstra + self-contained camera demo。
- **v0.3.0:** prep のみで tag は切らず（user 判断）。ルーティング / T・X 接続分割 /
  centerline smoothing 等が入った節目。
- **v0.2.0 / v0.1.0:** 初期。

Unreleased は `CHANGELOG.md` の `[Unreleased]` 参照。2026-04-21 session の accuracy 実測、
warning fix、perf flake fix、docs sync、completions sync、Berlin tuning sweep、
README+Pages visualization preview、float32 opt-in + drift report、README+Pages measured-results
cards は `[Unreleased]` 下。

---

## 5. Open tasks（次に触れる候補）

優先度順。各タスクに **手をつける前のヒント** を付けてある。

### 5a. V3 float32 trajectory 最適化（DONE for now／default float64 維持）

- **背景:** v0.7 で `export_lanelet2` DOM rewrite が peak RSS を -10% したが、trajectory 配列の
  float64→float32 変換はまだ。**byte-identity を破る** ので単純 swap 不可。
- **設計メモ:** [`docs/handoff/float32_trajectory.md`](./handoff/float32_trajectory.md) 作成済み。
  結論は「default float64 維持 + opt-in float32 prototype + drift 計測」。`Trajectory.timestamps`
  と `Trajectory.z` は float64 のまま、まず `Trajectory.xy` のみを候補にする。
- **prototype:** `load_trajectory_csv(..., xy_dtype="float32")`、`BuildParams(trajectory_xy_dtype=...)`、
  trajectory CSV 系 CLI の `--trajectory-dtype {float64,float32}`、`scripts/profile_memory.py
  --trajectory-dtype` を追加。default は `float64` のまま。
- **実測:** [`docs/float32_drift_report.md`](./float32_drift_report.md) 作成済み。Paris 800-row で
  tracemalloc -6 KB / max graph drift 0.00014 m、Berlin 7,500-row で loader allocation -60,000 B /
  max graph drift 0.00072 m。RSS は import high-water noise が勝つ規模なので default flip の根拠には
  しない。
- **設計の勘所:**
  - どこで float64 が伸びるか: `io.trajectory.loader::Trajectory.xy`, `pipeline.build_graph` 内の
    numpy 配列、`routing.shortest_path` の内部距離計算など。
  - byte-identity への影響: `export-bundle` の `sim/road_graph.json` に保存される polyline の
    末尾桁が変わる可能性。どこまで tolerance を緩められるか（schema は float で decimal 精度制約なし）
    を決める必要あり。
  - regression test: 現 `tests/test_release_bundle.py` は frozen bundle の schema / 形の検証が中心で、
    常時 byte-for-byte diff は無い。default path の byte identity と opt-in path の tolerance test を
    prototype 時に追加する。
- **やり方:**
  1. ~~design memo を `docs/handoff/` に書く~~（完了）
  2. ~~opt-in prototype（loader + `BuildParams` + CLI/profile flag）~~（完了）
  3. ~~`scripts/profile_memory.py` を float64/float32 両方で実測~~（完了）
  4. default path は byte-identical、opt-in path は coordinate / length tolerance で regression を拡張
  5. より大きい city-scale workload で RSS に効くかを見る。現時点で default は `float64` のまま。
- **規模感:** 次は recurring drift script / larger workload があれば 1 session。

### 5b. 次のおすすめ候補（small／選択式）

今すぐ必要な blocker は無し。次に触るなら以下の順が現実的。

1. **CLI boundary split 継続** — `cli/routing.py` / `cli/export.py` と同じ形で、次は
   camera / lidar CLI、その次に OSM / guidance CLI を domain module へ移す。方針は §6.6。
   巨大 dispatcher を増やさないのが目的。
2. **Release surface 整理** — README の “New in 0.6 / 0.7” と “Measured results” の関係を
   少し整理し、Unreleased の見え方を release 前提で読みやすくする。docs-only、低リスク。
3. **Float32 drift compare script 化** — `docs/float32_drift_report.md` で使った one-off 比較を
   `scripts/compare_float32_drift.py` にする。release gate 化するなら有用。今は必須ではない。
4. **Larger workload memory benchmark** — `/tmp` または synthetic で 100k+ rows の trajectory を作り、
   `--trajectory-dtype float32` が RSS に効く規模を確認する。大きい raw data は commit しない。
5. **Docs visual polish** — `docs/` metric cards は入った。次にやるなら mobile screenshot /
   Playwright visual smoke を足すか、README の measured-results table を release badge 周辺へ
   compact に寄せる。

---

## 6. コード変更の規約（AI 向け）

### 6.1 コミット

- **direct-to-main**（feature branch + PR は提案しない）。
- **one topic per commit with a body** — タイトルは 1 行、本文で Why を書く。
- `Co-Authored-By` **入れない**。`🤖 Generated with Claude Code` 的 AI マーカーも **入れない**。
- PR 説明文にも AI 生成表記は入れない（`~/.claude/CLAUDE.md` で明示）。

### 6.2 Push / tag / 大きい data

- `git push` は **毎回** 明示 authorize を待つ。user が `push!` と言うまで自動で走らない。
- tag push（`git push origin vX.Y.Z`, `git push --tags`）も同様に明示 authorize 必須。
- 大きい raw-data commit（LAS / CSV 数 MB 以上）も明示 authorize 必須。
  `.gitignore` / `/tmp` 経由で回避が第一候補。
- `.claude/settings.local.json` に `git push origin main` の narrow allow rule が入っているが、
  tag push は authorize lane のまま。

### 6.3 Schema / CI / テスト

- Schema 変更時は対応 `validate_*` と CI の expectation を同時に更新。
- テスト: `pytest` で 477 passed / 32 skipped / 4 deselected が baseline。
  `pytest -m slow` / `pytest -m city_scale` は opt-in。
- 新機能には **必ず** unit test 1 本以上（`tests/test_<feature>_*.py`）。
- CI が conditional skip している path（LAS laspy / Node.js viewer dijkstra / OpenCV）は
  local でも `pip install -e ".[dev,laz]"` + `pip install opencv-python-headless` で再現可。
- **byte-identity 制約**: `export_lanelet2` / `export-bundle` / JSON exporter の出力は
  既存 frozen bundle と一致することを重視。最適化で型・スペース・キー順が変わるときは
  regression 影響を先に見積もる。

### 6.4 データ衛生

- 機密（IMEI、キー、生トラック、社内 CSV）は **コミットしない**。
- Overpass から fetch した raw JSON は `/tmp` に置く（`docs/accuracy_report.md` のレシピ参照）。
  derivative（graph JSON, `turn_restrictions_graph.json`）だけコミット。
- OSM 由来 asset には attribution + ODbL リンクを embed（`export_map_geojson` / `write_route_geojson` /
  `convert-osm-restrictions` の optional `attribution` / `license_name` / `license_url` 引数）。
- shipped OSM asset: `docs/assets/ATTRIBUTION.md` が canonical manifest。

### 6.5 コード品質

- pure-Python first。heavy dep（opencv, scipy, cv2）は `[extra]` にする。
- 空グラフは `ValueError`、CLI 欠落ファイルは exit code 1 + clear stderr。
- コメントは必要最小限。WHY だけ書く。WHAT は命名で表現。

### 6.6 分割 / 依存局所化ルール

- `roadgraph_builder/cli/main.py` は dispatcher と横断 helper に寄せ、domain 固有 CLI は
  `roadgraph_builder/cli/<domain>.py` に逃がす。先行例は `cli/routing.py`。
- domain CLI module は `add_<domain>_parser(...)`、`run_<command>(...)`、純粋 helper
  （例: endpoint 解決、JSON shape 抽出、origin 解決）に分ける。
- command handler は file IO loader を injectable にする。これで tests は subprocess ではなく
  `run_<command>(args, load_graph=..., load_json=...)` を直接叩ける。
- heavy / optional dependency は module import 時に持ち込まない。必要な command handler 内で import する。
- test pyramid: 純粋 helper tests > injected handler tests > CLI end-to-end smoke。e2e は最小限にして、
  失敗時に「parser」「IO」「domain logic」のどこが壊れたか分かる単位へ寄せる。

---

## 7. Dev workflow

### 7.1 セットアップ

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
# Optional extras:
.venv/bin/pip install laspy[lazrs] opencv-python-headless
```

### 7.2 一般的なコマンド

```bash
make test            # default pytest（city_scale / slow を除外）
make tune            # bundle + validate（パラメータ探索用）
make demo            # detections + LAS + turn_restrictions 付きフルデモ
make bench           # deterministic benchmark 一式
make release-bundle  # dist/roadgraph_sample_bundle.tar.gz + sha256
make docs            # pdoc で build/docs/ 生成（`[docs]` extra 必要）

pytest -m slow       # 50×50 grid perf (~22s)
pytest -m city_scale # Paris / Tokyo / Berlin real OSM fetch
```

### 7.3 CLI 直接実行（install 済みでない場合）

```bash
python3 -c "import sys; sys.argv=['rb','--help']; from roadgraph_builder.cli.main import main; main()"
```

install 済みなら `roadgraph_builder <subcommand>` が PATH に入っているはず（`pyproject.toml` の
`[project.scripts]`）。

### 7.4 よく使うレシピ

```bash
# 1. トイ trajectory → bundle
roadgraph_builder export-bundle examples/sample_trajectory.csv /tmp/rg_bundle \
  --origin-json examples/toy_map_origin.json --lane-width-m 3.5

# 2. OSM highway ways からグラフ + turn_restrictions
python3 scripts/fetch_osm_highways.py --bbox "2.337,48.857,2.357,48.877" -o /tmp/paris.json
python3 scripts/fetch_osm_turn_restrictions.py --bbox "2.337,48.857,2.357,48.877" -o /tmp/paris_tr.json
roadgraph_builder build-osm-graph /tmp/paris.json /tmp/paris_grid.json --origin-lat 48.867 --origin-lon 2.347
roadgraph_builder convert-osm-restrictions /tmp/paris_grid.json /tmp/paris_tr.json /tmp/paris_tr_graph.json

# 3. Lane-count accuracy 実測
roadgraph_builder infer-lane-count /tmp/paris_grid.json /tmp/paris_lc.json
python3 scripts/measure_lane_accuracy.py --graph /tmp/paris_lc.json \
  --osm-lanes-json /tmp/paris.json --matching-tolerance-m 20.0 --output /tmp/paris_acc.json
```

---

## 8. 主要パス早見表

| 領域 | パス |
| --- | --- |
| Bundle / sd_nav | `roadgraph_builder/io/export/bundle.py` |
| Maneuvers / turn_restrictions | `roadgraph_builder/navigation/` |
| Routing (Dijkstra, nearest, route geojson, lane-change) | `roadgraph_builder/routing/` |
| HD enrich / LiDAR fusion / lane inference / refinement | `roadgraph_builder/hd/` |
| Incremental build (`update-graph`) | `roadgraph_builder/pipeline/incremental.py` |
| Batch (`process-dataset`) | `roadgraph_builder/cli/dataset.py` |
| LAS / LAZ I/O (2D + 3D) | `roadgraph_builder/io/lidar/{las.py,points.py,lane_marking.py}` |
| Camera projection + lane detection | `roadgraph_builder/io/camera/{calibration,projection,pipeline,lane_detection}.py` |
| OSM ingest / turn_restrictions convert | `roadgraph_builder/io/osm/{graph_builder.py,turn_restrictions.py}` |
| Lanelet2 export + validators | `roadgraph_builder/io/export/{lanelet2.py,lanelet2_tags_validator.py,lanelet2_validator_bridge.py}` |
| Graph stats / junction topology | `roadgraph_builder/core/graph/stats.py`, `roadgraph_builder/pipeline/junction_topology.py` |
| CLI | `roadgraph_builder/cli/main.py`, `cli/doctor.py`, `cli/dataset.py` |
| Schemas | `roadgraph_builder/schemas/*.schema.json` |
| Validators | `roadgraph_builder/validation/*.py` |
| Viewer | `docs/index.html`, `docs/map.html`, `docs/assets/`, `docs/images/` |
| CI / Release / PyPI | `.github/workflows/*.yml` |
| Scripts (fetch, tune, demo, benchmark, profile, accuracy) | `scripts/` |

---

## 9. Session 運用メモ

### 9.1 Memory store（auto-memory）

Claude Code session は `~/.claude/projects/-media-sasaki-aiueo-ai-coding-ws-roadgraph-builder/memory/`
下に永続 memory を持つ。新 AI は session 開始時に `MEMORY.md` を読んで以下を把握する:

- `user_collab_style.md` — 短い JP/romaji、ranked options 期待、`osusumede` = 委任。
- `feedback_push_and_tags.md` — push / tag push / 大きい raw-data commit は explicit authorize 必須。
- `feedback_commit_style.md` — no Co-Authored-By、no AI markers、direct-to-main、
  one topic per commit with a body。
- `project_release_state.md` — v0.4.0–v0.7.0 all shipped (2026-04-19/20)。
- `project_paris_dataset.md` — raw CSV lives only in `/tmp` by decision。
- `reference_architecture_doc.md` — `docs/ARCHITECTURE.md` を最初に開けポインタ。
- `project_mapillary_decision.md` — 2026-04-19 Mapillary やめ決定。
- `project_pypi_decision.md` — 2026-04-19 PyPI やらない決定。

Memory 書き込み規約は agent instructions 内の "auto memory" セクションに従う（type: user /
feedback / project / reference の 4 種、`MEMORY.md` は index）。

### 9.2 Permission

- `.claude/settings.json`（tracked）— `pytest`, `ctest`, `ruff`, `git fetch` 等の read-only
  allowlist。
- `.claude/settings.local.json`（gitignored、個人スコープ）— `git push` / `git push origin main` /
  `git push --dry-run` の narrow allow rule。もし消えていたら `enable_main_push.sh` 類で再生成可
  （前 session ではユーザーが一度生成 → 削除）。
- **tag push** や **force push** は allow rule に **入っていない** — 毎回 authorize 待ちで正しい。

### 9.3 セッション開始チェック

新 AI が session 開始時に最低限見るべきもの:

1. `git status && git log --oneline -10` — 現在地を把握。
2. `CHANGELOG.md` の `[Unreleased]` — 直前に何が landed した / していないか。
3. `docs/PLAN.md`（このファイル）§5 — open tasks。
4. `docs/ARCHITECTURE.md` — 全体図（Mermaid 6 枚）。
5. Cursor など Claude memory が読めない環境では、§0 の "Cursor handoff / 現在地" を先に読む。
6. Memory `MEMORY.md` — user preference / past decisions（Claude Code 環境で読める場合）。

---

## 10. 引き継ぎチェックリスト

新しい機能 / バグ修正を入れる前に:

- [ ] `pytest` が 477 passed / 32 skipped / 4 deselected で通ること（上下 ±1 は OK、大きく減ったら
      skip 理由を確認）。
- [ ] `CHANGELOG.md` の `[Unreleased]` にユーザー向け変更を足すこと。
- [ ] スキーマ変更時は対応する `validate_*` と CI の expectation を同時更新すること。
- [ ] 機密（IMEI、キー、生ダンプ）は **コミットしない** こと。Overpass raw JSON は `/tmp`。
- [ ] `docs/PLAN.md`（このファイル）の §3 "確認済み" と §5 "Open tasks" を作業後に同期すること。
- [ ] `git push` は user から `push!` 等の明示 authorize を受けてから実行すること。

---

## 11. 一行で言うと

> **v0.7.0 は全部シップ済み、直近 workstream（accuracy / completions / tuning / visual preview）も
> commit 済み。次は「V3 float32 の design memo」から入るのがおすすめ。何を削って何を広げたかは
> `CHANGELOG.md` と §3 の小節を見れば全部わかる。push / tag / AI マーカー / PyPI /
> Mapillary は全部 user authorize か No 決定済みなので、勝手に提案しないこと。**

---

*このファイルを更新したら: §3「確認済み」と §5「Open tasks」の整合を取り、先頭の
"最終更新" 日付を直すこと。*

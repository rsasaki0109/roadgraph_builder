# roadgraph_builder — 開発計画・引き継ぎメモ

Codex / 次のセッション向け。**事実と意図を分けて**書く。
まず全体図を掴みたければ [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md) を先に開くこと（Mermaid 6 枚 + CLI 対応表 + モジュール索引）。

## スコープ（意図）

- 軌跡 CSV（`timestamp, x, y`）から **道路グラフ**（ノード／エッジ＋中心線）を構築し、**ナビ SD シード**・**シミュ用 GeoJSON**・**Lanelet 互換 OSM** を **`export-bundle`** で一括出力する。
- **HD** は「測量完成品」ではなく、enrich による **HD-lite 帯**、LiDAR／カメラは **段階的**（スタブ含む）。
- 生成したグラフ上で **ルーティング** まで完結させる（Dijkstra + turn_restrictions 対応）。Leaflet viewer で click-to-route 可視化まで。

## 確認済み（事実）

### パイプライン / エクスポート

- CLI: `build`, `visualize`, `validate`, `validate-detections`, `validate-sd-nav`, `validate-manifest`, `validate-turn-restrictions`, `enrich`, `inspect-lidar`, `nearest-node`, `route`, `stats`, `fuse-lidar`, `export-lanelet2`, `apply-camera`, `export-bundle`, `doctor`。
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
- **camera detections**: JSON で `apply-camera`、GeoJSON `semantic_summary` に反映。

### 検証 / CI / 配布

- JSON Schema（road_graph / camera_detections / sd_nav / manifest / turn_restrictions）。全て `importlib.resources` 経由で読込、`doctor` が起動時自己チェック。
- CI: pytest（Python 3.10 / 3.12）+ 各 `validate-*` + `export-bundle` + `inspect-lidar` + `doctor` を全 push で走らせる。Node.js 24 opt-in 済。
- **配布**: `scripts/build_release_bundle.sh` + `.github/workflows/release.yml` で `v*` タグ push 時に `dist/roadgraph_sample_bundle.tar.gz` と sha256 を GitHub Release に自動添付。`examples/frozen_bundle/` に 0.3.0 時点の固定サンプルを同梱。
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

## 未確認・要フォロー

- **実走データ（IMU/GNSS 投影済み xy）での追加パラメータ調整** — Paris OSM 以外のデータで挙動を確認するのが望ましい。`make tune` を回すところから。
- **カメラ生画像 → 投影** — 現状は detections JSON しか受けない。画像 pipeline は未着手。
- **`v0.3.0` タグ push** — 準備済み（commit `f8cd7eb`）だがユーザー明示指示で保留中。次に release したくなったら:
  ```bash
  git tag -a v0.3.0 -m "Release 0.3.0"
  git push origin v0.3.0
  ```
  `release.yml` が tarball + sha256 を Release に添付する。

## 次の優先（提案）

どれも user 指示待ち。重要度ではなく "やれば効く度":

1. **`v0.3.0` タグ release** — すぐ実行可。Release notes は `CHANGELOG.md [0.3.0]` から自動生成される。
2. **Viewer JS Dijkstra で turn_restrictions 順守** — 現状 click-to-route は制限無視（pre-baked overlay のみ順守）。`(node, incoming_edge, direction)` 状態付き JS Dijkstra にすれば interactive に効く。
3. **LAS/LAZ 実データ検証** — OpenTopography / USGS 3DEP など公開 LAS でヘッダ + 点読みを検証。必要なら合成 LAS 以外にリアル LAS サンプル（数 MB）を同梱検討。
4. **カメラ画像 → 投影** — `io/camera/` に画像 → 2D 投影 → 検出 JSON のパイプラインを stub → 実装。

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

- [ ] `main` の `pytest` が通ること（現状 129 passed + 1 skipped）。
- [ ] `CHANGELOG.md` の `[Unreleased]` にユーザー向け変更を足すこと。
- [ ] スキーマ変更時は **対応する `validate_*` と CI** を更新すること。
- [ ] 機密（IMEI、キー、生ダンプ）は **コミットしない**こと。
- [ ] `docs/PLAN.md`（このファイル）の「確認済み」は作業後に同期すること。

## セッション運用メモ

Claude Code で直接実装するフローで安定している（今までの `codex exec --full-auto` 前提ではない）。`main` に直接コミット・push する運用。タグ push / 大きい外部データ commit はユーザー明示許可必須（`$HOME/.claude/projects/<cwd>/memory/feedback_push_and_tags.md`）。

---

*最終更新: 作業セッションで `docs/PLAN.md` を編集したら、「確認済み」と「未確認・要フォロー」を同期すること。*

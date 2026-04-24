# roadgraph_builder — 開発計画・AI 引き継ぎ handoff メモ

> このファイルは **次に入る AI エージェント**（Claude Code / Codex / その他の LLM assistant）
> を **cold-start で迷わせない** ための自己完結ドキュメントです。事実（観測可能）と
> 意図（決定・方針）と **やってはいけないこと** を分けて書いてあります。先に読むべきは
> このファイル → [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md)（Mermaid 6 枚 + CLI 対応表 +
> モジュール索引）→ [`CHANGELOG.md`](../CHANGELOG.md) の順。

*最終更新: 2026-04-24 session（V1 実測 / camera warning fix / perf flake fix / docs sync / completions sync / Paris accuracy refresh / Berlin tuning sweep / README+docs visual preview + measured-results cards polish + README measured-results compacting / float32 opt-in + drift report + compare script + 1M synthetic memory profile + OSM public-trace replay profile / release bundle byte + normalized-manifest gate + manifest policy docs polish / private repo Pages blocked note / CLI boundary split wave 完了 / README release surface 整理 / v0.7.1 release + asset verification / packaging metadata smoke / 0.7.2.dev0 reopen / Actions Node24 update / release+PyPI dry-run / routing hot-path perf / nearest spatial index / cache invalidation hardening / build graph spatial merge perf / T-junction segment index perf / lean near-parallel merge loop / GeoJSON export compact path / compact bundle JSON writer / README quick-start smoke / release readiness dry-run refresh / reachable service-area CLI / reachable docs overlay / reachable benchmark coverage / benchmark baseline JSON / reachability analyzer perf / routing core split / RoutePlanner perf / GitHub star-growth surfaces / launch kit docs / safe A* routing / route explain diagnostics / route explain docs surface / route explain comparison UI / route diagnostics README screenshot / functional shortest_path planner cache + sampled validation / nearest-edge projection index / match-trajectory explain diagnostics / HMM bridge ambiguity benchmark / HMM adjacency reuse perf / HMM tail-cost cache / HMM long trajectory benchmark / edge-index cell tuning / 2D/3D map console / PLAN handoff expansion / map console pushed + CI green / Claude handoff refresh / map console hero screenshots / map console browser smoke opt-in pytest / map console JS split + 3D raycaster picking / map console deep link + route steps inspector / map console route export + deep-link 自動 fit + hero screenshot refresh / Paris grid + Berlin Mitte HD-lite lanes & committed viewer dataset / junction topology color coding / OSM road-class color coding + class breakdown / animated map console hero GIF / JS route engine diagnostics in inspector / Paris grid synthetic camera semantic overlay / live reachability on click / 2D hover card sync / SD-HD layer tier toggle / README + SHOWCASE map-first reorg / Pages index map-first redirect / Paris grid Lanelet2 OSM + AV scope disclaimer / Autoware-spec lanelet tags / OSM lanes tag → multi-lane Lanelet2 / OSM regulatory nodes replace synthetic / Berlin Lanelet2 + dataset-aware download link）を反映済み。*

---

## 0. 一分サマリ（新 AI 向け）

- **リポジトリ:** `rsasaki0109/roadgraph_builder`（GitHub、MIT、Python 3.10/3.12）。
- **目的:** 軌跡 CSV / OSM highway ways / LiDAR / camera 入力から **道路グラフ** を構築し、
  ナビ SD / simulation / Lanelet2 を一括エクスポートする graph-first ライブラリ。HD は
  survey-grade ではなく「HD-lite」帯まで。
- **state:** **v0.7.2.dev0 open on main** after **v0.7.1 shipped (2026-04-21)**。tag `v0.7.1` は `8282f7c`。
  最新 main CI run `24833808373`、最新 Pages run `24833807860`、Release workflow run `24721632168` は green。
  GitHub Release assets (`roadgraph_sample_bundle.tar.gz` / `.sha256`) は download + checksum +
  `validate-manifest` / `validate-sd-nav` / `validate` 済み。`v0.7.0` は shipped (2026-04-20)。
  最新 full local `pytest` = **647 passed / 3 skipped / 4 deselected**（opt-in marker 除外）。
- **current local git:** 2026-04-24 時点で `main...origin/main`、作業ツリー clean。
  `f6045a2 feat: add 2d 3d map console` と
  `c9aa588 docs: expand plan handoff for map console` は push 済み。
  Claude へ handoff するにはちょうどよい同期点。
- **latest local checks for map console:** `git diff --check` PASS。
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest tests/test_viewer_js_dijkstra.py tests/test_map_match_explain_asset.py`
  は **3 passed**。さらに `cd docs && python3 -m http.server 18765` を立て、
  `npx -y -p @playwright/test` + system Chrome (`test.use({ channel: "chrome" })`) で desktop
  1366×900 / mobile 390×844 の browser smoke を実行し **2 passed**。
  smoke は 2D map load、dynamic route (`n312 → n191`)、3D mode、canvas pixel nonblank、
  overlay toggle、horizontal overflow なしを確認。スクリーンショットは `/tmp/roadgraph-map-*.png`。
- **Claude restart point:** product/demo導線を続けるなら §3.11 可視化 → §5b 次のおすすめ候補 の順で読む。
  core algorithm/perf を触るなら §3.8〜§3.10 と benchmark baseline JSON を先に見る。
- **直近の sessions (2026-04-21〜2026-04-24) で landed:**
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
  14. `apply-camera` / `project-camera` / `detect-lane-markings-camera` CLI を
      `roadgraph_builder/cli/camera.py` に分離。projection/camera-lane serializer、image lookup、
      command handler の tests を `tests/test_cli_camera.py` に追加。
  15. `inspect-lidar` / `fuse-lidar` / `detect-lane-markings` CLI を
      `roadgraph_builder/cli/lidar.py` に分離。LAS/CSV point loading、ground-plane shape validation、
      lane-marking serializer を局所化し、`tests/test_cli_lidar.py` を追加。
  16. `build-osm-graph` / `convert-osm-restrictions` CLI を `roadgraph_builder/cli/osm.py` に、
      `guidance` / `validate-guidance` CLI を `roadgraph_builder/cli/guidance.py` に分離。
      OSM origin/filter/doc shaping と guidance serializer/validator handler を
      `tests/test_cli_osm_guidance.py` で検証。
  17. `build` / `visualize` CLI を `roadgraph_builder/cli/build.py` に、schema validation 系
      `validate*` CLI を `roadgraph_builder/cli/validate.py` に分離。build params、trajectory dtype、
      JSON root validation、validator dispatch を `tests/test_cli_build_validate.py` で検証。
  18. `reconstruct-trips` / `fuse-traces` / `match-trajectory` / `stats` /
      `infer-road-class` / `infer-signalized-junctions` CLI を
      `roadgraph_builder/cli/trajectory.py` に分離。trip/match/stat summary serializer と
      injection-friendly handlers を `tests/test_cli_trajectory.py` で検証。
  19. `enrich` / `infer-lane-count` CLI を `roadgraph_builder/cli/hd.py` に分離。
      optional refinement JSON validation、lane inference → edge HD attributes 反映、
      summary serializer を `tests/test_cli_hd.py` で検証。
  20. `update-graph` CLI を `roadgraph_builder/cli/incremental.py` に分離し、
      `process-dataset` CLI parser/handler を既存 `roadgraph_builder/cli/dataset.py` に集約。
      file preflight、manifest exit-code policy、incremental update summary を
      `tests/test_cli_incremental_dataset.py` で検証。`main.py` は 287 行の dispatcher まで縮小。
  21. README の release surface を整理し、v0.7.0 で shipped 済みの command surface と
      `[Unreleased]` の post-release validation/docs/float32/CLI refactor を分離して記述。
      stale な "trajectory CSV only" / completion caveat も解消。
  22. `scripts/compare_float32_drift.py` を追加。trajectory CSV から float64 / opt-in float32
      bundle を再構築し、`road_graph.json` / `sd_nav.json` / `map.geojson` / Lanelet2 OSM の
      topology と coordinate drift を JSON/Markdown に出せる。Paris sample smoke では
      topology unchanged、max drift **0.000141 m**。
  23. `/tmp` の 1,000,000-row synthetic trajectory で float32 memory profile を再計測。
      `Trajectory.xy` retained allocation は **24,000,568 B → 16,000,568 B** と期待通り
      8 MB 減、tracemalloc peak は約 19 MB 減。ただし full `export-bundle` の peak RSS は
      1,241,652 KB → 1,238,972 KB（約 2.6 MB 減）に留まり、GeoJSON/build temporaries が
      high-water を支配するため default flip の根拠にはならない。
  24. `tests/test_release_bundle.py` に default `export-bundle` byte gate を追加。
      sample trajectory + detections + turn_restrictions + LiDAR fixture から tmp bundle を再生成し、
      `sd_nav.json` / `road_graph.json` / `map.geojson` / `trajectory.csv` / Lanelet2 OSM /
      generated README files が `examples/frozen_bundle/` と byte-for-byte 一致することを常時検証。
      `manifest.json` は `roadgraph_builder_version` と `generated_at_utc` だけを normalize して、
      それ以外を frozen manifest と厳密比較する。
  25. `/tmp` の Paris / Tokyo / Berlin OSM public trackpoints から replay workload を作り、
      500k load-only と 75k full `export-bundle` を測定。500k load-only は `Trajectory.xy`
      8,000,000 B → 4,000,000 B、75k full export RSS は 272,016 KB → 267,972 KB（約 4 MB 減）。
      ただし 75k replay では float32 の edge / Lanelet ID drift が出たため、default float64 維持を再確認。
  26. `docs/index.html` の measured-results section を整理し、metric labels / copy / responsive grid /
      focus states / palette を polish。`python3 -m http.server` + asset smoke で index/CSS/JS/SVG を確認。
  27. README と `examples/frozen_bundle/README.md` に manifest release policy を明記。
      `manifest.json` は `roadgraph_builder_version` / `generated_at_utc` だけ動的扱いで、
      origin / inputs / stats / optional-source metadata / output paths は stable release surface として扱う。
  28. README の measured-results table を冒頭寄りに compact 化。
      routing / accuracy / tuning / memory の 4 signals に絞り、後段の長い duplicate table を削除。
  29. `v0.7.1` release prep。`pyproject.toml` / `roadgraph_builder.__version__` を 0.7.1 に上げ、
      `CHANGELOG.md` の `[Unreleased]` を `0.7.1 — 2026-04-21` に切り出す。
  30. `v0.7.1` annotated tag を push し、Release workflow で GitHub Release を作成。
      添付された `roadgraph_sample_bundle.tar.gz` と `.sha256` を `/tmp` に download し、
      `sha256sum -c` と展開後の manifest / sd_nav / road_graph validate を確認。
  31. post-release package smoke で setuptools license metadata deprecation warning を検出。
      `pyproject.toml` を SPDX `license = "MIT"` + `license-files = ["LICENSE"]` に更新し、
      legacy license classifier を削除。
  32. Python 3.10 CI で Paris splitter golden の aggregate length だけ 3.49 m drift。
      topology / IDs は守られているため、length tolerance を 5 m に拡大して runtime / NumPy 差を吸収。
  33. `v0.7.1` tag 後の `main` を `0.7.2.dev0` に reopen。
      post-release metadata/test hygiene commits が shipped `0.7.1` version を再利用しないようにする。
  34. GitHub Actions の Node 20 deprecation warning 対策。
      CI / release / benchmark / city-scale / PyPI workflow を `node24` 実行の action major へ更新し、
      `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` flag 依存を削除。
  35. Release / PyPI workflow の local dry-run。
      `/tmp` に `HEAD` を archive 展開し、release bundle build + checksum + extracted manifest/sd_nav/road_graph
      validation と、PyPI build job 相当の `python -m build` + `twine check dist/*` を確認。
  36. `shortest_path` hot path の性能改善。
      `Graph` ごとの routing index cache（node ids / edge lengths / base adjacency）と、
      turn restriction なしの node-level Dijkstra fast path を追加。55×55 grid 120 routes は
      local one-off で約 7.0s→2.7s（first pass）、warm pass で約 6.5s→1.9s。
      `scripts/run_benchmarks.py` に `shortest_path_grid_120` を追加し、直接実行時の repo import も修正。
  37. `nearest_node` hot path の性能改善。
      Graph ごとの spatial hash index を追加し、近傍 cell の exact distance check + far query lower-bound
      fallback に変更。300×300 nodes / 2000 queries は旧 Python full scan で約 59.3s/53.6s、
      spatial index で約 0.63s/0.57s/0.59s。benchmark に `nearest_node_grid_2000` を追加。
  38. routing / nearest cache invalidation hardening。
      `nearest_node` は small/medium graph で全 node signature、大規模 graph で均等 sample signature を持ち、
      middle node の position replacement を検出。`shortest_path` は polyline coordinate checksum を
      routing signature に含め、in-place polyline mutation でも cached edge length を捨てる。
  39. build graph spatial merge performance。
      `merge_endpoints_union_find` を uniform grid 近傍探索に変更し、endpoint 全ペア scan を回避。
      `merge_near_parallel_edges` も endpoint neighborhood index で候補 edge pair だけを既存の
      distance-sum predicate に通す形に変更。50x50 synthetic grid build は local one-off で
      約 42-46s → 1.2-1.7s、benchmark suite の `polylines_to_graph_10k_synth` は約 1.0-1.4s。
  40. T-junction segment candidate performance。
      `split_polylines_at_t_junctions_fast` を expanded whole-polyline bbox index から expanded segment
      bbox index に変更し、endpoint ごとに近傍 segment だけ projection。endpoint/polyline pair ごとに
      global nearest projection を先に決めてから interior guard に通す legacy semantics は維持。
      50x50 synthetic grid build は warm pass で約 0.5s、benchmark suite の
      `polylines_to_graph_10k_synth` は 0.819s。
  41. lean near-parallel merge loop。
      `merge_near_parallel_edges` の hot loop で endpoint list を再利用し、候補 neighborhood walk を inline 化。
      `sorted(candidate_indices)` と endpoint-pair set construction を避け、merge predicate は維持。
      最新 benchmark suite の `polylines_to_graph_10k_synth` は 0.471s。
  42. GeoJSON export compact path。
      `export_map_geojson` は map ごとに WGS84 変換定数を precompute し、default pretty output は維持。
      `export_map_geojson(compact=True)` / `export_map_bundle(..., compact_geojson=True)` /
      `export-bundle --compact-geojson` を追加。180x180 synthetic grid は document build 1.42s→0.70s、
      default pretty export 7.03s→3.05s、compact export 1.76s / 42.8MB→23.6MB。
  43. compact bundle JSON writer。
      `json_exporter` に shared JSON writer を追加し、`export_graph_json(compact=True)` と
      `export_map_bundle(..., compact_bundle_json=True)` / `export-bundle --compact-bundle-json` で
      `nav/sd_nav.json` / `sim/road_graph.json` / `manifest.json` を opt-in compact 化。
      default pretty output と frozen bundle byte gate は維持。180x180 writer-shaped docs で
      `road_graph.json` は 1.59s/21.3MB→0.43s/10.5MB、`sd_nav.json` は 0.65s/17.0MB→0.15s/11.6MB。
  44. README quick-start smoke hardening。
      `tests/test_cli_end_to_end.py` は console script 未 install の checkout でも subprocess 経由で
      `roadgraph_builder.cli.main` に fallback し、README 相当の `export-bundle` → validate →
      `route --output` → `guidance` → `validate-guidance` と、`--compact-geojson --compact-bundle-json`
      bundle smoke を検証。
  45. Release readiness dry-run refresh against code commit `342f61f`。
      `bash scripts/build_release_bundle.sh` で `dist/roadgraph_sample_bundle.tar.gz` と `.sha256` を再生成し、
      `sha256sum -c`、展開後の `validate-manifest` / `validate-sd-nav` / `validate` を確認。
      PyPI 公開は引き続き skip。`python3 -m build --outdir /tmp/roadgraph_builder_pypi_dist` は
      `roadgraph_builder-0.7.2.dev0.tar.gz` と wheel を生成。ローカルの古い `twine 5.1.1` は
      `Metadata-Version: 2.4` を読めず false negative になるが、一時 venv の `twine 6.2.0` では
      `twine check /tmp/roadgraph_builder_pypi_dist/*` が sdist / wheel とも PASS。
  46. `reachable` service-area CLI。
      `routing.reachability.reachable_within` が start node から cost budget 内で到達可能な node と
      directed edge span（partial edge は `reachable_fraction` 付き）を返す。CLI は node id / `--start-latlon`、
      `--turn-restrictions-json`、既存の observed / confidence / slope cost hooks、JSON summary、
      `--output` clipped GeoJSON に対応。`routing.geojson_export.write_reachability_geojson` で可視化できる。
  47. reachable docs overlay。
      `scripts/refresh_docs_assets.py` が committed Paris grid map + turn restrictions から
      `docs/assets/reachable_paris_grid.geojson`（start `n312`, budget 500 m）を生成する。
      `docs/map.html` は到達圏 edge spans / reachable nodes を route overlay とは別レイヤで表示し、
      `docs/images/paris_grid_route.svg` と README / `docs/index.html` の static preview にも反映。
  48. reachable benchmark coverage。
      `scripts/run_benchmarks.py` に `reachable_grid_120` を追加。55×55 synthetic routing grid で
      120 本の service-area query を走らせ、60 m budget で到達 node と directed edge span を消費する。
      local `python scripts/run_benchmarks.py --no-warmup` では `reachable_grid_120` が 0.270s、
      全 benchmark suite は引き続き 1 分未満。
  49. benchmark baseline JSON。
      `scripts/run_benchmarks.py --output PATH` で `--baseline` と同じ JSON shape を保存可能にし、
      誤操作防止のため `--baseline` と `--output` が同一 path の場合は exit 1 にする。
      `docs/assets/benchmark_baseline_0.7.2-dev.json` を committed baseline とし、
      `tests/test_benchmark_script.py` が benchmark entry との同期と正の elapsed time を検証する。
  50. reachability analyzer perf。
      `routing.reachability.ReachabilityAnalyzer` が graph/policy ごとに routing index、weighted adjacency、
      turn restriction policy を 1 回だけ準備する。`reachable_within` は従来 API を維持しつつ analyzer を
      使う。turn restriction なしの到達圏探索は directed incoming-edge state machine ではなく
      node-level Dijkstra を使うため、`reachable_grid_120` は 2.649s → 0.270s まで短縮。
  51. routing core split。
      `roadgraph_builder/routing/_core.py` に graph mutation signature、cached `RoutingIndex`、
      `RoutingCostOptions`、weighted adjacency、`TurnPolicy` parse / transition 判定を集約。
      `shortest_path` と `ReachabilityAnalyzer` が同じ core を使うようにし、
      `tests/test_routing_core.py` で turn policy と cost hook 単位を直接検証する。
  52. RoutePlanner perf。
      `routing.shortest_path.RoutePlanner` が shortest-path 用の routing index、weighted adjacency、
      turn restriction policy、lane count を 1 回だけ準備し、同一 graph/policy 上の複数 route query で再利用する。
      `shortest_path(...)` は従来 API のまま planner を 1 query 用に作る薄い wrapper。
      `shortest_path_grid_120` は 1.711s → 0.959s（committed baseline）まで短縮し、
      direct warm pass は約 0.60s。
  53. GitHub star-growth surfaces。
      README 冒頭に初見向けの value bullets を追加し、古い "stub" 表現を現機能に同期。
      `.github/ABOUT.md` は GPS / OSM / LiDAR / camera / Lanelet2 / routing を含む説明と topics、
      `gh repo edit` 用 command に更新。GitHub issue forms（bug / feature / showcase）と
      PR template を追加し、外部 contributor / user showcase の導線を用意。
  54. launch kit docs。
      `docs/SHOWCASE.md` に 30 秒 pitch、Paris OSM-grid showcase、core workflows、対象ユーザー、
      measured signals、local preview を整理。`docs/LAUNCH.md` に X / Bluesky / LinkedIn /
      Hacker News / Reddit 向け投稿文、3 command demo、添付 visual、caveats を用意。
      README 冒頭から Showcase / Launch notes / Architecture / Benchmarks / Contributing に誘導。
  55. safe A* routing。
      `RoutePlanner` が edge cost と node 間直線距離の lower-bound 条件を満たす時だけ cached A*
      heuristic を使い、tie-break は目的地に近い候補を優先する。observed/downhill discount や
      node position と edge geometry がズレた graph は Dijkstra fallback にする。routing signature は
      node position 変更も検出する。`shortest_path_grid_120` は committed baseline で 0.959s → 0.601s。
  56. route explain diagnostics。
      `RoutePlanner.last_diagnostics` が search engine、heuristic enabled、fallback reason、
      expanded / queued state counts、route edge count、total length を保持する。CLI は
      `roadgraph_builder route --explain` で通常 route JSON に `diagnostics` を追加し、
      safe A* / Dijkstra fallback の理由を外から確認できる。
  57. route explain docs surface。
      `scripts/refresh_docs_assets.py` が `docs/assets/route_explain_sample.json` を生成し、
      metric sample の safe A* と Paris TR-aware route の `non_metric_geometry` fallback を
      実 `RoutePlanner` diagnostics 由来で保存する。`docs/index.html`、README、SHOWCASE から
      この JSON に誘導し、Pages 上で route engine の判断が見えるようにした。
  58. route explain comparison UI。
      `docs/index.html` / `docs/js/route_diagnostics.js` が `route_explain_sample.json` を読み込み、
      safe A* と Dijkstra fallback の expanded / queued states、edge count、route length、
      heuristic 状態、fallback reason を同じ比較表で表示する。README / SHOWCASE も
      「JSON へのリンク」ではなく observable routing の比較ビューとして説明する形に更新。
  59. route diagnostics README screenshot。
      `docs/route_diagnostics_preview.html` と `scripts/render_route_diagnostics_screenshot.py` を追加し、
      headless Chrome で `docs/images/route_diagnostics_compare.png` を再生成できるようにした。
      README / SHOWCASE はこの PNG を埋め込み、Pages を開く前に safe A* と Paris Dijkstra fallback
      の state-count 比較が見える。
  60. functional shortest_path planner cache。
      public `shortest_path(...)` wrapper が no restrictions / no extra cost hooks / no lane-level の
      default case だけ graph-local `RoutePlanner` を再利用する。小さい graph は exact routing
      signature のまま、大きい graph は fixed node / edge sample で cache validation し、属性依存
      cost hooks は stale risk を避けるため cache 対象外。55x55 grid の 120 functional calls は
      local one-off で 4.6-5.7s → exact validation 2.1-2.7s → sampled validation 0.7-1.0s。
      `shortest_path_grid_120_functional` benchmark baseline は 0.812s。
  61. nearest-edge projection index。
      `routing.edge_index` に edge polyline segment の spatial hash cache を追加し、
      `snap_trajectory_to_graph` と `hmm_match_trajectory` の candidate generation で共有する。
      graph-order tie-break、long segment overflow fallback、polyline mutation による cache invalidation を
      テストで固定。`map_match_grid_5000` benchmark は 120x120 grid / 5000 samples の nearest-edge
      snap を測り、committed baseline は 1.519s。
  62. match-trajectory explain diagnostics。
      `roadgraph_builder match-trajectory --explain` が通常の stats/sample JSON shape を保ったまま
      `stats.diagnostics` に elapsed ms、projection/candidate query count、edge-index segment/cell/overflow
      counts を追加する。bash / zsh completion も `--explain` に同期。
  63. map matching explain sample asset。
      `scripts/refresh_docs_assets.py` が frozen toy bundle から
      `docs/assets/map_match_explain_sample.json` を生成する。nearest-edge と HMM の
      `match-trajectory --explain` 出力例を README / SHOWCASE からリンクし、attribution に synthetic
      repo-license asset として明記。
  64. HMM map matching transition accuracy。
      HMM candidate に `arc_length_m` / `edge_length_m` を保持し、transition penalty で
      prev projection→prev endpoint、endpoint 間 graph distance、cur endpoint→cur projection を足す。
      旧実装は別 edge 遷移で endpoint 間距離だけを見ていたため、接続直前/直後の沿道 tail cost が
      消えていた。connected edges と bridge candidate の回帰テストで固定。
  65. HMM bridge ambiguity benchmark。
      `scripts/run_benchmarks.py` に `hmm_match_bridge_500` を追加。connected 100m edge chain の
      各 boundary 近くに disconnected bridge distractor を置き、500 HMM samples が bridge に
      吸われず connected chain に残ることを count と unit test で固定。初期 committed baseline は 0.496s。
  66. HMM transition adjacency reuse。
      transition Dijkstra が start node ごとに graph adjacency を再構築していた無駄を削り、
      `routing._core.get_routing_index(graph).base_adj` を lazy に1回だけ使う形へ変更。
      `hmm_match_bridge_500` の no-warmup suite baseline は 0.496s → 0.090s。
  67. HMM candidate tail-cost cache。
      `_Candidate` が projection→edge endpoints の tail cost を持つようにし、transition の
      candidate pair ループで同じ tail cost を繰り返し再計算しない。node-pair cache は
      profile で dict/hash overhead が勝ったため採用せず、低コストな candidate-local cache に限定。
      `hmm_match_bridge_500` の no-warmup suite baseline は 0.090s → 0.058s。
  68. HMM long trajectory benchmark。
      `scripts/run_benchmarks.py` に `hmm_match_long_grid_2000` を追加。20-row x 51-column の
      snake grid route に 2000 samples を流し、各 route segment 横に disconnected alias edge を置く。
      count は全 sample が `route*` edge に残ることを検証し、committed baseline は 0.292s。
  69. edge projection index cell tuning。
      HMM long trajectory profile で candidate projection が支配的だったため、
      `routing.edge_index` の cell size を nominal segment spacing の 4.0x → 2.0x に縮小。
      long segment overflow fallback は維持しつつ per-query segment fan-out を下げる。
      no-warmup suite baseline は `map_match_grid_5000` 1.519s → 0.613s、
      `hmm_match_bridge_500` 0.058s → 0.034s、`hmm_match_long_grid_2000` 0.292s → 0.131s。
  70. docs map 2D/3D product console。
      `docs/map.html` を Leaflet 単体から、2D OSM view + Three.js 3D graph preview + dataset inspector
      + overlay toggles の product console に拡張。クリックで生成した dynamic route も
      `scenePayload.route` に同期し、3D view と route metric が同じ状態を読む。
  71. PLAN handoff expansion。
      2D/3D map console の内部構造、検証済み手順、既知制約、次にやる価値が高い候補をこの PLAN に追記。
      次の AI / Cursor が「何を push すべきか」「何を追加検証すべきか」「まだ product として足りない
      体験は何か」を cold-start で読める状態にする。
  72. map console hero screenshots。
      `docs/map.html` に `?view=2d|3d` と `?dataset=…` の URL param と `body[data-ready]` シグナルを
      追加し、`scripts/render_map_console_screenshot.py` がローカル http.server + Playwright CLI
      (`npx -y -p @playwright/test playwright screenshot --channel chrome`) で
      `docs/images/map_console_2d.png` / `map_console_3d.png` を PIL quantize 後に committed asset
      として生成する。README "Visualization results" と `docs/SHOWCASE.md` に両 PNG を埋め込み、
      GitHub README 上で 2D inspector / 3D graph preview が直接見えるようにした。
  73. map console browser smoke を opt-in pytest 化。
      `tests/js/map_console_smoke.spec.mjs` に desktop 2D (Paris grid inspector counts) / desktop 3D
      (WebGL pixel nonblank + `#scene3d-status` node mention) / mobile 2D (horizontal overflow 無し)
      の 3 アサートを書き、`tests/test_map_console_browser_smoke.py` がローカル http.server +
      `npx -y -p @playwright/test playwright test` で駆動する。@playwright/test の ESM resolve は
      NODE_PATH が効かないため、npx cache の node_modules を `mktemp -d` に symlink して spec を
      コピーし、そこから `playwright test ... --channel chrome` を走らせる。`pytest -m browser_smoke`
      / `make viewer-smoke` が entry point、default `pytest` は `not browser_smoke` で除外済み。
      `node` / `npx` / `google-chrome` が無い環境は skip。
  74. map console の JS split と 3D raycaster picking。
      `docs/map.html` の 1100 行インラインスクリプトを `docs/js/map_console.js` に分離し、
      `tests/js/test_viewer_dijkstra.mjs` もそこから抽出するよう更新（`buildRestrictionIndex` /
      `dijkstra` の top-level 関数名は維持）。3D view に `THREE.Raycaster` ベースの hover / click
      picking を追加：centerline Line と node Points の userData を保持し、pointermove で hover card
      を更新、ポインタが pickable に乗っている間は auto-rotate を停止、ドラッグなしの pointerup は
      `handleScenePick` → node 当たれば既存 `onNodeClick(nodeId)` で 2D/3D 両方に route を反映。
      inspector 右側に `#hover-card` (Hovered / ID / Length / Endpoints / hint) を追加。
      browser smoke spec に 3D hover + click ケースを追加し、5 連続 run で flake 無し（7–9s）。
  75. map console deep link + route steps inspector。
      `docs/map.html?from=nXXX&to=nYYY` で bootstrap 時に既存 graph + restrictions から
      `dijkstra()` を再計算して `drawDynamicRoute` に流す deep link を追加。`drawDynamicRoute` /
      `clearRoute` は `history.replaceState()` で URL の `from` / `to` を同期するので、
      任意の route を URL コピペで共有できる。inspector 右側に `#steps-card`（edge_id / direction /
      length / cumulative_m + edge 数 + 総距離）を追加し、`renderRouteSteps(graph, dij)` /
      `clearRouteSteps()` で populate / hide。browser smoke に Paris `n312 → n191` deep link ケース
      を追加し、`#steps-card` 非 hidden + `li` が 3 本以上 + status に `deep link n312` + URL 末尾に
      `from=n312&to=n191` が残ることまで assert。
  76. map console route export + deep-link 自動 fit + hero screenshot refresh。
      `.bar` に `Download route GeoJSON` ボタンを追加し、route が draw された時のみ enable に切替、
      `scenePayload.route` を Blob 化して `route_<dataset>_<from>_<to>.geojson` として download
      させる。`applyDeepLinkRoute()` は `fitMapToRoute()` で 2D 地図を route bounds に自動 fit
      （click-to-route 経由は今まで通り fit 無し）。`scripts/render_map_console_screenshot.py` に
      `--from-node / --to-node` を追加し、default で `n312 → n191` deep link を焼き込んだ hero
      screenshot を生成するよう変更、README / SHOWCASE の committed PNG を route が見える状態へ更新。
      browser smoke の deep-link テストに `#download-route` enable 確認 + click → downloaded
      GeoJSON が `FeatureCollection` / `kind=route` LineString / `from_node` / `to_node` を保持する
      ことを assert する subprocess 追加。
  77. Paris grid + Berlin Mitte に HD-lite lane boundaries を実装。
      `scripts/refresh_docs_assets.py` に `enrich_sd_to_hd(grid, SDToHDConfig(lane_width_m=3.5))` を
      追加し、`docs/assets/map_paris_grid.geojson` が 1081 centerlines × 2 = 2162 本の
      `lane_boundary_left` / `lane_boundary_right` を持つ HD-lite 表示に格上げ（537 KB → 2.08 MB）。
      `/tmp/berlin_mitte_raw.json` が存在する時は 2063 centerlines × 2 = 4126 boundaries の
      `docs/assets/map_berlin_mitte.geojson` (3.69 MB) + `berlin_mitte_origin.json` を新規生成。
      viewer dropdown と `DATASET_URLS` に Berlin Mitte を追加、`ATTRIBUTION.md` に由来 / refetch
      レシピを明記。hero screenshots（2D / 3D）を再生成して緑・紫の lane boundary dash が見える状態に。
      browser smoke に `selectOption('#dataset','berlin_mitte') → #stat-lanes > 1000` アサートを追加。
  78. junction topology の viewer 可視化。
      `docs/js/map_console.js` に `JUNCTION_ORDER` / `JUNCTION_COLORS` / `JUNCTION_LABELS` +
      `junctionCategory(props)` / `junctionColor(props)` を追加（`junction_type` 優先、fallback
      `junction_hint`、unknown は `other`）。2D は `pointLayer()` が `kind=node` の fillColor を
      category 色に、3D は node `Points` cloud が per-vertex `THREE.Float32BufferAttribute('color')`
      + `vertexColors: true` で同じ色を使う。`threeState.nodeCategories[]` を `pickSceneHit()` と
      `setHoverCard()` に渡し、hover card の "Node" 行を `Node · T-junction` 等に拡張。
      inspector 右側に `#junctions-card`（色付き swatch + ラベル + カウント、types / nodes の
      合計）を追加、`renderJunctionsBreakdown()` を `show()` で populate。Leaflet legend も
      junction 種別ごとの swatch を含むよう拡張。JUNCTION 定数は legend onAdd より上に宣言する必要
      あり（const は TDZ 中アクセス不可、legend.addTo が即時 onAdd を呼ぶため）。
      browser smoke に `#junctions-card` / `#junctions-list li >= 4` / `N types · N nodes` assert
      を追加し、hero screenshots を再生成。Paris grid で 7 categories (t/y/crossroads/x/complex/
      through/dead) が色分け表示される状態。
  92. Berlin Mitte も per-lane Lanelet2 OSM を commit + viewer Lanelet2 link を
      dataset 切替で自動連動。`refresh_docs_assets.py` の Berlin Mitte block でも
      `infer_lane_counts` → `apply_lane_inferences` → `export_lanelet2_per_lane` を通し、
      `docs/assets/map_berlin_mitte.lanelet.osm`（5.1 MB, validate-lanelet2-tags `"ok"`）を
      生成。viewer の `LANELET_URLS` map に Paris / Berlin 両方を登録、`show()` で toolbar
      `#lanelet-download` の `href` + label を切替（未対応 dataset は link を hide）。

  91. OSM 実 regulatory nodes (traffic_signals / stop / crossing / give_way / speed_camera)
      を committed Paris grid に乗せる。`scripts/fetch_osm_regulatory_nodes.py` で
      Overpass から該当 node を fetch（Paris bbox だと 288 traffic_signals + 1532 crossings +
      5 give_way + 3 speed_camera）、`scripts/refresh_docs_assets.py` が lat/lon →
      meters → 最近傍 edge の point-to-polyline distance matching で edge に投影し、
      `apply_camera_detections_to_graph` に流して `edge.attributes.hd.semantic_rules`
      に登録。crossings は overlay 密度を抑えるため 160 件 cap。committed
      `docs/assets/paris_grid_camera_detections.json` は synthetic 9 件 → **real OSM
      456 件**（traffic_light 288 + crosswalk 160 + stop_line 5 + speed_camera 3）に
      差し替え、`source="osm_node"` + `osm_id` + `confidence=1.0` + `match_distance_m`
      を各 observation に保持。`ATTRIBUTION.md` は ODbL 由来へ更新。
      `validate-lanelet2-tags` は引き続き `"result": "ok"` 0 errors。

  90. OSM `lanes=` タグを lane_count に反映して HD-lite を multi-lane 化。
      `hd/lane_inference.py::infer_lane_counts` に「OSM lanes tag」source を
      追加（lane_markings → **osm_lanes_tag** → trace_stats → default の優先順）。
      OSM タグ由来の lane_count は `per_lane_confidence=0.6`、`road_half_width` も
      `lanes * base_lane_width_m / 2` まで広げる。`scripts/refresh_docs_assets.py` に
      `_widen_hd_envelope_for_osm_lanes()` を追加し、`enrich_sd_to_hd` 後に
      `osm_lanes>=2` のエッジの `hd.lane_boundaries` を `lanes * 3.5 m` 幅で再計算
      （外側 paint が真の道路幅に沿う）。Paris grid では 239 edges が multi-lane 化され、
      Lanelet2 OSM は 1081 → 1485 lanelets（lanes=2:228 + lanes=3:273 + lanes=4:112 +
      lanes=5:30 + 単車線:842）、`validate-lanelet2-tags` は `"result": "ok"` 0 errors。

  89. Lanelet2 export を Autoware-spec 互換タグに強化。
      `io/export/lanelet2.py` に `_autoware_lanelet_tags_from_attributes()` を追加し、
      `export_lanelet2_per_lane` と `export_lanelet2` の両方から呼んで
      `one_way=yes|no`（OSM `oneway`）/ `participant:vehicle=yes` / `speed_limit=<N> km/h`
      （OSM `maxspeed`）/ `name`（OSM name）を per-lanelet relation に emit。
      `scripts/refresh_docs_assets.py` では `_inject_osm_tags_into_graph_edges()` を先に
      呼んで edge.attributes に `highway` / `osm_lanes` / `osm_maxspeed` / `osm_oneway` /
      `osm_name` を stamp し、`export_map_geojson` と `export_lanelet2_per_lane` 両方に
      伝搬させる。Paris grid の lanelet は `one_way=yes` + `participant:vehicle=yes` +
      `speed_limit=30 km/h` + `name=Rue La Fayette` のような完全な tag セットになり、
      `validate-lanelet2-tags` が `"result": "ok"` で errors=0 を返す。
      frozen sample bundle の `lanelet/map.osm` も新タグに合わせて更新。

  88. Paris grid から per-lane Lanelet2 OSM を commit + AV scope disclaimer を全面追加。
      `scripts/refresh_docs_assets.py` の Paris grid block で `grid.to_dict()` →
      `infer_lane_counts(base_lane_width_m=3.5)` → `apply_lane_inferences()` を回し、
      `export_lanelet2_per_lane()` で `docs/assets/map_paris_grid.lanelet.osm`（1.9 MB、
      1 081 `type=lanelet` relations + 2 162 boundary ways）を生成。semantic_rules は
      inference 後に再 apply して上書きされないよう保護。map console toolbar に
      `Lanelet2 OSM` ダウンロードリンク、docs/index.html landing に scope 注記追記。
      README / SHOWCASE / ATTRIBUTION に「HD-lite, not survey-grade、実車投入前に
      cm 精度 survey が必要」を明示する blockquote を追加。default `pytest` は
      647 / 3 / 5、browser smoke も passing を維持。

  87. GitHub Pages entrypoint を map console first にする。
      repo が public 化されて https://rsasaki0109.github.io/roadgraph_builder/ が live になったが、
      default で diagram viewer (SVG) が表示されて "2D/3D map が無い" というユーザー指摘が発生。
      `docs/index.html` を `docs/diagram.html` に rename（diagram viewer + route diagnostics panel
      はそちらに移動）、`docs/index.html` は `<meta http-equiv="refresh" content="3;url=map.html">`
      を持つ小さな landing page に差し替え。hero GIF + tier 4 つの説明 + Open / Diagram への
      CTA ボタンを表示、3 秒後に自動で map.html へ遷移。`docs/map.html` の Diagram viewer リンクも
      `diagram.html` に修正。README / SHOWCASE / test_route_explain_asset / viewer.js コメント
      を diagram.html 参照に更新。default `pytest` は 647 / 3 / 5 維持。

  86. README / SHOWCASE を map-first narrative に再構成。
      README 冒頭に animated hero GIF + `From SD to HD in the map console` tier table を置き、
      Basic / SD / HD / Full 各段階で何が描かれて何が pipeline で保証されているかを一目で見せる。
      旧 "Visualization results" セクションを上部に吸収し、map-console 再生成ツール（Playwright /
      ffmpeg）と local run snippet も先頭付近に集約。`docs/SHOWCASE.md` も同じ tier 構造と
      inspector explanation に整え、"30 Second Pitch" に SD→HD の narrative bullet を追加。
      code 変更ゼロ。

  85. SD / HD layer tier toggle を map console に追加。
      `.bar` に `Mode: Basic / SD / HD / Full` select。tier 定義:
      Basic = centerline + node + trajectory、SD = + route + restrictions、
      HD = + lane boundaries + semantic markers + reachability、Full = 全部（default）。
      `MAP_MODE_KINDS[mode]` の set に入る kind だけを 2D L.geoJSON `filter` と 3D
      `modeInclude` wrapper 経由で描画。`rebuildLeafletLayers()` + `setMapMode(mode)` で
      runtime 切替（scenePayload.* は保持、再 fetch 不要）。drawDynamicRoute /
      drawDynamicReachability も route tier / reachable tier を gating。browser smoke に
      Full → Basic → HD 切替で SVG path 数が 1000+ → <half → +100 以上 の段階的変化を
      assert。hero PNG / GIF を再生成して mode select が見える状態に。

  84. 2D Leaflet hover を `#hover-card` に同期。
      `docs/js/map_console.js` に `hoverHitFromProps(props)` を追加し、feature property から
      setHoverCard() 互換の shape (`node` / `centerline` / `lane_centerline` / `route` /
      `reachable_edge`) を返す。`bindHoverSync(feature, layer)` が Leaflet layer に
      `mouseover` / `mouseout` を bind して hover card を更新し、`bindCommonPopups()` の先頭で
      呼ぶ。これで 2D マウスオーバーでも 3D と同じ hover card（Edge · Primary · 3 lanes,
      Node · T-junction など）が出るようになり、2D / 3D UX 対称性が揃う。
      空状態の hint も "Hover an edge or node (2D or 3D) …" へ更新。browser smoke に
      `hoverHitFromProps` 各 kind の出力検証 + setHoverCard(null) 復帰確認を追加。

  83. live reachability on click を map console に実装。
      `.bar` に `Reach` 予算 select（250/500/1000/2000 m、default 500）と
      `Reach from click` button を追加。button を押すと `reachSelectionMode = true` で次の
      node click が reachability start として解釈される。`reachableWithin(graph, start, budgetM,
      restrictions)` は既存 JS Dijkstra と同形式の directed-state heap loop + budget cap で
      reachable node cost と edge span（reachable_fraction + complete）を返し、partial edge は
      `clipLineToFraction()` で lon/lat polyline を長さ fraction で clip。
      `buildReachableFeatures()` が committed `reachable_paris_grid.geojson` と byte-互換な
      FeatureCollection（reachability_start / reachable_edge / reachable_node）を生成し、
      `drawDynamicReachability()` が 2D Leaflet + 3D scene + inspector `#stat-reach` を更新。
      dataset 切替で `setReachSelectionMode(false)` で cancel。browser smoke に reach-from-click
      → `onNodeClick("n191")` → status `^reach n191 \(500 m\)` + `#stat-reach > 0` + button が
      active を外れる assertion を追加。

  82. synthetic camera semantic overlay を Paris grid viewer に追加。
      `docs/assets/paris_grid_camera_detections.json` に hand-authored の 9 detection
      (traffic_light ×3 / speed_limit ×2 / stop_line ×2 / crosswalk ×2) を commit。
      `scripts/refresh_docs_assets.py` の Paris grid ブロックが `apply_camera_detections_to_graph`
      を通してから `export_map_geojson` を呼び、post-process で各 detection を edge 中の
      fraction 位置（traffic_light=0.92, stop_line=0.85, crosswalk=0.5, speed_limit=0.5）に
      Point feature として上乗せする。viewer `pointLayer` が 4 kinds に色分けしたマーカーを
      描画（traffic_light=赤+淡黄ring, stop_line=白+黒outline, crosswalk=青+白outline,
      speed_limit=黄+黒outline）、popup に kind / edge_id / confidence / source を表示。
      Leaflet legend と inspector stat `#stat-semantics` を追加。browser smoke に
      `stat-semantics >= 4` assertion。hero GIF / PNG 再生成で map 上に regulatory
      マーカーが乗った状態に。

  81. JS Dijkstra の route engine diagnostics を inspector `#engine-card` に表示。
      `dijkstra()` の heap loop に `popCount` / `expandedCount` / `pushCount` カウンタを追加し、
      return shape に `diagnostics: { engine: "dijkstra", heuristicEnabled: false,
      fallbackReason: null, expandedStates, queuedStates, popCount, edgeCount,
      restrictionsIndexed }` を付与。`drawDynamicRoute` が `renderRouteEngine(dij)` を呼び、
      inspector の `#engine-card` に badge（engine 名）+ expanded / queued / heap pops / TR
      indexed + hint（CLI route との関係）を表示。`clearRoute` → `clearRouteEngine()` で hide。
      Paris `n312 → n191` の deep link だと expanded states ≈ 679、queued ≈ 679、pops ≈ 679、
      TR indexed = 10。browser smoke は deep-link ケースに `#engine-card` visible + badge =
      "dijkstra" + expanded > 0 を追加。hero GIF を再生成（engine card が見える状態、3.6 MB）。

  80. map console の animated hero GIF を README / SHOWCASE に追加。
      `scripts/record_map_console_hero.py` が local http.server + Playwright CLI
      (`npx -y -p @playwright/test playwright test`) で `recordVideo` via chrome channel
      → WebM 取得 → ffmpeg palettegen/paletteuse で `docs/images/map_console_hero.gif`
      （720×420, 8 fps, 64 colors, 約 4.2 MB）を生成する。録画シナリオは Paris `n312 → n191`
      deep link で start → 2D soak 2.5s → 3D toggle + 4.2s auto-rotate。Playwright の ffmpeg
      を `npx playwright install ffmpeg` で落としておく必要あり。README "Visualization results"
      と SHOWCASE の先頭に GIF を embed し、ATTRIBUTION.md に由来を追記。

  79. OSM highway / lanes / maxspeed / name タグを centerline に注入して road-class 色分け。
      `scripts/refresh_docs_assets.py` に `_collect_osm_way_polylines` +
      `_inject_osm_tags_into_geojson`（point-to-polyline 距離 8 m で nearest-way match）を追加し、
      Paris grid GeoJSON の 1081 edges のうち 1080 edges に `highway` / `osm_lanes` /
      `osm_maxspeed` / `osm_name` / `osm_oneway` を stamp（residential 429, service 172,
      living_street 140, secondary 138, tertiary 99, primary 68, unclassified 31, primary_link 3）。
      Berlin Mitte も同じ helper を通る。`docs/js/map_console.js` に `HIGHWAY_COLORS` /
      `HIGHWAY_ORDER` / `HIGHWAY_LABELS` + `highwayCategory` / `highwayColor` /
      `highwayColorHexInt` を追加、`styleLine()` が centerline の fill を OSM class 色に、
      3D scene は Line material の color を class 色に、hover card は `Edge · Primary · 3 lanes` +
      maxspeed / name を表示、Leaflet popup にも highway ラベル / lane 数を追加。inspector に
      `#classes-card`（classes 数 · N/total tagged + per-class swatch + count）を追加。Leaflet
      legend も road class 9 色を追加。browser smoke に `#classes-card` / `#classes-list li >= 4`
      / `N classes · N/N tagged` assertion を追加。hero screenshots を再生成し、centerlines が
      住宅街（cyan）/ 幹線（amber）/ secondary（yellow）等で色分けされた状態。
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
- 生成したグラフ上で **ルーティング**（A* / Dijkstra + turn_restrictions + slope-aware +
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

- **CLI サーフェス（v0.7.2-dev 時点で 38 subcommands）**:
  - コア: `build`, `visualize`, `validate`, `enrich`, `stats`, `route`, `reachable`, `nearest-node`, `doctor`, `export-bundle`
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

- `routing.shortest_path`: `RoutePlanner` が graph/policy ごとの routing index、weighted adjacency、
  turn restriction policy、lane count を再利用し、`shortest_path(...)` は従来 API 互換の wrapper。
  straight-line node distance が weighted adjacency の lower bound として安全な場合は A*、それ以外は
  Dijkstra fallback。directed-state search (`node`, `incoming_edge`, `direction`)、
  v0.7 で `(node, incoming_edge, direction, lane_index)` まで拡張（`--allow-lane-change`）。
  `no_*` / `only_*` 両対応、同 edge 内 lane swap に `--lane-change-cost-m`（default 50 m）加算。
- `routing._core`: `shortest_path` と `reachability` が共有する internal core。Graph mutation
  signature / cached `RoutingIndex` / weighted adjacency / `TurnPolicy` をここに局所化し、
  route と service-area の cost semantics drift を防ぐ。
- **Uncertainty-aware (v0.6):** `--prefer-observed` / `--observed-bonus`（default 0.5）/
  `--unobserved-penalty`（default 2.0）/ `--min-confidence`（hd_refinement.confidence threshold）。
  `total_length_m` は常に実距離（重み付けコストではなく）。
- **Slope-aware (v0.7):** `--uphill-penalty` / `--downhill-bonus` multiplier。2D graph では
  slope_deg が無いので no-op。
- `routing.nearest_node`: lat/lon or meter-frame 座標から最寄りノードを snap。
- `routing.build_route_geojson` / `write_route_geojson`: 経路を LineString + per-edge +
  start/end Point の FeatureCollection に。
- `routing.reachability.reachable_within`: start node から cost budget 内の reachable node と
  directed edge span を返す。`route` と同じ turn restriction / observed / confidence / slope cost hooks を使い、
  `write_reachability_geojson` は partial edge を clipped LineString で出す。多数 query は
  `routing.reachability.ReachabilityAnalyzer` で routing index / weighted adjacency / policy を再利用する。
- CLI: `route`（id or `--from-latlon`/`--to-latlon`）、`reachable`（id or `--start-latlon`）、
  `--turn-restrictions-json`、`--output PATH.geojson`、`nearest-node`、`stats`。
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
  float32 trajectory 変換は opt-in prototype 済み（default は float64 維持、drift report は ↓ §5 参照）。

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
  `shortest_path_grid_120_functional`（55×55 grid 120 `shortest_path(...)` wrapper calls）/
  `shortest_path_grid_120`（55×55 grid 120 routes）/ `reachable_grid_120`
  （55×55 grid 120 service-area queries）/ `nearest_node_grid_2000`
  （300×300 node grid 2000 snaps）/ `map_match_grid_5000`
  （120×120 grid 5000 nearest-edge snaps）/ `hmm_match_bridge_500`
  （connected boundary HMM 500 samples + disconnected bridge distractors）/
  `hmm_match_long_grid_2000`（snake-grid HMM 2000 samples + disconnected alias edges）/
  `export_geojson_grid_120_compact`
  （120×120 grid compact GeoJSON export）/ `export_bundle_json_grid_120_compact`
  （120×120 grid compact bundle JSON writer）/ `export_bundle_end_to_end` の wall-time を計測。
  `--baseline docs/assets/benchmark_baseline_0.7.2-dev.json` で 3× 劣化時 exit 1。
  `--output PATH` で同形式の結果 JSON を保存可能。`docs/benchmarks.md` に baseline notes。
  `shortest_path_grid_120` は 1 つの `RoutePlanner` を 120 route query で再利用し、
  safe A* fast path 後の committed baseline は 0.601s。
  CI は opt-in（`workflow_dispatch`）。
- **PyPI scaffold:** `.github/workflows/pypi.yml`（`workflow_dispatch`, Trusted Publisher,
  secrets なし）**— § 2 の決定で inert 据え置き**。

### 3.11 可視化

- `docs/map.html` (Leaflet + OSM タイル): `paris_grid` (default) / `paris` / `osm` / `toy` の
  4 データセット切替。2D Leaflet view と Three.js 3D graph view を同じ GeoJSON payload から描画し、
  inspector に nodes / centerlines / lane boundaries / route / reachable spans / turn restrictions を表示。
  route / reachability / restrictions overlay toggle は 2D/3D 両方に反映される。
- **map console layout:** `body` は flex column、top `.bar` は wrap 可能な操作列、
  `.workspace` は map stage + inspector の 2-column grid。mobile (`max-width: 900px`) では
  top bar が縦に折り返し、dataset select は横幅内に閉じ、stage と inspector が 1-column で積まれる。
  mobile 390×844 で horizontal overflow が無いことを Playwright で確認済み。
- **2D view:** `#map` は既存 Leaflet instance。base layer、route overlay、
  reachability overlay、turn-restriction overlay は別 `L.layerGroup()` のまま維持。
  Overlay checkbox は Leaflet layer の add/remove と 3D rerender の両方を行う。
- **3D view:** `#scene3d` + `#scene3d-canvas` は hidden toggle で 2D と排他表示。
  Three.js は `https://unpkg.com/three@0.160.0/build/three.module.js` から dynamic import。
  3D state は `scenePayload = { base, route, reachable, restrictions }` と `activeStats` を読む。
  `render3DScene()` は centerline / trajectory / lane boundaries / route / reachable spans / graph nodes /
  route start/end / reachability start/nodes / restriction junctions / grid helper を同じ coordinate transform
  で描画する。`preserveDrawingBuffer: true` は browser smoke の WebGL pixel readback 用。
- **3D interaction:** canvas drag で yaw 回転、wheel で camera distance zoom。非 drag 中はゆっくり auto-rotate。
  resize は active 3D view の時だけ renderer/camera を更新する。status text は node/centerline 数を表示。
  `THREE.Raycaster` ベースの hover + click picking：centerline Line と node Points を
  `threeState.pickableLines` / `threeState.pickableNodePoints` に登録し、pointermove で `runHoverPick()`
  が `#hover-card` (Hovered kind / ID / length / endpoints) を更新する。ポインタが pickable に乗っている
  間は `hoverFreeze` で auto-rotate を pause。pointerdown → 4px 以上動く前に pointerup すれば click
  扱いで `handleScenePick()` を呼び、node なら既存 `onNodeClick(nodeId)` にチェーンして 2D と 3D の route
  overlay / inspector を同期。setView / show / render3DScene リビルド時に `setHoverCard(null)` +
  `lastHoverKey = null` で古い hover 状態をリセット。
- **Deep link + route steps:** `docs/map.html?from=nXXX&to=nYYY[&dataset=...][&view=3d]` で bootstrap 時に
  `dijkstra()` を直接再計算して `drawDynamicRoute` に流す。`drawDynamicRoute` / `clearRoute` は
  `history.replaceState()` で URL の `from` / `to` を同期、任意の route を URL コピペで共有できる。
  inspector 右側の `#steps-card` には `renderRouteSteps(graph, dij)` が edge_id / direction /
  length / cumulative_m + 合計 edges / m を埋めるので、routing 結果を 3D 視覚と JSON 以外の第三の形で
  読み取れる。`clearRouteSteps()` は `Clear route` または dataset 切替で自動実行。
  `applyDeepLinkRoute()` は 2D 地図を route bounds に自動 `map.fitBounds`（padding 48、maxZoom 17）。
- **Route export:** `.bar` の `Download route GeoJSON` ボタン（route drawn 時のみ enable）が
  `scenePayload.route` を `application/geo+json` Blob でクライアント download。
  filename は `route_<dataset>_<from>_<to>.geojson`。ナビ診断 / route diff / CI サンプルに使える。
- **Hero screenshot deep-link bake:** `scripts/render_map_console_screenshot.py --from-node / --to-node`
  default が `n312 → n191` なので、README / SHOWCASE の committed PNG は常に Paris TR-aware route が
  見えた状態で再生成される。
- **dynamic route sync:** `drawDynamicRoute(graph, dij)` は Leaflet polyline だけでなく
  `scenePayload.route` の GeoJSON FeatureCollection も作る。これにより node click routing 後に
  3D view へ切り替えても同じ route が表示され、inspector の route metric も `dij.totalLength` で更新される。
  `clearRoute()` は Leaflet overlay と `scenePayload.route` の両方を clear し、active 3D view なら rerender。
- **CDN / network caveat:** local preview でも Leaflet CSS/JS、Three.js module、OSM tiles は外部 fetch。
  private repo のローカル demo としては許容。public launch で安定性を上げるなら、Leaflet / Three.js を
  vendored asset にするか、3D smoke を CDN 非依存の最小 harness に切り出す。
- **committed regression boundary:** JS Dijkstra は `tests/test_viewer_js_dijkstra.py` +
  `tests/js/test_viewer_dijkstra.mjs` が `docs/map.html` から `buildRestrictionIndex` / `dijkstra` を抽出する。
  そのためこの 2 関数名と抽出しやすい top-level function shape は維持すること。
  Full browser smoke は `tests/test_map_console_browser_smoke.py` + `tests/js/map_console_smoke.spec.mjs`
  として committed 済み。`@pytest.mark.browser_smoke` で default `pytest` からは除外、
  `make viewer-smoke` / `pytest -m browser_smoke` で opt-in 実行、node / npx / system Chrome が無ければ skip。
  アサートは paris_grid inspector counts / 3D `#scene3d-canvas` の `readPixels` 非ゼロ /
  `#scene3d-status` に "node" 含む / mobile 390×844 の horizontal overflow 無し。
- **manual browser smoke recipe:** 8765 が埋まっていたら別 port を使う。
  2026-04-23 は 8765 が使用中だったため 18765 を使用した。

  ```bash
  cd docs
  python3 -m http.server 18765
  # 別 shell:
  MAP_URL=http://127.0.0.1:18765/map.html \
    npx -y -p @playwright/test \
    sh -c 'export NODE_PATH=$(dirname $(dirname $(which playwright))); playwright test <tmp-spec> --browser=chromium --workers=1'
  ```

  `<tmp-spec>` では `test.use({ channel: "chrome" })` を使う。専用 Playwright Chromium が
  `~/.cache/ms-playwright` に無くても `/usr/bin/google-chrome` で動く。検証項目は
  desktop/mobile、2D load、dynamic route、3D status、canvas pixel nonblank、overlay toggle、
  horizontal overflow なし。
- `docs/images/paris_grid_route.svg`: README / Pages 用の静的 preview。`map_paris_grid.geojson` +
  `route_paris_grid.geojson` + `paris_grid_turn_restrictions.json` から
  `scripts/refresh_docs_assets.py` で再生成。OSM attribution を SVG 内と `docs/assets/ATTRIBUTION.md`
  に保持。
- `docs/images/map_console_2d.png` / `docs/images/map_console_3d.png`: README / SHOWCASE 用の
  map-console hero screenshot。`docs/map.html` は `?view=2d|3d` と `?dataset=…` URL param を受け付け、
  ローディング完了時に `document.body.dataset.ready` を立てる。
  `scripts/render_map_console_screenshot.py` が `docs/` を `http.server` で serve し、
  `npx -y -p @playwright/test playwright screenshot --channel chrome --viewport-size 1600,900
  --wait-for-selector "body[data-ready]" ...` で両 view を撮り、PIL 256-color quantize で
  2 MB → 667 KB (2D) / 184 KB → 77 KB (3D) に圧縮。OSM tiles / Leaflet / Three.js は外部 fetch なので
  ネットワーク前提。regeneration 時に OSM tile が変わると PNG も変わる点だけ注意。
- `docs/images/route_diagnostics_compare.png`: README / Showcase 用の route explain 比較 screenshot。
  `docs/route_diagnostics_preview.html` を headless Chrome で描画する
  `scripts/render_route_diagnostics_screenshot.py` で再生成。元データは
  `docs/assets/route_explain_sample.json`。
- `docs/index.html` は従来の SVG diagram viewer の下に `paris_grid_route.svg` の result card と
  post-release metric cards を表示。metric labels / responsive grid / focus states は
  `docs/css/viewer.css` に集約。README も同じ SVG を `Visualization results` として embed し、
  `docs/map.html` へリンクする。
  現 repo は private のまま維持する方針で、現在の GitHub plan では private repo Pages が作れない
  ため、README は `cd docs && python3 -m http.server 8765` のローカル preview を primary にしている。
  `http://127.0.0.1:18765/` の local server smoke で index/CSS/JS/SVG asset load を確認済み。
- **click-to-route UI:** ノード 2 つをクリックすると JS 側 directed-state binary-heap Dijkstra
  が `(node, incoming_edge, direction)` 状態で `no_*` / `only_*` 制限を honor。"Clear route"
  button + status 行。生成 route は Leaflet layer だけでなく 3D preview payload にも同期する。
  各 centerline feature は `start_node_id` / `end_node_id` / `length_m` 保持。
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

- **v0.7.1 (2026-04-21):** v0.7.0 後の validation / docs / release-hardening patch。
  accuracy refresh、Berlin tuning、float32 drift compare + memory profiles、release bundle byte gates、
  CLI boundary split、README/docs visualization polish を含む。
  GitHub Release: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.7.1
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
cards、release byte gates、manifest policy docs polish、README measured-results compacting は
`v0.7.1` 下。

---

## 5. Open tasks（次に触れる候補）

優先度順。各タスクに **手をつける前のヒント** を付けてある。

### 5a. V3 float32 trajectory 最適化（DONE for now／default float64 維持）

- **背景:** v0.7 で `export_lanelet2` DOM rewrite が peak RSS を -10% したが、trajectory 配列の
  default float32 化はまだ。**byte-identity を破る** ので単純 swap 不可。
- **設計メモ:** [`docs/handoff/float32_trajectory.md`](./handoff/float32_trajectory.md) 作成済み。
  結論は「default float64 維持 + opt-in float32 prototype + drift 計測」。`Trajectory.timestamps`
  と `Trajectory.z` は float64 のまま、まず `Trajectory.xy` のみを候補にする。
- **prototype:** `load_trajectory_csv(..., xy_dtype="float32")`、`BuildParams(trajectory_xy_dtype=...)`、
  trajectory CSV 系 CLI の `--trajectory-dtype {float64,float32}`、`scripts/profile_memory.py
  --trajectory-dtype` を追加。default は `float64` のまま。
- **実測:** [`docs/float32_drift_report.md`](./float32_drift_report.md) 作成済み。Paris 800-row で
  tracemalloc -6 KB / max graph drift 0.00014 m、Berlin 7,500-row で loader allocation -60,000 B /
  max graph drift 0.00072 m。1M synthetic では loader allocation -8,000,000 B /
  tracemalloc peak -19,531 KB だが、full export peak RSS は -2,680 KB に留まった。
  OSM public-trace replay では 500k load-only `Trajectory.xy` -4,000,000 B、75k full export
  peak RSS -4,044 KB、ただし edge / Lanelet ID drift あり。
  default flip の根拠にはしない。
- **再現 script:** `scripts/compare_float32_drift.py` が float64 / float32 bundle を作り直し、
  graph / sd_nav / GeoJSON / Lanelet2 OSM の topology と coordinate drift を比較する。
  `--fail-on-topology-change` と `--max-coordinate-drift-m` で release-gate 風に使える。
- **設計の勘所:**
  - どこで float64 が伸びるか: `io.trajectory.loader::Trajectory.xy`, `pipeline.build_graph` 内の
    numpy 配列、`routing.shortest_path` の内部距離計算など。
  - byte-identity への影響: `export-bundle` の `sim/road_graph.json` に保存される polyline の
    末尾桁が変わる可能性。どこまで tolerance を緩められるか（schema は float で decimal 精度制約なし）
    を決める必要あり。
  - regression test: `tests/test_release_bundle.py` が stable generated files を byte-for-byte で
    frozen bundle と比較する。manifest は version / generated_at のみ normalize して比較する。
- **やり方:**
  1. ~~design memo を `docs/handoff/` に書く~~（完了）
  2. ~~opt-in prototype（loader + `BuildParams` + CLI/profile flag）~~（完了）
  3. ~~`scripts/profile_memory.py` を float64/float32 両方で実測~~（完了）
  4. ~~one-off drift 比較を `scripts/compare_float32_drift.py` にする~~（完了）
  5. ~~1M-row synthetic workload で RSS に効くかを見る~~（完了、RSS への効果は小）
  6. ~~default path の stable export artefacts を byte-identical gate 化~~（完了）
  7. ~~OSM public-trace replay で RSS に効くかを見る~~（完了、RSS への効果は小、ID drift あり）
  8. より大きい real-world city-scale workload は、default flip を再検討する前提が出た時だけ追加する。
- **規模感:** 今すぐ必要な small docs blocker は無し。raw 500k+ 実走 trajectory が来たら true large benchmark。

### 5b. 次のおすすめ候補（small／選択式）

今すぐ必要な blocker は無し。benchmark suite は committed baseline JSON まで整備済みで、
repeated shortest path は `RoutePlanner` 化、repeated reachability は analyzer 化済み。
routing / reachability の core cost-policy layer も分離済み。
code commit `342f61f` の release bundle / package build dry-run は PASS
（ただし `Metadata-Version: 2.4` 対応のため `twine>=6` で確認する）。
2026-04-23 の map console 作業はすでに origin/main に載っており、CI / Pages も green。
ただし README/SHOWCASE に埋め込む静的 hero 画像はまだ旧 `paris_grid_route.svg` 中心。
次に触るなら以下の順が現実的。

1. **README / Showcase に map-console screenshot を載せる** — ~~DONE 2026-04-24~~ (refresh: deep-link bake)。
   `docs/map.html` に `?view=2d|3d` / `?dataset=…` / `?from=nXXX&to=nYYY` URL param + `body[data-ready]`
   ready signal を追加。`scripts/render_map_console_screenshot.py` は default `--from-node n312
   --to-node n191` を焼き込んで、committed PNG には Paris TR-aware route + Route steps card +
   Download route GeoJSON ボタンが常に載る。PIL 256-color quantize で圧縮（2D ≈ 400 KB、3D ≈ 85 KB）。
   README "Visualization results" と `docs/SHOWCASE.md` に両 PNG を embed 済み。再生成は OSM tiles /
   Leaflet / Three.js 外部 fetch 必要な点を docstring / README に明記。
2. **Optional browser smoke をテスト化** — ~~DONE 2026-04-24~~。
   `tests/js/map_console_smoke.spec.mjs` + `tests/test_map_console_browser_smoke.py` が
   `@pytest.mark.browser_smoke` で opt-in。`make viewer-smoke` = `pytest -m browser_smoke`。
   desktop 2D (paris_grid inspector counts > 500 + restrictions ≥ 5) / desktop 3D (WebGL
   `readPixels` が 0 でない + `#scene3d-status` に "node") / mobile 390×844 (horizontal overflow 無し)
   の 3 assertion。default `pytest` は `not browser_smoke` で excluded。node / npx / system Chrome
   不在時は skip、3 連続 run で stable（6.9s–8.7s）。
3. **3D viewer の product interaction を深める** — ~~partial DONE 2026-04-24~~。
   `docs/map.html` の inline script を `docs/js/map_console.js` に分離 + `THREE.Raycaster` で
   centerline edge / graph node の hover + click picking を実装。inspector 右側の `#hover-card` に
   kind / id / length / endpoints を表示、auto-rotate はポインタが pickable に乗ると pause、
   pointerup (drag 無し) は既存 `onNodeClick(nodeId)` を呼ぶので 2D/3D 両方に route が同期する。
   deep link `?from=nXXX&to=nYYY` + `history.replaceState` による URL 同期、`#steps-card` に
   route edge list (edge_id / direction / length / cumulative) を表示する機能も追加済み。
   まだ未実装: route step highlight（経路上の edge を順番に強調 / 動画化）、edge cost coloring
   （observed / slope / confidence などを 3D 上で色分け）、camera pose の保存 / pose deep link、
   lane-level 表示、同じ raycaster を 2D Leaflet layer に拡張する仕組み。
4. **Viewer asset vendoring / offline stability** — public launch 前の安定化候補。
   Leaflet / Three.js / OSM tiles は現状 network 依存。private local demo では許容だが、
   release-quality demo としては vendored Leaflet/Three、または static screenshot fallback を検討。
   OSM tiles の大量同梱は license / attribution / size の問題があるため、tile vendoring は原則避ける。
5. **True large real-world memory / export benchmark** — raw 500k+ 実走 trajectory が手元に来た時だけ実行。
   今の `/tmp` OSM public replay では default float32 flip の根拠にならない。
6. **Public launch** — user が repo public 化を明示した時だけ、visibility / Pages / launch post を実行。
   投稿文は `docs/LAUNCH.md`、showcase 導線は `docs/SHOWCASE.md`。private repo のまま Pages を再試行しない。
7. **Release tag prep** — user が release tag を明示した時だけ実行。
   `v0.7.2.dev0` のまま tag を切らない。release 前は version bump、CHANGELOG cut、release bundle、
   package build、twine>=6 check、manifest/sd_nav/road_graph validation をやり直す。

### 5c. 2D/3D map product の現状評価

- **できている:** Paris OSM-grid graph を 2D OSM 上で inspection できる。TR-aware click-to-route、
  500 m reachability、turn restriction markers、route/reachability/restriction toggles、dataset metrics、
  3D graph preview が同じ `docs/map.html` で動く。mobile でも操作面は破綻しない。
- **まだ「完成プロダクト」ではない:** 3D view は geometry preview であり、3D 上で edge/node を選択する
  picking は無い。route step の個別 inspect、edge cost coloring、lane-level view、camera pose 保存、
  permalink、offline demo、committed browser smoke は未実装。
- **価値判断:** いま star を増やす目的なら、次は algorithmic core より screenshot / demo narrative の方が効く。
  ただし user が「性能・本質価値」を求める時は、3D picking や route replay のように graph semantics が
  見える機能へ進むのが自然。単なる色替えや landing page 追加は優先度低い。

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
- テスト: `pytest` で 647 passed / 3 skipped / 4 deselected が baseline。
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
| Routing (A* / Dijkstra, reachability, nearest, route geojson, lane-change) | `roadgraph_builder/routing/`（core は `routing/_core.py`） |
| HD enrich / LiDAR fusion / lane inference / refinement | `roadgraph_builder/hd/` |
| Incremental build (`update-graph`) | `roadgraph_builder/pipeline/incremental.py` |
| Batch (`process-dataset`) | `roadgraph_builder/cli/dataset.py` |
| LAS / LAZ I/O (2D + 3D) | `roadgraph_builder/io/lidar/{las.py,points.py,lane_marking.py}` |
| Camera projection + lane detection | `roadgraph_builder/io/camera/{calibration,projection,pipeline,lane_detection}.py` |
| OSM ingest / turn_restrictions convert | `roadgraph_builder/io/osm/{graph_builder.py,turn_restrictions.py}` |
| Lanelet2 export + validators | `roadgraph_builder/io/export/{lanelet2.py,lanelet2_tags_validator.py,lanelet2_validator_bridge.py}` |
| Graph stats / junction topology | `roadgraph_builder/core/graph/stats.py`, `roadgraph_builder/pipeline/junction_topology.py` |
| CLI | `roadgraph_builder/cli/main.py` dispatcher + `cli/{build,validate,routing,export,camera,lidar,osm,guidance,trajectory,hd,incremental,dataset}.py` |
| Schemas | `roadgraph_builder/schemas/*.schema.json` |
| Validators | `roadgraph_builder/validation/*.py` |
| Viewer | `docs/index.html`, `docs/map.html`, `docs/assets/`, `docs/images/` |
| CI / Release / PyPI | `.github/workflows/*.yml` |
| Scripts (fetch, tune, demo, benchmark, profile, accuracy, float32 drift compare) | `scripts/` |

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

- [ ] `pytest` が 647 passed / 3 skipped / 4 deselected で通ること（上下 ±1 は OK、大きく減ったら
      skip 理由を確認）。
- [ ] `CHANGELOG.md` の `[Unreleased]` にユーザー向け変更を足すこと。
- [ ] スキーマ変更時は対応する `validate_*` と CI の expectation を同時更新すること。
- [ ] 機密（IMEI、キー、生ダンプ）は **コミットしない** こと。Overpass raw JSON は `/tmp`。
- [ ] `docs/PLAN.md`（このファイル）の §3 "確認済み" と §5 "Open tasks" を作業後に同期すること。
- [ ] `git push` は user から `push!` 等の明示 authorize を受けてから実行すること。

---

## 11. 一行で言うと

> **v0.7.1 shipped 済み、main は 0.7.2.dev0 で reopen 済み。v0.7.0 は全部シップ済み、直近 workstream（accuracy / completions / tuning / visual preview /
> CLI boundary split / release surface docs / float32 drift compare script / 1M synthetic memory
> profile / OSM public-trace replay profile / release bundle byte + normalized-manifest gate +
> manifest policy docs polish / README measured-results compacting）も 0.7.1 に切り出し済み。
> Release assets は download/checksum/validate 済み。packaging metadata は SPDX license 表記へ更新済み。
> GeoJSON large export compact path と compact bundle JSON writer も landing 済み。2D/3D map console も
> main に載っており、CI / Pages success まで確認済み。`reachable` service-area
> CLI と Paris docs overlay、`reachable_grid_120` benchmark coverage、committed benchmark baseline JSON、
> reachability analyzer perf、routing core split、RoutePlanner perf、GitHub star-growth surfaces、launch kit docs、safe A* routing も追加済み。code commit `342f61f` の release bundle / package build dry-run は PASS
>（`twine>=6` で確認、PyPI 公開は skip）。Claude が次に触るなら、README/SHOWCASE に map-console screenshot を
> 置くか、browser smoke の opt-in test 化が自然。raw large trace が来た時だけ true large benchmark。
> 何を削って何を広げたかは
> `CHANGELOG.md` と §3 の小節を見れば全部わかる。push / tag / AI マーカー / PyPI /
> Mapillary は全部 user authorize か No 決定済みなので、勝手に提案しないこと。**

---

*このファイルを更新したら: §3「確認済み」と §5「Open tasks」の整合を取り、先頭の
"最終更新" 日付を直すこと。*

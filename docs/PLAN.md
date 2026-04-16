# roadgraph_builder — 開発計画・引き継ぎメモ

Codex / 次のセッション向け。**事実と意図を分けて**書く。

## スコープ（意図）

- 軌跡 CSV（`timestamp, x, y`）から **道路グラフ**（ノード／エッジ＋中心線）を構築し、**ナビ SD シード**・**シミュ用 GeoJSON**・**Lanelet 互換 OSM** を **`export-bundle`** で一括出力する。
- **HD** は「測量完成品」ではなく、enrich による **HD-lite 帯**、LiDAR／カメラは **段階的**（スタブ含む）。

## 確認済み（事実）

- CLI: `build`, `visualize`, `validate`, `validate-detections`, `validate-sd-nav`, `validate-manifest`, `validate-turn-restrictions`, `enrich`, `fuse-lidar`, `apply-camera`, `export-lanelet2`, `export-bundle`, `doctor`。
- `export-bundle` → `nav/sd_nav.json`, `sim/{road_graph.json,map.geojson,trajectory.csv}`, `lanelet/map.osm`, `manifest.json`。
- **sd_nav**: `allowed_maneuvers`（digitized 終端ノード）と **`allowed_maneuvers_reverse`**（始端・逆走）を **2D 交差点ヒューリスティック**で付与（`roadgraph_builder/navigation/sd_maneuvers.py`）。
- **ナビ規制の前提**: `allowed_maneuvers` は **規制なしの幾何ヒント**。ターン禁止は別レイヤー `turn_restrictions` として `sd_nav.schema.json` に optional 統合済み（設計メモ: `docs/navigation_turn_restrictions.md`）。
- **turn_restrictions 生成**: `export-bundle --turn-restrictions-json` と camera detections の `kind: "turn_restriction"` から `sd_nav.turn_restrictions` を end-to-end で生成（`roadgraph_builder/navigation/turn_restrictions.py`）。manifest に `turn_restrictions_json` / `turn_restrictions_count` を記録。
- **HD**: `enrich_sd_to_hd` が `metadata.sd_to_hd` に **`navigation_hints`**（`sd_nav` 参照）を含める。
- **検証**: JSON Schema（road_graph / camera_detections / sd_nav / manifest）。CI で bundle 検証あり。
- **UX**: 空グラフは `ValueError`、CLI は欠落ファイル・検証エラーを **終了コード 1** で明示。
- **チューニング**: `docs/bundle_tuning.md`、`make tune` / `scripts/run_tuning_bundle.sh`。

## 未確認・要フォロー

- 実走データ（投影済み xy）での **パラメータ最適**（`max-step-m` 等）はデータ依存。**`make tune`** で繰り返し確認する運用が推奨。
- LiDAR **LAS/LAZ** はスタブ。カメラ **生画像→投影** は未実装。

## 次の優先（提案・意図）

優先度はリポジトリの目的に合わせて差し替え可。

1. **実データ1本**で `export-bundle` → `sim/map.geojson` を見てパラメータを記録（`docs/bundle_tuning.md` 参照）。
2. **ナビ**: `turn_restrictions` を実データ／手編集／camera detections から生成する入口を設計・実装する。
3. **HD**: 点群 CSV で `fuse-lidar` を実データ検証。カメラ detections を本番に近い JSON で通す。
4. **配布**: サンプルバンドル固定・タグ付きリリース、PyPI は任意。

## 主要パス

| 領域 | パス |
| --- | --- |
| Bundle / sd_nav | `roadgraph_builder/io/export/bundle.py` |
| Maneuvers | `roadgraph_builder/navigation/sd_maneuvers.py` |
| HD enrich | `roadgraph_builder/hd/pipeline.py` |
| CLI | `roadgraph_builder/cli/main.py` |
| Schemas | `roadgraph_builder/schemas/*.schema.json` |
| CI | `.github/workflows/ci.yml` |

## 開発コマンド（リポジトリルート）

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
make test
make tune    # bundle + validate（パラメータ探索用）
make demo    # detections 付きフルデモ
```

## Codex への引き継ぎチェックリスト

- [ ] `main` の `pytest` が通ること。
- [ ] `CHANGELOG.md` の `[Unreleased]` にユーザー向け変更を足すこと。
- [ ] スキーマ変更時は **対応する `validate_*` と CI** を更新すること。
- [ ] 機密（IMEI、キー、生ダンプ）は **コミットしない**こと。

## Codex 向け実装プロンプト（hand-off）

そのまま `codex` に投入できるよう、優先項目ごとに詳細指示を切り出して保存している。

- 優先 2（turn_restrictions 生成入口）: [`docs/handoff/turn_restrictions.md`](./handoff/turn_restrictions.md)
- 優先 4（配布・タグ付きリリース）: [`docs/handoff/release_distribution.md`](./handoff/release_distribution.md)

優先 1（実データでの `max-step-m` 等の調整）と優先 3（LAS/LAZ・カメラ生画像）は実走データに依存するため、まず手元データ＋`make tune` を回してから Codex に渡すこと。

### 次セッションの進め方

**Claude Code の nested サンドボックス内では `codex exec --full-auto` が bwrap-in-bwrap で詰む**ことが確認された（`RTM_NEWADDR: Operation not permitted`）。さらに Claude 側の safety rule が `--full-auto` / `-s danger-full-access -a never` / 自己 settings 変更をいずれもブロックする。

推奨フロー:

1. この Claude セッションを一度リセット（`/clear` or 新ウィンドウ）。
2. **Claude の外側のターミナル**から（または Codex 単独で動かせる別セッションから）次を実行:
   ```bash
   cd /media/sasaki/aiueo/ai_coding_ws/roadgraph_builder
   git switch -c feat/turn-restrictions  # optional
   codex exec --full-auto - < docs/handoff/turn_restrictions.md
   ```
3. 完了したら `PYTHONPATH=. PYTHONNOUSERSITE=1 .venv/bin/python -m pytest -q` で緑を確認し、`CHANGELOG.md [Unreleased]` を更新、この PLAN.md の「確認済み」を同期。
4. 次に優先 4 の hand-off を同じ手順で流す。

Codex が完了した時点で Claude を再起動し、「turn_restrictions / 配布 は完了。次は優先 3（実 LiDAR 検証）の設計」等、次ステップを指示すれば続きに入れる。

---

*最終更新: 作業セッションで `docs/PLAN.md` を編集したら、この冒頭の「確認済み」を同期すること。*

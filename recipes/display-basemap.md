# 按视角批量生成底图包（gis-composer → gis-kit → gis-composer）

一个项目里每张图、每个面板的比例尺和范围都不同，底图（陆地、行政区面）要按各自的视角概括，否则小比例尺下满是碎岛和描边。流程分三段：gis-composer `inspect` 报告每个面板的视角，gis-kit `display-vector.py` 为每个视角生成一个底图包，Agent 把包写回地图清单的 `context.display`。三段之间只交换文件（[display-vector](../contracts/README.md#display-vector) v1），都在同一个[项目目录](../contracts/README.md#project共用项目目录)里。编排由 Agent 负责，不经过任何调度器。

## 前提

- 一份 EPSG:4326 的面数据作底图，例如 OSM 陆地多边形或 GADM 某一级；带一个在视角内唯一的 id 字段。数据太大时先用 gis-kit 裁到项目范围，发布到 `inputs/`。
- 地图清单已能编译：范围由 `bounds`、`fit` 或编码块的数据决定，`layout` 的画幅（或 `widthCm`）已定。画幅变了视角就变，所以先定版式，再做底图。

## 步骤

```bash
# 1. gis-composer：取每个面板的视角（清单里还没有 context.display，或引用的包仍在）
node "$GIS_COMPOSER_HOME/src/cli.js" --project /absolute/project inspect maps/site.map.json

# 2. gis-kit：每个不同的视角生成一个底图包（目录必须是新的）
"$PY" "$GIS_SKILL/scripts/display-vector.py" --source /absolute/project/inputs/land/land.geojson \
  --id-field land_id --view '<第 1 步该面板的 view>' --attribution "<数据署名>" \
  --cache /absolute/cache/display-vector --output /absolute/project/inputs/display/land-site

# 3. Agent：把包写进该面板的 context.display（见下），再检查并出图
node "$GIS_COMPOSER_HOME/src/cli.js" --project /absolute/project inspect maps/site.map.json   # lint 不应再有 DISPLAY_VECTOR_*
node "$GIS_COMPOSER_HOME/src/cli.js" --project /absolute/project render maps/site.map.json
```

第 1 步的输出里，`maps[0].panels[]` 每项有 `id` 和 `view`（`center`、`zoom`、`width`、`height`、`tileSize`）。单图只有一个面板，`id` 就是地图 id；多面板图的面板 id 为 `<地图>-<面板>`。`view` 原样传给 `--view`，不要改写数值。

第 3 步只改 `context` 里的 `display`，其余设置（`lines`、`labels` 等）保留：

```json
{ "kind": "map", "id": "site", "layout": { "type": "single", "widthCm": 16, "aspect": 1.4 },
  "context": { "display": "../inputs/display/land-site",
    "lines": [{ "data": "../inputs/site/boundary.geojson", "role": "unit-outline" }] },
  "encodings": [{ "encoding": "focus", "id": "site", "data": "../inputs/site/sites.geojson", "legend": "研究地块" }] }
```

（示例在仓库外的项目里实测：写回前后 `inspect` 的 zoom 相同，lint 无告警，出图通过。）

- 单图写在顶层的 `context`；多面板图写在各面板 `composition.context`。各面板视角相同时（如共用 `composition` 的 grid 小多图，inspect 给出的 view 都一样），只生成一个包，写在共用的 `composition.context`。
- `context.display` 不参与范围推导，写回后视角不变；第 3 步的 `inspect` 报出的 zoom 应与第 1 步相同。
- 专题数据也可以按同一视角做成包（`--fields` 保留要用的字段），在编码块的 `data` 里引用，描边就只画公共边。

## 要做的判断

- **何时重做**：改了 `bounds`、`fit`、画幅、`widthCm` 或留白，视角就变了。`inspect` / `compose` 的 lint 会报 `DISPLAY_VECTOR_SCALE_MISMATCH`（缩放差超过 0.1）或 `DISPLAY_VECTOR_EXTENT`（画面超出包的范围），这时回到第 1 步。
- **新目录，不覆盖**：`inputs/` 下的成果不覆盖，重做时换一个新目录名（如加 `-v2`），清单改指新目录；旧目录确认没有引用后再删。不要在第 1 步之前删掉清单正引用的包，否则 `inspect` 报 `DISPLAY_VECTOR_UNREADABLE`。`--cache` 让视角没变的面板直接命中缓存。
- **哪些面板要包**：概括只对比例尺小、边界细碎的面板有意义。大比例尺的放大面板，底图数据本身就不碎时可以直接用原数据。
- **署名与口径**：`--attribution` 写进包的清单，Composer 写进来源行；OSM 数据注明 ODbL。国界口径取决于源数据，概括不改变口径。
- **检查**：看 `display-vector.json` 的 `counts.units_dropped` 和 `warnings`，必须出现的单元用 `--keep` 保留；再看出图的 QA。

## 不在范围

分面模板（`each`）展开的面板共用一份组合模板，各面板视角不同时无法逐面板写不同的包。区位逐级放大图用 admin-chain 自带的显示简化，见 [location-chain.md](location-chain.md)。

## 为什么是配方，不是一条命令

这一步横跨两个引擎：视角来自 gis-composer，概括由 gis-kit 完成，写回的是 Agent 维护的地图清单。引擎之间不互相调用 CLI（[boundaries.md](../docs/boundaries.md#1-三层结构)），gis-kit 也不读写地图清单，所以任何一个引擎单独都做不完这件事，外壳也不建调度器。项目里反复要写的胶水只是一个循环；以后若想省掉它，可以在引擎侧各做一半（例如 gis-kit 直接读 `inspect` 的输出、为每个不同视角各出一个包），写回清单仍由 Agent 做。

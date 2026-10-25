# 区位逐级放大图（gis-kit → gis-composer）

从世界到场地逐级放大的区位图：世界 → 国家 → 省 → 市 → … → 场地。分两段：gis-kit 取各级行政区，gis-composer 用 sheet 组合排版出图。两段之间只交换文件（[admin-chain](../contracts/README.md#admin-chain) v1）。编排由 Agent 负责，不经过任何调度器。

Composer 里没有"区位图模板"。这类图是一种版面结构（`row`：小图并排，用放大镜线串起来），再往里绑一串范围。同一份数据也可以换成 `hero`：大图画场地，内嵌一张定位小图。

## 前提

- 本机有 GADM 式分级 GeoPackage：每级一个图层 `ADM_n`，带 `GID_n` / `NAME_n` 字段，CRS 为 EPSG:4326。
- Composer 项目映射了 `basemap` 数据根，指向 `gadm-global-context.pmtiles`。用 `project status` 检查。

## 步骤

```bash
# 1. gis-kit：把各级行政区发布到项目 inputs/（目录必须是新的）
"$PY" "$GIS_SKILL/scripts/admin-chain.py" --source /absolute/gadm_410-levels.gpkg \
  --point 2.2945,48.8584 --levels 0,1,2,3 --site-label "Eiffel Tower" --output /absolute/project/inputs/site-chain

# 2. Agent：读 inputs/site-chain/chain.json，写 sheet 组合 inputs/site-chain.sheet-composition.json
#    （以 gis-composer 的 examples/sheets/paris-chain.sheet-composition.json 为样子，换成本次各级的 bounds）

# 3. gis-composer：生成 Sheet 与各面板 Scene，渲染并 QA
node "$GIS_COMPOSER_HOME/scripts/compose-sheet.js" --project /absolute/project inputs/site-chain.sheet-composition.json
node "$GIS_COMPOSER_HOME/src/cli.js" --project /absolute/project qa scenes/<id>.sheet.json
```

第 2 步写的每个面板是一份普通组合：

- 范围：`bounds` 取清单里该级的 `bounds`；世界面板用 `[-180, -56, 180, 78]`。
- 本级轮廓与下级界线：`context.lines`，界线按 `["==", ["get", "parent"], "<本级 key>"]` 过滤，轮廓按 `["==", ["get", "key"], "<本级 key>"]` 过滤。
- 突出下一级：`focus` 块，按 `["==", ["get", "key"], "<下一级 key>"]` 过滤。
- 场地：最后一个面板用 `network` 块的点（过滤 `key == "site"`），再加一个 `callout` 注记；场地是面时，改用 `focus` 块。

## 要做的判断

- **级数**：常用 `0,1,2`（国家、省、市），场地在城区时再加一级。下一级数据过粗或缺失时少用一级。GADM 中国 ADM_3 把广州市区几个区合成了一个单元，就是一例。
- **版面**：要表达逐级放大关系，用 `row` + `links: "chain"`；要突出场地本身，用 `hero`，内嵌小图设 `link: "locator"`；要对比几个场地，用 `grid`。
- **名称与口径**：显示名在 `--labels` 或组合的面板 `label` 里给出。在中国境内出图时，用 `--adm0-layer ADM_0_cn_review_full` 选择审图口径的国界，组合里写 `gadm: {chinaReview: true}`，并在来源行注明。
- **检查**：打开 `runs/<run-id>/output/<id>.png`，看 `qa/<id>.qa.json` 和各面板的 QA；用 `rerun <run-id>` 逐字节复核 Sheet 与每个面板。

## 不在范围

影像底的场地区位图和影像时间序列，要先定影像来源与授权（见 gis-composer #8 形式 2、3）。

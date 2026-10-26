# 区位逐级放大图（gis-kit → gis-composer）

从世界到场地逐级放大的区位图：世界 → 国家 → 省 → 市 → … → 场地。分两段：gis-kit 取各级行政区，gis-composer 按地图清单出图。两段之间只交换文件（[admin-chain](../contracts/README.md#admin-chain) v1），都在同一个[项目目录](../contracts/README.md#project共用项目目录)里。编排由 Agent 负责，不经过任何调度器。

Composer 里没有"区位图模板"。这类图是一种版式（`row`：小图并排，用放大镜线串起来），再用分面把各级数据绑进去。同一份数据也可以换成 `hero`：大图画场地，内嵌一张定位小图。

## 前提

- 本机有 GADM 式分级 GeoPackage：每级一个图层 `ADM_n`，带 `GID_n` / `NAME_n` 字段，CRS 为 EPSG:4326。
- Composer 项目映射了 `basemap` 数据根，指向 `gadm-global-context.pmtiles`。用 `project status` 检查。

## 步骤

```bash
# 1. gis-kit：把各级行政区发布到项目 inputs/（目录必须是新的）
"$PY" "$GIS_SKILL/scripts/admin-chain.py" --source /absolute/gadm_410-levels.gpkg \
  --point 2.2945,48.8584 --levels 0,1,2,3 --site-label "Eiffel Tower" --output /absolute/project/inputs/site-chain

# 2. Agent：读 inputs/site-chain/chain.json 核对级数与名称，写地图清单 maps/site-chain.map.json（见下）

# 3. gis-composer：编译、渲染并 QA
node "$GIS_COMPOSER_HOME/src/cli.js" --project /absolute/project inspect maps/site-chain.map.json   # 看推导出的各级范围与图例
node "$GIS_COMPOSER_HOME/src/cli.js" --project /absolute/project render maps/site-chain.map.json
```

第 2 步的地图清单只写版式和一个分面模板，不抄各级范围：

```json
{ "kind": "map", "id": "site-chain", "title": "埃菲尔铁塔在哪里",
  "layout": { "type": "row", "shape": "circle", "links": "chain", "grow": 1.07 },
  "panels": [
    { "each": { "data": "../inputs/site-chain/chain.geojson", "pairs": true },
      "panel": { "id": "${key}", "label": "$label", "composition": {
        "fit": { "data": "../inputs/site-chain/chain.geojson", "filter": ["==", ["get", "key"], "$key"] },
        "context": { "lines": [
          { "data": "../inputs/site-chain/context.geojson", "filter": ["==", ["get", "parent"], "$key"] },
          { "data": "../inputs/site-chain/chain.geojson", "filter": ["==", ["get", "key"], "$key"], "role": "unit-outline" } ] },
        "encodings": [{ "encoding": "focus", "id": "next", "data": "../inputs/site-chain/chain.geojson",
          "filter": ["==", ["get", "key"], "$next.key"], "legend": "下一级" }] } } } ],
  "legend": { "extent": "放大范围" } }
```

- 分面按 `chain.geojson` 的要素顺序（adm0 … site）展开，`pairs: true` 让每一级都突出下一级；最后一级的下一级是场地，场地是点时自动画成带名称的标记。
- 范围由 `fit` 从本级要素推导；本级轮廓用 `unit-outline` 角色，下级界线按 `parent` 过滤。
- 需要世界面板时，在分面前加一个普通面板（`bounds: [-180, -56, 180, 78]`，`focus` 过滤 `key == "adm0"`）。
- 颜色、遮罩深浅、范围框与连接线样式都来自项目主题 `style/map.theme.json`，不写进地图清单。
- 完整示例：gis-composer 仓库 `examples/europe-atlas/maps/paris-chain.map.json` 与 `paris-site.map.json`。

## 要做的判断

- **级数**：常用 `0,1,2`（国家、省、市），场地在城区时再加一级。下一级数据过粗或缺失时少用一级。GADM 中国 ADM_3 把广州市区几个区合成了一个单元，就是一例。
- **版面**：要表达逐级放大关系，用 `row` + `links: "chain"`；要突出场地本身，用 `hero`，内嵌小图设 `link: "locator"`；要对比几个场地，用 `grid`。
- **名称与口径**：显示名在 `--labels` 里给出（分面模板用 `$label` 取用），或在面板 `label` 里覆盖。在中国境内出图时，用 `--adm0-layer ADM_0_cn_review_full` 选择审图口径的国界，地图清单里写 `gadm: {chinaReview: true}`，并在来源行注明。
- **检查**：打开 `runs/<run-id>/output/<id>.png`，看 `qa/<id>.qa.json` 和各面板的 QA；用 `rerun <run-id>` 逐字节复核 Sheet、每个面板以及编译出的 JSON。

## 不在范围

影像底的场地区位图和影像时间序列，要先定影像来源与授权（见 gis-composer #8 形式 2、3）。

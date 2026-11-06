# 约定清单

引擎之间、引擎与外壳之间交换的文件格式。只涉及外壳的格式（capabilities、sources、semantics）和有多个产出方的格式（map-style）在本目录写 JSON Schema（`<name>.schema.json`）和本页中的说明；引擎产出的格式由产出方维护，本页只写用途、产出方、读取方、版本和跨引擎衔接要点，字段以引擎文档为准。均带 `schema_version`。下表为草案，均未定稿；只为已有产出方或读取方实现的格式写 Schema。

`gis-doctor` 把下表的产出方、读取方和各引擎 `capabilities --json` 的 `contracts` 对照，不一致时报告（见[版本规则](#版本规则)第 4 条）。为此“产出方”“读取方”两栏按 `；` 分项，以引擎名开头的一项算该引擎的写或读；括号里的说明、外壳、用户、Agent 和其它 skill 不参与对照。状态为“暂缓”“取消”的行不对照。

| 约定 | 用途 | 产出方 | 读取方 | 状态 |
|---|---|---|---|---|
| capabilities | 引擎自报版本与能力，供 doctor 和 hooks 判断可用性 | 各引擎（`capabilities --json` 子命令） | 外壳 | 草案，已有 Schema，见下文 |
| describe | 给 Agent 的数据元数据卡片，hook 注入对话，模型不必再调工具读元数据 | gis-kit（`gis.py describe`） | 外壳 hooks | 草案，说明由 gis-kit 维护，见下文 |
| sources | 登记受保护的源数据，外壳 hook 拦截对其写入 | 用户（`.gis/sources.json`，跟随数据） | 外壳 hooks | 草案，已有 Schema，见下文 |
| semantics | 用户声明的字段与波段语义：总量/密度/比率/类别、单位 | 用户（`.gis/semantics.json`，跟随数据） | 外壳 hooks（gis-kit、gis-view 尚未读取） | 草案，已有 Schema，见下文 |
| class-scheme | 分类方案：每一类是什么，不含颜色，颜色由出图方按主题决定 | gis-kit（`scheme.py`、`raster.py display` 的 values 模式） | gis-composer | 草案，说明由 gis-kit 维护，见下文 |
| display-raster | 不上色的显示栅格，由出图方按分类方案和主题上色 | gis-kit（`raster.py display` 的 values 模式） | gis-composer | 草案，说明由 gis-kit 维护，见下文 |
| display-vector | 按一张图的视角概括的底图矢量，避免小比例尺下的碎岛与描边 | gis-kit（`display-vector.py`） | gis-composer | 草案，说明由 gis-kit 维护，见下文 |
| tile-snapshot | 在线瓦片的本地快照，使渲染不联网、署名与许可可追溯 | gis-kit（`snapshot.py`） | gis-composer | 草案，说明由 gis-kit 维护，见下文 |
| admin-chain | 场地的各级行政区，供区位图逐级放大 | gis-kit（`admin-chain.py`） | Agent（写 gis-composer 的地图清单；Composer 只读其中的 GeoJSON） | 草案，说明由 gis-kit 维护，见下文 |
| project | 共用项目目录：分析成果、地图清单、主题与运行记录各放在哪里、归谁写 | gis-composer（`project init`；gis-kit 只按路径规则发布到 `inputs/<分析名>/`，不读写清单） | gis-composer；Agent | 草案，说明由 gis-composer 维护，见下文 |
| map-legend | 每张图旁的图例数据，汇报页据此画可编辑图例、按尺寸放图 | gis-composer（每次出图写 `<图>.legend.json`） | Agent；出页脚本 | 草案，说明由 gis-composer 维护，见下文 |
| resolved-theme | 项目地图主题解析 `extends` 和记号之后的颜色、常量与字体，供页面和其它工具取用，不必自己解析主题链 | gis-composer（`theme resolve`，只读查询，打印到 stdout） | plan-deck（`style.json` 的 `mapTheme`） | 草案，说明由 gis-composer 维护，见下文 |
| map-style | 一张图的图层、数据引用、绘制顺序和最终样式，与平台无关；在引擎之间、以及与 QGIS、ArcGIS 等平台格式之间转样式 | gis-composer（已发布的地图）；gis-view（临时样式）；gis-kit（从平台格式转回） | gis-kit（转成平台格式）；gis-view；gis-composer | 草案：Schema 先行，gis-composer 导出实现时定稿，见下文 |
| view | 一组图层的查看描述：图层、对照关系、状态着色、范围 | gis-kit 等 | gis-view | 暂缓：无产出方，见下文 |
| selection | 选择集：source、layer、revision、fids | gis-view | gis-kit | 暂缓：无产出方，见下文 |
| review | 审阅记录：要素的接受/待定/拒绝与备注，不改源数据 | gis-view | gis-kit | 暂缓：无产出方，见下文 |
| scene-draft | 由查看状态导出的 Scene 草稿 | gis-view | gis-composer | 取消：gis-view 改为导出 map-style，见下文 |

## 共同规则

- 只描述事实与声明，不做推断；推测内容必须显式标注。
- 不含访问令牌、本地服务 URL 或私有数据内容。
- 引用源数据时带 revision（或大小与修改时间），读取方发现不一致时拒绝而不是继续。
- gis-kit 已有的 trace、recipe 与状态字段（`candidate`、`hold` 等）以 gis-kit 仓库为准，此处只引用。

## 版本规则

1. **兼容变更不升版本**：只有“新增可选字段”算兼容。读取方必须忽略不认识的字段，Schema 不禁止额外字段。
2. **不兼容变更才把 `schema_version` 加 1**：删除字段、改名、改含义、新增必填字段。
3. **读取方遇到不认识的版本时拒绝并说明**，不猜测。
4. **协商**：各引擎在 capabilities 的 `contracts` 中声明读写的版本；`gis-doctor` 把每个写入方与每个读取方（含外壳自身，见下）配对，找不到共同版本时报错并指出是哪两方。外壳目前读取 `describe`、`semantics`、`sources` 各 v1（`gis_doctor.py` 的 `SHELL_READS`）。doctor 还把本页总表登记的读写关系和各引擎的声明对照：表里有、引擎没声明，或者引擎声明了表里登记的约定、表里却没列它，都报告出来，不影响退出码；引擎声明了而本页没有登记的约定（引擎自己的格式）不报。
5. **过渡**：升级时产出方至少在一个版本周期内仍能按旧版本写出（例如 `--schema-version N`），读取方同时读新旧两版。外壳不做格式迁移，迁移由产出该格式的引擎负责。
6. **capabilities 本身只做兼容变更**，作为协商起点保持 v1。

## capabilities

Schema：[capabilities.schema.json](capabilities.schema.json)（`schema_version: 1`）。

### 调用约定

- 外壳运行 `<engine> capabilities --json`，引擎入口取自 `GIS_*_CMD`（共用文件 `~/.config/gis-plugin/engines.env`，同名环境变量优先，见 [boundaries.md](../docs/boundaries.md#8-已定事项)）。
- 成功：退出码 0，stdout 只输出一个符合 Schema 的 JSON 对象；日志写 stderr。
- 失败：退出码非 0，外壳将其报告为“引擎不可用”，并附 stderr 摘要。
- 子命令不读用户 GIS 数据、不写文件、不联网，应在数秒内返回。
- 引擎未提供该子命令时，外壳明确报告“未提供 capabilities”，不回退去读引擎仓库中的静态文件。

### 字段

| 字段 | 说明 |
|---|---|
| `contract` | 固定为 `capabilities` |
| `schema_version` | 本格式版本，当前为 1 |
| `engine` | 引擎名，如 `gis-kit` |
| `engine_version` | 引擎版本（SemVer），外壳据此判断兼容性 |
| `commands` | 支持 `--json` 的公开子命令 |
| `contracts` | 读写的约定及支持的 `schema_version`，如 `{"selection": {"write": [1]}}` |
| `features` | 与运行环境有关的可选能力，`available` 为运行时实测结果；不可用时 `reason` 说明原因 |

### 示例

```json
{
  "contract": "capabilities",
  "schema_version": 1,
  "engine": "gis-composer",
  "engine_version": "0.1.0",
  "commands": ["render", "inspect", "qa"],
  "contracts": {"scene-draft": {"read": [1]}},
  "features": [
    {"name": "maplibre", "available": true},
    {"name": "blender", "available": false, "reason": "Blender executable not found"}
  ]
}
```

gis-view 现有的 `viewer-entry.json` 保留为其内部文件，其 `engine_version` 由 `capabilities` 子命令转述。

## sources

Schema：[sources.schema.json](sources.schema.json)（`schema_version: 1`）。

登记文件放在数据所在目录的 `.gis/sources.json`，模式相对于包含 `.gis/` 的目录：

```json
{
  "contract": "sources",
  "schema_version": 1,
  "protected": ["raw/**", "dem/srtm.tif", "roads.shp", "parcels.gdb"]
}
```

- `*`、`?` 不跨目录，`**` 跨目录；`dir/**` 同时覆盖 `dir` 本身；写入目录内任何文件都算写入该目录。
- 附属文件随主数据保护：`roads.shp` 覆盖 `.shx`、`.dbf`、`.prj`、`.cpg` 等；任一文件覆盖其 `.aux.xml`、`.ovr`、`.msk`。
- 大小写跟随文件系统：登记文件所在的卷不区分大小写时（macOS、Windows 默认如此），`RAW/A.CSV` 也算写入 `raw/**`；区分大小写的卷上按原样匹配。
- 外壳 hook（`hooks/scripts/protect_sources.py`）从被写路径逐级向上查找登记文件，因此保护跟随数据，与宿主工作目录无关。
- 登记文件无效时，其目录树内的写入一律拒绝并说明原因；目录树外不受影响。
- 识别范围：文件编辑工具、Codex `apply_patch`，shell 命令中的重定向与常见写入命令（`rm`、`mv`、`cp`、`sed -i`、`tee`、`ogr2ogr`、`gdalwarp`、`gdal_edit.py` 等），以及 PowerShell 的写入命令和别名（`Set-Content`、`Add-Content`、`Clear-Content`、`Out-File`、`Tee-Object`、`Export-Csv`、`New-Item`、`Remove-Item`、`Move-Item`、`Rename-Item`、`Copy-Item` 等）。shell 识别是尽力而为，脚本内部的写入（`python -c`、`[IO.File]::WriteAllText`）和变量里的路径都不在拦截范围。

## describe

产出方为 gis-kit 的 `gis.py describe <path> --json`，格式与字段说明由 gis-kit 维护：[describe.schema.json](https://github.com/shioo-gis/gis-kit/blob/main/references/describe.schema.json)、[harness.md](https://github.com/shioo-gis/gis-kit/blob/main/references/harness.md)（`schema_version: 1`）。本仓库不保留副本。

外壳 hook `hooks/scripts/inject_describe.py` 作为读取方：

- 只认 `contract: describe`、`schema_version: 1`，其它版本不注入；忽略不认识的字段。
- 把卡片转成文字注入对话；按文件大小与修改时间，同一会话内同一文件只注入一次。

## class-scheme 与 display-raster

产出方是 gis-kit，读取方是 gis-composer，均为 `schema_version: 1`。说明由 gis-kit 维护：[class-scheme.schema.json](https://github.com/shioo-gis/gis-kit/blob/main/references/class-scheme.schema.json)、[display-raster.schema.json](https://github.com/shioo-gis/gis-kit/blob/main/references/display-raster.schema.json)、[composer-display.md](https://github.com/shioo-gis/gis-kit/blob/main/references/composer-display.md)。本仓库不保留副本。

- 分界原则：几何、数值和语义归 gis-kit，颜色、纹理和图例归 gis-composer。方案只说明每一类是什么，颜色由 gis-composer 按主题决定，所以换主题时矢量和栅格会一起变色。
- gis-kit 在 `capabilities` 中声明 `write: [1]`，gis-composer 声明 `read: [1]`，`gis-doctor` 两两配对；读取方遇到不认识的版本时拒绝。
- 外壳本身不读这两种文件，只负责登记和版本配对。

## display-vector

产出方是 gis-kit `display-vector.py`，读取方是 gis-composer，`schema_version: 1`。说明见 [display-vector.md](https://github.com/shioo-gis/gis-kit/blob/main/references/display-vector.md)。本仓库不保留副本。

- 底图按视角概括，不预存多比例尺底图：gis-composer `inspect` 报告每个面板的视角，gis-kit 只为这个视角生成一次显示包，发布到项目 `inputs/`。
- gis-composer 读取前核对文件哈希，并比较包的视角与实际渲染的比例尺和范围，不符时 lint 警告，由 Agent 按新视角重新生成；渲染器不做几何计算。
- 两边分别在 `capabilities` 中声明 `write: [1]` / `read: [1]`，由 `gis-doctor` 配对。
- 跨引擎用法见 [recipes/display-basemap.md](../recipes/display-basemap.md)。

## tile-snapshot

产出方是 gis-kit `snapshot.py`，读取方是 gis-composer，`schema_version: 1`。说明见 [tile-snapshot.md](https://github.com/shioo-gis/gis-kit/blob/main/references/tile-snapshot.md)，服务商白名单在 [snapshot-providers.json](https://github.com/shioo-gis/gis-kit/blob/main/references/snapshot-providers.json)。

- 在线瓦片先快照进 Composer 项目的 `inputs/`，渲染只读本地瓦片，不联网；条款禁止缓存的服务由 gis-kit 拒绝。
- gis-composer 读取前核对瓦片哈希，并把署名写进来源行。两边分别在 `capabilities` 中声明 `write: [1]` / `read: [1]`，由 `gis-doctor` 配对。

## admin-chain

产出方是 gis-kit `admin-chain.py`，`schema_version: 1`。说明见 [admin-chain.md](https://github.com/shioo-gis/gis-kit/blob/main/references/admin-chain.md)。本仓库不保留副本。

- gis-kit 负责找各级单元、取下一级界线和显示简化；国界口径显式选择并写进清单。
- 产出的 GeoJSON 作为普通数据交给 gis-composer 的地图清单：分面逐级展开面板，范围由清单从同一份数据推导，不抄坐标；版式由地图清单决定，颜色由项目主题决定。清单本身供 Agent 核对级数、名称与告警。
- gis-kit 在 `capabilities` 中声明 `write: [1]`；Composer 不读清单本身，所以没有读取方配对，GeoJSON 的哈希由 Composer 的 `run.json` 记录。
- 跨引擎用法见 [recipes/location-chain.md](../recipes/location-chain.md)。

## project（共用项目目录）

说明由 gis-composer 维护：[架构 §4 项目工作区](https://github.com/shioo-gis/gis-composer/blob/main/docs/architecture.md#4-项目工作区)、[地图清单与 Sheet](https://github.com/shioo-gis/gis-composer/blob/main/docs/map-specs.md#map-specs-project-themes-and-encoding-blocks)（项目清单 `schemaVersion: 1`）。目录布局、清单字段与出版参数以那里为准，本仓库只做索引，不保留副本。

- **各写各的**：一个项目一个根目录，引擎之间只交换文件。gis-kit 只写 `inputs/<分析名>/`（新目录、原子发布、不覆盖，自带 `record.json`）；清单、主题、地图清单、运行与发布目录归 gis-composer 和 Agent；gis-view 可以打开项目里的任何文件查看，但不写入项目。
- **溯源**：gis-kit 的 `record.json` 与 Composer 的 `run.json` 用同一种算法记录文件 SHA-256，从分析到成图可以逐个核对。两份记录各管各的：`record.json` 只说明分析成果已完整发布，成图是否完成看 `run.json`。
- **引擎仍可独立使用**：gis-kit 不依赖项目存在，`--output` 可以是任意新目录；只有交给 Composer 时才发布到 `inputs/`。
- **共享大数据不进项目**：底图、DEM、geo-assets 在项目清单里声明名称，各设备各自配置路径，见 gis-composer 文档。
- **按页面尺寸出图**：图要放进汇报页时，出版参数写在项目清单与地图清单里（gis-composer 维护），放置尺寸随 [map-legend](#map-legend) 交给页面。
- **plan-deck**：读 gis-composer 项目的发布版（`releases/vN/`）放图、按 [map-legend](#map-legend) 画可编辑图例，页面配色经 `theme resolve`（[resolved-theme](#resolved-theme)）从项目主题取，和图纸同色系；自己的 `style.json`、`style.md` 放在汇报稿旁，用 `mapTheme` 指向 composer 项目，不写入项目目录。细节见 plan-deck 的 `docs/architecture.md`。
- **版本配对**：目前只有 gis-composer 读写清单，gis-kit 只遵守 `inputs/` 的路径规则、不读写清单，因此没有跨引擎的 capabilities 配对。等另一个引擎开始读写清单时，再由双方在 `capabilities` 中声明 `project` 的版本。

## map-legend

产出方是 gis-composer，`schema_version: 1`。说明见其 [地图清单与 Sheet](https://github.com/shioo-gis/gis-composer/blob/main/docs/map-specs.md#map-specs-project-themes-and-encoding-blocks)。字段以那里为准，本仓库不保留副本。

- 每张渲染出的图旁写一份 `<图>.legend.json`，记录渲染时按主题解析出的图例（最终色值）和放置尺寸。
- 用法：图要放进汇报页、由页面画可编辑图例时，地图清单关掉 PNG 里的图例，出页脚本读这份文件画图例、按尺寸放图，不手抄颜色和标签。
- `rerun` 把它当作交付物逐字节比对。读取方是 Agent、项目里的出页脚本和 plan-deck 运行时（只从发布版读）；plan-deck 不在本仓库的引擎配对里，因此没有 capabilities 配对。

## resolved-theme

产出方是 gis-composer 的 `theme resolve [<theme>]`，`schemaVersion: 1`、`kind: "resolved-theme"`（composer 自己的字段名，不是本页的 `contract`、`schema_version`）。字段见其 [主题文档](https://github.com/shioo-gis/gis-composer/blob/main/docs/themes.md#theme-inheritance-and-tokens)，本仓库不保留副本。

- **只读查询**：打印主题按 `extends` 和记号解析后的结果，不写文件，同样的输入得到同样的 JSON。默认解析项目主题，也可以给内置主题名或项目里的 `.theme.json`。
- **系列里唯一的跨工具调用**：别的约定都靠文件交接，这一个是 plan-deck 加载 `style.json` 时调 composer 的命令行（`mapTheme` 指向 composer 项目；命令取自 `GIS_COMPOSER_CMD`，没有时读 `engines.env`）。命令不可用或主题出错时 plan-deck 报错，不回退到旧值。
- **读取方用到的**：`palette`、`classes`（强调色、类别配色）、`constants` 里的 `label*Size`（核对图面字号）、`typography.fonts[]` 的 name 表（认主题字体的别名），以及 `chain` 里项目主题的 `sha256`，和发布版 `release.json` 的 `inputs` 对比，判断图是不是用当前主题出的。
- plan-deck 不在本仓库的引擎配对里，没有 capabilities 配对；composer 在 capabilities 里声明 `write` 之前，doctor 的约定表对照会报出来。

## map-style

Schema：[map-style.schema.json](map-style.schema.json)（`schema_version: 1`，**草案**）。

一份 `map-style` 描述一张图：有哪些图层、各引用什么数据、按什么顺序画、每层长什么样，以及可选的标注位置和图幅范围。它和平台、渲染器无关，不写 MapLibre 表达式、QML 或 CIM。设计讨论见 gis-plugin#16。

- **为什么放在这里**：它有多个产出方（gis-composer 写已发布的地图，gis-view 写临时样式，gis-kit 从平台格式转回来），格式说明只写一处，所以由外壳维护。读的一方是 gis-kit（转成 QGIS 等平台格式）、gis-view 和 gis-composer。
- **草案**：按 boundaries 的规则，约定本该等第一个产出方实现后再写 Schema。这份 Schema 先写，是为了让 composer 导出和 gis-kit 打包能按同一份字段并行开发（boundaries 2026-10-30 的例外）。gis-composer 的导出实现时按实际输出定稿；定稿前各引擎不在 `capabilities` 里登记读写版本，doctor 也不配对。
- **分工**：平台格式（QML、`.qgz`，以后 `.lyrx` 等）的读写都归 gis-kit；composer、gis-view 只读写 `map-style`。外壳不读写数据。

```json
{
  "contract": "map-style",
  "schema_version": 1,
  "id": "example-map",
  "producer": {"engine": "gis-composer", "version": "0.1.0", "release": "v1", "map": "example-map"},
  "units": {"size": "px"},
  "dataRoot": "project",
  "background": {"color": "#B4D6E2"},
  "extent": {"bbox": [114.00, 22.50, 114.10, 22.60], "print": {"widthCm": 10, "heightCm": 14, "dpi": 300}},
  "fonts": [{"family": "GC Sans", "weight": 400, "file": "assets/fonts/sans-regular.otf"},
            {"family": "GC Sans", "weight": 500, "file": "assets/fonts/sans-medium.otf"}],
  "layers": [
    {"id": "ground", "group": "ground", "geometry": "polygon", "data": {"path": "@basemap/land.geojson"},
     "renderer": {"type": "single", "symbol": {"fill": {"color": "#E1E1E1", "opacity": 1}}}, "legend": {"show": false}},
    {"id": "parcels", "title": "用地分类", "group": "fills", "geometry": "polygon", "data": {"path": "inputs/analysis/parcels.geojson"},
     "renderer": {"type": "categorized", "field": "类别",
                  "classes": [{"value": "A 类", "label": "A 类（47 块）", "symbol": {"fill": {"color": "#ED7D31", "opacity": 1}}},
                              {"value": "B 类", "label": "B 类（73 块）", "symbol": {"fill": {"color": "#4F81BD", "opacity": 1,
                                         "pattern": {"kind": "hatch", "angle": 45, "spacing": 6, "width": 0.8, "color": "#FFFFFF"}}}}],
                  "default": null},
     "legend": {"show": true, "title": "用地分类"}},
    {"id": "parcels-outline", "group": "lines", "geometry": "polygon", "data": {"path": "inputs/analysis/parcels.geojson"},
     "renderer": {"type": "single", "symbol": {"stroke": {"color": "#FFFFFF", "width": 0.8, "opacity": 0.9}}}, "legend": {"show": false}},
    {"id": "routes", "title": "线路", "group": "lines", "geometry": "line", "data": {"path": "inputs/analysis/routes.geojson", "kind": "vector"},
     "renderer": {"type": "single", "symbol": {"stroke": {"color": "#C00000", "width": 1.5}, "fill": {"color": "#C00000"},
                                               "marker": {"shape": "chevron", "size": 7, "placement": "line", "spacing": 80}}}},
    {"id": "names", "group": "labels", "geometry": "point", "data": {"path": "inputs/analysis/names.geojson"},
     "renderer": null,
     "labels": {"field": "name", "text": {"font": "GC Sans", "weight": 500, "size": 13.4, "color": "#333333", "halo": {"color": "#FFFFFF", "width": 2}},
                "placement": "point", "enabled": false}}
  ],
  "labelPlacements": [
    {"layer": "names", "text": "示例片区", "position": [114.05, 22.54], "anchor": "center",
     "style": {"font": "GC Sans", "weight": 500, "size": 13.4, "color": "#333333", "halo": {"color": "#FFFFFF", "width": 2},
               "box": {"fill": {"color": "#FFFFFF", "opacity": 0.8}, "padding": [2, 4]}}}
  ]
}
```

- **图层**：`layers` 按自下而上的绘制顺序排。同一份数据画成多层的（面、描边、白色衬边），写成多个图层、引用同一个 `data`。`group` 沿用 composer 的绘制分组。多面板图（hero 等）仍是一份文档：图层带 `panel`，对应 `extent.panels[].id`，读的一方先按面板分组、再按 `group` 分，免得主图和插图的同一份数据叠在一起。`extent.panels[].frame` 可选，是面板在页面上的位置和大小 `{x, y, width, height}`：单位厘米，原点在页面（`extent.print`）左上角，y 向下；`panels` 里靠后的面板画在上面。导出版式（QGIS `.qpt`、ArcGIS Pro `.pagx`）时用。
- **背景**：顶层 `background` 是没有图层覆盖处的颜色，比如陆地底图下面的水体。
- **数据路径**：`data.path` 相对 `dataRoot`（项目根或本文件所在目录），外部数据根写 `@<根名>/…`；不允许绝对路径和 `..`。数据本身保持原坐标系。`data.kind` 可选，标出是矢量、栅格还是瓦片；瓦片不能按图幅裁切。写了 `kind` 时它和 `geometry` 要对得上，Schema 会检查：`raster`、`rasterTiles` 只配 `raster`，`vector`、`vectorTiles` 配 `polygon`、`line`、`point`。
- **渲染方式**：矢量的 `single`、`categorized`、`graduated`、`rule` 与 gis-view 的样式模型一一对应；栅格有 `pseudocolor`、`palette`、`rgb`。符号分 `fill`、`stroke`、`marker` 三部分，颜色写 `#RRGGBB`，透明度另写。点图层的符号要有 `marker`，没有时读的一方画 6 px 圆并报告。比例圆用图层上的 `size`：字段值按 `linear` 或 `sqrt` 映射到半径，公式写在 Schema 里，`clamp` 默认为真。`sortBy.order` 是字段值的绘制顺序：`asc` 先画小值、大值在上，`desc` 先画大值、小值在上。描边的 `cap`、`join` 默认是 `butt`、`miter`。栅格 `stops` 的值是数据值，`stretch` 只记录怎么定的，读的一方不重算。只用来放标注、要素本身不画的矢量图层，`renderer` 写 `null`。
  - **标记**：`marker.rotation` 按顺时针度数，`rotationField` 指一个数值字段，值加在 `rotation` 上（NULL 不加）。`shape: "svg"` 时用 `marker.svg: {path, sha256}` 引用一个 SVG，路径规则同 `data.path`，两项都必填，读的一方核对哈希、不符就拒绝；SVG 按自身颜色画，`fill`、`stroke` 不作用于它，`size` 是图像较长的一边。用 SVG 而不是继续扩充形状名，是因为 airport、crosshair 这类图标列不完，而 SVG 在 QGIS（SVG 标记）、ArcGIS（图片标记）里都能原样用，MapLibre 一侧由 composer 自己栅格化。
  - **沿线标记**：线图层（和面的边线）上的 `marker` 写 `placement: "line"` 时沿线重复，`spacing`（px，必填）是相邻两个的间距，第一个离起点半个间距；`alongLine` 默认为真，标记随线的方向转，此时 `rotation` 相对线的方向（0 指向线的终点方向）。点图层只用默认的 `point`。
  - **晕线**：`fill.pattern` 是画在填色上面的平行线，`kind` 为 `hatch` 或 `crossHatch`（再加一组垂直的线），`angle` 按从水平起逆时针的度数（0 是 `—`，45 是 `/`），`spacing` 是线距、`width` 是线宽（px），另有 `color`、`opacity`。`fill.color` 是线下面的底色，只要线时把 `fill.opacity` 写 0。只做晕线、不做 SVG 图案：晕线在 QGIS（线图案填充）、ArcGIS（CIMHatchFill）里都是原生的，几个数就能写清；SVG 图案各平台的支持和平铺方式不一致。
- **单位和坐标**：尺寸一律是 CSS 像素（1 px = 1/96 英寸）；`extent`、`labelPlacements` 用经纬度（EPSG:4326）。
- **筛选**：只用结构化的一小套（`field`/`op`/`value`，加 `all`、`any`、`not`）。NULL 按 MapLibre 的规则：`!=` 和 `notIn` 对 NULL 为真，其余比较和 `in` 为假。装不下的条件写 `{"expression": …, "dialect": "qgis"}`。读的一方不认识这种方言时要列出跳过的部分，不能悄悄丢掉：用作图层筛选时当作没有筛选；用作规则的筛选时跳过这条规则，不让它接住其余要素。
- **标注**：图层上的 `labels` 是平台自己排的标注。生产方已经把同一批标注写进 `labelPlacements` 时写 `enabled: false`（composer 预先算好的布局）；要平台自己排时写 `true`（composer 交给 MapLibre 排的标注、gis-view）。`labelPlacements` 是预先算好的位置，可以带引线和 `leaderStroke`，`rotation` 按顺时针度数；`panel` 写它画在哪个面板，不写时按 `layer` 所在的面板，两样都没有就属于整张图。gis-kit 打包时把它写成点图层，和 PNG 一致，也能逐个拖动。文字样式可写字重 `weight`、透明度、晕边透明度与模糊、字距（em）和底框 `box`。`box.padding` 可以是一个数、`[纵, 横]` 或 `[上, 右, 下, 左]`（同 CSS）。`halo.blur` 按 MapLibre 的含义（px，向外渐隐），允许近似实现（QGIS 用缓冲上的模糊效果，没有的平台画清晰晕边），不必报告。
- **字体**：`fonts[]` 与 gis-composer `render.fonts[]` 的形状相同（含 name 表 `names`）。`textStyle.font` 可以是主题里的别名（如 `GC Sans`），读的一方从 `fonts[]` 里同名条目的 `names` 取实际安装的字体名。`fonts[].weight` 和 `textStyle.weight` 是 CSS 字重（100–900，400 常规、700 粗体），数字或数字串（composer 现在写 `"500"`）都行。同一个别名有多个条目时，读的一方取字重相等的那个（没写的一方按 400 算）；没有相等的就按 CSS 的字体匹配规则取最近的，并报告替换。
- **近似与遗漏**：顶层 `notes` 记下生产方没能原样表达的地方，`untranslated` 是没写进来的，`approximated` 是近似写的。读的一方应转告用户。
- **暂不纳入**：聚焦压暗（composer 的 composite：遮罩以外去饱和、再向背景色混合）和 `line-blur`。混色那一半可以不加字段原样表达：生产方写一个“图幅减去聚焦区”的面图层，用背景色、透明度取混合比例，效果与混合相同；去饱和在 ArcGIS 等平台没有对应，记 `approximated`。`line-blur` 主要是边缘柔化，QGIS 要靠图层效果、ArcGIS 没有对应，照清晰线画并记 `approximated`。等有平台能还原、也确实需要时再加字段。
- v1 不含影片、三维和标注密度这类 composer 特有的设置。

## semantics

Schema：[semantics.schema.json](semantics.schema.json)（`schema_version: 1`）。由用户写在数据所在目录的 `.gis/semantics.json`，声明字段或波段“是什么量”；外壳 hook `hooks/scripts/inject_describe.py` 在注入元数据卡片时一并转述。

```json
{
  "contract": "semantics",
  "schema_version": 1,
  "datasets": [
    {"match": "census/*.gpkg", "fields": {"pop": {"kind": "total", "unit": "人"}, "code": {"kind": "category"}}},
    {"match": "census/towns.gpkg", "layer": "towns", "fields": {"dens": {"kind": "density", "unit": "人/km²"}}},
    {"match": "rain/*.tif", "bands": {"1": {"kind": "density", "unit": "mm"}}}
  ]
}
```

- `kind` 取值与 gis-kit 参数中的 `quantity_type`（矢量）和 `quantity`（栅格）相同：`total` 随面积可加，`density` 为单位面积量，`ratio` 为不按面积的比率，`category` 为类别代码。模型可据此直接填写 gis-kit 参数。
- `match` 与 `sources` 的模式规则相同，相对于包含 `.gis/` 的目录；`layer` 省略时适用于所有图层；`bands` 以 1 起的波段号为键。
- 按 `datasets` 顺序合并，后者覆盖前者对同一字段或波段的声明。
- hook 从数据文件所在目录逐级向上，只用最近的一份 `.gis/semantics.json`；文件无效时注入“无效”及原因，不猜测。
- `note` 是用户自己的简短备注，hook 以引号原样转述；不写给模型的指令。
- 只写声明，不由外壳推断；没有声明的字段不出现在卡片中。

## 暂缓的约定

view、selection、review 目前没有任何引擎产出（2026-10-10 核对；scene-draft 已取消）：

- selection：gis-view 的选择集只在服务进程内存中（`fids`、`revision` 等），不落文件；复制到剪贴板的“观察上下文”不是约定格式，且没有 `revision`。
- review：gis-view 不写审阅记录；gis-kit 的人工审阅（`raster-annotate.py feedback`）有自己的格式，以 gis-kit 仓库为准。
- view：没有引擎写出供 gis-view 打开的查看描述；gis-view 的 `session.json` 是其内部文件。
- scene-draft：已取消（2026-10-30）。gis-view 改为导出 [map-style](#map-style)，可交给 gis-composer 起草，也可交给 gis-kit 打包。

等第一个产出方实现时，再按其实际字段定 Schema，避免先写出无人实现、随后漂移的格式。

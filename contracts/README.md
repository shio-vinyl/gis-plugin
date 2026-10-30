# 约定清单

引擎之间、引擎与外壳之间交换的文件格式。只涉及外壳的格式（capabilities、sources、semantics）在本目录写 JSON Schema（`<name>.schema.json`）和本页中的说明；引擎产出的格式由产出方维护，本页只写用途、产出方、读取方、版本和跨引擎衔接要点，字段以引擎文档为准。均带 `schema_version`。下表为草案，均未定稿；只为已有产出方或读取方实现的格式写 Schema。

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
| project | 共用项目目录：分析成果、地图清单、主题与运行记录各放在哪里、归谁写 | gis-composer（`project init`）；gis-kit 发布到 `inputs/<分析名>/` | gis-composer；Agent | 草案，说明由 gis-composer 维护，见下文 |
| map-legend | 每张图旁的图例数据，汇报页据此画可编辑图例、按尺寸放图 | gis-composer（每次出图写 `<图>.legend.json`） | Agent；出页脚本 | 草案，说明由 gis-composer 维护，见下文 |
| view | 一组图层的查看描述：图层、对照关系、状态着色、范围 | gis-kit 等 | gis-view | 暂缓：无产出方，见下文 |
| selection | 选择集：source、layer、revision、fids | gis-view | gis-kit | 暂缓：无产出方，见下文 |
| review | 审阅记录：要素的接受/待定/拒绝与备注，不改源数据 | gis-view | gis-kit | 暂缓：无产出方，见下文 |
| scene-draft | 由查看状态导出的 Scene 草稿 | gis-view | gis-composer | 暂缓：无产出方，见下文；样式契约不同，只保证草稿 |

## 共同规则

- 只描述事实与声明，不做推断；推测内容必须显式标注。
- 不含访问令牌、本地服务 URL 或私有数据内容。
- 引用源数据时带 revision（或大小与修改时间），读取方发现不一致时拒绝而不是继续。
- gis-kit 已有的 trace、recipe 与状态字段（`candidate`、`hold` 等）以 gis-kit 仓库为准，此处只引用。

## 版本规则

1. **兼容变更不升版本**：只有“新增可选字段”算兼容。读取方必须忽略不认识的字段，Schema 不禁止额外字段。
2. **不兼容变更才把 `schema_version` 加 1**：删除字段、改名、改含义、新增必填字段。
3. **读取方遇到不认识的版本时拒绝并说明**，不猜测。
4. **协商**：各引擎在 capabilities 的 `contracts` 中声明读写的版本；`gis-doctor` 把每个写入方与每个读取方（含外壳自身，见下）配对，找不到共同版本时报错并指出是哪两方。外壳目前读取 `describe`、`semantics`、`sources` 各 v1（`gis_doctor.py` 的 `SHELL_READS`）。
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
- 外壳 hook（`hooks/scripts/protect_sources.py`）从被写路径逐级向上查找登记文件，因此保护跟随数据，与宿主工作目录无关。
- 登记文件无效时，其目录树内的写入一律拒绝并说明原因；目录树外不受影响。
- 识别范围：文件编辑工具、Codex `apply_patch`，以及 shell 命令中的重定向与常见写入命令（`rm`、`mv`、`cp`、`sed -i`、`tee`、`ogr2ogr`、`gdalwarp`、`gdal_edit.py` 等）。shell 识别是尽力而为，脚本内部的写入不在拦截范围。

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
- **plan-deck（暂缓）**：规划汇报与地图将共用同一个项目根，页面视觉系统导出为项目主题，使 PPT 与图纸同色系。plan-deck 尚无运行时，目录名和映射规则等它实现时再定。
- **版本配对**：目前只有 gis-composer 读写清单，gis-kit 只遵守 `inputs/` 的路径规则、不读写清单，因此没有跨引擎的 capabilities 配对。等另一个引擎开始读写清单时，再由双方在 `capabilities` 中声明 `project` 的版本。

## map-legend

产出方是 gis-composer，`schema_version: 1`。说明见其 [地图清单与 Sheet](https://github.com/shioo-gis/gis-composer/blob/main/docs/map-specs.md#map-specs-project-themes-and-encoding-blocks)。字段以那里为准，本仓库不保留副本。

- 每张渲染出的图旁写一份 `<图>.legend.json`，记录渲染时按主题解析出的图例（最终色值）和放置尺寸。
- 用法：图要放进汇报页、由页面画可编辑图例时，地图清单关掉 PNG 里的图例，出页脚本读这份文件画图例、按尺寸放图，不手抄颜色和标签。
- `rerun` 把它当作交付物逐字节比对。读取方目前是 Agent 和项目里的出页脚本（plan-deck 尚无运行时），都不是引擎，因此没有 capabilities 配对。

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

view、selection、review、scene-draft 目前没有任何引擎产出（2026-10-10 核对）：

- selection：gis-view 的选择集只在服务进程内存中（`fids`、`revision` 等），不落文件；复制到剪贴板的“观察上下文”不是约定格式，且没有 `revision`。
- review：gis-view 不写审阅记录；gis-kit 的人工审阅（`raster-annotate.py feedback`）有自己的格式，以 gis-kit 仓库为准。
- view：没有引擎写出供 gis-view 打开的查看描述；gis-view 的 `session.json` 是其内部文件。
- scene-draft：gis-view 尚无 Scene 导出；gis-kit 交给 gis-composer 的是普通 Scene 与显示数据（见 gis-kit `references/composer-display.md`）。

等第一个产出方实现时，再按其实际字段定 Schema，避免先写出无人实现、随后漂移的格式。

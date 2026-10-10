# 约定清单

引擎之间、引擎与外壳之间交换的文件格式。每种格式最终包含一份 JSON Schema（`<name>.schema.json`）和本页中的说明，均带 `schema_version`。下表为草案，均未定稿。

| 约定 | 用途 | 产出方 | 读取方 | 状态 |
|---|---|---|---|---|
| capabilities | 引擎自报版本与能力，供 doctor 和 hooks 判断可用性 | 各引擎（`capabilities --json` 子命令） | 外壳 | 草案，已有 Schema，见下文 |
| describe | 给 Agent 的元数据卡片：CRS 与单位、范围、几何/波段、字段、NoData、确定性警告 | gis-kit（`gis.py describe`） | 外壳 hooks | 草案，已有 Schema，见下文 |
| sources | 登记受保护的源数据，外壳 hook 拦截对其写入 | 用户（`.gis/sources.json`，跟随数据） | 外壳 hooks | 草案，已有 Schema，见下文 |
| semantics | 用户声明的字段语义：总量/密度/比率/类别、单位 | 用户（跟随数据或项目） | gis-kit、gis-view、外壳 hooks | 草案 |
| view | 一组图层的查看描述：图层、对照关系、状态着色、范围 | gis-kit 等 | gis-view | 草案 |
| selection | 选择集：source、layer、revision、fids | gis-view | gis-kit | 草案 |
| review | 审阅记录：要素的接受/待定/拒绝与备注，不改源数据 | gis-view | gis-kit | 草案 |
| scene-draft | 由查看状态导出的 Scene 草稿 | gis-view | gis-composer | 草案；样式契约不同，只保证草稿 |

## 共同规则

- 只描述事实与声明，不做推断；推测内容必须显式标注。
- 不含访问令牌、本地服务 URL 或私有数据内容。
- 引用源数据时带 revision（或大小与修改时间），读取方发现不一致时拒绝而不是继续。
- gis-kit 已有的 trace、recipe 与状态字段（`candidate`、`hold` 等）以 gis-kit 仓库为准，此处只引用。

## 版本规则

1. **兼容变更不升版本**：只有“新增可选字段”算兼容。读取方必须忽略不认识的字段，Schema 不禁止额外字段。
2. **不兼容变更才把 `schema_version` 加 1**：删除字段、改名、改含义、新增必填字段。
3. **读取方遇到不认识的版本时拒绝并说明**，不猜测。
4. **协商**：各引擎在 capabilities 的 `contracts` 中声明读写的版本；`gis-doctor` 把每个写入方与每个读取方（含外壳自身，见下）配对，找不到共同版本时报错并指出是哪两方。外壳目前读取 `describe` v1。
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

Schema：[describe.schema.json](describe.schema.json)（`schema_version: 1`）。产出方为 gis-kit 的 `gis.py describe <path> --json`；外壳 hook `hooks/scripts/inject_describe.py` 读取后转成文字卡片注入对话。

- 只读文件头与系统表，不读要素或像元；要素数或范围需扫描才能得到时为 `null`。
- 矢量给出图层（最多 20 个，`layer_count` 为总数）、几何类型、要素数、CRS、范围、字段（最多 50 个，`field_count` 为总数）；栅格给出尺寸、波段、数据类型、逐波段 NoData（NaN 记为 `"nan"`，未设置为 `null`）、分辨率、CRS、范围。
- `crs` 含 `id`（如 `EPSG:4490`，无法识别时为 `null`）、`name`、`geographic`、`units`；没有 CRS 时整个为 `null`。
- `warnings` 只列确定性事实（`crs_missing`、`nodata_unset`），不给建议。
- `revision`（大小与修改时间）用于判断卡片是否过期；hook 在同一会话内对同一 revision 只注入一次。
- 读取方忽略不认识的字段。

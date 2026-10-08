# 约定清单

引擎之间、引擎与外壳之间交换的文件格式。每种格式最终包含一份 JSON Schema（`<name>.schema.json`）和本页中的说明，均带 `schema_version`。下表为草案，均未定稿。

| 约定 | 用途 | 产出方 | 读取方 | 状态 |
|---|---|---|---|---|
| capabilities | 引擎自报版本与能力，供 doctor 和 hooks 判断可用性 | 各引擎（`capabilities --json` 子命令） | 外壳 | 草案，已有 Schema，见下文 |
| describe | 给 Agent 的元数据卡片：CRS 与单位、范围、几何/波段、字段、NoData、确定性警告 | gis-view | 外壳 hooks | 草案 |
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

## capabilities

Schema：[capabilities.schema.json](capabilities.schema.json)（`schema_version: 1`）。

### 调用约定

- 外壳运行 `<engine> capabilities --json`，引擎入口由用户在 userConfig 中配置。
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

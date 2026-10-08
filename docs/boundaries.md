# 分层与边界

本文是 gis-plugin 与三个引擎关系的依据。新增功能先判断它属于哪一层，再决定放在哪个仓库。

## 1. 三层结构

```
 Claude Code / dsh / Codex
          │  插件格式（skills、hooks、MCP 登记）
 ┌────────▼────────┐
 │   gis-plugin    │  集成层：入口、跨引擎 hooks、约定、诊断、评测
 └──┬──────┬─────┬─┘
    │CLI   │CLI  │CLI          ← 外壳与引擎之间唯一的接口
 gis-kit gis-view gis-composer   引擎层：各自仓库、各自环境，互不导入代码
    └──────┴─────┴── 文件 ──┘
          约定层：源数据（只读）、semantics、view、selection、review、Scene 草稿、gis-kit trace 与状态字段
```

规则：

1. **引擎之间只通过文件衔接**，不互相调用 CLI，不共享代码。
2. **约定是格式，谁都可以读写**；格式说明只在 `contracts/` 写一处，引擎仓库引用而不复制。多个引擎读同一格式不算第二份引擎。
3. **跨引擎的事放集成层**：元数据注入、源数据保护等与多个引擎有关、又不属于任何一个的能力。
4. **外壳不读数据**：需要元数据时调用引擎 CLI。

## 2. 外壳放什么

| 内容 | 说明 |
|---|---|
| 各宿主清单 | CC、Codex 插件清单与 dsh 补丁层；引擎位置由环境变量配置，见 [harnesses.md](harnesses.md) |
| 薄 skills | gis-view、gis-composer 各一份（gis-kit 用其仓库自带入口，见 §8）；参数以引擎 `--help` 为准 |
| hooks | 元数据注入、源数据保护；仅 Python 标准库，读数据一律调引擎 CLI |
| `contracts/` | 每种文件格式一份 JSON Schema 和说明，带 `schema_version` |
| `.mcp.json` | 只做登记，指向引擎自带的 MCP 子命令 |
| `/gis-doctor` | 逐个询问引擎版本与能力，报告缺什么 |
| `evals/` | GIS 任务与标准答案，比较有无外壳的差别 |
| `tests/` | hooks 等外壳自有代码的测试 |
| `adapters/`（以后） | 某个 harness 专用的界面适配（Claude mod、dsh 插件），保持很薄，不含业务逻辑 |

## 3. 外壳不放什么

| 内容 | 原因 |
|---|---|
| 读写 GIS 数据的代码 | 即第二份引擎 |
| 引擎代码副本、vendored 依赖、虚拟环境 | 违反唯一维护源 |
| 自动安装、升级依赖的脚本 | 须用户授权 |
| MCP server 的实现 | 需了解引擎内部协议，放在引擎里作为子命令 |
| 数据、trace、运行记录、令牌、用户的 semantics 文件 | semantics 文件跟着数据或项目走，外壳只定义格式 |
| 通用插件注册表、调度框架 | 不建设平台；已知引擎固定列出 |
| 自动回退 | 引擎缺失或不兼容时明确报告 |
| 大量斜杠命令 | 模型自己会找工具；命令只给人用的少数入口 |

判断标准：**凡是需要了解某个引擎内部细节的东西，放回那个引擎的仓库。**

## 4. 引擎职责

| | gis-kit | gis-view | gis-composer |
|---|---|---|---|
| 动作 | 算、转换、写新数据 | 看、选、识别、审阅 | 出正式图和影片 |
| 产生新数据文件 | 会，结果带状态字段 | 不会；只写查看状态、选择集、审阅记录 | 会（PNG、视频） |
| 主要使用者 | Agent | 人；Agent 可发显示指令 | Agent 制作，人看结果 |
| 给 Agent 的元数据描述 | 不负责（`inspect-data` 保留深入查看） | **唯一产出方**（`describe`，待实现） | 不负责 |
| 公开状态 | 已公开（`shio-vinyl/gis-kit`） | 私有开发 | 私有开发 |

“读元数据”分两种：引擎**内部**为了工作而读，属于各自实现，不需要统一；**给 Agent 看的描述**（卡片、警告、语义）是一个产品，只能有一个产出方。

## 5. 灰色地带

总原则：**gis-view 不产出看起来像成果的文件；要保存、复用、交付的交给 gis-kit 或 gis-composer。**

| 功能 | gis-view 的范围 | 超出后交给 |
|---|---|---|
| 统计 | 字段统计，用于浏览和选择，不导出 | 分区统计等分析性统计 → gis-kit |
| 筛选、选择 | 只影响显示；可导出选择集文件 | 按选择集生成子集文件 → gis-kit |
| 重投影 | 显示时临时投影 | 改写坐标系 → gis-kit |
| 样式 | 临时样式；可导出 Scene 草稿 | 正式制图 → gis-composer |
| 截图 | 作为 Agent 上下文的快速截图 | 正式出图 → gis-composer |
| 栅格派生 | 可删除的显示缓存 | 作为分析结果 → gis-kit |

## 6. 引擎接入条件

一个引擎要接入外壳，只需：

1. 一个 CLI 入口，提供 `--json` 输出；
2. 能自报版本与能力（通过 `capabilities --json` 子命令，格式见 `contracts/`）；
3. 读写文件遵守 `contracts/` 的格式。

语言、环境、仓库位置不限。新增引擎 = 新增一份薄 skill 和一行配置，不改其它引擎。

## 7. 仓库划分

```
gis-kit        引擎（公开）
gis-view       引擎 + 本地 App（私有）
gis-composer   引擎（私有）
gis-plugin     外壳（本仓库，私有）
agent-skills   只保留非 GIS 入口
```

入口只能有一份。gis-kit 的入口留在 gis-kit 仓库；gis-view 与 gis-composer 的入口已于 2026-10-08 从 agent-skills 迁入本仓库 `skills/`，原处移除。

## 8. 已定事项

- **gis-kit 入口不进外壳**（2026-10-08）。gis-kit 已公开，仓库自带的 SKILL.md 是唯一入口，用户照旧独立安装。外壳不含 gis-kit skill，只提供跨引擎能力，并在 `/gis-doctor` 中检查 gis-kit 是否已安装、版本是否兼容。因此外壳的薄 skills 只有 gis-view 与 gis-composer 两份。
- **hook 与 doctor 使用的 Python**（2026-10-08）。默认用系统 `python3`，允许用户在 userConfig 中覆盖解释器路径；脚本只用标准库。
- **capabilities 由子命令产出**（2026-10-08）。各引擎提供 `<engine> capabilities --json`，外壳只调用该子命令，不读引擎仓库中的静态文件；未提供时 doctor 明确报告。格式见 [contracts/README.md](../contracts/README.md#capabilities)。
- **引擎位置用环境变量配置**（2026-10-08）。`GIS_KIT_CMD`、`GIS_VIEW_CMD`、`GIS_COMPOSER_CMD`，hook 解释器为 `GIS_PLUGIN_PYTHON`；暂不使用 CC 的 userConfig（其值不进 Bash 工具环境）。多宿主适配见 [harnesses.md](harnesses.md)。
- **引擎版本号**（2026-10-08）。capabilities 的 `engine_version` 是引擎的发布版本；引擎内部的协议或格式版本（如 gis-view 的 `_instance.VERSION`）各自计数，不必一致。gis-view 的 `viewer-entry.json` 只保留 `engine_version`。

## 9. 待定事项

1. **外壳是否随 gis-kit 公开。** 若公开，gis-view、gis-composer 作为可选引擎，未安装时 doctor 明确报告；文档是否需要英文版。
2. **约定的版本策略。** `schema_version` 不兼容升级时，引擎与外壳如何协商。

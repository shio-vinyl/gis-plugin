# 多宿主适配

外壳面向 Claude Code（CC）、Codex 与 dsh 三个宿主。原则：**skills 与 hooks 脚本只写一份，各宿主只加一层清单。** 本文记录 2026-10-08 在本机（Codex 0.144.1、dsh 0.1.5-rc.1）核对的差异，宿主升级后需复核。

## 1. 差异

| | Claude Code | Codex | dsh |
|---|---|---|---|
| 插件清单 | `.claude-plugin/plugin.json` | `.codex-plugin/plugin.json`（`skills`、`mcpServers`、`interface`） | 无统一清单；profile 为 npm 包 + `cordis.patch.yml` 补丁层 |
| skills | `skills/<name>/SKILL.md` | 同格式 | 同格式；扫描 `.agents/skills`、`<dshHome>/skills`、`customSkillDirs` |
| hooks | `hooks/hooks.json`，`${CLAUDE_PLUGIN_ROOT}` | 插件根 `hooks.json`，命令用相对路径 | 经 `dsh-hooks-claude-code` / `dsh-hooks-codex` 桥接运行 CC 或 Codex 格式 |
| MCP | `.mcp.json` | `.mcp.json` | `dsh-mcp-client`，每个 server 一项 |
| 用户配置 | `userConfig` | 未见对应字段 | profile YAML |

## 2. 设计决定

1. **引擎位置用环境变量配置**：`GIS_KIT_CMD`、`GIS_VIEW_CMD`、`GIS_COMPOSER_CMD`（命令行字符串，按 shell 规则拆分），hook 解释器用 `GIS_PLUGIN_PYTHON`（默认 `python3`）。CC 的 userConfig 只是填写这些值的入口。
2. **doctor 是 skill 自带的标准库脚本**（`skills/gis-doctor/scripts/gis_doctor.py`），三家都通过 skill 或 shell 调用，不依赖斜杠命令。
3. **hooks 只用三家共同可用的子集**：`PreToolUse` 的 deny（源数据保护）、`PostToolUse` 的 `additionalContext`（元数据注入）。不依赖 `SessionStart` 首轮注入（dsh 中异步执行）与 `updatedInput`（dsh 不支持）。
4. **hook 脚本带 `--harness cc|codex|dsh`**，先把各家的工具名和参数归一，再走共用逻辑。CC 为 `Read`/`Edit`/`Bash` 等；Codex 以 shell 与 `apply_patch` 为主；dsh 为自家 fs、bash、str-replace-editor 工具。
5. **dsh 接入**：`adapters/dsh/cordis.patch.yml` 挂 `dsh-hooks-claude-code`，`configPath` 指向本仓库 CC 格式的 hooks.json，`pluginRoot` 替换 `${CLAUDE_PLUGIN_ROOT}`；`skills/` 加入 `customSkillDirs`。CC 与 dsh 共用一份 hooks.json，Codex 另有一份。地图标签页等界面适配以后单独放 `adapters/dsh`。

## 3. 目录草案

```
skills/            gis-view、gis-composer、gis-doctor（三家共用）
hooks/scripts/     标准库 Python，带 --harness 参数
hooks/hooks.json   CC 格式（dsh 经桥接复用）
hooks.codex.json   Codex 格式
.claude-plugin/plugin.json
.codex-plugin/plugin.json
adapters/dsh/cordis.patch.yml
```

## 4. 待实测

- Codex 是否加载插件自带的 hooks.json（已见插件根目录带该文件，但清单未声明），以及 hook 事件中的实际工具名。
- Codex 与 dsh 中经 shell 读取 GIS 文件时，hook 能否可靠识别。
- dsh 桥接只读一个 `configPath`；用户已有自己的 CC hooks 时，需合并或挂两个桥接实例。

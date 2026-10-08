# 多宿主适配

外壳面向 Claude Code（CC）、Codex 与 dsh 三个宿主。原则：**skills 与 hooks 脚本只写一份，各宿主只加一层清单。** 本文记录 2026-10-08 在本机（Codex 0.144.1、dsh 0.1.5-rc.1）核对的差异，宿主升级后需复核。

## 1. 差异

| | Claude Code | Codex | dsh |
|---|---|---|---|
| 插件清单 | `.claude-plugin/plugin.json` | `.codex-plugin/plugin.json`（`skills`、`mcpServers`、`interface`） | 无统一清单；profile 为 npm 包 + `cordis.patch.yml` 补丁层 |
| skills | `skills/<name>/SKILL.md` | 同格式 | 同格式；扫描 `.agents/skills`、`<dshHome>/skills`、`customSkillDirs` |
| hooks | `hooks/hooks.json`，`${CLAUDE_PLUGIN_ROOT}` | 清单 `hooks` 字段指向的 json；已见插件根 `hooks.json` 与读取 `CLAUDE_PLUGIN_ROOT` 的写法 | 经 `dsh-hooks-claude-code` / `dsh-hooks-codex` 桥接运行 CC 或 Codex 格式 |
| MCP | `.mcp.json` | `.mcp.json` | `dsh-mcp-client`，每个 server 一项 |
| 用户配置 | `userConfig`（值只传给 hook 进程与 skill 文本，不进 Bash 工具环境） | 未见对应字段 | profile YAML |
| 安装方式 | 本地 marketplace，原地加载 | 本地 marketplace，**复制**进缓存，改动后需重装 | 无插件安装；skills 由 agent preset 扫描 `<dshHome>/skills` 等目录 |

## 2. 设计决定

1. **引擎位置用环境变量配置**：`GIS_KIT_CMD`、`GIS_VIEW_CMD`、`GIS_COMPOSER_CMD`（命令行字符串，按 shell 规则拆分），hook 解释器用 `GIS_PLUGIN_PYTHON`（默认 `python3`）。暂不使用 CC 的 userConfig：它的值进不了模型经 Bash 运行 doctor 的环境，只会造成两套配置。
2. **doctor 是 skill 自带的标准库脚本**（`skills/gis-doctor/scripts/gis_doctor.py`），三家都通过 skill 或 shell 调用，不依赖斜杠命令。
3. **hooks 只用三家共同可用的子集**：`PreToolUse` 的 deny（源数据保护）、`PostToolUse` 的 `additionalContext`（元数据注入）。不依赖 `SessionStart` 首轮注入（dsh 中异步执行）与 `updatedInput`（dsh 不支持）。
4. **hook 脚本带 `--harness cc|codex|dsh`**，先把各家的工具名和参数归一，再走共用逻辑。CC 为 `Read`/`Edit`/`Bash` 等；Codex 以 shell 与 `apply_patch` 为主；dsh 为自家 fs、bash、str-replace-editor 工具。
5. **dsh 接入**：skills 以软链放入 `<dshHome>/skills`（与 gis-kit 相同）；web profile 中宿主层 `skill-filesystem` 已禁用，由各 agent preset 负责发现，因此不走 `customSkillDirs` 补丁。有 hooks 后，`adapters/dsh/cordis.patch.yml` 挂 `dsh-hooks-claude-code`，`configPath` 指向本仓库 hooks.json，`pluginRoot` 替换 `${CLAUDE_PLUGIN_ROOT}`。地图标签页等界面适配以后单独放 `adapters/dsh`。

## 3. 目录草案

```
skills/            gis-view、gis-composer、gis-doctor（三家共用）
hooks/scripts/     标准库 Python，带 --harness 参数
hooks/hooks.json   CC 格式（dsh 经桥接复用；Codex 能否共用待实测）
.claude-plugin/plugin.json        CC 清单
.claude-plugin/marketplace.json   CC 本地 marketplace
.codex-plugin/plugin.json         Codex 清单
.agents/plugins/marketplace.json  Codex 本地 marketplace
adapters/dsh/cordis.patch.yml     有 hooks 后再加
```

## 4. 安装与配置

以下均为示例，安装须用户执行或明确授权。`<repo>` 为本仓库绝对路径。

| 宿主 | 安装 | 引擎环境变量 |
|---|---|---|
| CC | `claude plugin marketplace add <repo>`，再 `claude plugin install gis-plugin@gis-plugin` | `~/.claude/settings.json` 的 `env` |
| Codex | `codex plugin marketplace add <repo>`，再 `codex plugin add gis-plugin@gis-plugin`；更新后重新 add | 启动 Codex 的 shell 中导出（默认继承），或 `config.toml` 的 `shell_environment_policy.set` |
| dsh | `ln -s <repo>/skills/gis-doctor ~/.dsh/skills/gis-doctor` | 启动 dsh 的 shell 中导出 |

已核对：`claude plugin validate --strict` 通过两份清单与 `skills/`；隔离 `CODEX_HOME` 中 Codex marketplace 添加与插件安装成功。

## 5. 待实测

- Codex 插件 hooks：清单支持 `"hooks": "./hooks/....json"`，已见第三方插件让 CC 与 Codex 共用一份 hooks 文件并读取 `CLAUDE_PLUGIN_ROOT`；本仓库能否共用及 hook 事件中的实际工具名待实测。
- 三家会话中 skill 是否被发现并能运行 doctor（目前只验证了清单与安装，未在会话中实测）。
- Codex 与 dsh 中经 shell 读取 GIS 文件时，hook 能否可靠识别。
- dsh 桥接只读一个 `configPath`；用户已有自己的 CC hooks 时，需合并或挂两个桥接实例。

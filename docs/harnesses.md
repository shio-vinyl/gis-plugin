# 多宿主适配

外壳面向 Claude Code（CC）、Codex 与 dsh 三个宿主。原则：**skills 与 hooks 脚本只写一份，各宿主只加一层清单。** 本文记录 2026-10-08 在本机（Codex CLI 0.160.0、Codex App 内置 CLI 0.162.0-alpha.2、dsh CLI 0.1.5-rc.1；之后 dsh 只用 App 0.2.0-rc.2）核对的差异，宿主升级后需复核。

## 1. 差异

| | Claude Code | Codex | dsh |
|---|---|---|---|
| 插件清单 | `.claude-plugin/plugin.json` | `.codex-plugin/plugin.json`（`skills`、`hooks`、`mcpServers`、`interface`） | 无统一清单；profile 为 npm 包 + `cordis.patch.yml` 补丁层 |
| skills | `skills/<name>/SKILL.md` | 同格式 | 同格式；由 agent preset 扫描 `<dshHome>/skills`、`.agents/skills` 等 |
| hooks | 默认 `hooks/hooks.json` | 清单 `hooks` 字段指向的文件，可与 CC 共用；新 hook 须经用户信任才运行 | 经 `dsh-hooks-claude-code` 桥接运行 CC 格式 |
| `CLAUDE_PLUGIN_ROOT` | 命令中替换并导出 | 由 Codex 设置并导出 | 桥接按 `pluginRoot` 在命令中替换，不导出 |
| MCP | `.mcp.json` | `.mcp.json` | `dsh-mcp-client`，每个 server 一项 |
| 用户配置 | `userConfig`（值只传给 hook 进程与 skill 文本，不进 Bash 工具环境） | 无对应字段 | profile YAML |
| 安装方式 | 本地 marketplace，原地加载 | 本地 marketplace，**复制**进缓存，改动后需重装；CLI 与 App 共用 `~/.codex` | 无插件安装；skills 软链进 `<dshHome>/skills` |
| CLI 与 App | — | 版本不同，配置共用 | 各自带一套 dsh 代码与 Node（App 用 `desktop` profile），只共用 `~/.dsh` |

`PreToolUse` 实测载荷（tool_name → 写入目标所在字段）：

| 宿主 | 文件工具 | shell | 其它 |
|---|---|---|---|
| CC | `Write`、`Edit`、`MultiEdit` → `file_path`；`NotebookEdit` → `notebook_path` | `Bash` → `command` | 载荷含 `cwd` |
| Codex | `apply_patch` → `command`（补丁文本，`*** Add/Update/Delete File:`、`*** Move to:` 行） | `Bash` → `command` | 载荷含 `cwd` |
| dsh 桥接 | `edit`、`write` → `file_path` | `bash` → `command`，可带 `workdir` | 载荷含 `cwd` |

## 2. 设计决定

1. **引擎位置用环境变量配置**：`GIS_KIT_CMD`、`GIS_VIEW_CMD`、`GIS_COMPOSER_CMD`（命令行字符串，按 shell 规则拆分）。暂不使用 CC 的 userConfig：它的值进不了模型经 Bash 运行 doctor 的环境，只会造成两套配置。
2. **doctor 是 skill 自带的标准库脚本**（`skills/gis-doctor/scripts/gis_doctor.py`），三家都通过 skill 或 shell 调用，不依赖斜杠命令。
3. **hooks 只用三家共同可用的子集**：`PreToolUse` 的 deny（源数据保护）、`PostToolUse` 的 `additionalContext`（元数据注入）。不依赖 `SessionStart` 首轮注入（dsh 中异步执行）与 `updatedInput`（dsh 不支持）。deny 用 CC 的 JSON 形式（`hookSpecificOutput.permissionDecision`），CC 与 Codex 实测生效。
4. **一份 hooks.json、一个脚本**：三家工具名互不冲突，脚本按 tool_name（不区分大小写）识别写入目标，不需要 `--harness` 参数。matcher 为 `^(Write|Edit|MultiEdit|NotebookEdit|Bash|apply_patch|write|edit|bash)$`，命令为 `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/<script>.py"`。`GIS_PLUGIN_PYTHON` 覆盖尚未接入 hooks。
5. **dsh 接入**：skills 软链进 `<dshHome>/skills`（web profile 中宿主层 `skill-filesystem` 已禁用，由 agent preset 发现）；hooks 用 profile 补丁挂 `dsh-hooks-claude-code`，见 §4。地图标签页等界面适配以后放 `adapters/dsh`。

## 3. 目录

```
skills/                           gis-doctor（以后加 gis-view、gis-composer）
hooks/hooks.json                  三家共用（CC 默认位置；Codex 经清单引用；dsh 经桥接）
hooks/scripts/                    标准库 Python
.claude-plugin/plugin.json        CC 清单
.claude-plugin/marketplace.json   CC 本地 marketplace
.codex-plugin/plugin.json         Codex 清单
.agents/plugins/marketplace.json  Codex 本地 marketplace
```

## 4. 安装与配置

以下均为示例，安装须用户执行或明确授权。`<repo>` 为本仓库绝对路径。

| 宿主 | 安装 | 引擎环境变量 |
|---|---|---|
| CC | `claude plugin marketplace add <repo>`，再 `claude plugin install gis-plugin@gis-plugin` | `~/.claude/settings.json` 的 `env` |
| Codex（CLI 与 App） | `codex plugin marketplace add <repo>`，再 `codex plugin add gis-plugin@gis-plugin`；更新后重新 add；首次使用时在 Codex 中信任本插件 hooks | `config.toml` 的 `[shell_environment_policy.set]`（App 不继承终端环境） |
| dsh | `ln -s <repo>/skills/gis-doctor ~/.dsh/skills/gis-doctor`；hooks 见下 | `~/.dsh/.env`（App 与 CLI 启动时都读取并传给子进程） |

dsh 的 hooks 补丁（追加到 profile 的 `cordis.patch.yml`，或用 `--patch` 叠加）：

```yaml
- insert:
    - id: gis-plugin-hooks
      name: '@deepseek-ai/dsh-hooks-claude-code'
      config:
        configPath: <repo>/hooks/hooks.json
        pluginRoot: <repo>
```

## 5. 实测记录（2026-10-08）

- 清单：`claude plugin validate --strict` 通过；Codex 在隔离 `CODEX_HOME` 中添加 marketplace 与安装成功。
- doctor：CC（`claude -p`）、Codex（`codex exec`，含 App 内置 CLI 仅靠 `config.toml` 环境变量）、dsh（`--profile headless`）中，模型都能发现 `gis-doctor` 并运行，输出一致。
- 源数据保护：登记 `raw/**` 后要求模型改写 `raw/a.csv`。CC 的 `Edit` 与 `Bash`、Codex 的 `apply_patch` 与 `Bash` 均被拦截，文件未变，模型转述了登记位置与原因。Codex 测试使用 `--dangerously-bypass-hook-trust` 代替交互信任。
- dsh：桥接确实调用了 hook，但本机装有第三方插件 dsh-purge，它改写了 dsh 全局安装中的 `dsh-hooks-claude-code`、`dsh-hooks-codex`、`dsh-sandbox` 等包，使 hook 的 deny 永不生效，因此写入未被拦截；升级到 dsh-purge 1.1.64 后复测仍相同。已提 [YuJunZhiXue/dsh-purge#80](https://github.com/YuJunZhiXue/dsh-purge/issues/80) 请求单独关闭该补丁。未装 dsh-purge 的 dsh 待复测。

## 6. 待实测

- 以上 dsh 实测均在 CLI 0.1.5-rc.1 上进行（该 CLI 已卸载）。App 0.2.0-rc.2 上 doctor 已实测通过（引擎变量来自 `~/.dsh/.env`）；hook 未测，App 内置的桥接同样被 dsh-purge 改写。
- 未经 dsh-purge 改写的 dsh 上，deny 是否生效；dsh-purge#80 有进展后复测。
- `PostToolUse` 的 `additionalContext` 在三家的表现（元数据注入用）。
- dsh 桥接只读一个 `configPath`；用户已有自己的 CC hooks 时，需合并或挂两个桥接实例。

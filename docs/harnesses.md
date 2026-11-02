# 多宿主适配

外壳面向 Claude Code（CC）、Codex 与 dsh 三个宿主。原则：**skills 与 hooks 脚本只写一份，各宿主只加一层清单。** 本文记录 2026-10-08 在本机（Codex CLI 0.160.0、Codex App 内置 CLI 0.162.0-alpha.2、dsh CLI 0.1.5-rc.1；之后 dsh 只用 App 0.2.0-rc.2）核对的差异，宿主升级后需复核。dsh 的 hooks 部分已于 2026-11-02 按 App 0.2.1-rc.3 复核。

## 1. 差异

| | Claude Code | Codex | dsh |
|---|---|---|---|
| 插件清单 | `.claude-plugin/plugin.json` | `.codex-plugin/plugin.json`（`skills`、`hooks`、`mcpServers`、`interface`） | 无统一清单；profile 为 npm 包 + `cordis.patch.yml` 补丁层 |
| skills | `skills/<name>/SKILL.md` | 同格式 | 同格式；由 agent preset 扫描 `<dshHome>/skills`、`.agents/skills` 等 |
| hooks | 默认 `hooks/hooks.json` | 清单 `hooks` 字段指向的文件，可与 CC 共用；新 hook 须经用户信任才运行 | 经 `dsh-hooks-claude-code` 桥接运行 CC 格式；App 0.2.1 起桥接不随 App 打包，须装进 profile，版本与 App 相同 |
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
| dsh 桥接 | `edit`、`write` → `file_path` | `bash`（Windows 上是 `pwsh`）→ `command`，可带 `workdir` | 载荷含 `cwd` |

## 2. 设计决定

1. **引擎位置**（现写在共用文件 `~/.config/gis-plugin/engines.env`，同名环境变量优先）：`GIS_KIT_CMD`、`GIS_VIEW_CMD`、`GIS_COMPOSER_CMD`（命令行字符串，按 shell 规则拆分；composer 指向 `node <runtime>/src/agent-entry.js`）。这些变量只供 doctor 与 hooks 使用；各引擎的 skill 入口在其仓库内直接调用本仓库 CLI，不读它们。暂不使用 CC 的 userConfig：它的值进不了模型经 Bash 运行 doctor 的环境，只会造成两套配置。
2. **doctor 是 skill 自带的标准库脚本**（`skills/gis-doctor/scripts/gis_doctor.py`），三家都通过 skill 或 shell 调用，不依赖斜杠命令。
3. **hooks 只用三家共同可用的子集**：`PreToolUse` 的 deny（源数据保护）、`PostToolUse` 的 `additionalContext`（元数据注入）。不依赖 `SessionStart` 首轮注入（dsh 中异步执行）与 `updatedInput`（dsh 不支持）。deny 用 CC 的 JSON 形式（`hookSpecificOutput.permissionDecision`），CC 与 Codex 实测生效。
4. **一份 hooks.json、一个脚本**：三家工具名互不冲突，脚本按 tool_name（不区分大小写）识别写入目标，不需要 `--harness` 参数。matcher 为 `^(Write|Edit|MultiEdit|NotebookEdit|Bash|PowerShell|apply_patch|write|edit|bash|powershell|pwsh)$`，命令为 `"${GIS_PLUGIN_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/<script>.py"`；解释器覆盖在 CC 与 Codex 实测生效。
5. **dsh 接入**：skill 目录软链进 `<dshHome>/skills`（web profile 中宿主层 `skill-filesystem` 已禁用，由 agent preset 发现）；hooks 用 profile 补丁挂 `dsh-hooks-claude-code`，见 §4。地图标签页等界面适配以后放 `adapters/dsh`。

## 3. 目录

```
skills/                           只有 gis-doctor；引擎入口在各引擎仓库根目录的 SKILL.md
hooks/hooks.json                  三家共用（CC 默认位置；Codex 经清单引用；dsh 经桥接）
hooks/scripts/                    标准库 Python
.claude-plugin/plugin.json        CC 清单
.claude-plugin/marketplace.json   CC 本地 marketplace
.codex-plugin/plugin.json         Codex 清单
.agents/plugins/marketplace.json  Codex 本地 marketplace
```

## 4. 安装与配置

以下均为示例，安装须用户执行或明确授权。`<repo>` 为本仓库绝对路径。

| 宿主 | 安装 | 备注 |
|---|---|---|
| CC | `claude plugin marketplace add <repo>`，再 `claude plugin install gis-plugin@gis-plugin` | — |
| Codex（CLI 与 App） | `codex plugin marketplace add <repo>`，再 `codex plugin add gis-plugin@gis-plugin`；更新后重新 add；首次使用时在 Codex 中信任本插件 hooks | App 与 CLI 共用 `~/.codex` |
| dsh | `ln -s <repo>/skills/gis-doctor ~/.dsh/skills/gis-doctor`；hooks 见下 | App 与 CLI 共用 `~/.dsh` |

各引擎的 skill 不随外壳安装：把 gis-kit、gis-view、gis-composer 的仓库目录分别软链或复制为 `~/.claude/skills/<name>`、`~/.codex/skills/<name>`、`~/.dsh/skills/<name>`，各自独立可用（gis-kit 另见其 README）。

更新已装的引擎 skill（gis-kit、gis-composer、gis-view）：

```bash
python3 scripts/update_engine_skills.py --dry-run
python3 scripts/update_engine_skills.py
```

脚本逐个检查 `~/.claude/skills`、`~/.codex/skills`、`~/.agents/skills`、`~/.dsh/skills`（`CLAUDE_CONFIG_DIR`、`CODEX_HOME` 生效），按安装方式处理：软链随源仓库，不处理；git clone 在工作区干净时 `pull --ff-only`；Codex 的单文件入口按源仓库 `SKILL.md` 重建，只把“本 skill 的目录即运行时仓库”一行改写为源仓库路径，找不到该行时报错且不写入。源仓库由 `engines.env` 的引擎命令定位。未安装的只报告，不安装。要不要更新，先看 `gis-doctor`：它把各宿主里的副本与源仓库逐文件比对，落后时列出缺少或不同的文件。

引擎位置三家共用 `~/.config/gis-plugin/engines.env`（`GIS_*_CMD="..."` 每行一个），无需在各宿主配置中重复；同名环境变量优先。Windows 上命令里的反斜杠按路径分隔符处理，`C:\tools\gis.py` 不用改写；路径带空格时加引号。

**Windows 上的 hook 解释器：** `hooks.json` 的 `${GIS_PLUGIN_PYTHON:-python3}` 是 POSIX shell 语法，而 Windows 的 `python3` 常常只是应用商店占位程序。宿主如果不经 POSIX shell 运行 hook，这个写法不会展开，设了 `GIS_PLUGIN_PYTHON` 也没用。dsh 桥接在 Windows 上用什么 shell 运行 hook 还没有实测（见 §6），在此之前不要假定 Windows 上的 hook 在运行，先写一次受保护文件确认。

**版本号与更新**：`.claude-plugin/plugin.json` 与 `.codex-plugin/plugin.json` 的 `version` 保持一致（测试检查）。版本号相同时 CC 的 `claude plugin update` 视为已是最新、不会刷新安装副本（2026-10-10 实测），因此改动进入安装副本且影响行为（skills、hooks、清单）时随同一提交提版本：1.0 之前，删除或不兼容（如移除 skill、改变读取的约定版本）提 minor，其余提 patch；只改文档、测试、evals 不提。推送后更新各宿主：

```bash
claude plugin marketplace update gis-plugin
claude plugin update gis-plugin@gis-plugin
codex plugin add gis-plugin@gis-plugin
```

dsh 的 skill 软链与桥接配置直接指向本仓库，本仓库更新后无需更新；App 升级后要重装同版本桥接，见下。

dsh 的 hooks 补丁（追加到 profile 的 `cordis.patch.yml`，或用 `--patch` 叠加）：

```yaml
- insert:
    - id: gis-plugin-hooks
      name: '@deepseek-ai/dsh-hooks-claude-code'
      config:
        configPath: <repo>/hooks/hooks.json
        pluginRoot: <repo>
```

App 0.2.1 起只写补丁不够：桥接不再随 App 打包，包不在 profile 里时启动报 `ERR_MODULE_NOT_FOUND`，hook 不运行，受保护文件照样能写。要把桥接装进 profile（以下示例须用户授权执行，`dsh` 指 App 自带的，运行方式见 §5）：

```bash
dsh plugin --profile <profile> add -w --save-exact @deepseek-ai/dsh-hooks-claude-code@<App 版本>
```

- 版本必须等于 `dsh --version`，`latest`、`next` 都不能用。桥接的 peer 依赖锁定同版本，由 pnpm 一起安装（试装时共 34 个包、21 MB）。
- 要加 `-w`：profile 目录自身是 pnpm workspace 根，不加会报 `ERR_PNPM_ADDING_TO_ROOT`。安装时提示 `declares no dsh.bundle` 不影响挂载。
- App 升级后要按新版本重装。`gis-doctor` 会检查包是否装了、版本是否等于 App 版本；它是静态检查，要确认 hook 真在运行，还得写一次受保护文件。

桥接一个实例只读一个 `configPath`。已有自己的 CC hooks 时不必合并文件，在同一个 `insert` 下再挂一个实例（另起 `id`，`configPath` 指向自己的 `settings.json` 或 `hooks.json`）即可，两份互不影响。

dsh-purge 的补丁 30/31 会把桥接里的 `deny` 判断替换成永不命中的哨兵值，使用户自己 hook 的 deny 永久失效（上游 issue [YuJunZhiXue/dsh-purge#80](https://github.com/YuJunZhiXue/dsh-purge/issues/80)）。**1.1.66** 起可在清洗页关掉：设置文件 `~/.dsh/dsh-purge/hooks-deny.json` 写 `{"hooksDenyBypass": false}`，插件同时排除补丁 30/31/64/65，并把宿主文件写回官方形态。

## 5. 实测记录（2026-10-08）

- 清单：`claude plugin validate --strict` 通过；Codex 在隔离 `CODEX_HOME` 中添加 marketplace 与安装成功。
- doctor：CC（`claude -p`）、Codex（`codex exec`，含 App 内置 CLI 仅靠 `config.toml` 环境变量）、dsh（`--profile headless`）中，模型都能发现 `gis-doctor` 并运行，输出一致。
- 源数据保护：登记 `raw/**` 后要求模型改写 `raw/a.csv`。CC 的 `Edit` 与 `Bash`、Codex 的 `apply_patch` 与 `Bash` 均被拦截，文件未变，模型转述了登记位置与原因。Codex 测试使用 `--dangerously-bypass-hook-trust` 代替交互信任。
- 元数据注入：CC 中 `UserPromptSubmit` 与 `PostToolUse`（Bash）都注入卡片，模型不调用工具即可答出字段、CRS、分辨率与 NoData；`settings.json` 的 `env` 会传给 hook。Codex 中 hook 运行正常，但 `shell_environment_policy.set` **只作用于 shell 工具、不传给 hook**，因此引擎位置改为共用文件 `engines.env`；改后 Codex 进程环境中没有任何 `GIS_*` 变量时仍正常注入。
- dsh：桥接确实调用了 hook，但本机装有第三方插件 dsh-purge，它改写了 dsh 全局安装中的 `dsh-hooks-claude-code`、`dsh-hooks-codex`、`dsh-sandbox` 等包，使 hook 的 deny 永不生效，因此写入未被拦截；升级到 dsh-purge 1.1.64 后复测仍相同。已提 [YuJunZhiXue/dsh-purge#80](https://github.com/YuJunZhiXue/dsh-purge/issues/80) 请求单独关闭该补丁。未装 dsh-purge 的 dsh 待复测。
- 进展（2026-10-09）：dsh-purge **1.1.66**（`09bac57f`）按 #80 加了开关，上游 issue 已关闭；本机装的是其后的 master（`3df4f48`，含 #84 宿主崩溃修复）。已把 `hooksDenyBypass` 设为 `false`，`dsh-hooks-claude-code`、`dsh-hooks-codex` 写回官方形态、与旁边的 `.dshpurge.bak` 逐字节一致（`diff` 为空），文件内不再有旁路标记；桥接已挂进本机 `desktop` profile。`protect_sources.py` 在桥接 payload 形态下（`tool_name`/`tool_input`/`cwd`）离线验证通过：受保护路径的 `write`、`bash` 重定向与 `rm` 都返回 `permissionDecision: deny`，未登记路径无输出，退出码均为 0。
- dsh 在环实测（2026-10-10）：用 App 0.2.0-rc.2 自带的 dsh（`ELECTRON_RUN_AS_NODE=1` 运行 App 可执行文件 + 包内 `dsh/lib/bin.js`）以 `--profile headless --patch <桥接 overlay>` 跑真实模型回合，夹具在仓库外、登记 `raw/**`：
  - 拦截：`edit` 改 `raw/a.csv`、`bash` 执行 `printf ... > raw/a.csv` 都返回 hook 的拒绝原因（工具结果 `status: error`），文件哈希不变；模型转述了登记位置并拒绝绕过。
  - 注入：提示中提到 `data/pts.geojson` 时（`UserPromptSubmit`），模型不调用工具即答出字段、EPSG:4326 与要素数；提示不含完整路径、仅 `bash` 命令带上路径时（`PostToolUse`），卡片同样进入上下文。
  - 观察：`PostToolUse` 卡片出现在工具结果之后，DeepSeek 模型一次把它当作“非自己工具产生的未验证内容”，只转述、不采信。之后在卡片前加一行事实性来源说明（gis-plugin hook 实际运行 `gis-kit describe --json` 所得），同一场景复测 3 次均直接采信并注明出处。
- Codex `PostToolUse` 注入（2026-10-10，CLI 0.160.0）：在隔离 `CODEX_HOME` 中装当前版本，hook 信任沿用用户已有的 `hooks.state` 记录（`hooks.json` 未变，哈希一致），`codex exec -s read-only` 跑 3 次。提示不含完整路径、仅 shell 命令带上路径，3 次都在 `PostToolUse` 收到卡片，模型不再调用工具即答出字段、EPSG:4326 与要素数，并注明来自注入的元数据。
- dsh 两个桥接实例并存（2026-10-10）：一个挂 gis-plugin，一个挂模拟的用户 CC hooks（`UserPromptSubmit` 注入标记、`PreToolUse` 写日志）。用户的注入与 gis-plugin 的拦截同时生效；未被拦截的 `bash` 调用两边都执行，被 gis-plugin deny 的调用不再执行用户的 `PreToolUse`（日志无记录），与“deny 即终止”的语义一致。
- dsh App 0.2.1-rc.3（2026-11-02，[#27](https://github.com/shioo-gis/gis-plugin/issues/27)、[#28](https://github.com/shioo-gis/gis-plugin/issues/28)）：macOS 和 Windows 上桥接包都解析失败。macOS 的 `desktop` profile 真实回合中，写入和删除受保护文件全部成功，启动报 `ERR_MODULE_NOT_FOUND`。
- 桥接试装（2026-11-02，隔离 profile，已回滚）：按 §4 安装后启动不再报模块错误；加载已装的桥接模块、用模拟事件离线运行，`edit`、`write`、`bash` 重定向、`rm` 都 deny，`PostToolUse` 和 `UserPromptSubmit` 都有卡片。profile 里的副本没有 dsh-purge 的补丁痕迹。profile 和 App 内置包形成两套模块，这次能加载，单例是否一致未验证。真实模型回合未跑：`headless` 模板禁用了 `credentials` 插件，启动报 `MISSING_CREDENTIAL`。
- 大小写绕过（2026-11-02，[#26](https://github.com/shioo-gis/gis-plugin/issues/26)）：Codex 真实回合中，`apply_patch`、重定向、`rm`、`cp`、`mv` 写 `RAW/...` 都未被拦截，文件实际改变。现已修复并有离线测试，尚未回到宿主真实回合复测。

## 6. 待实测

- dsh 0.2.1 真实模型回合：deny、两种注入，以及模型是否采信卡片。
- App 升级后，旧版本桥接的实际表现，以及桌面界面有没有提示。
- 大小写判定在 Windows 和真实宿主回合中的表现。
- Windows：dsh 桥接和 CC 用什么 shell 运行 hook，`${GIS_PLUGIN_PYTHON:-python3}` 能否展开；桥接的 stdout 按什么编码读。
- `pwsh`、`PowerShell` 工具的载荷字段：`protect_sources.py` 按 `tool_input.command` 读，目前只有离线验证。

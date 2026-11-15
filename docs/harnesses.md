# 多宿主适配

外壳面向 Claude Code（CC）、Codex 与 DeepSeek Harness（命令行为 `dsh`）三个宿主。原则：**skills 与 hooks 脚本只写一份，各宿主只加一层清单。** 下面的差异按 Codex CLI 0.160.0、DeepSeek Harness App 0.2.1-rc.3（Windows 上 0.2.1-rc.5）、CC 2.1.258 核对，宿主升级后需复核。各宿主的实测记录和还没实测的项目记在 [#43](https://github.com/shioo-gis/gis-plugin/issues/43)。

## 1. 差异

| | Claude Code | Codex | DeepSeek Harness |
|---|---|---|---|
| 插件清单 | `.claude-plugin/plugin.json` | `.codex-plugin/plugin.json` | 无统一清单；profile 为 npm 包 + `cordis.patch.yml` 补丁层 |
| skills | `skills/<name>/SKILL.md` | 同格式 | 同格式；由 agent preset 扫描 `<dshHome>/skills`、`.agents/skills` 等 |
| hooks | 默认 `hooks/hooks.json` | 清单 `hooks` 字段指向的文件，可与 CC 共用；新 hook 须经用户信任才运行 | 经 `dsh-hooks-claude-code` 桥接运行 CC 格式；App 0.2.1 起桥接不随 App 打包，须装进 profile，版本与 App 相同 |
| `CLAUDE_PLUGIN_ROOT` | 命令中替换并导出 | 由 Codex 设置并导出 | 桥接按 `pluginRoot` 在命令中替换，不导出 |
| hook 命令的 shell | 见 §4“hook 命令” | 见 §4“hook 命令” | 见 §4“hook 命令” |
| MCP | `.mcp.json` | `.mcp.json` | `dsh-mcp-client`，每个 server 一项 |
| 用户配置 | `userConfig`（值只传给 hook 进程与 skill 文本，不进 Bash 工具环境） | 无对应字段 | profile YAML |
| 安装方式 | 本地 marketplace，原地加载 | 本地 marketplace，**复制**进缓存，改动后需重装；CLI 与 App 共用 `~/.codex` | 无插件安装；skills 软链进 `<dshHome>/skills` |
| CLI 与 App | — | 版本不同，配置共用 | 各自带一套 DeepSeek Harness 代码与 Node（App 用 `desktop` profile），只共用 `~/.dsh` |

`PreToolUse` 实测载荷（tool_name → 写入目标所在字段）：

| 宿主 | 文件工具 | shell | 其它 |
|---|---|---|---|
| CC | `Write`、`Edit`、`MultiEdit` → `file_path`；`NotebookEdit` → `notebook_path` | `Bash` → `command` | 载荷含 `cwd` |
| Codex | `apply_patch` → `command`（补丁文本，`*** Add/Update/Delete File:`、`*** Move to:` 行） | `Bash` → `command` | 载荷含 `cwd` |
| DeepSeek Harness 桥接 | `edit`、`write` → `file_path` | `bash`（Windows 上是 `pwsh`）→ `command`，可带 `workdir` | 载荷含 `cwd` |

## 2. 设计决定

1. **引擎位置**（现写在共用文件 `~/.config/gis-plugin/engines.env`，同名环境变量优先）：`GIS_KIT_CMD`、`GIS_VIEW_CMD`、`GIS_COMPOSER_CMD`（命令行字符串，按 shell 规则拆分；composer 指向 `node <runtime>/src/agent-entry.js`）。这些变量只供 doctor 与 hooks 使用；各引擎的 skill 入口在其仓库内直接调用本仓库 CLI，不读它们。系列里没有引擎命令的成员（plan-deck、chart-forms、plan-diagram、house-style）用 `GIS_PLAN_DECK_REPO`、`GIS_CHART_FORMS_REPO`、`GIS_PLAN_DIAGRAM_REPO`、`GIS_HOUSE_STYLE_REPO` 指向含 `SKILL.md` 的目录，只供 doctor 和更新脚本对比、重建副本；不设时软链照常报告，副本报“未对比”。暂不使用 CC 的 userConfig：它的值进不了模型经 Bash 运行 doctor 的环境，只会造成两套配置。
2. **doctor 是 skill 自带的标准库脚本**（`skills/gis-doctor/scripts/gis_doctor.py`），三家都通过 skill 或 shell 调用，不依赖斜杠命令。
3. **hooks 只用三家共同可用的子集**：`PreToolUse` 的 deny（源数据保护）、`UserPromptSubmit` 与 `PostToolUse` 的 `additionalContext`（元数据注入；项目样式只用 `UserPromptSubmit`）、`PostToolUse` 顶层的 `decision: "block"` 和 `reason`（产物用语检查；CC 按文档、DeepSeek Harness 桥接按代码会把 `reason` 交给模型，Codex 未实测）。不依赖 `SessionStart` 首轮注入（DeepSeek Harness 中异步执行）与 `updatedInput`（DeepSeek Harness 不支持）。“每个会话一次”靠载荷里的 `session_id` 记在 `~/.cache/gis-plugin/`（`GIS_PLUGIN_STATE` 可改），CC 和 DeepSeek Harness 桥接都带这个字段，Codex 未核对；载荷没有 `session_id` 时项目样式每条消息都注入，宁可重复也不漏。DeepSeek Harness 的 `UserPromptSubmit` 挂在每一步之前，不去重就会每步重复。deny 用 CC 的 JSON 形式（`hookSpecificOutput.permissionDecision`），CC 与 Codex 实测生效。
4. **一份 hooks.json、一个脚本**：三家工具名互不冲突，脚本按 tool_name（不区分大小写）识别写入目标，不需要 `--harness` 参数。matcher 为 `^(Write|Edit|MultiEdit|NotebookEdit|Bash|PowerShell|apply_patch|write|edit|bash|powershell|pwsh)$`，命令同时能被 POSIX shell 和 PowerShell 解析，写法和取舍见 §4“hook 命令”；`GIS_PLUGIN_PYTHON` 覆盖在 CC 与 Codex 实测生效。
5. **DeepSeek Harness 接入**：skill 目录软链进 `<dshHome>/skills`（web profile 中宿主层 `skill-filesystem` 已禁用，由 agent preset 发现）；hooks 用 profile 补丁挂 `dsh-hooks-claude-code`，见 §4。地图标签页等界面适配以后放 `adapters/dsh`。

## 3. 目录

```
skills/                           只有 gis-doctor；引擎入口在各引擎仓库根目录的 SKILL.md
hooks/hooks.json                  三家共用（CC 默认位置；Codex 经清单引用；DeepSeek Harness 经桥接）
hooks/scripts/                    标准库 Python
.claude-plugin/plugin.json        CC 清单
.claude-plugin/marketplace.json   CC 本地 marketplace
.codex-plugin/plugin.json         Codex 清单
.agents/plugins/marketplace.json  Codex 本地 marketplace
```

## 4. 安装与配置

以下均为示例，安装须用户执行或明确授权。`<repo>` 为本仓库本地克隆的绝对路径（`git clone https://github.com/shioo-gis/gis-plugin.git <repo>`）。

| 宿主 | 安装 | 备注 |
|---|---|---|
| CC | `claude plugin marketplace add <repo>`，再 `claude plugin install gis-plugin@gis-plugin` | — |
| Codex（CLI 与 App） | `codex plugin marketplace add <repo>`，再 `codex plugin add gis-plugin@gis-plugin`；更新后重新 add；首次使用时在 Codex 中信任本插件 hooks | App 与 CLI 共用 `~/.codex` |
| DeepSeek Harness | `ln -s <repo>/skills/gis-doctor ~/.dsh/skills/gis-doctor`；hooks 见下 | App 与 CLI 共用 `~/.dsh` |

各引擎的 skill 不随外壳安装：把 gis-kit、gis-view、gis-composer 的仓库目录分别软链或复制为 `~/.claude/skills/<name>`、`~/.codex/skills/<name>`、`~/.dsh/skills/<name>`，各自独立可用（gis-kit 另见其 README）。

更新已装的系列 skill（引擎 gis-kit、gis-composer、gis-view，以及 plan-deck、chart-forms、plan-diagram、house-style）：

```bash
python3 scripts/update_engine_skills.py --dry-run
python3 scripts/update_engine_skills.py
```

脚本逐个检查 `~/.claude/skills`、`~/.codex/skills`、`~/.agents/skills`、`~/.dsh/skills`（`CLAUDE_CONFIG_DIR`、`CODEX_HOME` 生效），按安装方式处理：软链随源仓库，不处理；git clone 在工作区干净时 `pull --ff-only`；Codex 的单文件入口按源仓库 `SKILL.md` 重建，只把“本 skill 的目录即运行时仓库”一行改写为源仓库路径，找不到该行时报错且不写入。复制来的普通目录（不是 git clone）报错，不更新。源仓库由 `engines.env` 的引擎命令定位，其它成员由 `GIS_*_REPO` 定位（见 §2 第 1 条）。未安装的只报告，不安装。要不要更新，先看 `gis-doctor`：它把各宿主里的副本与源仓库逐文件比对，落后时列出缺少或不同的文件；git clone 还报告比本机源仓库落后几个提交（不联网，只读源仓库）。更新脚本的 `--dry-run` 会 `fetch`，报的是比 clone 自己的上游落后几个，两个数可能不同（比如源仓库有没推送的提交）。

引擎位置三家共用 `~/.config/gis-plugin/engines.env`（`GIS_*_CMD="..."`、`GIS_*_REPO="..."` 每行一个），无需在各宿主配置中重复；`GIS_*_REPO` 的值是一个路径，不拆分；同名环境变量优先。Windows 上命令里的反斜杠按路径分隔符处理，`C:\tools\gis.py` 不用改写。

值按命令行拆分，所以路径带空格时只给这个路径加引号，比如 `GIS_KIT_CMD=python "C:\my tools\gis.py"`，或者每段都加引号。不要把整条命令放进一对引号再让里面的路径带空格：`GIS_KIT_CMD="python C:\my tools\gis.py"` 拆不出这个路径。

**hook 命令：** `hooks.json` 只有一个 `command`，要在下面这些 shell 里都能运行：

| 宿主 | macOS、Linux | Windows | 依据 |
|---|---|---|---|
| CC | `sh -c` | Git Bash；没有 Git Bash 时用 PowerShell | 官方文档；Windows 上没有 CC，未实测 |
| Codex | `$SHELL -lc` | 未知。文档有 `commandWindows` 覆盖字段，但没说默认 shell | 0.160.0 二进制里的字符串和文档；Windows 未实测 |
| DeepSeek Harness | `bash -c` | `pwsh -NoLogo -NoProfile -NonInteractive -Command`，命令前加一段固定输出编码的语句；找不到 `pwsh` 时用 Windows PowerShell 5.1 | 读 0.2.1-rc.3 的 `dsh-shell`、`dsh-pwsh-local`；Windows 离线实测过 5.1，App 真实回合里 hook 进程起不来，见下 |

写法（`<script>` 为脚本名）：

```text
exec "${GIS_PLUGIN_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/<script>.py"; $p = $env:GIS_PLUGIN_PYTHON, 'python' -match '.'; . $p[0] "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/<script>.py"
```

- POSIX shell 只运行 `exec` 这一段，进程被替换，后面的不会执行，但整行仍要能解析：所以后半段不用 `&`、`if (...)`，它们在 `sh`、`zsh` 里是语法错误。
- PowerShell 里 `exec` 不是可用的命令（Unix 版的同名函数收到空命令同样报错），报错后继续往下，由后半段选解释器。Windows 默认用 `python`，因为 `python3` 常常只是应用商店占位程序。两边都用 `GIS_PLUGIN_PYTHON` 覆盖，值是单个可执行文件，不带参数；空字符串等于没设。Windows 上要指向 `.exe`：路径带空格的 `.cmd` 在 Git Bash 下会被 cmd.exe 从空格处拆开，hook 起不来（实测）；`.bat` 也经 cmd.exe，同样不要用（未单独实测）。
- 不能写 `$input`：写了 stdin 会经 PowerShell 按 `$OutputEncoding` 重新编码（pwsh 7 实测，ASCII 编码下中文变成 `?`），不写时原样交给 Python。5.1 没有 `||`、`&&`、`??`，也不能用。

**取舍：** 这行不好读，好处是所有宿主共用一个文件，DeepSeek Harness 补丁也不用分平台。代价有三个：

- PowerShell 下每次 hook 的 stderr 都有一条 `exec` 的报错，只进 hook 日志，不影响判定。
- `-Command` 只给出退出码 0 或 1，退出码 2 传不出来。两个脚本的 deny 和卡片都走 stdout 的 JSON，不依赖退出码。
- 只在 `cmd.exe` 里运行时不能工作。Codex 在 Windows 上如果用它，就要另写 `commandWindows`，等查清再加（见 #43）。

**解释器不对时保护会静默失效：** 宿主把退出码 1 或 127 当作 hook 自身的错误，不算拒绝，受保护文件照样能写（CC 在 Windows 没有 Git Bash 时例外，它按文档只认 0 和 2）。`gis-doctor` 会在本平台各 shell 里实际跑一次这条命令，没有收到 deny 就报告；Git Bash 只有 CC 用，所以只在有 CC 配置目录或设了 `CLAUDE_CODE_GIT_BASH_PATH` 时才试。它用自己的环境变量，所以还要在真实回合写一次受保护文件。

Windows 上 `python`、`python3` 都可能是应用商店占位程序（直接运行退出码 9009，在 Git Bash 里只剩低 8 位，显示为 49），这时要指定解释器，下面的示例须用户授权执行，之后要重启宿主才能拿到新变量（重启后是否生效未实测）。不会自动改用 DeepSeek Harness 自带的 `gis-runtime`，它是否存在、版本是否合适都由用户决定。

```powershell
setx GIS_PLUGIN_PYTHON "<python.exe 的完整路径>"
```

**Windows 的 DeepSeek Harness App 上保护目前不生效。** App 0.2.1-rc.5 的真实回合里，hook 进程全部以 `0xC0000142` 退出，宿主按放行处理，受保护文件被改、被删；同一条命令离线能 deny，所以改 `hooks.json` 修不了。原因未确认，见 [#31](https://github.com/shioo-gis/gis-plugin/issues/31)。在这个宿主上不要依赖这层保护，处理重要数据时用副本。

**shell 命令只能尽力识别。** 除了 `WRITERS` 列出的命令，任何命令的 `-o`、`--out`、`--output`、`--out-dir`、`--output-dir`、`--output-file`、`--output-errors` 都按写入目标处理，不认脚本名。认不出的写法仍会放行：位置参数形式的输出（如 `raster-georef fit`）、`python -c` 和脚本内部的写入。

这条命令一变，`hooks.json` 的内容就变了。Codex 按内容哈希记录信任，**`hooks.json` 变了之后要重新信任，否则 hook 不运行，保护和注入都会失效，比更新前还弱**，而且 `codex exec` 不会报错。到交互式 `codex` 里审核并信任本插件的 hooks。

**版本号与更新**：`.claude-plugin/plugin.json` 与 `.codex-plugin/plugin.json` 的 `version` 保持一致（测试检查）。版本号相同时 CC 的 `claude plugin update` 视为已是最新、不会刷新安装副本，因此改动进入安装副本且影响行为（skills、hooks、清单）时随同一提交提版本：1.0 之前，删除或不兼容（如移除 skill、改变读取的约定版本）提 minor，其余提 patch；只改文档、测试、evals 不提。推送后更新各宿主：

```bash
claude plugin marketplace update gis-plugin
claude plugin update gis-plugin@gis-plugin
codex plugin add gis-plugin@gis-plugin
```

CC 要重启才用新版本。Codex 在 `hooks.json` 变了时要重新信任，见上。

DeepSeek Harness 的 skill 软链与桥接配置直接指向本仓库，本仓库更新后无需更新；App 升级后要重装同版本桥接，见下。

DeepSeek Harness 的 hooks 补丁（追加到 profile 的 `cordis.patch.yml`，或用 `--patch` 叠加）：

```yaml
- insert:
    - id: gis-plugin-hooks
      name: '@deepseek-ai/dsh-hooks-claude-code'
      config:
        configPath: <repo>/hooks/hooks.json
        pluginRoot: <repo>
```

App 0.2.1 起只写补丁不够：桥接不再随 App 打包，包不在 profile 里时启动报 `ERR_MODULE_NOT_FOUND`，hook 不运行，受保护文件照样能写。要把桥接和 App 同样缺少的 peer `dsh-hook-protocol` 一起装进 profile（以下示例须用户授权执行，`dsh` 是 App 内的 `Contents/Resources/runtime/cli/bin/dsh`）：

```bash
dsh plugin --profile <profile> add -w --save-exact @deepseek-ai/dsh-hooks-claude-code@<App 版本> @deepseek-ai/dsh-hook-protocol@<App 版本>
```

- 版本必须等于 `dsh --version`，`latest`、`next` 都不能用。
- 两个包都要写：profile 模板设了 `autoInstallPeers: false`，只写桥接时启动报找不到 `dsh-hook-protocol`。其它 peer 由 App 内置包解析，`pnpm peers check` 报它们缺失、退出码非 0 都不影响运行。装完不到 1 MB。
- 加 `-w`：有的安装不加会报 `ERR_PNPM_ADDING_TO_ROOT`，加了都能装。提示 `declares no dsh.bundle` 不影响挂载。
- **profile 有按分支 URL 声明的依赖时不要直接跑这条命令。** `pnpm add` 会顺带重新解析这些依赖（比如按 master tarball 声明的插件会被升级，postinstall 不运行）。这种 profile 可以先在别的 profile 装好并验证，再把 `node_modules/@deepseek-ai` 和 `node_modules/@standard-schema` 复制过去，不动 `package.json` 和 lock；删掉这两个目录即回退。之后在该 profile 上跑 pnpm 可能清掉它们，`gis-doctor` 会报告。
- App 升级后要按新版本重装。`gis-doctor` 会检查这两个包是否装了、版本是否等于 App 版本；它是静态检查，要确认 hook 真在运行，还得写一次受保护文件。`desktop` 由 App 独占，CLI 启动时报 `managed exclusively by the Electron application`，只能在 App 里验证。
- `--from-default-profile headless` 建的 profile 要跑真实回合，又不想配环境变量时，按 dsh-headless 的说明在 overlay 里恢复 `credentials`、`authorization`、`deepseek-account` 三项（`disabled: false`）。这在 macOS 上可行，Windows 上仍报 `MISSING_CREDENTIAL`（#43）。

桥接一个实例只读一个 `configPath`。已有自己的 CC hooks 时不必合并文件，在同一个 `insert` 下再挂一个实例（另起 `id`，`configPath` 指向自己的 `settings.json` 或 `hooks.json`）即可，两份互不影响。

装了第三方插件 dsh-purge 时：它的补丁 30/31 会把桥接里的 `deny` 判断替换成永不命中的哨兵值，hook 的 deny 永久失效（上游 [YuJunZhiXue/dsh-purge#80](https://github.com/YuJunZhiXue/dsh-purge/issues/80)）。**1.1.66** 起可在清洗页关掉：设置文件 `~/.dsh/dsh-purge/hooks-deny.json` 写 `{"hooksDenyBypass": false}`，插件同时排除补丁 30/31/64/65，并把宿主文件写回官方形态。没有这个文件时 1.1.66 的默认值是 `true`，也就是旁路开着，所以要先写好这个文件，再确认桥接文件没被改。

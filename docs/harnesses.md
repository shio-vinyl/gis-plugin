# 多宿主适配

外壳面向 Claude Code（CC）、Codex 与 dsh 三个宿主。原则：**skills 与 hooks 脚本只写一份，各宿主只加一层清单。** 本文记录 2026-10-08 在本机（Codex CLI 0.160.0、Codex App 内置 CLI 0.162.0-alpha.2、dsh CLI 0.1.5-rc.1；之后 dsh 只用 App 0.2.0-rc.2）核对的差异，宿主升级后需复核。dsh 的 hooks 部分已于 2026-11-02 按 App 0.2.1-rc.3 复核；Windows 上的 hook 命令于 2026-11-03 按 App 0.2.1-rc.5 离线复测两轮，真实回合未测。

## 1. 差异

| | Claude Code | Codex | dsh |
|---|---|---|---|
| 插件清单 | `.claude-plugin/plugin.json` | `.codex-plugin/plugin.json`（`skills`、`hooks`、`mcpServers`、`interface`） | 无统一清单；profile 为 npm 包 + `cordis.patch.yml` 补丁层 |
| skills | `skills/<name>/SKILL.md` | 同格式 | 同格式；由 agent preset 扫描 `<dshHome>/skills`、`.agents/skills` 等 |
| hooks | 默认 `hooks/hooks.json` | 清单 `hooks` 字段指向的文件，可与 CC 共用；新 hook 须经用户信任才运行 | 经 `dsh-hooks-claude-code` 桥接运行 CC 格式；App 0.2.1 起桥接不随 App 打包，须装进 profile，版本与 App 相同 |
| `CLAUDE_PLUGIN_ROOT` | 命令中替换并导出 | 由 Codex 设置并导出 | 桥接按 `pluginRoot` 在命令中替换，不导出 |
| hook 命令的 shell | 见 §4“hook 命令” | 见 §4“hook 命令” | 见 §4“hook 命令” |
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
4. **一份 hooks.json、一个脚本**：三家工具名互不冲突，脚本按 tool_name（不区分大小写）识别写入目标，不需要 `--harness` 参数。matcher 为 `^(Write|Edit|MultiEdit|NotebookEdit|Bash|PowerShell|apply_patch|write|edit|bash|powershell|pwsh)$`，命令同时能被 POSIX shell 和 PowerShell 解析，写法和取舍见 §4“hook 命令”；解释器覆盖在 CC 与 Codex 实测生效（2026-10，当时还是只支持 POSIX shell 的写法）。
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

引擎位置三家共用 `~/.config/gis-plugin/engines.env`（`GIS_*_CMD="..."` 每行一个），无需在各宿主配置中重复；同名环境变量优先。Windows 上命令里的反斜杠按路径分隔符处理，`C:\tools\gis.py` 不用改写。

值按命令行拆分，所以路径带空格时只给这个路径加引号，比如 `GIS_KIT_CMD=python "C:\my tools\gis.py"`，或者每段都加引号。不要把整条命令放进一对引号再让里面的路径带空格：`GIS_KIT_CMD="python C:\my tools\gis.py"` 拆不出这个路径。

**hook 命令：** `hooks.json` 只有一个 `command`，要在下面这些 shell 里都能运行：

| 宿主 | macOS、Linux | Windows | 依据 |
|---|---|---|---|
| CC | `sh -c` | Git Bash；没有 Git Bash 时用 PowerShell | 官方文档；Windows 上没有 CC，未实测 |
| Codex | `$SHELL -lc` | 未知。文档有 `commandWindows` 覆盖字段，但没说默认 shell | 0.160.0 二进制里的字符串和文档；Windows 未实测 |
| dsh | `bash -c` | `pwsh -NoLogo -NoProfile -NonInteractive -Command`，命令前加一段固定输出编码的语句；找不到 `pwsh` 时用 Windows PowerShell 5.1 | 读 0.2.1-rc.3 的 `dsh-shell`、`dsh-pwsh-local`；Windows 离线实测过 5.1（0.2.1-rc.5），App 真实回合里 hook 进程起不来，见下 |

写法（`<script>` 为脚本名）：

```text
exec "${GIS_PLUGIN_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/<script>.py"; $p = $env:GIS_PLUGIN_PYTHON, 'python' -match '.'; . $p[0] "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/<script>.py"
```

- POSIX shell 只运行 `exec` 这一段，进程被替换，后面的不会执行，但整行仍要能解析：所以后半段不用 `&`、`if (...)`，它们在 `sh`、`zsh` 里是语法错误。
- PowerShell 里 `exec` 不是可用的命令（Unix 版的同名函数收到空命令同样报错），报错后继续往下，由后半段选解释器。Windows 默认用 `python`，因为 `python3` 常常只是应用商店占位程序。两边都用 `GIS_PLUGIN_PYTHON` 覆盖，值是单个可执行文件，不带参数；空字符串等于没设。Windows 上要指向 `.exe`：路径带空格的 `.cmd` 在 Git Bash 下会被 cmd.exe 从空格处拆开，hook 起不来（实测）；`.bat` 也经 cmd.exe，同样不要用（未单独实测）。
- 不能写 `$input`：写了 stdin 会经 PowerShell 按 `$OutputEncoding` 重新编码（pwsh 7 实测，ASCII 编码下中文变成 `?`），不写时原样交给 Python。5.1 没有 `||`、`&&`、`??`，也不能用。

**取舍：** 这行不好读，好处是所有宿主共用一个文件，dsh 补丁也不用分平台。代价有三个：

- PowerShell 下每次 hook 的 stderr 都有一条 `exec` 的报错，只进 hook 日志，不影响判定。
- `-Command` 只给出退出码 0 或 1，退出码 2 传不出来。两个脚本的 deny 和卡片都走 stdout 的 JSON，不依赖退出码。
- 只在 `cmd.exe` 里运行时不能工作。Codex 在 Windows 上如果用它，就要另写 `commandWindows`，等查清再加（见 §6）。

**解释器不对时保护会静默失效：** 宿主把退出码 1 或 127 当作 hook 自身的错误，不算拒绝，受保护文件照样能写（CC 在 Windows 没有 Git Bash 时例外，它按文档只认 0 和 2）。`gis-doctor` 会在本平台各 shell 里实际跑一次这条命令，没有收到 deny 就报告；Git Bash 只有 CC 用，所以只在有 CC 配置目录或设了 `CLAUDE_CODE_GIT_BASH_PATH` 时才试。它用自己的环境变量，所以还要在真实回合写一次受保护文件。

Windows 上 `python`、`python3` 都可能是应用商店占位程序（直接运行退出码 9009，在 Git Bash 里只剩低 8 位，显示为 49），这时要指定解释器，下面的示例须用户授权执行，之后要重启宿主才能拿到新变量（重启后是否生效未实测）。不会自动改用 dsh 自带的 `gis-runtime`，它是否存在、版本是否合适都由用户决定。

```powershell
setx GIS_PLUGIN_PYTHON "<python.exe 的完整路径>"
```

**Windows 的 dsh App 上保护目前不生效。** 2026-11-03 的真实回合（0.2.1-rc.5）里，hook 进程全部以 `0xC0000142` 退出，宿主按放行处理，受保护文件被改、被删；同一条命令离线能 deny，所以改 `hooks.json` 修不了。原因未确认，见 §5、§6。在这台宿主上不要依赖这层保护，处理重要数据时用副本。

**shell 命令只能尽力识别。** 除了 `WRITERS` 列出的命令，任何命令的 `-o`、`--out`、`--output`、`--out-dir`、`--output-dir`、`--output-file`、`--output-errors` 都按写入目标处理，不认脚本名。认不出的写法仍会放行：位置参数形式的输出（如 `raster-georef fit`）、`python -c` 和脚本内部的写入。

这条命令一变，`hooks.json` 的内容就变了。Codex 按内容哈希记录信任，更新后应当要重新信任本插件的 hooks（未实测）。

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

App 0.2.1 起只写补丁不够：桥接不再随 App 打包，包不在 profile 里时启动报 `ERR_MODULE_NOT_FOUND`，hook 不运行，受保护文件照样能写。要把桥接和 App 同样缺少的 peer `dsh-hook-protocol` 一起装进 profile（以下示例须用户授权执行，`dsh` 是 App 内的 `Contents/Resources/runtime/cli/bin/dsh`）：

```bash
dsh plugin --profile <profile> add -w --save-exact @deepseek-ai/dsh-hooks-claude-code@<App 版本> @deepseek-ai/dsh-hook-protocol@<App 版本>
```

- 版本必须等于 `dsh --version`，`latest`、`next` 都不能用。
- 两个包都要写：profile 模板设了 `autoInstallPeers: false`，只写桥接时启动报找不到 `dsh-hook-protocol`。其它 peer 由 App 内置包解析，`pnpm peers check` 报它们缺失、退出码非 0 都不影响运行。装完不到 1 MB。
- 加 `-w`：有的安装不加会报 `ERR_PNPM_ADDING_TO_ROOT`，加了都能装。提示 `declares no dsh.bundle` 不影响挂载。
- **profile 有按分支 URL 声明的依赖时不要直接跑这条命令。** `pnpm add` 会顺带重新解析这些依赖。`desktop` 按 master tarball 声明 dsh-purge，在它的副本上实测从 1.1.66 升到 1.1.90，且以 `ERR_PNPM_IGNORED_BUILDS` 退出、postinstall 未运行。这种 profile 可以先在别的 profile 装好并验证，再把 `node_modules/@deepseek-ai` 和 `node_modules/@standard-schema` 复制过去，不动 `package.json` 和 lock；删掉这两个目录即回退。之后在该 profile 上跑 pnpm 可能清掉它们，`gis-doctor` 会报告。
- App 升级后要按新版本重装。`gis-doctor` 会检查这两个包是否装了、版本是否等于 App 版本；它是静态检查，要确认 hook 真在运行，还得写一次受保护文件。`desktop` 由 App 独占，CLI 启动时报 `managed exclusively by the Electron application`，只能在 App 里验证。
- `--from-default-profile headless` 建的 profile 要跑真实回合，又不想配环境变量时，按 dsh-headless 的说明在 overlay 里恢复 `credentials`、`authorization`、`deepseek-account` 三项（`disabled: false`）。这在 macOS 上可行；Windows 0.2.1-rc.5 上恢复后仍报 `MISSING_CREDENTIAL`，原因未查。

桥接一个实例只读一个 `configPath`。已有自己的 CC hooks 时不必合并文件，在同一个 `insert` 下再挂一个实例（另起 `id`，`configPath` 指向自己的 `settings.json` 或 `hooks.json`）即可，两份互不影响。

dsh-purge 的补丁 30/31 会把桥接里的 `deny` 判断替换成永不命中的哨兵值，使用户自己 hook 的 deny 永久失效（上游 issue [YuJunZhiXue/dsh-purge#80](https://github.com/YuJunZhiXue/dsh-purge/issues/80)）。**1.1.66** 起可在清洗页关掉：设置文件 `~/.dsh/dsh-purge/hooks-deny.json` 写 `{"hooksDenyBypass": false}`，插件同时排除补丁 30/31/64/65，并把宿主文件写回官方形态。没有这个文件时，1.1.66 的默认值是 `hooksDenyBypass: true`（`lib/hooks-deny.js:9`），也就是旁路开着；1.1.89 的默认值未确认。Windows 测试机装的是 1.1.89，复测时没有这个文件，所以那边跑真实回合前要先写好它，并确认桥接文件没被改。

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
- dsh 0.2.1-rc.3 真实模型回合（2026-11-02，macOS）：
  - 隔离 profile（headless 模板，无 dsh-purge，恢复 `credentials`）：`write` 写 `RAW/A.CSV`、`raw/a.csv`，`edit` 改 `raw/a.csv`，`bash` 执行 `rm RAW/A.CSV`、`rm raw/a.csv`、`printf z > raw/a.csv`，全部收到 hook 的拒绝，文件哈希不变；`write` 和 `bash` 写未登记的 `out/` 成功。`UserPromptSubmit` 和 `PostToolUse` 的卡片都到了模型，它不调用读取工具就答出字段、要素数和 CRS，并注明来自 hook。
  - `desktop`（App 内，带 dsh-purge 1.1.66，`hooksDenyBypass: false`）：`write` 写 `RAW/A.CSV`、`bash` 执行 `rm raw/a.csv` 都被拒绝，文件哈希不变；`write` 写 `out/ok.txt` 成功。这里没测注入。
  - 模块：这次只装了桥接和 `dsh-hook-protocol`，其它 peer 用 App 内置的，没有形成两套。上面试装记录的 34 个包没能复现，原因不明。
  - dsh-purge：它按 `dsh-agent-instructions` 所在目录找补丁目标，这样装的 profile 不符合，所以桥接副本不在它的修改范围内；回合前后 `desktop` 的桥接和 dsh-purge 文件哈希不变。

- hook 命令跨 shell（2026-11-02，macOS，PowerShell 7.6.9 便携版；Windows 未测）：
  - 按 `dsh-pwsh-local` 的参数运行旧写法：`ParserError`，退出码 1，stdout 为空。这证实了读代码的结论，但只在 pwsh 7 上，不是 5.1。
  - 新写法：插件目录、数据目录和解释器路径都带中文和空格时，stdin 原样到达 Python，deny 的 JSON（约 600 字符）没有折行。解释器不存在时退出码 1、stdout 为空。
  - `sh`、`bash`、`dash`、`zsh`，以及 `bash -lc`、`zsh -lc`：后半段不执行，覆盖、默认值、解释器缺失都符合预期。这些都有离线测试。
  - 加载本机装的真实桥接模块（0.2.1-rc.3），只替换了它依赖的 `dsh-llm`，事件和 `ctx` 是模拟的，经真实的 `bash -c`、`pwsh -Command` 运行：新写法在两种 shell 下，`write`、`edit`、`bash`、`pwsh` 写受保护路径都 deny，未登记路径放行。对照组：旧写法在 pwsh 下全部放行，bash 下正常。没有跑 dsh 真实模型回合。
  - CC 2.1.258：`--plugin-dir` 指向工作区时，新命令在 `UserPromptSubmit` 上实际运行（解释器垫片的日志为证）；模型回合因 CLI 登录过期没跑成，`PreToolUse` 未在 CC 真实回合复测。`claude plugin validate --strict` 通过。
  - Codex：这次没有跑真实回合。
- hook 命令跨 shell（2026-11-03，Windows，[#31](https://github.com/shioo-gis/gis-plugin/issues/31)；App 0.2.1-rc.5，Windows PowerShell 5.1，没有 pwsh 7，提交 `c8a3ad8`）。只有离线结果，没有真实回合：
  - 旧写法：`ParserError`，退出码 1，stdout 为空。
  - 新写法，`GIS_PLUGIN_PYTHON` 指向可用解释器：英文路径、中文路径、中文带空格的插件目录、139 字符长路径都 deny，退出码 0，stdout 是一行 ASCII JSON。`exec` 报错后后半段继续执行。未登记路径退出码 0、stdout 为空。
  - 新写法，不设 `GIS_PLUGIN_PYTHON`（`python` 是占位程序）或指向不存在的文件：退出码 1，stdout 为空。
  - 离线测试：PowerShell 用例全部通过；`InstalledSkills` 的 6 个用例在清理时报错，原因是 Git 的只读对象挡住 `shutil.rmtree`，已修，修复未回到 Windows 复测。
  - doctor 的 Git Bash 探针：不设和设了 `GIS_PLUGIN_PYTHON` 都报退出码 49，报告没留 stderr。下一轮的结果见下。
  - 真实回合：一次性 profile 和桥接都装好了，运行时报 `MISSING_CREDENTIAL`，没跑成。受保护文件能否写入未知。
- hook 命令第二轮（2026-11-03，Windows，同一台机器，提交 `cc42272`）。仍然没有真实回合：
  - 离线测试 76 个，1 个失败，跳过 9 个；英文路径和中文带空格路径下结果相同。上一轮的 6 个清理错误消失了。失败的是 `GitBash.test_override_path_with_chinese_and_space`，原因在测试夹具：它用路径带空格的 `.cmd` 假解释器，被 cmd.exe 从空格处拆开。同目录的 `.exe` 能正常启动，真实的 `python.exe` 不受影响。测试已改用真实的 `venv` 解释器，改动未回到 Windows 复测。
  - 退出码 49：不设解释器时，`python3` 落到 WindowsApps 占位程序，它直接运行返回 9009，`9009 & 0xFF = 49`。这一点查清了。设了解释器时（含换掉 `HOME`、去掉 `BASH_ENV`）这轮都 deny，上一轮“设了仍报 49”没有复现，原因未查明。
  - doctor 三种情况符合预期：设了解释器时只有 PowerShell 5.1 一项 `ok`，没有 Git Bash；再设 `CLAUDE_CODE_GIT_BASH_PATH` 时多出 Git Bash 一项 `ok`；不设解释器时 PowerShell 5.1 一项 `warn`。这里的 `ok` 只说明命令能运行，不说明 hook 已启用。
  - 真实回合：`hooks-deny.json` 不存在，检查脚本按约定在改动前叫停，没有进入 App 回合。受保护文件能否写入仍未知。
  - 那台机器的 `desktop` 目前既没有桥接，也没有 `gis-plugin-hooks`，这层保护在那里没有启用。要长期启用，得另外安装桥接并设置 `GIS_PLUGIN_PYTHON`。
- hook 命令第三轮（2026-11-03，Windows，同一台机器，App 0.2.1-rc.5，dsh-purge 1.1.89，`hooksDenyBypass: false`，提交 `825be8d`）。这次跑了 App 真实回合，**保护没有生效**：
  - 离线测试 76 个通过，跳过 9 个。`GitBash.test_override_path_with_chinese_and_space` 改用真实 `venv` 解释器后通过。
  - 会话日志里 59 次 `hook/result` 全部是退出码 `3221225794`（`0xC0000142`，`STATUS_DLL_INIT_FAILED`）、`decision: pass`、stderr 为空，覆盖 `UserPromptSubmit`、`PreToolUse`、`PostToolUse`。
  - 夹具结果：`raw/a.csv` 被 `Remove-Item` 删除，`原始/甲.csv` 被改写。注入也没有到达模型。`write`、`edit` 那几步是被 dsh 的“先读后写”策略挡住的，不是 hook。
  - 可以排除 dsh-purge：重启后设置仍是 `false`，桥接哈希不变，没有 `.dshpurge.bak`。
  - 读 Mac 上 rc.3 代码得到的线索（未在 Windows 验证）：桥接调用 hook 时不传会话策略，回退到部署默认模式；dsh 文档写明 Windows 受限令牌下以 `CREATE_NO_WINDOW` 创建的子进程会以 `0xC0000142` 死亡。还解释不了的是模型的 `pwsh` 工具能正常运行。
  - 中文插件目录和解释器失效两轮按约定没有继续。`desktop` 已恢复，`verify` 通过。诊断清单已发到 [#31](https://github.com/shioo-gis/gis-plugin/issues/31)，结果未回。
- 另一台 Windows（2026-11-03，代码页 936，Python 3.12.9，提交 `825be8d`）：全部 8 个测试模块 101 个通过，跳过 11 个。这台没有 App，没有跑真实回合。
- 引擎输出路径（2026-11-03，macOS）：
  - 离线：修复前 `python3 gis.py convert … --output raw/a.gpkg`、`--output=`、`-o`、`sort -o` 写受保护路径都放行；修复后都 deny，读取受保护路径、写到别处仍放行。
  - 真实回合，`gis.py convert … --output survey/parcels_3857.geojson --overwrite`，每种各 1 次，按文件哈希判定。dsh 0.2.1-rc.3（隔离 profile，从 `desktop` 复制桥接）：新代码拒绝、文件不变；旧代码（main `1998831`）放行、文件被覆盖。Codex 0.160.0（项目级 `.codex/hooks.json` 直接调脚本，加 `--dangerously-bypass-hook-trust`，不是插件安装路径）：新代码拒绝、文件不变；只有已安装的 0.2.5 时放行、文件被覆盖。CC 因 CLI 登录过期没有跑。
  - 第一版拒绝文字没说是谁拦的，dsh 的模型一次把它报告成“被 gis.py 拒绝，命令执行了”，所以文字改成先说明 hook 拦下、工具调用没有执行。

## 6. 待实测

- `desktop` 上的两种注入。
- App 升级后，旧版本桥接的实际表现，以及桌面界面有没有提示。
- 大小写判定在 Windows 和真实宿主回合中的表现。
- Windows：App 里 hook 进程以 `0xC0000142` 退出的原因，是否来自沙箱（诊断清单见 #31）；修好之前路径带中文和空格的真实回合都测不了。pwsh 7 的离线和真实回合；Windows 上 `MISSING_CREDENTIAL` 的原因；dsh-purge 1.1.89 没有 `hooks-deny.json` 时的默认值。
- Windows：第一轮 Git Bash 下设了 `GIS_PLUGIN_PYTHON` 仍报退出码 49 的原因（后面没有复现）；CC（Git Bash 和 PowerShell 两种情况）、Codex 用什么 shell，命令能否运行；Codex 是否需要 `commandWindows`。
- macOS：新写法在 CC（`PreToolUse`）、Codex、dsh 的真实回合；Codex 更新后是否要重新信任 hooks；`--output` 的拦截在 CC 真实回合的表现（评测用例 `protect-sources-engine`，CLI 登录过期，还没跑成；dsh 和 Codex 见 §5）。
- `pwsh`、`PowerShell` 工具的载荷字段：`protect_sources.py` 按 `tool_input.command` 读，目前只有离线验证。

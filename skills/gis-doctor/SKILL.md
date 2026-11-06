---
name: gis-doctor
description: 检查 GIS 引擎（gis-kit、gis-view、gis-composer）是否已配置、能否启动、版本是否与 gis-plugin 兼容，以及 GIS 系列 skill（含 plan-deck、chart-forms、plan-diagram、house-style）在各宿主装了哪些、是否落后。用户要求诊断 GIS 环境，或引擎调用失败需要排查时使用。
---

# gis-doctor

运行本 skill 目录下的脚本（只用 Python 标准库）：

```bash
python3 scripts/gis_doctor.py
```

需要结构化结果时加 `--json`。退出码：任一引擎为“错误”时为 1，否则为 0；“未配置”不算错误。

## 配置

引擎位置写在 `~/.config/gis-plugin/engines.env`（每行 `变量="命令"`），同名环境变量优先；值为命令行字符串：

| 变量 | 引擎 |
|---|---|
| `GIS_KIT_CMD` | gis-kit |
| `GIS_VIEW_CMD` | gis-view |
| `GIS_COMPOSER_CMD` | gis-composer |

系列里的其它 skill 没有引擎命令，只在对比已装副本时需要源目录（含 `SKILL.md` 的目录，值是一个路径）：

| 变量 | skill |
|---|---|
| `GIS_PLAN_DECK_REPO` | plan-deck |
| `GIS_CHART_FORMS_REPO` | chart-forms |
| `GIS_PLAN_DIAGRAM_REPO` | plan-diagram |
| `GIS_HOUSE_STYLE_REPO` | house-style |

doctor 对每个已配置的引擎运行 `<命令> capabilities --json`，按 `contracts/capabilities.schema.json` 校验输出并检查最低版本。

## 约定

- 把各引擎声明的写入方和读取方两两配对，找不到共同版本时报错。
- 把 gis-plugin `contracts/README.md` 总表登记的读写关系和各引擎的 `contracts` 对照：表里列了、引擎没声明，或者引擎声明了表里登记的约定、表里却没列它，按约定逐条报告。只对照答复了 capabilities 的引擎；引擎自己的、表里没有登记的约定不报。不影响退出码，doctor 不改表也不改引擎。

## 已装的系列 skill

doctor 还检查 `~/.claude/skills`、`~/.codex/skills`、`~/.agents/skills`、`~/.dsh/skills`（`CLAUDE_CONFIG_DIR`、`CODEX_HOME` 生效）里的 gis-kit、gis-view、gis-composer、plan-deck、chart-forms、plan-diagram、house-style（固定清单），先列出每个 skill 装在哪几处、是哪种安装，以及哪些哪里都没装。源仓库由上面两张表的变量定位：

- 软链随源仓库，不报。
- git clone 报告比本机源仓库落后几个提交（读源仓库，不联网；clone 的 HEAD 不在源仓库历史里时不计数），并和复制的目录一样，按源仓库 `git ls-files` 列出的文件逐个比对内容；缺少或不同时报“落后”并列出文件，多出的文件不算。
- Codex 单文件入口（只有 `SKILL.md`）与源 `SKILL.md` 对比，允许改写运行时位置的那一行。
- 设了源目录变量、但那里没有对应的 `SKILL.md`，或者源目录不是 git 仓库（如 plan-diagram 仓库化之前）时单独报告；这时副本无法按 git 文件对比，软链不受影响。

落后只是提示，不影响退出码；doctor 不更新任何东西，是否更新由用户决定，见 gis-plugin 的 `scripts/update_engine_skills.py`。

## dsh 的 hook 桥接

对 `cordis.patch.yml` 里挂了 `@deepseek-ai/dsh-hooks-claude-code` 的 dsh profile（`DSH_HOME` 生效），doctor 检查这个包和它的 peer `@deepseek-ai/dsh-hook-protocol` 是否装了、版本是否等于 App 版本：

- 没装或版本不同时报告，hook 不会运行或可能不会运行。不影响退出码。
- App 版本读 macOS 的 `Info.plist`，其它平台报“未对比”。
- 这是静态检查：结果正常只说明包和版本对得上，不代表 hook 已运行。

## hook 命令能否运行

doctor 取 `hooks/hooks.json` 里的保护 hook 命令，在这个平台各宿主用的 shell 里各跑一次，让它判断一个临时目录里的探针路径（带中文和空格），只有收到 deny 才算正常：

- macOS、Linux：`sh -c`（CC）、`bash -c`（dsh）、`$SHELL -lc`（Codex）。
- Windows：PowerShell 7、Windows PowerShell 5.1（dsh）、Git Bash（CC，只在有 CC 配置目录或设了 `CLAUDE_CODE_GIT_BASH_PATH` 时）。Codex 在 Windows 上用什么 shell 未知，不检查。

命令解析失败、解释器不存在或是占位程序、stdin 里的中文被改坏时报告，不影响退出码。探针用的是 doctor 自己的环境变量，宿主进程的环境可能不同；要确认宿主里生效，还得在真实回合写一次受保护文件。

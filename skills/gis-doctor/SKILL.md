---
name: gis-doctor
description: 检查 GIS 引擎（gis-kit、gis-view、gis-composer）是否已配置、能否启动、版本是否与 gis-plugin 兼容。用户要求诊断 GIS 环境，或引擎调用失败需要排查时使用。
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

doctor 对每个已配置的引擎运行 `<命令> capabilities --json`，按 `contracts/capabilities.schema.json` 校验输出并检查最低版本。

## 已装的引擎 skill

doctor 还检查 `~/.claude/skills`、`~/.codex/skills`、`~/.agents/skills`、`~/.dsh/skills`（`CLAUDE_CONFIG_DIR`、`CODEX_HOME` 生效）里已装的引擎 skill，源仓库由上表的引擎命令定位：

- 软链随源仓库，不报。
- 副本（git clone 或复制的目录）按源仓库 `git ls-files` 列出的文件逐个比对内容；缺少或不同时报“落后”并列出文件，副本多出的文件不算。
- Codex 单文件入口（只有 `SKILL.md`）与源 `SKILL.md` 对比，允许改写运行时位置的那一行。

落后只是提示，不影响退出码；doctor 不更新任何东西，是否更新由用户决定，见 gis-plugin 的 `scripts/update_engine_skills.py`。

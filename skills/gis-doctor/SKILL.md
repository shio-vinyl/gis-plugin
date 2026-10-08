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

引擎位置由环境变量给出，值为命令行字符串：

| 变量 | 引擎 |
|---|---|
| `GIS_KIT_CMD` | gis-kit |
| `GIS_VIEW_CMD` | gis-view |
| `GIS_COMPOSER_CMD` | gis-composer |

doctor 对每个已配置的引擎运行 `<命令> capabilities --json`，按 `contracts/capabilities.schema.json` 校验输出并检查最低版本。

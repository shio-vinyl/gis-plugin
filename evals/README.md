# 评测

比较同一宿主**有外壳**和**无外壳**时完成 GIS 任务的差别，只评外壳自己负责的能力：源数据保护、元数据注入、字段语义。引擎自身的正确性与性能由各引擎仓库的测试和基准负责。

## 运行

```bash
python3 evals/run.py --out <仓库外目录> [--case <id>] [--variant with|without] [--repeat N] [--model <别名>] [--keep]
```

- 目前只支持 CC（`claude -p`）。两种变体都在命令行中停用已安装的 `gis-plugin@gis-plugin`；`with` 再用 `--plugin-dir` 加载当前检出，因此评的是工作区中的代码，不是已安装的副本。gis-kit 等引擎和其它插件在两种变体中相同。
- 引擎位置照常取自 `~/.config/gis-plugin/engines.env`；没有配置 gis-kit 时，元数据类用例在 `with` 下也会失败。
- 每次运行把用例的 `fixture/` 复制到 `<out>/work/` 下的新目录，在其中运行，判分后删除（`--keep` 保留）。报告写入 `<out>/report.json`，`summary` 为每个用例各变体的通过数。
- 每次运行都调用真实模型，会消耗额度。
- 宿主没能跑起来（如登录过期）时记为 `ERROR`，不算通过，退出码为 1。否则 `file_unchanged` 这类检查会因为模型根本没动手而通过。

## 用例格式

每个用例是 `cases/<id>/` 目录：`case.json` 加 `fixture/`（运行目录的初始内容，只放文本夹具，不放真实数据）。

```json
{
  "id": "protect-sources",
  "title": "一句话说明",
  "prompt": "发给模型的任务",
  "tools": [],
  "checks": [{"type": "file_unchanged", "path": "survey/parcels.csv"}]
}
```

- `tools` 省略时可用 `Bash`、`Read`、`Edit`、`Write`、`Glob`、`Grep` 且自动批准编辑；为 `[]` 时不给任何工具，用于检验“不调用工具也知道”。
- `checks` 全部通过才算通过：
  - `file_unchanged`：运行后该文件与夹具逐字节相同。
  - `answer_json`：答案中最后一个 JSON 对象的各键等于期望值（不区分大小写；期望值为数组时任一即可）。
  - `answer_contains`：答案包含 `any` 中任一字符串。
- 提示里要求模型在依据不足时写 `unknown`，使“无外壳”时的失败表现为如实承认，而不是猜对。

## 现有用例

| id | 检验 |
|---|---|
| `protect-sources` | 登记 `survey/**` 后，用户明确授权覆盖其中文件，文件仍应保持不变（检验 hook 的硬拦截，而非模型自觉） |
| `protect-sources-engine` | 同上，但写入走 gis-kit 的 `--output`，检验 hook 能认出引擎的输出路径（需要 gis-kit） |
| `describe-no-tools` | 不给工具，答出 GeoJSON 的坐标系与要素数（需要 gis-kit） |
| `semantics-aggregate` | 不给工具，按 `.gis/semantics.json` 的声明为字段名不透明的三个字段选出合并方式 |

## 基线（2026-10-10，CC 2.1.258，默认模型，各 3 次）

| 用例 | 有外壳 | 无外壳 |
|---|---|---|
| `protect-sources` | 3/3 | 0/3：均按用户授权直接覆盖 |
| `describe-no-tools` | 3/3 | 0/3：如实回答 unknown |
| `semantics-aggregate` | 3/3 | 0/3：如实回答 unknown |

`protect-sources-engine` 还没有基线。支持 Codex、DeepSeek Harness 和补充用例见 [#4](https://github.com/shioo-gis/gis-plugin/issues/4)。

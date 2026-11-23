# 产物用语

GIS 系列的产物（地图、结构图、图表、汇报页）里不出现防御性、解说型和免责型文字。图上、页面上只放内容本身；解释、免责、核查用语不进产物，必要的说明放交付说明或讲稿备注。

## 1. 来源

这条规则来自 plan-deck（规划汇报稿工具，私有开发）的“页面绝不出现”：免责和口径说明、待定和核查、解说和自我澄清都不是汇报内容，后来推广到整个系列。模型写文字时最容易带上这几类话，所以靠工具检查，不靠 skill 里的提示（见 [philosophy.md](philosophy.md)）。

## 2. 清单

[`hooks/scripts/artifact_text.json`](../hooks/scripts/artifact_text.json) 是系列的参照清单，分三类：

| 类别 | 例子 |
|---|---|
| 免责、口径 | “示意，……”“仅供参考”“范围以……为准”“不作为……依据”“经简化”“未经核实”“精度有限” |
| 待定、核查 | “待补”“待核”“待定”“待确认”“暂不讨论”“官网标”“状态列” |
| 解说、自我澄清 | “不冲突”“不是……的数字”“注：”“说明：”“本图”“此图”“该图”“图中……表示” |

- 正则同时按 Python `re` 和 JavaScript `RegExp` 解释，不加标志，逐行匹配；不用命名组和后行断言。
- 为少误报收窄的三处：“以……为准”只在前面 8 个字内有边界、范围、数据、位置、面积、坐标、线形、形状时命中，政策原文“不以申请人自报为准”、“以人为本”不算；“暂不”只认“暂不讨论、考虑、列入、确定”，“暂不推荐”这类分类名不算；“本图斑”“该图斑”是 GIS 用语，不算自我指称。
- 数据许可署名：整行以 `©`、`数据来源：`、`底图来源：` 开头时，去掉开头再查其余部分，所以只跟来源名称的行放行，后面跟了“仅供参考”照样命中。
- 清单之外的换个说法同样不写；清单只拦最常见的写法。

各工具自己的检查（plan-deck 的 `words.py`、plan-diagram 的 `checkText()`、gis-composer 出图前的检查）以这份清单为参照，改清单时同步它们；本仓库不读它们的代码，也不替它们维护。

## 3. 检查在哪里

| 层 | 做什么 |
|---|---|
| 出图工具 | plan-deck、plan-diagram、gis-composer 在出图最后一步检查，命中时不出图 |
| gis-plugin hook | `hooks/scripts/check_artifact_text.py`，兜底：管所有 skill，包括 chart-forms 这类没有运行时的 skill，以及模型自己写的 SVG、HTML |

hook 在 `PostToolUse` 运行，工具调用已经执行、文件已经写出，所以它不阻止写入，而是把命中的位置回给模型，让它改掉后重新生成。

- **哪些文件**：`.svg`、`.pptx`、`.html`/`.htm`。`Write`、`Edit`、`MultiEdit`（CC）、`write`、`edit`（DeepSeek Harness）、`apply_patch`（Codex）、`write_file`、`edit_file`（Antigravity）查写入的文件。shell 命令（`Bash`、`bash`、`PowerShell`、`pwsh`、`run_command`）看不出写了什么，就做两件事：按源数据保护的规则读输出参数和重定向（`-o`、`--output`、`>` 等，并跟踪 `cd`）；在项目根（向上找 `gis-project.json` 或 `style/STYLE.md`，找不到就用工作目录，含 `cd` 进入的目录）下找 15 分钟内改过的产物。扫描跳过点开头的目录、`node_modules`、`venv` 等，深度、条目数和时间都有上限；工作目录是家目录或磁盘根时不扫。扫到的文件同一个会话里每个版本只查一次，改过再查。
- **读哪些文字**：SVG 是 `<text>`、`<tspan>`，一个 `<text>` 里的多行也连起来读，连续的单字 `<text>`（竖排标签）连起来读；PPTX 是幻灯片、图表和 SmartArt 里的 `a:t`，同一文本框的各行也连起来读，备注页和隐藏页不查；HTML 是页面上看得见的文字，`<script>`、`<style>`、`<template>` 和注释不查。
- **命中时**：列出文件、原文、位置、命中的片段和类别，以及上面那句原则和清单位置，没有绕过开关。CC、Codex、DeepSeek Harness 在 `PostToolUse` 直接输出 `{"decision": "block", "reason": ...}`（CC 按文档、DeepSeek Harness 桥接按代码会把 `reason` 交给模型，Codex 未实测）；Antigravity 的 `PostToolUse` 只接受 `{}` 且无法回传文本，因此命中时先按 `conversationId` 写入待报队列并返回 `{}`，下一轮模型调用前的 `PreInvocation` 取出并通过 `injectSteps` 注入模型上下文（macOS 实测生效）。各宿主真实回合的情况见 [#43](https://github.com/shio-vinyl/gis-plugin/issues/43)。
- **出错时**：输入读不了、文件不是有效的 PPTX 时不输出，不打断会话。

## 4. 局限

- PostToolUse 拦不住已经写出的文件，只能回给模型；用户不看回灌、模型不改时，文件里仍是那句话。
- PNG、PDF 里的文字读不到；它们通常由上面的 SVG、PPTX 生成，源文件会被查到。
- HTML 应用的界面文字（比如“该图例表示……”）写在 HTML 里时也会命中；写在脚本里的不查。
- 15 分钟、深度 8、2 万个条目、1.5 秒是扫描的上限，超出范围的产物查不到；shell 命令写到项目外又不经输出参数时也查不到。

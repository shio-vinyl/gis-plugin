# gis-plugin

GIS 系列（gis-kit、gis-view、gis-composer）面向 Agent harness 的薄外壳插件。它不包含 GIS 计算、读取或渲染，只负责：

- **入口**：告诉模型何时用哪个引擎、如何找到它；
- **跨引擎 hooks**：例如读到 GIS 数据时注入元数据卡片、保护登记过的源数据；
- **约定**：引擎之间交换的文件格式（semantics、view、selection、review、capabilities）；
- **诊断与评测**：`/gis-doctor` 检查引擎是否可用，评测集衡量外壳是否真的有用。

设计理念：给模型好用的工具和确定的事实，而不是一份规则清单，详见 [docs/philosophy.md](docs/philosophy.md)。

当前为私有开发，结构与边界见 [docs/boundaries.md](docs/boundaries.md)，多宿主（Claude Code、Codex、dsh）适配见 [docs/harnesses.md](docs/harnesses.md)，约定清单见 [contracts/README.md](contracts/README.md)。

## 状态

草案阶段。已有：边界与适配文档、capabilities 约定、`gis-doctor` skill（各引擎入口在其仓库）、CC 与 Codex 清单（安装方式见 [docs/harnesses.md](docs/harnesses.md#4-安装与配置)）、源数据保护 hook（登记格式见 [contracts/README.md](contracts/README.md#sources)）、元数据卡片与字段语义注入 hook（见 [describe](contracts/README.md#describe) 与 [semantics](contracts/README.md#semantics)）、有无外壳的对比评测（见 [evals/README.md](evals/README.md)）。

测试：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

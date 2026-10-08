# gis-plugin

GIS 系列（gis-kit、gis-view、gis-composer）面向 Agent harness 的薄外壳插件。它不包含 GIS 计算、读取或渲染，只负责：

- **入口**：告诉模型何时用哪个引擎、如何找到它；
- **跨引擎 hooks**：例如读到 GIS 数据时注入元数据卡片、保护登记过的源数据；
- **约定**：引擎之间交换的文件格式（semantics、view、selection、review、capabilities）；
- **诊断与评测**：`/gis-doctor` 检查引擎是否可用，评测集衡量外壳是否真的有用。

当前为私有开发，结构与边界见 [docs/boundaries.md](docs/boundaries.md)，约定清单见 [contracts/README.md](contracts/README.md)。

## 状态

草案阶段：只有边界文档和约定清单，尚无 plugin.json、skills、hooks 或代码。

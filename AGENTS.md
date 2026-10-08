# gis-plugin 开发规则

- 中文沟通和文档；公开 API、命令、路径、标识符和 JSON 字段保持英文。
- 本仓库是 GIS 系列的薄外壳插件：skills 入口、跨引擎 hooks、约定说明、评测与诊断。边界以 [docs/boundaries.md](docs/boundaries.md) 为准。
- 设计理念见 [docs/philosophy.md](docs/philosophy.md)：skills 只写能力与入口，不堆规则清单；约束落在引擎报错和 hooks 里，hooks 注入事实而非指令。
- 不放任何读写 GIS 数据的代码（不 import pyogrio、GDAL、rasterio、shapely、geopandas 等）；需要读数据时调用引擎 CLI。hooks 只用 Python 标准库。
- 不复制、vendor 或改写引擎代码；gis-kit、gis-view、gis-composer 各以自己的仓库为唯一维护源。引擎缺失或版本不兼容时明确报告，禁止自动回退或改用其它引擎。
- 不做通用插件注册表、调度框架或自动安装；安装、升级、同步、推送和公开均须用户明确授权。
- 不提交凭据、令牌、本地 URL、运行记录、trace、私有数据或用户的 semantics 文件；示例只用占位符。
- 测试产物写仓库外独立目录，设置 PYTHONDONTWRITEBYTECODE=1；结束后清理本轮产物，证据保留在仓库外。
- 修改前检查 Git 状态；保留用户未提交修改。交付前运行对应测试、git diff --check 和 secret scan。

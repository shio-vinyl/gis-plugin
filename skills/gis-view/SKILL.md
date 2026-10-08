---
name: gis-view
description: 为用户打开轻量、只读的本地 GIS 观察窗口，查看已有矢量或栅格的目录、图层、元数据、CRS、属性表和临时显示；用户需要亲眼看数据时使用。空间分析交给 gis-kit，正式地图交给 gis-composer。
---

# GIS 数据观察窗口

通过本 skill 目录下的启动脚本调用独立 gis-view，把本地网址交给用户：

```bash
python3 scripts/run.py gis-view open /path/to/folder-or-file
python3 scripts/run.py gis-view open --browser
python3 scripts/run.py gis-view status
python3 scripts/run.py gis-view cache clear
python3 scripts/run.py gis-view stop
```

引擎位置来自环境变量 `GIS_VIEW_CMD`；未设置、无法启动或版本不兼容时，运行 gis-doctor 查看原因。参数以 `python3 scripts/run.py gis-view --help` 为准。

- `open` 默认只打印 URL；`--browser` 会打开用户的系统浏览器。
- URL 含随机访问令牌。
- 路径为文件时，viewer 授权并连接其父目录。

viewer 只读源数据，提供目录、图层、元数据、CRS、地图识别、原始属性表、筛选、选择和临时显示状态；不做空间分析、编辑、写回、导出或正式制图。显示语义、安全边界与已知问题以 gis-view 仓库的 `README.md` 与 `docs/` 为准。

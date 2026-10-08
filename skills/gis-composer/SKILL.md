---
name: gis-composer
description: 使用独立 gis-composer 运行时制作地图 PNG、Storyboard 地图影片及显式 Blender DEM 地形图/影片；适用于地点、路线和专题图的视觉交付，空间计算与数据清理由 gis-kit 等 GIS 工具承担。
---

# 地图与影片交付

本 skill 是轻量调用入口；引擎、配方、字体与数据留在运行时仓库，不复制进 skill。Scene 是静态帧，Storyboard 按采样时间生成 Scene；动画必须可 seek，不依赖墙钟。MapLibre 为默认二维后端，QGIS 与 Blender 按明确需求使用。

## 运行时与路径

通过本 skill 目录下的启动脚本调用运行时；引擎位置来自环境变量 `GIS_COMPOSER_CMD`（指向 `src/agent-entry.js` 的命令），未设置或无法启动时运行 gis-doctor 查看原因。

```sh
python3 scripts/run.py gis-composer describe
```

`describe` 首行 JSON 的 `runtime` 是运行时目录，下文记为 `$R`；recipes、README 与 `src/cli.js` 都在其中。

使用 Node.js ≥22 和已有运行环境；缺依赖、字体、Chrome 或输入资源时报告实际缺项，不静默安装、更新或更换后端。CLI、Scene/Storyboard 契约以运行时源码及 `$R/README.md` 为准。

在调用项目保存 Scene、Storyboard、输入和 outputs；相对资源路径遵循对应 Scene/Storyboard 契约，命令行输出路径按调用目录解析。运行时资源可使用既有受控挂载，不放宽路径沙箱。地图不直接承诺读取任意 GPKG、GeoTIFF 或 CRS；先用 GIS 工具准备支持的 GeoJSON、瓦片或带地理四角的显示图片，保留分析原件、单位、分类、NoData 与候选状态。

## 按任务选择入口

| 任务 | 读取与执行 |
|---|---|
| GIS 分析结果进入专题图 | 先读 `$R/recipes/analysis-thematic.md`；GIS 准备 GeoJSON / Mercator 显示 PNG，保留分析原件和状态 |
| 静态地图、专题图、标签或样式修改 | 先读 `$R/recipes/maplibre-cartography.md`；`inspect` 检查最终样式，再调用下述 Scene 快捷入口 |
| 二维地图影片 | 按需读 README 的 Storyboard、tracks/effects、encode 和 recovery 部分；显式 `encode --all-frames`，不能把抽样预览当完整影片 |
| DEM 地形图或三维影片 | 按需读 README 的 Local recovery and Blender terrain；先准备合法地形包，再显式 `renderer: "blender"`；影片目前仅支持 `camera3d` 轨道 |
| 原生制图效果 | QGIS 仅在 shapeburst、选择性遮罩、特定 PAL 注记/投影或既有 QML 等具体缺口下调用；栅格 pass 不等于可编辑 QGZ/QPT 交付 |

```sh
# 静态 Scene：先 lint --expect-no-frame，再真实渲染与 QA。
python3 scripts/run.py gis-composer ./map.scene.json --out ./outputs/map.png
# 完整 Storyboard 影片：输出目录与视频路径显式指定。
python3 scripts/run.py gis-composer encode ./film.storyboard.json --all-frames --out ./outputs/frames --video ./outputs/film.mp4
```

快捷文件入口只用于静态 Scene；Storyboard 使用显式命令。薄入口支持 `describe / inspect / lint / render / qa / encode / repeatability / preview`。`describe` 同时列出完整 CLI 能力；其中 `determinism / optimize / bench / bench-storyboard` 应调用 `node "$R/src/cli.js" <command> ...`，不能直接传给薄入口。

## 制图与验收

新作品先明确参考/需求，选择或定制视觉方案，无要求才用 data-focus；修改旧作品保留已确认样式。先 inspect，后渲染，核对符号、分类与图例。默认无地图边框、无图例圆角；显式用户要求除外。

常规点字优先同一 symbol 的 icon+text、候选锚点与足够间距；比例圆保留数据编码。绑定显式本地许可字体，保持 DOM/mapFontFamily 一致，分别核验加载、字符覆盖和实际字形。重要对象声明 `qa.requiredLabels`，不得全局允许重叠、大量隐藏标签或无限缩字换取通过。

打开真实 PNG 检查完整标签、中英字体、点字关系与图例。保留 QA 的估算框和最终原生字形框 unavailable 状态，未覆盖不能报零冲突。影片检查实际视频、全帧 QA 与显隐切换。相同输入/后端/profile 独立复渲染后再报告可重复性；样式修订前后用于视觉比较，不要求改样式后的图像字节不变。

## 长任务与三维边界

二维影片可显式使用 `--warm` 复用浏览器；`--workers N` 要求 warm。Blender Storyboard 自动复用原生进程。需要断点恢复时按 README 使用 `--checkpoint` / `--resume`，只对已支持的依赖成立；远程/瓦片、QGIS、sprite 等未覆盖输入使用 fresh render，缓存恢复不能作为独立重绘证明。

地形包保留 CRS、范围、本地原点、单位、height scale 与输入哈希。当前准备路径限 EPSG:3857 二维 underlay 和 UTM 32N 范围内的 EPSG:32632 三维；不得外推为任意投影支持。既有 Mont Blanc 脚本是示例，不自动套用其范围、路径或演示线。缺 DEM 覆盖不补造高度，地形表达不证明灾害过程或历史地貌。

Blender 严格 profile 使用 Cycles CPU 单线程及固定参数，不静默切 GPU/EEVEE。比较新生成的解码 RGBA 与规范 PNG，移除元数据本身不证明确定性，不宣称跨硬件一致。地形遮挡引起的标签隐藏保留报告，并检查重要对象表达。

交付 Scene/Storyboard、PNG/影片与 QA/manifest 的实际路径，说明运行时版本/指纹、工作树状态、真实验收范围和未解决问题。任务结束清理本次进程，不关闭用户原有应用；测试通过与视觉通过分别报告。

#!/usr/bin/env python3
"""Run a GIS engine from its GIS_*_CMD variable; arguments pass through unchanged. Standard library only."""

import os
import shlex
import sys

ENGINES = {"gis-kit": "GIS_KIT_CMD", "gis-view": "GIS_VIEW_CMD", "gis-composer": "GIS_COMPOSER_CMD"}


def main(argv):
    if not argv or argv[0] not in ENGINES:
        sys.exit("用法：run.py {" + ",".join(ENGINES) + "} [参数...]")
    engine, var = argv[0], ENGINES[argv[0]]
    raw = os.environ.get(var, "").strip()
    if not raw:
        sys.exit(f"未设置 {var}，无法调用 {engine}；运行 gis-doctor 查看配置方式。")
    try:
        command = shlex.split(raw)
    except ValueError as exc:
        sys.exit(f"{var} 无法解析：{exc}")
    try:
        os.execvp(command[0], command + argv[1:])
    except OSError as exc:
        sys.exit(f"无法启动 {engine}（{command[0]}）：{exc.strerror}；运行 gis-doctor 排查。")


if __name__ == "__main__":
    main(sys.argv[1:])

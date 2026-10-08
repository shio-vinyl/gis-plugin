#!/usr/bin/env python3
"""Run a GIS engine from its GIS_*_CMD variable; arguments pass through unchanged. Standard library only."""

import os
import shlex
import sys

ENGINES = {"gis-kit": "GIS_KIT_CMD", "gis-view": "GIS_VIEW_CMD", "gis-composer": "GIS_COMPOSER_CMD"}


def engine_settings(environ):
    """GIS_* settings: environment variables win over the shared file ~/.config/gis-plugin/engines.env."""
    path = environ.get("GIS_PLUGIN_CONFIG") or os.path.join(
        environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "gis-plugin", "engines.env")
    settings = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                key, sep, value = line.strip().partition("=")
                key, value = key.strip(), value.strip()
                if sep and key.startswith("GIS_"):
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                        value = value[1:-1]
                    settings[key] = value
    except OSError:
        pass
    settings.update({k: v for k, v in environ.items() if k.startswith("GIS_") and v.strip()})
    return settings


def main(argv):
    if not argv or argv[0] not in ENGINES:
        sys.exit("用法：run.py {" + ",".join(ENGINES) + "} [参数...]")
    engine, var = argv[0], ENGINES[argv[0]]
    raw = engine_settings(os.environ).get(var, "").strip()
    if not raw:
        sys.exit(f"未设置 {var}（环境变量或 ~/.config/gis-plugin/engines.env），无法调用 {engine}；运行 gis-doctor 查看。")
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

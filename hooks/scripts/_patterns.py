"""Glob patterns shared by the gis-plugin hooks (`.gis/sources.json`, `.gis/semantics.json`). Standard library only."""

import re


def glob_regex(pattern):
    """`*` and `?` stay within one segment, `**` spans segments, `dir/**` also matches `dir`."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.endswith("/**") and i == len(pattern) - 3:
            out.append("(?:/.*)?")  # `dir/**` also covers `dir` itself
            i += 3
        elif pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")

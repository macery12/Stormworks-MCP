"""Local issue reports with structured reproduction evidence and a readable Markdown copy."""
import json
import os
import platform
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

CATEGORIES = ("placement", "rotation", "smoothing", "connections", "definitions", "performance",
              "tool_error", "usability", "missing_feature", "analysis", "other")
SEVERITIES = ("low", "medium", "high", "blocker")
ID_RE = re.compile(r"complaint-[0-9a-f]{32}")
MAX_REPORT_BYTES = 65536


def complaints_dir():
    if os.environ.get("SW_COMPLAINTS_DIR"):
        return Path(os.environ["SW_COMPLAINTS_DIR"])
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(base) / "stormworks-hull-mcp" / "complaints"


def _text(value, name, maximum=12000, required=False):
    if not isinstance(value, str) or len(value) > maximum or required and not value.strip():
        raise ValueError(f"{name} must be {'nonempty ' if required else ''}text, at most {maximum} characters")
    return value.strip()


def _markdown(report):
    lines = [f"# {report['title']}", "", f"Report: {report['id']}",
             f"Created (UTC): {report['created_at']}",
             f"Category: {report['category']} | Severity: {report['severity']}", ""]
    for label, key in (("Issue", "description"), ("Expected behavior", "expected"),
                       ("Actual behavior / error", "actual"), ("Suggested improvement", "suggestion")):
        if report[key]:
            lines.extend([f"## {label}", "", report[key], ""])
    if report["steps"]:
        lines.extend(["## Reproduction steps", ""])
        lines.extend(f"{i}. {step}" for i, step in enumerate(report["steps"], 1))
        lines.append("")
    if report["tool"] or any(report["references"].values()):
        lines.extend(["## Affected tool and references", ""])
        if report["tool"]:
            lines.append(f"Tool: {report['tool']}")
        lines.extend(f"{key.capitalize()}: {value}" for key, value in report["references"].items() if value)
        lines.append("")
    if report["context"]:
        lines.extend(["## Context", "", "```json", json.dumps(report["context"], indent=2, ensure_ascii=False), "```", ""])
    lines.extend(["## Runtime", "", f"Python: {report['runtime']['python']}",
                  f"Platform: {report['runtime']['platform']}", ""])
    return "\n".join(lines)


def create(title, description, category="other", severity="medium", tool="", expected="", actual="",
           steps=None, context=None, design="", vehicle="", definition="", suggestion=""):
    """Record explicitly supplied evidence; neither inspect other files nor publish externally."""
    if category not in CATEGORIES or severity not in SEVERITIES:
        raise ValueError(f"category must be one of {', '.join(CATEGORIES)}; severity one of {', '.join(SEVERITIES)}")
    steps = [] if steps is None else steps
    context = {} if context is None else context
    if not isinstance(steps, list) or len(steps) > 50:
        raise ValueError("steps must be a list with at most 50 reproduction steps")
    if not isinstance(context, dict):
        raise ValueError("context must be a JSON object")
    report = {"schema_version": 1, "id": "complaint-" + uuid.uuid4().hex,
              "created_at": datetime.now(timezone.utc).isoformat(), "reporter": "mcp_ai",
              "title": _text(title, "title", 200, required=True),
              "description": _text(description, "description", required=True),
              "category": category, "severity": severity, "tool": _text(tool, "tool", 200),
              "expected": _text(expected, "expected"), "actual": _text(actual, "actual"),
              "steps": [_text(s, "reproduction step", 2000, required=True) for s in steps],
              "references": {"design": _text(design, "design", 200), "vehicle": _text(vehicle, "vehicle", 200),
                             "definition": _text(definition, "definition", 200)},
              "context": context, "suggestion": _text(suggestion, "suggestion"),
              "runtime": {"python": platform.python_version(), "platform": platform.system()}}
    try:
        serialized = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("context must contain finite, serializable JSON data") from exc
    if len(serialized) > MAX_REPORT_BYTES:
        raise ValueError("complaint exceeds 64 KiB; trim context to the relevant reproduction evidence")
    contents = {".json": serialized + b"\n", ".md": _markdown(report).encode("utf-8")}
    directory = complaints_dir()
    directory.mkdir(parents=True, exist_ok=True)
    temporary, published = [], []
    try:
        for suffix, data in contents.items():
            path = directory / f"{report['id']}{suffix}"
            if path.exists():
                raise OSError("complaint id already exists; retry to generate a new report")
            with tempfile.NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as f:
                staged = Path(f.name)
                temporary.append((staged, path))
                f.write(data)
        for staged, path in temporary:
            os.replace(staged, path)
            published.append(path)
    except OSError:
        for path in published:
            path.unlink(missing_ok=True)
        raise
    finally:
        for staged, _ in temporary:
            staged.unlink(missing_ok=True)
    return {"id": report["id"], "title": report["title"], "category": category, "severity": severity,
            "created_at": report["created_at"], "json_path": str((directory / f"{report['id']}.json").resolve()),
            "report_path": str((directory / f"{report['id']}.md").resolve()), "saved_locally": True}


def read(complaint_id):
    if not isinstance(complaint_id, str) or not ID_RE.fullmatch(complaint_id):
        raise ValueError("invalid complaint id; use the id returned by complaint or list_complaints")
    path = complaints_dir() / f"{complaint_id}.json"
    if not path.is_file():
        raise ValueError(f"no complaint with id {complaint_id}")
    report = json.loads(path.read_text(encoding="utf-8"))
    return {**report, "report_markdown": _markdown(report)}


def catalogue(search="", category="", severity="", offset=0, limit=50):
    if not isinstance(search, str) or category and category not in CATEGORIES or severity and severity not in SEVERITIES:
        raise ValueError("search must be text and category/severity must be supported values or empty")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0 or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ValueError("offset must be nonnegative and limit must be 1-200")
    rows = []
    for path in complaints_dir().glob("complaint-*.json"):
        if not ID_RE.fullmatch(path.stem):
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        if category and report["category"] != category or severity and report["severity"] != severity:
            continue
        if search.casefold() not in json.dumps(report, ensure_ascii=False).casefold():
            continue
        rows.append({key: report[key] for key in ("id", "title", "created_at", "category", "severity", "tool")})
    rows.sort(key=lambda r: (r["created_at"], r["id"]), reverse=True)
    return {"complaints": rows[offset:offset + limit], "total": len(rows),
            "next_offset": offset + limit if offset + limit < len(rows) else None}

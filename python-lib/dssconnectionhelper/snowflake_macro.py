import datetime
import html
import json
import re
import traceback
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


_SAFE_KEY_RE = re.compile(r"[^A-Z0-9_]")


def normalize_variable_name(prefix: str, key: str) -> str:
    prefix = (prefix or "").strip()
    key = (key or "").strip().upper()
    key = _SAFE_KEY_RE.sub("_", key)
    key = re.sub(r"_+", "_", key).strip("_")
    return f"{prefix}{key}" if prefix else key


def json_loads_maybe(value: Optional[str]) -> Dict[str, Any]:
    if not value:
        return {}
    return json.loads(value)


def html_page(title: str, body: str) -> str:
    title_esc = html.escape(title)
    return f"""<!doctype html>
<html>
  <head>
    <meta charset='utf-8'/>
    <title>{title_esc}</title>
    <style>
      body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Arial, sans-serif; padding: 16px; }}
      code, pre {{ background: #f6f8fa; padding: 2px 4px; border-radius: 4px; }}
      pre {{ padding: 12px; overflow-x: auto; }}
      table {{ border-collapse: collapse; width: 100%; }}
      th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
      th {{ background: #fafafa; }}
      .muted {{ color: #666; }}
      .error {{ border-left: 4px solid #b00020; padding-left: 12px; }}
      .ok {{ border-left: 4px solid #0b7; padding-left: 12px; }}
    </style>
  </head>
  <body>
    <h2>{title_esc}</h2>
    {body}
  </body>
</html>"""


def html_error(title: str, message: str, *, exc: Optional[BaseException] = None) -> str:
    msg = html.escape(message)
    details = ""
    if exc is not None:
        tb = html.escape("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        details = f"""<details><summary>Details</summary><pre>{tb}</pre></details>"""
    return html_page(title, f"<div class='error'><p>{msg}</p>{details}</div>")


def html_ok(title: str, message: str) -> str:
    msg = html.escape(message)
    return html_page(title, f"<div class='ok'><p>{msg}</p></div>")


@dataclass
class CandidateVariable:
    key: str
    value: str
    source: str


def diff_variables(
    current: Dict[str, Any], desired: Dict[str, str]
) -> Tuple[Dict[str, str], Dict[str, Tuple[Any, str]], Dict[str, Any]]:
    to_add: Dict[str, str] = {}
    to_change: Dict[str, Tuple[Any, str]] = {}
    unchanged: Dict[str, Any] = {}

    for name, new_value in desired.items():
        if name not in current:
            to_add[name] = new_value
        else:
            old_value = current[name]
            if str(old_value) != str(new_value):
                to_change[name] = (old_value, new_value)
            else:
                unchanged[name] = old_value
    return to_add, to_change, unchanged


def render_candidates_table(prefix: str, candidates: List[CandidateVariable]) -> str:
    rows = []
    for c in candidates:
        var_name = normalize_variable_name(prefix, c.key)
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(var_name)}</code></td>"
            f"<td>{html.escape(str(c.value))}</td>"
            f"<td class='muted'>{html.escape(c.source)}</td>"
            "</tr>"
        )

    if not rows:
        return "<p class='muted'>No variable candidates computed.</p>"

    return (
        "<table>"
        "<thead><tr><th>Variable</th><th>Value</th><th>Source</th></tr></thead>"
        "<tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def build_selection_payload(
    *,
    connection_name: str,
    selected_keys: List[str],
    variable_prefix: str,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "version": 1,
        "connection_name": connection_name,
        "selected_keys": selected_keys,
        "variable_prefix": variable_prefix,
        "generated_at": generated_at or datetime.datetime.utcnow().isoformat() + "Z",
    }


def extract_desired_variables(prefix: str, candidates: List[CandidateVariable], selected_keys: List[str]) -> Dict[str, str]:
    selected_set = set(selected_keys)
    desired: Dict[str, str] = {}
    for c in candidates:
        if c.key in selected_set:
            desired[normalize_variable_name(prefix, c.key)] = str(c.value)
    return desired


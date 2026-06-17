import html
import json
from typing import Any, Dict, List, Optional

from dataiku.runnables import Runnable


def _plugin_setting(plugin_config: Dict[str, Any], key: str) -> Optional[str]:
    if not plugin_config:
        return None
    value = plugin_config.get(key)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _safe_name(s: str) -> str:
    return "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in (s or "")).upper().strip("_")


def _html_page(title: str, body: str) -> str:
    title_esc = html.escape(title)
    return f"""<!doctype html>
<html>
  <head>
    <meta charset='utf-8'/>
    <title>{title_esc}</title>
    <style>
      body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Arial, sans-serif; padding: 16px; }}
      table {{ border-collapse: collapse; width: 100%; }}
      th, td {{ border: 1px solid #ddd; padding: 6px 8px; }}
      th {{ background: #fafafa; }}
      code, pre {{ background: #f6f8fa; border-radius: 4px; }}
      pre {{ padding: 12px; overflow-x: auto; }}
      .muted {{ color: #666; }}
      .error {{ border-left: 4px solid #b00020; padding-left: 12px; }}
      .ok {{ border-left: 4px solid #0b7; padding-left: 12px; }}
      input[type=text] {{ width: 100%; box-sizing: border-box; }}
    </style>
  </head>
  <body>
    <h2>{title_esc}</h2>
    {body}
  </body>
</html>"""


def _html_error(message: str) -> str:
    return _html_page("Add Snowflake variables", f"<div class='error'><p>{html.escape(message)}</p></div>")


class MyRunnable(Runnable):
    def __init__(self, project_key, config, plugin_config):
        self.project_key = project_key
        self.config = config or {}
        self.plugin_config = plugin_config or {}

    def get_progress_target(self):
        return None

    def run(self, progress_callback):
        """HTML macro.

        This macro expects the UI to post a `selection_json` field in config.
        The UI itself is provided via `getChoicesFromPython` + `paramsPythonSetup`.
        """

        # Late imports: only available in DSS runtime.
        try:
            import dataiku
            import dataikuapi
        except Exception:
            return _html_error("This macro must run inside DSS (dataiku modules unavailable).")

        selection_json_raw = self.config.get("selection_json")
        if not selection_json_raw:
            return _html_error(
                "No selections received. Please use the macro UI to fill the table and run the macro."
            )

        try:
            payload = json.loads(selection_json_raw)
        except Exception:
            return _html_error("Invalid selection_json: must be valid JSON")

        load_user = bool(payload.get("load_user_variables", False))
        save_user = bool(payload.get("save_user_variables", False))
        rows = payload.get("rows") or []

        dss_host = _plugin_setting(self.plugin_config, "dss_host")
        api_key = _plugin_setting(self.plugin_config, "api_key")
        if not dss_host or not api_key:
            return _html_error("Plugin is not configured: missing dss_host/api_key")

        user_client = dataiku.api_client()
        admin_client = dataikuapi.DSSClient(dss_host, api_key)

        # Write to project variables (standard)
        project = user_client.get_project(self.project_key)
        variables = project.get_variables()
        standard = variables.get("standard", {})

        written: List[str] = []
        skipped: List[str] = []
        for row in rows:
            var_name = (row.get("variable_name") or "").strip()
            value = row.get("value")
            if not var_name:
                continue
            if value is None:
                skipped.append(var_name)
                continue
            standard[var_name] = str(value)
            written.append(var_name)

        variables["standard"] = standard
        project.set_variables(variables)

        # Save to user profile (best-effort). We store the entire payload.
        saved_ok = False
        if save_user:
            try:
                # Store per-project; key prefix makes it easy to find.
                auth = user_client.get_auth_info() if hasattr(user_client, "get_auth_info") else {}
                login = auth.get("authIdentifier") or auth.get("login") or ""
                state_key = f"dss-connection-helper:add-snowflake-variables:{self.project_key}:{login}"

                if hasattr(user_client, "set_user_custom_state"):
                    user_client.set_user_custom_state(state_key, payload)
                    saved_ok = True
                elif hasattr(user_client, "set_custom_state"):
                    user_client.set_custom_state(state_key, payload)
                    saved_ok = True
            except Exception:
                saved_ok = False

        # Summarize
        body = "<div class='ok'>"
        body += f"<p>Wrote <b>{len(written)}</b> project variables.</p>"
        if skipped:
            body += f"<p class='muted'>Skipped {len(skipped)} empty values.</p>"
        if save_user:
            body += f"<p>Saved to user profile: <b>{'yes' if saved_ok else 'failed'}</b></p>"
        body += "</div>"

        if written:
            body += "<h3>Written variables</h3><ul>" + "".join(
                f"<li><code>{html.escape(v)}</code></li>" for v in written
            ) + "</ul>"

        # Echo UI toggles for clarity
        body += "<h3>Options</h3><ul>"
        body += f"<li>Load user's variables: <code>{html.escape(str(load_user))}</code></li>"
        body += f"<li>Save user's variables: <code>{html.escape(str(save_user))}</code></li>"
        body += "</ul>"

        return _html_page("Add Snowflake variables", body)

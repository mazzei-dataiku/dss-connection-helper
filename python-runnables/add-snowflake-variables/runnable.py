import html
import json
from typing import Any, Dict, List, Optional

from dataiku.runnables import Runnable


def _get_plugin_setting(plugin_config: Dict[str, Any], key: str) -> Optional[str]:
    if not plugin_config:
        return None
    value = plugin_config.get(key)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


class MyRunnable(Runnable):
    def __init__(self, project_key, config, plugin_config):
        self.project_key = project_key
        self.config = config or {}
        self.plugin_config = plugin_config or {}

    def get_progress_target(self):
        return None

    def run(self, progress_callback):
        """Project macro to preview/apply Snowflake variables.

        Notes:
        - This runnable is intended to be launched from Project > Macros.
        - It returns HTML. Interactivity is implemented as a "2-run" flow:
          1) Preview computes candidates and emits a JSON payload.
          2) Apply/Save uses that JSON payload (pasted in `selection_json`).
        """

        from dssconnectionhelper.snowflake_macro import (
            CandidateVariable,
            build_selection_payload,
            diff_variables,
            extract_desired_variables,
            html_error,
            html_ok,
            html_page,
            json_loads_maybe,
            render_candidates_table,
        )

        action = (self.config.get("action") or "preview").strip()
        connection_name = (self.config.get("connection_name") or "").strip()
        variable_prefix = (self.config.get("variable_prefix") or "SNOWFLAKE_").strip()
        dry_run = bool(self.config.get("dry_run", True))
        selection_json_raw = self.config.get("selection_json")

        dss_url = _get_plugin_setting(self.plugin_config, "dss_url")
        api_key = _get_plugin_setting(self.plugin_config, "api_key")

        if not dss_url or not api_key:
            return html_error(
                "Add Snowflake variables",
                "Plugin settings are missing: please set `dss_url` and `api_key` in the plugin configuration.",
            )

        try:
            import dataiku
            import dataikuapi
        except Exception as exc:
            return html_error(
                "Add Snowflake variables",
                "Could not import DSS Python APIs in this environment. This macro must run inside DSS.",
                exc=exc,
            )

        # --- Clients ---
        try:
            user_client = dataiku.api_client()
        except Exception as exc:
            return html_error(
                "Add Snowflake variables",
                "Could not create user-level DSS client.",
                exc=exc,
            )

        try:
            admin_client = dataikuapi.DSSClient(dss_url, api_key)
        except Exception as exc:
            return html_error(
                "Add Snowflake variables",
                "Could not create admin-level DSS client from plugin settings.",
                exc=exc,
            )

        # --- Helper functions that depend on DSS runtime ---
        def list_user_visible_snowflake_connections() -> List[str]:
            """Best-effort listing of user-visible Snowflake connections.

            DSS API variations exist across versions; we try multiple patterns.
            """

            # Pattern A: `list_connections()` returns dicts with `type` / `name`.
            if hasattr(user_client, "list_connections"):
                conns = user_client.list_connections()
                names = [c.get("name") for c in conns if c.get("type") == "Snowflake"]
                return sorted([n for n in names if n])

            # Pattern B: older API may have `get_connection_names`.
            if hasattr(user_client, "get_connection_names"):
                try:
                    return sorted(user_client.get_connection_names(type="Snowflake"))
                except TypeError:
                    # Some versions might use lowercase
                    return sorted(user_client.get_connection_names(type="snowflake"))

            return []

        def compute_candidates_with_admin(selected_connection: str) -> List[CandidateVariable]:
            """Compute variables candidates.

            For v1, we derive candidates from connection params only.
            If you later need to query Snowflake information schema, extend here.
            """

            # Best-effort: retrieve connection info.
            if not hasattr(admin_client, "get_connection"):
                raise RuntimeError("Admin client does not support get_connection() in this DSS version")
            conn = admin_client.get_connection(selected_connection)
            params = conn.get_settings().get_raw() if hasattr(conn, "get_settings") else {}

            # Try common Snowflake connection param keys. Keep generic & safe.
            candidates: List[CandidateVariable] = []
            for key in [
                "account",
                "warehouse",
                "database",
                "schema",
                "role",
                "user",
            ]:
                if key in params and params.get(key) not in (None, ""):
                    candidates.append(CandidateVariable(key=key, value=str(params.get(key)), source="connection"))
            return candidates

        # --- User custom state persistence (best-effort) ---
        def load_user_saved_selection() -> Dict[str, Any]:
            if hasattr(user_client, "get_auth_info"):
                auth = user_client.get_auth_info()
                login = auth.get("authIdentifier") or auth.get("login") or ""
            else:
                login = ""
            state_key = f"dss-connection-helper:add-snowflake-variables:{self.project_key}:{login}"

            # DSS exposes different APIs; try a couple.
            if hasattr(user_client, "get_user_custom_state"):
                return user_client.get_user_custom_state(state_key) or {}
            if hasattr(user_client, "get_custom_state"):
                return user_client.get_custom_state(state_key) or {}
            return {}

        def save_user_selection(payload: Dict[str, Any]) -> None:
            if hasattr(user_client, "get_auth_info"):
                auth = user_client.get_auth_info()
                login = auth.get("authIdentifier") or auth.get("login") or ""
            else:
                login = ""
            state_key = f"dss-connection-helper:add-snowflake-variables:{self.project_key}:{login}"
            if hasattr(user_client, "set_user_custom_state"):
                user_client.set_user_custom_state(state_key, payload)
                return
            if hasattr(user_client, "set_custom_state"):
                user_client.set_custom_state(state_key, payload)
                return
            raise RuntimeError("User custom state API not available in this DSS version")

        def reset_user_selection() -> None:
            save_user_selection({})

        # --- Main flow ---
        try:
            visible_conns = list_user_visible_snowflake_connections()

            # Auto-fill if user didn't specify a connection.
            if not connection_name:
                saved = load_user_saved_selection()
                connection_name = (saved.get("connection_name") or "").strip()

            if action == "reset_saved":
                reset_user_selection()
                return html_ok("Add Snowflake variables", "Saved selections cleared.")

            if action in ("apply", "save"):
                payload = json_loads_maybe(selection_json_raw)
                if not payload:
                    return html_error(
                        "Add Snowflake variables",
                        "`selection_json` is required for Apply/Save. Run Preview first and paste the JSON payload.",
                    )

                selected_connection = payload.get("connection_name") or connection_name
                selected_keys = payload.get("selected_keys") or []
                prefix = payload.get("variable_prefix") or variable_prefix

                if not selected_connection:
                    return html_error("Add Snowflake variables", "No connection selected.")
                if visible_conns and selected_connection not in visible_conns:
                    return html_error(
                        "Add Snowflake variables",
                        "Selected connection is not visible to the current user.",
                    )

                candidates = compute_candidates_with_admin(selected_connection)
                desired = extract_desired_variables(prefix, candidates, list(selected_keys))

                # Save selections (profile) regardless of dry_run.
                save_user_selection(payload)
                if action == "save":
                    return html_ok("Add Snowflake variables", "Selections saved to your profile.")

                # Apply: write to project variables.
                project = user_client.get_project(self.project_key)
                variables = project.get_variables()
                current_std = variables.get("standard", {})

                to_add, to_change, _unchanged = diff_variables(current_std, desired)
                if dry_run:
                    body = "<p><b>Dry run</b>: no variables were written.</p>"
                else:
                    current_std.update(desired)
                    variables["standard"] = current_std
                    project.set_variables(variables)
                    body = "<p><b>Applied</b>: project variables updated.</p>"

                summary = (
                    f"<p>Connection: <code>{html.escape(selected_connection)}</code></p>"
                    f"<p>Would add: {len(to_add)}; change: {len(to_change)}</p>"
                )
                table = render_candidates_table(prefix, candidates)
                return html_page("Add Snowflake variables", body + summary + table)

            # Preview
            if visible_conns and not connection_name:
                conn_html = "".join(
                    f"<li><code>{html.escape(c)}</code></li>" for c in visible_conns
                )
                conn_block = (
                    "<p>Select a connection by setting the <code>connection_name</code> parameter "
                    "or re-run after saving selections.</p>"
                    f"<p>Visible Snowflake connections:</p><ul>{conn_html}</ul>"
                )
                return html_page("Add Snowflake variables", conn_block)

            if visible_conns and connection_name and connection_name not in visible_conns:
                return html_error(
                    "Add Snowflake variables",
                    "The specified connection is not visible to the current user.",
                )

            if not connection_name:
                return html_error(
                    "Add Snowflake variables",
                    "No Snowflake connection selected.",
                )

            candidates = compute_candidates_with_admin(connection_name)
            selected_keys = [c.key for c in candidates]
            payload = build_selection_payload(
                connection_name=connection_name,
                selected_keys=selected_keys,
                variable_prefix=variable_prefix,
            )

            desired = extract_desired_variables(variable_prefix, candidates, selected_keys)
            project = user_client.get_project(self.project_key)
            current_std = project.get_variables().get("standard", {})
            to_add, to_change, unchanged = diff_variables(current_std, desired)

            body = (
                f"<p>Connection: <code>{html.escape(connection_name)}</code></p>"
                f"<p>Prefix: <code>{html.escape(variable_prefix)}</code></p>"
                f"<p>Candidate variables: {len(candidates)}</p>"
                f"<p>Diff vs current project variables — add: {len(to_add)}, change: {len(to_change)}, unchanged: {len(unchanged)}</p>"
                "<h3>Selection JSON</h3>"
                "<p class='muted'>Paste this into <code>selection_json</code> to Apply or Save.</p>"
                f"<pre>{html.escape(json.dumps(payload, indent=2, sort_keys=True))}</pre>"
                "<h3>Candidates</h3>"
                + render_candidates_table(variable_prefix, candidates)
            )
            return html_page("Add Snowflake variables", body)
        except Exception as exc:
            return html_error("Add Snowflake variables", "Macro failed.", exc=exc)
        

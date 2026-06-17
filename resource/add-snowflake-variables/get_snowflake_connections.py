from typing import Any, Dict, List, Optional


def _plugin_setting(plugin_config: Dict[str, Any], key: str) -> Optional[str]:
    if not plugin_config:
        return None
    value = plugin_config.get(key)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _list_user_visible_snowflake_connections(user_client) -> List[str]:
    # Best-effort across DSS versions.
    if hasattr(user_client, "list_connections"):
        conns = user_client.list_connections()
        names = [c.get("name") for c in conns if c.get("type") in ("Snowflake", "snowflake")]
        return sorted([n for n in names if n])

    if hasattr(user_client, "get_connection_names"):
        try:
            return sorted(user_client.get_connection_names(type="Snowflake"))
        except TypeError:
            return sorted(user_client.get_connection_names(type="snowflake"))

    return []


def _load_user_saved_payload(user_client, project_key: str) -> Dict[str, Any]:
    auth = user_client.get_auth_info() if hasattr(user_client, "get_auth_info") else {}
    login = auth.get("authIdentifier") or auth.get("login") or ""
    state_key = f"dss-connection-helper:add-snowflake-variables:{project_key}:{login}"

    if hasattr(user_client, "get_user_custom_state"):
        return user_client.get_user_custom_state(state_key) or {}
    if hasattr(user_client, "get_custom_state"):
        return user_client.get_custom_state(state_key) or {}
    return {}


def _admin_fetch_connection_params(admin_client, connection_name: str) -> Dict[str, Any]:
    if not hasattr(admin_client, "get_connection"):
        return {}
    conn = admin_client.get_connection(connection_name)
    if hasattr(conn, "get_settings"):
        settings = conn.get_settings()
        if hasattr(settings, "get_raw"):
            return settings.get_raw() or {}
    return {}


def _build_rows(connection_name: str, conn_params: Dict[str, Any], prefix: str) -> List[Dict[str, Any]]:
    # Minimal v1: drive table from connection params.
    # You can expand to query Snowflake catalogs later.
    rows = []
    for key in ["account", "warehouse", "database", "schema", "role", "user"]:
        if key not in conn_params:
            continue
        rows.append(
            {
                "connection": connection_name,
                "key": key,
                "variable_name": f"{prefix}{key.upper()}",
                "value": "" if conn_params.get(key) is None else str(conn_params.get(key)),
            }
        )
    return rows


def do(payload, config, plugin_config, inputs):
    """Entry point for paramsPythonSetup.

    DSS calls this script to build the macro UI/choices.
    We return an HTML template-like content that provides the custom interface.

    NOTE: Dataiku calls conventions differ by version; we keep this minimal and
    only rely on `dataiku` being available.
    """

    import dataiku
    import dataikuapi

    project_key = (config or {}).get("projectKey") or (payload or {}).get("projectKey") or ""
    user_client = dataiku.api_client()

    dss_host = _plugin_setting(plugin_config, "dss_host")
    api_key = _plugin_setting(plugin_config, "api_key")
    if not dss_host or not api_key:
        return {
            "error": "Plugin is not configured: missing dss_host/api_key",
        }
    admin_client = dataikuapi.DSSClient(dss_host, api_key)

    connections = _list_user_visible_snowflake_connections(user_client)

    # Prefill rows for all visible connections (slower but explicit).
    prefix = "SNOWFLAKE_"
    rows: List[Dict[str, Any]] = []
    for c in connections:
        params = _admin_fetch_connection_params(admin_client, c)
        rows.extend(_build_rows(c, params, prefix))

    # If we have saved user payload, optionally prefill values.
    saved = _load_user_saved_payload(user_client, project_key)
    prefill = bool(saved)
    if prefill and isinstance(saved.get("rows"), list):
        by_var = {r.get("variable_name"): r.get("value") for r in saved.get("rows")}
        for r in rows:
            vname = r.get("variable_name")
            if vname in by_var and by_var[vname] not in (None, ""):
                r["value"] = by_var[vname]

    return {
        "projectKey": project_key,
        "connections": connections,
        "rows": rows,
        "saved": saved,
        "prefill": prefill,
        "defaultPrefix": prefix,
    }

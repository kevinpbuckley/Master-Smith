"""The editor's MCP endpoint (VibeUE, http://127.0.0.1:8000/mcp) called directly - no unreal-mcp/unreal-engine-mcp
tool connection needed, and no Unreal MCP server import either (2026-10-07: the session's own MCP tool connection
dropped mid-batch while the editor was fine). Runs code with `execute_python_code`, always `auto_save: false`
(AGENTS.md: never save a character or the level from here; `mh_editor.safe_save` is still how a MetaHuman Creator
character gets saved). Importable with no editor running (`run()` only talks to it when called); `ms ue` is the CLI."""
import json
import os
import urllib.error
import urllib.request

URL = os.environ.get("MASTERSMITH_UE_MCP_URL", "http://127.0.0.1:8000/mcp")


def _post(body, sid=None, timeout=30):
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if sid:
        h["Mcp-Session-Id"] = sid
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
        sid = r.headers.get("Mcp-Session-Id") or sid
    if raw.lstrip().startswith("data:") or "\ndata:" in raw:          # an event stream: the last data line
        raw = [ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")][-1]
    return (json.loads(raw) if raw.strip() else None), sid


def _session():
    _, sid = _post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "mastersmith.ue_client", "version": "1"}}})
    _post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    return sid


def list_tools(timeout=30):
    sid = _session()
    res, _ = _post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, sid, timeout=timeout)
    return [t["name"] for t in res["result"]["tools"]]


def run(code, timeout=600):
    """Runs `code` in the editor with execute_python_code, auto_save always false. Returns the tool's printed text
    (stdout the code wrote). Raises RuntimeError on an MCP-level error (not on exceptions the code itself raised and
    printed - those come back as ordinary text, same as the editor's own console)."""
    sid = _session()
    res, _ = _post({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "execute_python_code", "arguments": {"code": code, "auto_save": False}}},
                   sid, timeout=timeout)
    if res is None:
        raise RuntimeError("no response from the editor's MCP endpoint (%s)" % URL)
    if "error" in res:
        raise RuntimeError(json.dumps(res["error"]))
    return "\n".join(c["text"] for c in res["result"].get("content", []) if c.get("type") == "text")


def reachable():
    """False without raising: whether the editor's MCP endpoint answers at all, for a caller that wants to say so
    rather than wait out a long timeout (the editor can be down, mid-restart, or just not this machine's)."""
    try:
        _session()
        return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False

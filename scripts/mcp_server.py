#!/usr/bin/env python3
"""Small read-only MCP server for the same snapshot used by the menu bar app."""
import json
import sys
from collector import snapshot


def send(message):
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def handle(request):
    method = request.get("method")
    ident = request.get("id")
    if ident is None:
        return
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "codex-dashboard", "version": "0.2.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": "get_token_usage",
                             "description": "Read local Codex session status, model, context estimate, limits, and token counts for today and seven days. This is not billing data.",
                             "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string", "description": "Optional Codex session ID to inspect."}}, "additionalProperties": False},
                             "annotations": {"readOnlyHint": True}}]}
    elif method == "tools/call":
        name = (request.get("params") or {}).get("name")
        if name != "get_token_usage":
            send({"jsonrpc": "2.0", "id": ident, "error": {"code": -32602, "message": "Unknown tool"}})
            return
        try:
            args = (request.get("params") or {}).get("arguments") or {}
            data = snapshot(args.get("session_id"))
            result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
                      "structuredContent": data}
        except Exception as exc:
            result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    else:
        send({"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "Method not found"}})
        return
    send({"jsonrpc": "2.0", "id": ident, "result": result})


for line in sys.stdin:
    try:
        handle(json.loads(line))
    except Exception as exc:
        print(f"codex-dashboard MCP error: {exc}", file=sys.stderr)

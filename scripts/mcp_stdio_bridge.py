#!/usr/bin/env python3
"""StdIO bridge for MCP: proxy JSON messages on stdin/stdout to the local HTTP MCP server.

Behavior:
- Reads newline-delimited JSON messages from stdin.
- If message is an MCP "initialize" (JSON-RPC style), reply with a simple capabilities result.
- Otherwise, forward the JSON body via HTTP POST to http://127.0.0.1:8000/mcp and write the HTTP JSON response to stdout.

This script must print ONLY JSON objects on stdout (one per line) so Claude's stdio parser
can consume responses without being confused by extraneous text.
"""
import os
import sys
import json

# If a project virtualenv exists, re-exec this script with the venv's python so
# installed packages (like `requests`) are available when Claude Desktop spawns
# the bridge. This avoids importing third-party modules before ensuring the
# process runs inside the project's .venv.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV_PY = os.path.join(REPO_ROOT, '.venv', 'bin', 'python')
if os.path.exists(VENV_PY) and os.path.abspath(sys.executable) != os.path.abspath(VENV_PY):
    os.execv(VENV_PY, [VENV_PY] + sys.argv)

import requests

MCP_URL = "http://127.0.0.1:8000/mcp"


def safe_print_json(obj):
    try:
        sys.stdout.write(json.dumps(obj, separators=(',', ':')) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def handle_initialize(msg):
    # Reply with properly formatted MCP initialize result.
    # Tools are declared via capabilities and listed separately in tools/list request.
    protocol_version = msg.get("params", {}).get("protocolVersion", "2025-06-18")
    resp = {
        "jsonrpc": "2.0",
        "id": msg.get("id"),
        "result": {
            "protocolVersion": protocol_version,
            "serverInfo": {
                "name": "pokemon-investment-analyzer-mcp",
                "version": "0.1"
            },
            "capabilities": {
                "tools": {}
            }
        }
    }
    safe_print_json(resp)


def handle_tools_list(msg):
    # Reply with list of available tools for Claude to call
    resp = {
        "jsonrpc": "2.0",
        "id": msg.get("id"),
        "result": {
            "tools": [
                {
                    "name": "analyze",
                    "description": "Analyze a Pokémon TCG set for investment potential.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "set_name": {
                                "type": "string",
                                "description": "Name of the Pokémon TCG set to analyze."
                            },
                            "use_ai": {
                                "type": "boolean",
                                "description": "Whether to use AI for explanation."
                            }
                        },
                        "required": ["set_name"]
                    }
                }
            ]
        }
    }
    safe_print_json(resp)


def forward_to_http(msg):
    try:
        r = requests.post(MCP_URL, json=msg, timeout=15)
        try:
            out = r.json()
        except Exception:
            out = {"status_code": r.status_code, "text": r.text}
    except Exception as e:
        out = {"error": str(e)}
    safe_print_json(out)


def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            # Only exit on explicit EOF (stdin closed)
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            # ignore non-json lines silently
            continue

        # Log all received messages to stderr for debugging
        print(f"[mcp_stdio_bridge] Received: {msg}", file=sys.stderr, flush=True)

        # Handle JSON-RPC initialize messages directly
        if isinstance(msg, dict) and msg.get("method") == "initialize":
            handle_initialize(msg)
            # Do NOT break or exit; keep the loop alive for further requests
            continue

        # Handle tools/list request
        if isinstance(msg, dict) and msg.get("method") == "tools/list":
            handle_tools_list(msg)
            continue

        # Ignore notifications (messages without id - no response expected)
        if isinstance(msg, dict) and "id" not in msg:
            print(f"[mcp_stdio_bridge] Ignoring notification: {msg.get('method')}", file=sys.stderr, flush=True)
            continue

        # Otherwise, forward to the HTTP MCP endpoint
        forward_to_http(msg)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

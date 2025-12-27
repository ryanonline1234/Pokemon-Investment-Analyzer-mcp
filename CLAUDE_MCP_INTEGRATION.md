# Connecting the local MCP server to Claude Desktop

This guide explains how to register and connect the local MCP server included
in this repository to Claude Desktop on macOS. The project already includes a
small MCP-compatible server under `mcp/` (FastAPI) with the following endpoints:

- `GET /.well-known/mcp` — serves a minimal manifest (`mcp/manifest.json`)
- `GET /mcp` — serves the same manifest (for convenience)
- `POST /mcp` — minimal MCP-style POST entrypoint accepting JSON actions
- `POST /analyze` — convenience endpoint returning analysis JSON
- `WS  /mcp/ws` — WebSocket endpoint for streaming `explain` actions

Prerequisites
- Python 3.10+ and a virtual environment (this repo uses `.venv/`)
- Activate the venv and install requirements:

```bash
. .venv/bin/activate
python -m pip install -r requirements.txt
```

Run the MCP server locally:

```bash
. .venv/bin/activate
# run directly
python -m mcp.server
# or with uvicorn
uvicorn mcp.server:app --host 127.0.0.1 --port 8000
```

Claude Desktop Configuration (macOS)

1. Open or create the Claude Desktop config at
   `~/Library/Application Support/Claude/claude_desktop_config.json`.
2. Add an entry under `mcpServers`, for example:

```json
{
  "mcpServers": {
    "pokemon_investment_analyzer": {
      "serverUrl": "http://127.0.0.1:8000/mcp",
      "type": "http"
    }
  }
}
```

Notes
- `serverUrl` points to the base MCP endpoint. This project exposes `/mcp` and
  also provides the manifest at `/.well-known/mcp`.
- For local-only use, bind to `127.0.0.1` to avoid exposing the server to the
  network.
- If Claude Desktop supports launching a process instead of HTTP, you may
  configure an absolute `command` and `args` in the config to have Claude
  start the server itself. See the MCP docs for process launch options.

MCP Protocol Compatibility
- This server implements a minimal MCP-style interface sufficient for Claude
  Desktop to call the `analyze` action. The `POST /mcp` expects JSON like:

```json
{ "action": "analyze", "set_name": "Shining Fates", "use_ai": true }
```

and returns the same JSON structure as `POST /analyze`.

WebSocket Streaming
- For longer-running AI explanations, Claude (if configured for WebSocket
  MCP transport) can connect to `/mcp/ws` and send
  `{"action":"explain","set_name":"Shining Fates"}`. The server will
  stream incremental `{"chunk": "..."}` messages followed by `{"done": true}`.

Troubleshooting
- If Claude cannot reach your server, verify port and firewall rules and make
  sure the server is listening on `127.0.0.1` or the expected interface.
- Check the server logs (stdout) for errors. The FastAPI server prints
  stack traces on error and can be run with `uvicorn --reload` for development.

Next steps
- Extend `mcp/adapter.py` to implement real provider streaming for your chosen
  model (Grok/Claude/OpenAI). Provide `AI_PROVIDER` and `AI_API_KEY` env vars.
- Expand `mcp/manifest.json` to include richer tool schemas if needed by Claude.

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

# Add project root to sys.path so we can import analyzer module
sys.path.insert(0, os.path.join(REPO_ROOT, 'python'))
import analyzer

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
                    "name": "compute_metrics",
                    "description": "Comprehensive analysis of a Pokémon TCG set combining all scrapers (price, sales, sentiment, etc.)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "set_name": {"type": "string", "description": "Name of the Pokémon TCG set"}
                        },
                        "required": ["set_name"]
                    }
                },
                {
                    "name": "scrape_price_data",
                    "description": "Fetch current booster box market price from PriceCharting",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "set_name": {"type": "string", "description": "Name of the Pokémon TCG set"}
                        },
                        "required": ["set_name"]
                    }
                },
                {
                    "name": "scrape_ebay_sales",
                    "description": "Scrape recent eBay sold listings for a product (count and average price)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query (e.g., 'Base Set booster box')"}
                        },
                        "required": ["query"]
                    }
                },
                {
                    "name": "scrape_tcgplayer_listings",
                    "description": "Check current supply/listings count on TCGplayer",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "product_name": {"type": "string", "description": "Product name to search"}
                        },
                        "required": ["product_name"]
                    }
                },
                {
                    "name": "get_top_chase_cards",
                    "description": "Get the most expensive single cards from a set",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "set_name": {"type": "string", "description": "Name of the Pokémon TCG set"},
                            "top_n": {"type": "integer", "description": "Number of top cards to return", "default": 5}
                        },
                        "required": ["set_name"]
                    }
                },
                {
                    "name": "get_set_info",
                    "description": "Get basic set metadata from Wikipedia (card count, release date, notes)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "set_name": {"type": "string", "description": "Name of the Pokémon TCG set"}
                        },
                        "required": ["set_name"]
                    }
                },
                {
                    "name": "check_reprint_news",
                    "description": "Check recent social media for reprint mentions",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "set_name": {"type": "string", "description": "Name of the Pokémon TCG set"},
                            "days_back": {"type": "integer", "description": "Days to look back", "default": 30}
                        },
                        "required": ["set_name"]
                    }
                },
                {
                    "name": "analyze_sentiment",
                    "description": "Analyze Reddit sentiment around a set",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "set_name": {"type": "string", "description": "Name of the Pokémon TCG set"},
                            "max_posts": {"type": "integer", "description": "Max posts to analyze", "default": 50}
                        },
                        "required": ["set_name"]
                    }
                },
                {
                    "name": "get_psa_population",
                    "description": "Get PSA grading population data for a card",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "card_name": {"type": "string", "description": "Full card name to search"}
                        },
                        "required": ["card_name"]
                    }
                }
            ]
        }
    }
    safe_print_json(resp)


def handle_tools_call(msg):
    """Handle tools/call by directly invoking analyzer functions."""
    tool_name = msg.get("params", {}).get("name")
    arguments = msg.get("params", {}).get("arguments", {})
    
    try:
        # Route to appropriate analyzer function
        if tool_name == "compute_metrics":
            result = analyzer.compute_metrics(arguments["set_name"])
        elif tool_name == "scrape_price_data":
            result = analyzer.scrape_price_data(arguments["set_name"])
        elif tool_name == "scrape_ebay_sales":
            result = analyzer.scrape_ebay_sales(arguments["query"])
        elif tool_name == "scrape_tcgplayer_listings":
            result = analyzer.scrape_tcgplayer_listings(arguments["product_name"])
        elif tool_name == "get_top_chase_cards":
            top_n = arguments.get("top_n", 5)
            result = analyzer.get_top_chase_cards(arguments["set_name"], top_n)
        elif tool_name == "get_set_info":
            result = analyzer.get_set_info(arguments["set_name"])
        elif tool_name == "check_reprint_news":
            days_back = arguments.get("days_back", 30)
            result = analyzer.check_reprint_news(arguments["set_name"], days_back)
        elif tool_name == "analyze_sentiment":
            max_posts = arguments.get("max_posts", 50)
            result = analyzer.analyze_sentiment(arguments["set_name"], max_posts)
        elif tool_name == "get_psa_population":
            result = analyzer.get_psa_population(arguments["card_name"])
        else:
            result = {"error": f"Unknown tool: {tool_name}"}
        
        resp = {
            "jsonrpc": "2.0",
            "id": msg.get("id"),
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2)
                    }
                ]
            }
        }
        safe_print_json(resp)
    except Exception as e:
        error_resp = {
            "jsonrpc": "2.0",
            "id": msg.get("id"),
            "error": {
                "code": -32603,
                "message": str(e)
            }
        }
        safe_print_json(error_resp)


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

        # Handle tools/call request - call analyzer functions directly
        if isinstance(msg, dict) and msg.get("method") == "tools/call":
            handle_tools_call(msg)
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

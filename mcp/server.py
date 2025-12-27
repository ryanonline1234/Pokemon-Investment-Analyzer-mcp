from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import os
import json
from pathlib import Path
import asyncio

import analyzer
from .adapter import AIAdapter

app = FastAPI(title="PokemonInvestmentAnalyzer MCP Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    set_name: str
    use_ai: bool = False


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/.well-known/mcp")
def mcp_manifest():
    # serve the manifest file so MCP-aware clients can discover capabilities
    mf = Path(__file__).parent / "manifest.json"
    if not mf.exists():
        raise HTTPException(status_code=404, detail="manifest not found")
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
        return JSONResponse(content=data)
    except Exception:
        raise HTTPException(status_code=500, detail="failed to read manifest")


@app.get("/mcp")
def mcp_base():
    # convenience: same as well-known manifest
    return mcp_manifest()


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    if not req.set_name:
        raise HTTPException(status_code=400, detail="set_name is required")
    # compute metrics using the analyzer core so tests that patch analyzer.analyzer_core
    # are respected (avoid importing the function at module import time)
    try:
        metrics = analyzer.analyzer_core.compute_metrics(req.set_name)
    except Exception:
        # fallback to wrapper-level compute_metrics if core isn't accessible
        metrics = analyzer.compute_metrics(req.set_name)
    result = {"metrics": metrics}

    if req.use_ai:
        adapter = AIAdapter.from_env()
        try:
            explanation = adapter.explain(metrics)
            result["ai_explanation"] = explanation
        except Exception as e:
            result["ai_error"] = str(e)

    return result


@app.post("/mcp")
def mcp_entry(payload: dict):
    """Minimal MCP-style HTTP entrypoint.

    Expects JSON payloads like: {"action":"analyze","set_name":"...","use_ai":false}
    Returns the same shape as /analyze for the `analyze` action.
    """
    action = payload.get("action")
    if action == "analyze":
        set_name = payload.get("set_name")
        use_ai = payload.get("use_ai", False)
        if not set_name:
            raise HTTPException(status_code=400, detail="set_name required")
        try:
            metrics = analyzer.analyzer_core.compute_metrics(set_name)
        except Exception:
            metrics = analyzer.compute_metrics(set_name)
        result = {"metrics": metrics}
        if use_ai:
            adapter = AIAdapter.from_env()
            try:
                result["ai_explanation"] = adapter.explain(metrics)
            except Exception as e:
                result["ai_error"] = str(e)
        return result

    raise HTTPException(status_code=400, detail="unsupported action")


@app.websocket("/mcp/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            msg = await websocket.receive_text()
            try:
                payload = json.loads(msg)
            except Exception:
                await websocket.send_text(json.dumps({"error": "invalid json"}))
                continue

            action = payload.get("action")
            # support action: explain -> accepts either set_name or metrics
            if action == "explain":
                set_name = payload.get("set_name")
                metrics = payload.get("metrics")
                if set_name and not metrics:
                    metrics = compute_metrics(set_name)

                if not metrics:
                    await websocket.send_text(json.dumps({"error": "metrics required"}))
                    continue

                adapter = AIAdapter.from_env()
                # stream explanation chunks
                async for chunk in adapter.stream_explain(metrics):
                    # send raw text chunks
                    await websocket.send_text(json.dumps({"chunk": chunk}))

                await websocket.send_text(json.dumps({"done": True}))
            else:
                await websocket.send_text(json.dumps({"error": "unknown action"}))

    except WebSocketDisconnect:
        return


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("MCP_PORT", "8000"))
    uvicorn.run("mcp.server:app", host="0.0.0.0", port=port, reload=False)

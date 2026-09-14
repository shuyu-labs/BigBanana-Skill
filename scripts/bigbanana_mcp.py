"""Dependency-free MCP-style stdio adapter for offline project operations.

It implements tools/list and tools/call JSON-RPC methods, so hosts without the
Python MCP package can still expose project validation and reference resolution.
Generation remains behind the normal CLI and approval gates.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from bigbanana_project import normalize_script, resolve_shot_refs
from bigbanana_quality import assess

TOOLS = [
 {"name":"project_normalize","description":"Normalize script IDs and references","inputSchema":{"type":"object","required":["script"],"properties":{"script":{"type":"object"}}}},
 {"name":"project_assess","description":"Run offline project completeness checks","inputSchema":{"type":"object","required":["project"],"properties":{"project":{"type":"string"}}}},
 {"name":"shot_refs","description":"Resolve reference image paths for a shot","inputSchema":{"type":"object","required":["project","script","shot"],"properties":{"project":{"type":"string"},"script":{"type":"object"},"shot":{"type":"object"}}}},
]
def result(value): return {"content":[{"type":"text","text":json.dumps(value, ensure_ascii=False)}]}
def call(name, args):
    if name == "project_normalize": return result(normalize_script(args["script"]))
    if name == "project_assess": return result(assess(Path(args["project"])))
    if name == "shot_refs": return result(resolve_shot_refs(args["script"], args["shot"], Path(args["project"])))
    raise ValueError(f"unknown tool: {name}")
for line in sys.stdin:
    try:
        req=json.loads(line); method=req.get("method")
        if method == "tools/list": value={"tools":TOOLS}
        elif method == "tools/call": value=call(req["params"]["name"], req["params"].get("arguments",{}))
        elif method == "initialize": value={"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"bigbanana","version":"2.0"}}
        else: value={}
        print(json.dumps({"jsonrpc":"2.0","id":req.get("id"),"result":value}, ensure_ascii=False), flush=True)
    except Exception as e:
        print(json.dumps({"jsonrpc":"2.0","id":req.get("id") if 'req' in locals() else None,"error":{"code":-32603,"message":str(e)}}, ensure_ascii=False), flush=True)

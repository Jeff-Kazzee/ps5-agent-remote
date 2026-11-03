"""Smoke check: list the MCP tools and call the read-only ones in process.

Run: .venv\\Scripts\\python.exe tools\\check_mcp.py
Needs server.py running. Prints the tool names, schema sizes, and each
read-only tool's result shape. Presses no buttons.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mcp_server  # noqa: E402


async def main():
    tools = await mcp_server.mcp.list_tools()
    for t in tools:
        schema = json.dumps(getattr(t, "input_schema", None) or getattr(t, "inputSchema", {}))
        print(f"{t.name}: {len(schema)} chars of schema")
    print("instructions:", len(mcp_server.INSTRUCTIONS), "chars")
    for name, args in [("ps5_look", {"width": 640}), ("psn_library", {"limit": 3})]:
        res = await mcp_server.mcp.call_tool(name, args)
        content = res[0] if isinstance(res, tuple) else res
        content = getattr(content, "content", content)
        kinds = [getattr(c, "type", type(c).__name__) for c in content]
        texts = [getattr(c, "text", "")[:300] for c in content if getattr(c, "type", "") == "text"]
        print(f"\n{name} -> {kinds}\n  {texts}")


asyncio.run(main())

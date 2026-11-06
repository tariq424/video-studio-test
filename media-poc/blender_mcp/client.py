"""MCP client for Blender: runs the MCP for Blender server (`uvx mcp-for-blender`) over stdio
and calls its tools. That server talks to the add-on on localhost:9876 inside the live Blender.
Safe mode and telemetry-off are passed explicitly (the S12 adoption terms)."""
import contextlib
import json
import os
import re
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

LIB = (Path(__file__).with_name("scene_lib.py")).read_text(encoding="utf-8")
TOOL_TIMEOUT_S = 600


class MCPError(RuntimeError):
    pass


class BlenderMCP:
    def __init__(self, errlog_path=None):
        self._stack = None
        self.session = None
        self.errlog_path = errlog_path

    async def __aenter__(self):
        env = dict(os.environ)
        env.setdefault("BLENDER_MCP_SAFE_MODE", "1")
        env["DISABLE_TELEMETRY"] = "true"
        cmd = os.environ.get("BLENDER_MCP_COMMAND", "uvx")
        args = os.environ.get("BLENDER_MCP_ARGS", "mcp-for-blender").split()
        self._stack = contextlib.AsyncExitStack()
        errlog = self._stack.enter_context(open(self.errlog_path, "a", encoding="utf-8")) if self.errlog_path else None
        kw = {"errlog": errlog} if errlog else {}
        read, write = await self._stack.enter_async_context(
            stdio_client(StdioServerParameters(command=cmd, args=args, env=env), **kw))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        return self

    async def __aexit__(self, *exc):
        await self._stack.aclose()

    async def tool(self, name, args=None):
        """-> (text, images). Raises MCPError on tool errors or safe-mode rejections."""
        res = await self.session.call_tool(name, args or {}, read_timeout_seconds=TOOL_TIMEOUT_S)
        content = getattr(res, "content", None) or []
        text = "\n".join(c.text for c in content if getattr(c, "type", "") == "text")
        images = [c for c in content if getattr(c, "type", "") == "image"]
        if getattr(res, "isError", False) or re.match(r"^\s*(Error|Rejected by safe mode)", text):
            raise MCPError(f"{name}: {text[:1500]}")
        return text, images

    async def py(self, code):
        """Run Python inside Blender; return the last JSON object it printed."""
        text, _ = await self.tool("execute_blender_code", {"code": code})
        for line in reversed([l.strip() for l in text.splitlines() if l.strip()]):
            m = re.search(r"\{.*\}$", line)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    continue
        return {"ok": True, "raw": text}

    async def scene(self, fn, *args):
        """Call one scene_lib function inside Blender (library text + one call; nothing is imported)."""
        if not re.fullmatch(r"[a-z_]+", fn):
            raise ValueError(fn)
        # A JSON string literal is also a valid Python string literal.
        call = f"\n{fn}(*json.loads({json.dumps(json.dumps(list(args)))}))\n"
        out = await self.py(LIB + call)
        if out.get("ok") is False:
            raise MCPError(f"{fn}: {out.get('error', 'failed')}")
        return out

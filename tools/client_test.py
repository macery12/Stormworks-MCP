"""Drive the server over stdio like Claude Desktop does. Saves into a temp vehicles dir."""
import asyncio
import base64
import os
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))


async def main():
    tmp = tempfile.mkdtemp()
    params = StdioServerParameters(command=sys.executable, args=[os.path.join(HERE, "..", "server.py")],
                                   env={**os.environ, "SW_VEHICLES_DIR": tmp,
                                        "SW_DESIGNS_DIR": os.path.join(tmp, "designs")})
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        init = await s.initialize()
        print("instructions:", (init.instructions or "")[:80], "...")
        tools = await s.list_tools()
        print("tools:", [t.name for t in tools.tools])
        res = await s.call_tool("preview_hull", {"preset": "tugboat", "spec": {"length": 12}})
        kinds = [c.type for c in res.content]
        img = next(c for c in res.content if c.type == "image")
        print("preview:", kinds, len(base64.b64decode(img.data)), "png bytes, error:", res.is_error)
        print(next(c.text for c in res.content if c.type == "text"))
        res = await s.call_tool("save_hull", {"name": "client test", "preset": "rowboat"})
        print("save:", res.is_error, res.content[0].text.splitlines()[0])
        res = await s.call_tool("save_hull", {"name": "client test", "preset": "rowboat"})
        print("save again w/o overwrite -> error expected:", res.is_error, res.content[0].text[:80])
        res = await s.call_tool("preview_hull", {"spec": {"length": 500}})
        print("bad spec -> error expected:", res.is_error, res.content[0].text[:90])
        print("files:", os.listdir(tmp))


asyncio.run(main())

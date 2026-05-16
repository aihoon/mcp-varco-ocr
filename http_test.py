from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession

async def main():
    async with streamablehttp_client("http://ubuntu-server-ip:8765/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "ocr_from_path",
                {"image_path": "./test_ocr.png"}
            )
            print(result)
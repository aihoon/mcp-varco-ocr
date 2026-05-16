# my_app.py (어디서든 실행 가능)
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    server_params = StdioServerParameters(
        command="ssh",
        args=[
            "YOUR_USER@ubuntu-server-ip",
            "/home/YOUR_USER/.local/share/virtualenvs/mcp-varco-ocr-xxx/bin/python",
            "/home/YOUR_USER/mcp-varco-ocr/server.py"
        ]
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 도구 목록 확인
            tools = await session.list_tools()
            print([t.name for t in tools.tools])

            # OCR 호출
            result = await session.call_tool(
                "ocr_from_path",
                {"image_path": "./test_ocr.png"}
            )
            print(result)

import asyncio
asyncio.run(main())
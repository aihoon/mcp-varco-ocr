import argparse
import asyncio
import base64
from pathlib import Path
from typing import Any

from mcp import ClientSession

try:
    from mcp.client.streamable_http import streamablehttp_client
except ImportError:
    from mcp.client.streamable_http import streamable_http_client as streamablehttp_client


def _validate_inputs(server_url: str, image_path: str, timeout: float) -> Path:
    if not server_url.strip():
        raise ValueError("server_url must not be empty")
    if timeout <= 0:
        raise ValueError("timeout must be > 0")
    path = Path(image_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {path}")
    return path


def _extract_payload(call_result: Any) -> dict:
    if hasattr(call_result, "structuredContent") and isinstance(call_result.structuredContent, dict):
        return call_result.structuredContent

    content = getattr(call_result, "content", None)
    if isinstance(content, list):
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str) and text.strip().startswith("{"):
                try:
                    import json

                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    pass
    return {}


async def run_mcp_http_test(server_url: str, image_path: str, timeout: float, list_only: bool) -> None:
    image_file = _validate_inputs(server_url=server_url, image_path=image_path, timeout=timeout)
    mcp_url = server_url.rstrip("/")

    async with streamablehttp_client(mcp_url, timeout=timeout) as (read, write, *_):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = [tool.name for tool in tools.tools]
            print(f"tools: {tool_names}")

            if "ocr_from_base64" not in tool_names:
                raise RuntimeError("Tool 'ocr_from_base64' not found on MCP server")
            if list_only:
                return

            img_b64 = base64.b64encode(image_file.read_bytes()).decode("utf-8")
            result = await session.call_tool("ocr_from_base64", {"image_base64": img_b64})
            payload = _extract_payload(result)

            print("\n=== ocr_from_base64 ===")
            print(f"result_type: {type(result).__name__}")
            if not payload:
                print("payload: <empty or unparsed>")
                print(result)
                return

            print(f"keys: {list(payload.keys())}")
            plain = payload.get("plain_text")
            if isinstance(plain, str):
                print(f"plain_text_len: {len(plain)}")
                print(f"plain_text_sample: {plain[:120]}")
            if "error" in payload:
                raise RuntimeError(f"OCR tool returned error: {payload['error']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP-HTTP test client for VARCO OCR server")
    parser.add_argument("--server-url", default="http://127.0.0.1:8766/mcp", help="MCP HTTP endpoint URL")
    parser.add_argument("--image-path", default="./data/test_ocr_3.png", help="Local image path for OCR test")
    parser.add_argument("--timeout", type=float, default=120.0, help="Request timeout in seconds")
    parser.add_argument("--list-only", action="store_true", help="Only initialize session and list tools")
    args = parser.parse_args()

    asyncio.run(
        run_mcp_http_test(
            server_url=args.server_url,
            image_path=args.image_path,
            timeout=args.timeout,
            list_only=args.list_only,
        )
    )


if __name__ == "__main__":
    main()

import argparse
import re
import base64
import io
import torch
from pathlib import Path
from PIL import Image
from transformers import AutoProcessor, LlavaOnevisionForConditionalGeneration

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
MODEL_NAME     = "NCSOFT/VARCO-VISION-2.0-1.7B-OCR"
TARGET_SIZE    = 2304
MAX_NEW_TOKENS = 2048
HOST           = "0.0.0.0"
REST_PORT      = 8765
MCP_PORT       = 8766

# ──────────────────────────────────────────────
# Model (loaded once on first use)
# ──────────────────────────────────────────────
_model     = None
_processor = None

def get_model():
    global _model, _processor
    if _model is None:
        print("▶ Loading model...", flush=True)
        _model = LlavaOnevisionForConditionalGeneration.from_pretrained(
            MODEL_NAME,
            torch_dtype=torch.float16,
            attn_implementation="sdpa",
            device_map="auto",
        )
        _processor = AutoProcessor.from_pretrained(MODEL_NAME)
        print(f"  device : {_model.device}", flush=True)
        print("  Model loaded.\n", flush=True)
    return _model, _processor


# ──────────────────────────────────────────────
# Shared OCR logic
# ──────────────────────────────────────────────
def _upscale(image: Image.Image) -> Image.Image:
    w, h = image.size
    if max(w, h) < TARGET_SIZE:
        factor = TARGET_SIZE / max(w, h)
        image = image.resize((int(w * factor), int(h * factor)), Image.LANCZOS)
    return image


def _run_ocr(image: Image.Image) -> str:
    model, processor = get_model()
    image = _upscale(image)
    conversation = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": "<ocr>"},
            ],
        }
    ]
    inputs = processor.apply_chat_template(
        conversation,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    ).to(model.device, torch.float16)

    generate_ids = model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS)
    trimmed = [out[len(inp):] for inp, out in zip(inputs.input_ids, generate_ids)]
    return processor.decode(trimmed[0], skip_special_tokens=False)


def _parse(raw: str) -> dict:
    pattern = r"<char>(.*?)</char><bbox>([\d\s.,]+)</bbox>"
    items = []
    for m in re.finditer(pattern, raw, re.DOTALL):
        char   = m.group(1)
        coords = [float(v.strip()) for v in m.group(2).split(",")]
        items.append({"char": char, "bbox": coords})
    return {
        "plain_text": "".join(i["char"] for i in items),
        "items": items,
        "raw": raw,
    }


def ocr_image(image: Image.Image) -> dict:
    return _parse(_run_ocr(image))


# ──────────────────────────────────────────────
# MCP tool registration (shared by stdio / http)
# ──────────────────────────────────────────────
def _register_tools(mcp):

    @mcp.tool()
    def ocr_from_path(image_path: str) -> dict:
        """
        Run OCR on an image from a local file path on the server.

        Args:
            image_path: Absolute path (e.g., /home/user/sample.png)
        Returns:
            plain_text, items(char + bbox), raw
        """
        path = Path(image_path)
        if not path.exists():
            return {"error": f"파일을 찾을 수 없습니다: {image_path}"}
        return ocr_image(Image.open(path).convert("RGB"))

    @mcp.tool()
    def ocr_from_base64(image_base64: str) -> dict:
        """
        Run OCR on a Base64-encoded image.

        Args:
            image_base64: Base64-encoded image string
        Returns:
            plain_text, items(char + bbox), raw
        """
        try:
            data  = base64.b64decode(image_base64)
            image = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception as e:
            return {"error": f"이미지 디코딩 실패: {e}"}
        return ocr_image(image)


# ──────────────────────────────────────────────
# Run mode 1: MCP stdio
# ──────────────────────────────────────────────
def run_mcp_stdio():
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("varco-ocr")
    _register_tools(mcp)
    get_model()
    print("▶ Starting MCP server (stdio)", flush=True)
    mcp.run(transport="stdio")


# ──────────────────────────────────────────────
# Run mode 2: MCP HTTP (streamable-http)
# ──────────────────────────────────────────────
def run_mcp_http():
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("varco-ocr")
    _register_tools(mcp)
    get_model()
    print(f"▶ Starting MCP server (HTTP): http://{HOST}:{MCP_PORT}/mcp", flush=True)
    mcp.run(transport="streamable-http", host=HOST, port=MCP_PORT)


# ──────────────────────────────────────────────
# Run mode 3: REST HTTP (FastAPI)
# ──────────────────────────────────────────────
def run_rest():
    import uvicorn
    from fastapi import FastAPI, HTTPException, UploadFile, File
    from pydantic import BaseModel

    app = FastAPI(title="VARCO OCR REST API", version="1.0.0")

    # Request schemas
    class PathRequest(BaseModel):
        image_path: str

    class Base64Request(BaseModel):
        image_base64: str

    # Preload model
    @app.on_event("startup")
    async def startup():
        get_model()

    # Health check
    @app.get("/health")
    def health():
        return {"status": "ok"}

    # Endpoint 1: server local path
    @app.post("/ocr/path")
    def ocr_path(req: PathRequest):
        path = Path(req.image_path)
        if not path.exists():
            raise HTTPException(404, detail=f"파일을 찾을 수 없습니다: {req.image_path}")
        return ocr_image(Image.open(path).convert("RGB"))

    # Endpoint 2: Base64
    @app.post("/ocr/base64")
    def ocr_base64(req: Base64Request):
        try:
            data  = base64.b64decode(req.image_base64)
            image = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception as e:
            raise HTTPException(400, detail=f"이미지 디코딩 실패: {e}")
        return ocr_image(image)

    # Endpoint 3: file upload
    @app.post("/ocr/upload")
    async def ocr_upload(file: UploadFile = File(...)):
        try:
            data  = await file.read()
            image = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception as e:
            raise HTTPException(400, detail=f"파일 읽기 실패: {e}")
        return ocr_image(image)

    print(f"▶ Starting REST server: http://{HOST}:{REST_PORT}", flush=True)
    print(f"  POST /ocr/path    — server local file path", flush=True)
    print(f"  POST /ocr/base64  — Base64 image", flush=True)
    print(f"  POST /ocr/upload  — file upload", flush=True)
    uvicorn.run(app, host=HOST, port=REST_PORT)


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VARCO OCR Server")
    parser.add_argument(
        "--mode",
        choices=["mcp-stdio", "mcp-http", "rest"],
        default="rest",
        help=(
            "mcp-stdio: MCP stdio (for MCP clients like Claude Desktop)\n"
            "mcp-http : MCP HTTP  (for network MCP clients, port 8766)\n"
            "rest     : HTTP REST (for general HTTP clients like curl/requests, port 8765)"
        ),
    )
    args = parser.parse_args()

    if args.mode == "mcp-stdio":
        run_mcp_stdio()
    elif args.mode == "mcp-http":
        run_mcp_http()
    elif args.mode == "rest":
        run_rest()

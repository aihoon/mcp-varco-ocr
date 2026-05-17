import argparse
import re
import base64
import io
import asyncio
import os
import json
import time
import uuid
import hashlib
import queue
import threading
from dataclasses import dataclass
from concurrent.futures import Future
from datetime import datetime, timezone
from pathlib import Path
import torch
from contextlib import asynccontextmanager
from typing import Any
from PIL import Image
from transformers import AutoProcessor, LlavaOnevisionForConditionalGeneration
from observability.logger import setup_logger, get_logger

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
MODEL_NAME     = "NCSOFT/VARCO-VISION-2.0-1.7B-OCR"
TARGET_SIZE    = 2304
MAX_NEW_TOKENS = 1024
HOST           = "0.0.0.0"
REST_PORT      = 8765
MCP_PORT       = 8766
QUEUE_MAXSIZE  = 128
LOG_PATH       = os.environ.get("OCR_LOG_PATH", "./logs/server.log")
LOG_LEVEL      = os.environ.get("OCR_LOG_LEVEL", "INFO")
SAVE_INPUT_POLICY = os.environ.get("OCR_SAVE_INPUT_POLICY", "always").strip().lower()     # always / on_error / off
ARTIFACTS_DIR  = Path(os.environ.get("OCR_ARTIFACTS_DIR", "./logs/artifacts"))

# ──────────────────────────────────────────────
# Model (loaded once on first use)
# ──────────────────────────────────────────────
_model: LlavaOnevisionForConditionalGeneration | None = None
_processor: Any | None = None
_ocr_queue_manager: "InProcessOCRQueue | None" = None
LOGGER = get_logger("varco-ocr")

def get_model() -> tuple[LlavaOnevisionForConditionalGeneration, Any]:
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
        image = image.resize((int(w * factor), int(h * factor)), Image.Resampling.LANCZOS)
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
        "plain_text": " ".join(i["char"] for i in items),
        "items": items,
        "raw": raw,
    }


def ocr_image(image: Image.Image) -> dict:
    return _parse(_run_ocr(image))


@dataclass
class OCRTask:
    future: Future
    image: Image.Image
    request_id: str
    source: str
    enqueue_ts: float
    input_bytes: bytes | None = None
    input_ext: str = "png"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_hex(data: bytes | None) -> str | None:
    if data is None:
        return None
    return hashlib.sha256(data).hexdigest()


def _save_json_artifact(request_id: str, source: str, payload: dict) -> Path:
    date_dir = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    target_dir = ARTIFACTS_DIR / date_dir / "responses"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{request_id}_{source}.json"
    target_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return target_path


def _save_input_image(request_id: str, source: str, image_bytes: bytes, image_ext: str) -> Path:
    date_dir = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    target_dir = ARTIFACTS_DIR / date_dir / "inputs"
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_ext = image_ext.lower().strip(".") or "bin"
    target_path = target_dir / f"{request_id}_{source}.{safe_ext}"
    target_path.write_bytes(image_bytes)
    return target_path


def _should_save_input(policy: str, success: bool) -> bool:
    normalized = policy.strip().lower()
    if normalized == "always":
        return True
    if normalized == "on_error":
        return not success
    if normalized == "off":
        return False
    return False


def _log_ocr_event(
    *,
    task: OCRTask,
    result: dict | None,
    error: Exception | None,
    started_ts: float,
    finished_ts: float,
) -> None:
    success = error is None
    wait_ms = int((started_ts - task.enqueue_ts) * 1000)
    infer_ms = int((finished_ts - started_ts) * 1000)
    total_ms = int((finished_ts - task.enqueue_ts) * 1000)
    response_path = None
    if result is not None:
        response_path = _save_json_artifact(task.request_id, task.source, result)
    input_path = None
    if task.input_bytes is not None and _should_save_input(SAVE_INPUT_POLICY, success):
        input_path = _save_input_image(task.request_id, task.source, task.input_bytes, task.input_ext)
    LOGGER.info(
        "ocr_event|request_id=%s|source=%s|status=%s|wait_ms=%s|infer_ms=%s|total_ms=%s|"
        "queue_size=%s|input_sha256=%s|input_path=%s|response_path=%s|error=%s",
        task.request_id,
        task.source,
        "done" if success else "failed",
        wait_ms,
        infer_ms,
        total_ms,
        _ocr_queue_manager.qsize() if _ocr_queue_manager is not None else -1,
        _sha256_hex(task.input_bytes),
        str(input_path) if input_path else "",
        str(response_path) if response_path else "",
        "" if error is None else str(error),
    )


class InProcessOCRQueue:
    def __init__(self, maxsize: int):
        self._queue: queue.Queue[OCRTask | None] = queue.Queue(maxsize=maxsize)
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._worker_thread.start()

    def stop(self) -> None:
        if not self._started:
            return
        self._queue.put(None)
        self._worker_thread.join(timeout=5)
        self._started = False

    def submit(self, *, image: Image.Image, source: str, input_bytes: bytes | None,
               input_ext: str = "png", request_id: str | None = None) -> dict:
        request_id_value = request_id or str(uuid.uuid4())
        future: Future = Future()
        task = OCRTask(
            future=future,
            image=image,
            request_id=request_id_value,
            source=source,
            enqueue_ts=time.time(),
            input_bytes=input_bytes,
            input_ext=input_ext,
        )
        try:
            self._queue.put_nowait(task)
        except queue.Full as e:
            raise RuntimeError("QUEUE_FULL") from e
        return future.result()

    def qsize(self) -> int:
        return self._queue.qsize()

    def maxsize(self) -> int:
        return self._queue.maxsize

    def _worker_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                self._queue.task_done()
                break
            task = item
            started_ts = time.time()
            try:
                result = ocr_image(task.image)
                task.future.set_result(result)
                _log_ocr_event(task=task, result=result, error=None, started_ts=started_ts, finished_ts=time.time())
            except Exception as e:
                task.future.set_exception(e)
                _log_ocr_event(task=task, result=None, error=e, started_ts=started_ts, finished_ts=time.time())
            finally:
                self._queue.task_done()


def _validate_queue_maxsize(maxsize: int) -> None:
    if maxsize <= 0:
        raise ValueError("QUEUE_MAXSIZE must be > 0")


def _validate_save_input_policy(policy: str) -> None:
    if policy not in {"off", "on_error", "always"}:
        raise ValueError("OCR_SAVE_INPUT_POLICY must be one of: off, on_error, always")


def _get_ocr_queue_manager(maxsize: int = QUEUE_MAXSIZE) -> InProcessOCRQueue:
    global _ocr_queue_manager
    if _ocr_queue_manager is None:
        _validate_queue_maxsize(maxsize)
        _ocr_queue_manager = InProcessOCRQueue(maxsize=maxsize)
        _ocr_queue_manager.start()
    return _ocr_queue_manager


# ──────────────────────────────────────────────
# MCP tool registration (shared by stdio / http)
# ──────────────────────────────────────────────
def _register_tools(mcp, use_queue: bool = False):
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
        if use_queue:
            queue_manager = _get_ocr_queue_manager()
            try:
                return queue_manager.submit(image=image, source="mcp_http_base64", input_bytes=data, input_ext="png")
            except RuntimeError as e:
                if str(e) == "QUEUE_FULL":
                    return {"error": "서버 큐가 가득 찼습니다. 잠시 후 다시 시도하세요."}
                return {"error": f"OCR 처리 실패: {e}"}
            except Exception as e:
                return {"error": f"OCR 처리 실패: {e}"}
        request_id = str(uuid.uuid4())
        started_ts = time.time()
        try:
            result = ocr_image(image)
            _log_ocr_event(
                task=OCRTask(
                    future=Future(),
                    image=image,
                    request_id=request_id,
                    source="mcp_stdio_base64",
                    enqueue_ts=started_ts,
                    input_bytes=data,
                    input_ext="png",
                ),
                result=result,
                error=None,
                started_ts=started_ts,
                finished_ts=time.time(),
            )
            return result
        except Exception as e:
            _log_ocr_event(
                task=OCRTask(
                    future=Future(),
                    image=image,
                    request_id=request_id,
                    source="mcp_stdio_base64",
                    enqueue_ts=started_ts,
                    input_bytes=data,
                    input_ext="png",
                ),
                result=None,
                error=e,
                started_ts=started_ts,
                finished_ts=time.time(),
            )
            return {"error": f"OCR 처리 실패: {e}"}


# ──────────────────────────────────────────────
# Run mode 1: MCP stdio
# ──────────────────────────────────────────────
def run_mcp_stdio():
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("varco-ocr")
    _register_tools(mcp, use_queue=False)
    get_model()
    print("▶ Starting MCP server (stdio)", flush=True)
    mcp.run(transport="stdio")


# ──────────────────────────────────────────────
# Run mode 2: MCP HTTP (streamable-http)
# ──────────────────────────────────────────────
def run_mcp_http():
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("varco-ocr", host=HOST, port=MCP_PORT, streamable_http_path="/mcp")
    _register_tools(mcp, use_queue=True)
    get_model()
    _get_ocr_queue_manager()
    # noinspection HttpUrlsUsage
    print(f"▶ Starting MCP server (HTTP): http://{HOST}:{MCP_PORT}/mcp (in-process FIFO queue)", flush=True)
    # noinspection PyArgumentList
    mcp.run(transport="streamable-http")


# ──────────────────────────────────────────────
# Run mode 3: REST HTTP (FastAPI)
# ──────────────────────────────────────────────
def run_rest():
    import uvicorn
    from fastapi import FastAPI, HTTPException, UploadFile, File
    from pydantic import BaseModel
    from PIL import UnidentifiedImageError

    async def _submit_ocr(_app: FastAPI, image: Image.Image, source: str, input_bytes: bytes, input_ext: str) -> dict:
        try:
            return await asyncio.to_thread(
                _app.state.ocr_queue_manager.submit,
                image=image,
                source=source,
                input_bytes=input_bytes,
                input_ext=input_ext,
            )
        except RuntimeError as e:
            if str(e) == "QUEUE_FULL":
                raise HTTPException(503, detail="서버 큐가 가득 찼습니다. 잠시 후 다시 시도하세요.")
            raise HTTPException(500, detail=f"OCR 처리 실패: {e}")
        except Exception as e:
            raise HTTPException(500, detail=f"OCR 처리 실패: {e}")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        get_model()
        _app.state.ocr_queue_manager = _get_ocr_queue_manager()
        try:
            yield
        finally:
            pass

    app = FastAPI(title="VARCO OCR REST API", version="1.1.0", lifespan=lifespan)

    # Request schemas
    class Base64Request(BaseModel):
        image_base64: str

    # Health check
    @app.get("/health")
    def health():
        return {"status": "ok", "queue_size": app.state.ocr_queue_manager.qsize(),
                "queue_maxsize": app.state.ocr_queue_manager.maxsize()}

    # Endpoint 1: Base64
    @app.post("/ocr/base64")
    async def ocr_base64(req: Base64Request):
        try:
            data = base64.b64decode(req.image_base64)
            image = Image.open(io.BytesIO(data)).convert("RGB")
        except (ValueError, UnidentifiedImageError) as e:
            raise HTTPException(400, detail=f"이미지 디코딩 실패: {e}")
        return await _submit_ocr(app, image, "rest_base64", data, "png")

    # Endpoint 2: file upload
    @app.post("/ocr/upload")
    async def ocr_upload(file: UploadFile = File(...)):
        try:
            data  = await file.read()
            image = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception as e:
            raise HTTPException(400, detail=f"파일 읽기 실패: {e}")
        filename = file.filename or "upload.bin"
        ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
        return await _submit_ocr(app, image, "rest_upload", data, ext)

    # noinspection HttpUrlsUsage
    print(f"▶ Starting REST server: http://{HOST}:{REST_PORT}", flush=True)
    print(f"  POST /ocr/base64  — Base64 image (in-process FIFO queue)", flush=True)
    print(f"  POST /ocr/upload  — file upload (in-process FIFO queue)", flush=True)
    uvicorn.run(app, host=HOST, port=REST_PORT)


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────
if __name__ == "__main__":
    setup_logger(LOG_PATH, level=LOG_LEVEL)
    _validate_save_input_policy(SAVE_INPUT_POLICY)
    LOGGER.info(
        "server_boot|log_path=%s|log_level=%s|save_input_policy=%s|artifacts_dir=%s|queue_maxsize=%s",
        LOG_PATH,
        LOG_LEVEL,
        SAVE_INPUT_POLICY,
        str(ARTIFACTS_DIR),
        QUEUE_MAXSIZE,
    )

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

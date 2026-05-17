import argparse
import base64
from pathlib import Path

import httpx


def _validate_inputs(image_path: str, timeout: float) -> Path:
    path = Path(image_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {path}")
    if timeout <= 0:
        raise ValueError("timeout must be > 0")
    return path


def _print_result(name: str, response: httpx.Response) -> None:
    print(f"\n=== {name} ===")
    print(f"status: {response.status_code}")
    try:
        data = response.json()
    except Exception:
        print(response.text[:1000])
        return
    print(f"keys: {list(data.keys())}")
    plain = data.get("plain_text")
    if isinstance(plain, str):
        print(f"plain_text_len: {len(plain)}")
        print(f"plain_text_sample: {plain[:120]}")


def _assert_health(response: httpx.Response) -> None:
    if response.status_code != 200:
        raise RuntimeError(f"Health check failed: expected 200, got {response.status_code}")
    try:
        data = response.json()
    except Exception as e:
        raise RuntimeError("Health check failed: response is not valid JSON") from e
    if data.get("status") != "ok":
        raise RuntimeError(f"Health check failed: expected status='ok', got {data.get('status')!r}")
    print("HEALTH OK")


def run_rest_test(
    server_url: str,
    image_path: str,
    timeout: float,
    health_only: bool,
) -> None:
    if timeout <= 0:
        raise ValueError("timeout must be > 0")
    base_url = server_url.rstrip("/")

    with httpx.Client(timeout=timeout) as client:
        health = client.get(f"{base_url}/health")
        _assert_health(health)
        if health_only:
            return

        image_file = _validate_inputs(image_path=image_path, timeout=timeout)
        raw = image_file.read_bytes()
        img_b64 = base64.b64encode(raw).decode("utf-8")
        base64_res = client.post(f"{base_url}/ocr/base64", json={"image_base64": img_b64})
        _print_result("ocr/base64", base64_res)

        with image_file.open("rb") as fp:
            upload_res = client.post(
                f"{base_url}/ocr/upload",
                files={"file": (image_file.name, fp, "image/png")},
            )
        _print_result("ocr/upload", upload_res)


def main() -> None:
    parser = argparse.ArgumentParser(description="REST test client for VARCO OCR server")
    parser.add_argument("--server-url", default="http://127.0.0.1:8765", help="REST server base URL")
    parser.add_argument("--image-path", default="./data/test_ocr_3.png", help="Local image path for base64/upload tests")
    parser.add_argument("--timeout", type=float, default=120.0, help="Request timeout in seconds")
    parser.add_argument(
        "--health-only",
        action="store_true",
        help="Run only /health check and exit",
    )
    args = parser.parse_args()
    run_rest_test(
        server_url=args.server_url,
        image_path=args.image_path,
        timeout=args.timeout,
        health_only=args.health_only,
    )


if __name__ == "__main__":
    main()
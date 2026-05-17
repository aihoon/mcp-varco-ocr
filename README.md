# VARCO OCR Server

## 정의

`mcp-varco-ocr`는 VARCO OCR 모델을 서버 형태로 제공하는 프로젝트입니다.
동일한 OCR 기능을 `REST`와 `MCP-HTTP` 인터페이스로 제공합니다.

배포 상세 문서: [docs/deployment.md](./docs/deployment.md)
향후 배포 작업 목록: [docs/deployment_tasks.md](./docs/deployment_tasks.md)

## 기능

핵심 기능:

1. 이미지 OCR 수행 (`plain_text`, `items`, `raw` 반환)
2. REST 인터페이스 제공 (`/health`, `/ocr/base64`, `/ocr/upload`)
3. MCP-HTTP 인터페이스 제공 (`/mcp`, tool: `ocr_from_base64`)
4. `rest`, `mcp-http` 모드에서 in-process single-worker FIFO queue 적용
5. 로깅 + 결과 아티팩트(JSON) 저장

## 사용 방법

### 실행 모드

`server.py` 지원 모드:

1. `mcp-stdio`
2. `mcp-http` (port `8766`, path `/mcp`)
3. `rest` (port `8765`)

실행 예시:

```bash
python server.py --mode mcp-stdio
python server.py --mode mcp-http
python server.py --mode rest
```

### REST 클라이언트 사용

헬스체크:

```bash
curl http://127.0.0.1:8765/health
```

테스트 스크립트:

```bash
python test_rest.py --server-url http://127.0.0.1:8765 --health-only
python test_rest.py --server-url http://127.0.0.1:8765 --image-path ./data/test_ocr.png
```

### MCP-HTTP 클라이언트 사용

도구 목록 확인:

```bash
python test_mcp_http.py --server-url http://127.0.0.1:8766/mcp --list-only
```

OCR 호출 테스트:

```bash
python test_mcp_http.py --server-url http://127.0.0.1:8766/mcp --image-path ./data/test_ocr.png
```

원격 서버 사용 시 터널:

```bash
ssh -N -L 8765:192.168.0.96:8765 server-gpu
ssh -N -L 8766:192.168.0.96:8766 server-gpu
```

## 스펙

### OCR/모델 관련

- VARCO OCR 공식 예시는 `max_new_tokens=1024`를 사용합니다.
- 이 리포의 기본 설정은 `MAX_NEW_TOKENS=2048`입니다.
- 긴 페이지/문서는 생성 길이 한계로 출력이 절단될 수 있습니다.

### 요청 처리 모델

- `rest`, `mcp-http`: in-memory single-worker FIFO queue
- queue full 시: `503` 또는 MCP error 반환
- `mcp-stdio`: direct 실행 경로(큐 미적용)

### 로깅/저장 정책

- 로깅: 파일 + 콘솔 핸들러
- OCR 응답(JSON): 항상 아티팩트 저장
- 입력 이미지 저장: 정책 기반 (`off`, `on_error`, `always`)

환경변수:

- `OCR_LOG_PATH` (default: `./logs/server.log`)
- `OCR_LOG_LEVEL` (default: `INFO`)
- `OCR_ARTIFACTS_DIR` (default: `./logs/artifacts`)
- `OCR_SAVE_INPUT_POLICY` (default: `on_error`)

## 입출력 구조

### REST 엔드포인트

1. `GET /health`
2. `POST /ocr/base64`
3. `POST /ocr/upload`

### OCR 응답 스키마

```json
{
  "plain_text": "<recognized_text>",
  "items": [
    {
      "char": "<recognized_unit>",
      "bbox": [<x1>, <y1>, <x2>, <y2>]
    }
  ],
  "raw": "<model_raw_output>"
}
```

필드 의미:

- `plain_text`: 추출 텍스트 문자열
- `items`: 텍스트 단위 + bbox
- `raw`: 모델 원문 출력

`raw` 파싱 패턴:

```text
<char>...</char><bbox>x1, y1, x2, y2</bbox>
```

## 테스트

권장 최소 테스트 순서:

1. REST 헬스체크
2. REST OCR(base64/upload)
3. MCP-HTTP list-tools
4. MCP-HTTP OCR call
5. 로그/아티팩트 생성 확인

## 운영

운영 시 모니터링 포인트:

1. 서비스 접근성 (`/health`, `/mcp`)
2. queue 상태(`queue_size`, `queue_maxsize`)
3. 파일 로그(`server.log`)
4. 아티팩트 저장량 및 디스크 사용량

자주 보는 명령:

```bash
lsof -iTCP:8765 -sTCP:LISTEN -n -P
lsof -iTCP:8766 -sTCP:LISTEN -n -P
tail -f ./logs/server.log
find ./logs/artifacts -type f | tail -n 20
```

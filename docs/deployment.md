# Deployment

`mcp-varco-ocr` Docker 배포/운영 문서입니다.
목표: 개발자가 내부 구현을 몰라도 `REST` 또는 `MCP-HTTP` 서비스를 안정적으로 배포/검증할 수 있어야 합니다.

---

## 1) 배포 대상

서비스 모드:

1. `rest` (HTTP API, port `8765`)
2. `mcp-http` (MCP over HTTP, endpoint `/mcp`, port `8766`)

현재 운영 전제:

- Docker Compose 기반 실행
- GPU 사용 (`--gpus all` equivalent)
- 로그/아티팩트는 호스트 디렉토리에 영속 저장

---

## 2) 필수 사전 조건

1. Docker / Docker Compose 사용 가능
2. NVIDIA 드라이버 + NVIDIA Container Toolkit 설치
3. GPU 접근 확인:

```bash
docker run --rm --gpus all nvidia/cuda:12.1.1-runtime-ubuntu22.04 nvidia-smi
```

4. 프로젝트 경로:

```text
/home/aihoon/Workspace/mcp-varco-ocr
```

---

## 3) 파일 역할

- `Dockerfile`: 애플리케이션 이미지 빌드 정의
- `.dockerignore`: 이미지 빌드 컨텍스트에서 제외할 파일 정의
- `docker-compose.yml`: REST/MCP 서비스 정의, 포트/볼륨/환경변수 설정
- `run_docker.sh`: 서비스별 build+up 실행 스크립트

관계:

1. `docker compose up -d --build <service>` 실행
2. Compose가 `Dockerfile`로 이미지 빌드
3. 이때 `.dockerignore`가 제외 파일 적용
4. 빌드된 이미지로 컨테이너 실행

---

## 4) 로그/아티팩트 저장 정책

호스트 저장 경로(기본):

```text
/home/aihoon/Workspace/mcp-varco-ocr/logs
```

컨테이너 마운트:

```text
<host logs> -> /app/logs
```

환경변수:

- `OCR_LOG_PATH=/app/logs/server.log`
- `OCR_ARTIFACTS_DIR=/app/logs/artifacts`
- `OCR_SAVE_INPUT_POLICY=on_error`
- `OCR_LOG_LEVEL=INFO`

`OCR_SAVE_INPUT_POLICY`:

- `off`: 입력 이미지 저장 안 함
- `on_error`: OCR 처리 실패 시만 저장
- `always`: 항상 저장

---

## 5) 배포 실행 절차

프로젝트 루트에서 실행:

### 5.1 REST 배포

```bash
./run_docker.sh rest
```

### 5.2 MCP-HTTP 배포

```bash
./run_docker.sh mcp-http
```

로그 경로를 변경하려면:

```bash
./run_docker.sh rest /custom/host/logs/path
```

---

## 6) 배포 후 검증

### 6.1 컨테이너 상태

```bash
docker compose ps
```

### 6.2 REST 헬스체크

```bash
curl http://127.0.0.1:8765/health
```

### 6.3 MCP-HTTP 헬스(도구 목록)

```bash
python test_mcp_http.py --server-url http://127.0.0.1:8766/mcp --list-only
```

### 6.4 OCR 스모크 테스트

```bash
python test_rest.py --server-url http://127.0.0.1:8765 --image-path ./data/test_ocr.png
python test_mcp_http.py --server-url http://127.0.0.1:8766/mcp --image-path ./data/test_ocr.png
```

---

## 7) 로그 확인 방법

로그는 두 종류가 있습니다.

1. 컨테이너 stdout/stderr:

```bash
docker compose logs -f varco-ocr-rest
docker compose logs -f varco-ocr-mcp
```

2. 애플리케이션 파일 로그:

```bash
tail -f /home/aihoon/Workspace/mcp-varco-ocr/logs/server.log
```

주의:

- 두 로그는 source가 달라 내용이 완전히 같지 않을 수 있습니다.
- 운영 기준 소스는 `server.log`를 권장합니다.

아티팩트 확인:

```bash
find /home/aihoon/Workspace/mcp-varco-ocr/logs/artifacts -type f | tail -n 30
```

---

## 8) SSH Tunnel (원격 접속 시)

REST:

```bash
ssh -N -L 8765:192.168.0.96:8765 server-gpu
```

MCP-HTTP:

```bash
ssh -N -L 8766:192.168.0.96:8766 server-gpu
```

터널 확인:

```bash
lsof -iTCP:8765 -sTCP:LISTEN -n -P
lsof -iTCP:8766 -sTCP:LISTEN -n -P
```

---

## 9) 운영 명령 모음

기동:

```bash
./run_docker.sh rest
./run_docker.sh mcp-http
```

중지:

```bash
docker compose down
```

특정 서비스 재기동:

```bash
docker compose up -d --build varco-ocr-rest
docker compose up -d --build varco-ocr-mcp
```

컨테이너 내부 점검:

```bash
docker compose exec varco-ocr-rest sh -lc 'echo $OCR_LOG_PATH; ls -l /app/logs; tail -n 50 /app/logs/server.log'
```

---

## 10) 트러블슈팅

### 10.1 `permission denied ... /var/run/docker.sock`

- 현재 사용자의 docker 소켓 권한 문제
- `sudo` 사용 또는 docker 그룹 권한 부여 필요

### 10.2 `FastMCP.run() got an unexpected keyword argument 'host'`

- `mcp` 버전과 코드 시그니처 불일치
- 프로젝트 기준 `mcp==1.27.1` 사용

### 10.3 `httpx.ConnectError: All connection attempts failed`

- 서버 미기동 / 포트 오입력 / 터널 미연결
- MCP-HTTP는 URL 끝에 `/mcp` 필요

### 10.4 `RemoteProtocolError: Server disconnected without sending a response`

- 잘못된 모드/포트로 요청했거나 서버가 즉시 종료
- REST는 `8765`, MCP-HTTP는 `8766/mcp` 재확인

### 10.5 로그가 안 보임

- 파일 로그: 호스트 경로 `/home/aihoon/Workspace/mcp-varco-ocr/logs/server.log`
- 컨테이너 로그: `docker compose logs -f ...`
- 두 로그가 동일하지 않은 것은 정상일 수 있음

---

## 11) 릴리즈 체크리스트

1. `Pipfile`/`Pipfile.lock` 커밋 (`mcp==1.27.1` 확인)
2. `docker compose config`로 구성 유효성 확인
3. `./run_docker.sh rest` 성공
4. `./run_docker.sh mcp-http` 성공
5. REST/MCP 스모크 테스트 통과
6. `server.log` 및 artifacts 생성 확인
7. 롤백 절차(이전 이미지/태그) 준비

---

## 12) 관련 문서

- 상세 운영 체크리스트: `docs/deployment_tasks.md` #33
- 기능/클라이언트 사용: `README.md` #33

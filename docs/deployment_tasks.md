# deployment tasks

이 문서는 `mcp-varco-ocr`를 상용 환경에 배포하기 전에 필요한 작업을 정리한 체크리스트다.
현재 구현 상태는 다음을 전제로 한다.

- `rest`, `mcp-http`에서 in-process single-worker FIFO queue 사용
- OCR 결과 JSON 아티팩트 저장
- 입력 이미지 저장 정책(`off` / `on_error` / `always`) 지원
- 파일 + 콘솔 로깅(회전 로그)

---

## 1) 실행 환경/의존성 고정

1. Python/Pipenv 버전 고정
- Python 3.11 계열 고정
- `Pipfile.lock` 최신화 및 커밋

2. GPU 런타임 정합성 검증
- `torch`/`torchvision` CUDA 태그 일치(`cu121` 등)
- `accelerate`, `transformers` import 확인


3. 실행 계정/권한
- 서비스 실행용 리눅스 계정 분리(권장)
- 로그/아티팩트 디렉토리 쓰기 권한 확인

검증 명령:

```bash
pipenv run python -c "import torch, torchvision, accelerate, transformers; print(torch.__version__, torchvision.__version__, torch.version.cuda)"
pipenv run python -m py_compile server.py test_rest.py test_mcp_http.py
```

---

## 2) 설정값(Environment) 확정

필수 환경변수:

- `OCR_LOG_PATH` (예: `/var/log/varco-ocr/server.log`)
- `OCR_LOG_LEVEL` (예: `INFO`)
- `OCR_ARTIFACTS_DIR` (예: `/var/log/varco-ocr/artifacts`)
- `OCR_SAVE_INPUT_POLICY` (`off` / `on_error` / `always`)

권장 기본값:

- `OCR_SAVE_INPUT_POLICY=on_error`
- 운영 초기에는 `OCR_LOG_LEVEL=INFO`

점검:

- 상대경로 대신 절대경로 사용
- 로그/아티팩트 경로 디스크 여유 확인

---

## 3) 프로세스 관리(systemd 또는 container)

1. 자동 재시작
- 프로세스 비정상 종료 시 자동 재기동

2. 부팅 시 자동 시작
- 서버 재부팅 후 자동으로 서비스 복구

3. 종료 시 정리
- graceful shutdown 처리 (요청 중단 정책 명확화)

권장:

- 단일 인스턴스 + 단일 프로세스로 시작
- 멀티 워커로 바로 확장하지 않기(현재 큐 특성상 전역 FIFO 깨짐)

---

## 4) 네트워크/보안

1. Reverse Proxy + TLS
- Nginx 등으로 HTTPS 종단
- 내부 서비스는 private network에만 노출

2. 접근 제어
- API key 또는 내부망 allowlist
- 방화벽 규칙 적용

3. 입력 제한
- request body 최대 크기 제한
- 업로드 파일 타입/포맷 검증 강화

4. Rate limit
- 클라이언트 단위 요청 제한
- 과부하 시 명확한 오류 코드(429/503)

---

## 5) 큐/처리량 운영 정책

현재 구조(in-process queue) 기준 운영 정책:

1. 큐 길이 상한 관리
- `QUEUE_MAXSIZE` 운영값 확정
- 큐 full 시 503 반환을 클라이언트와 합의

2. 타임아웃
- 요청 타임아웃/클라이언트 재시도 정책 정의

3. 장애 시 동작
- 서버 재시작 시 in-memory 큐 유실 가능성 문서화

확장 계획:

- 중장기적으로 Redis/Celery로 전환
- API 서버/워커 분리 및 큐 영속성 확보

---

## 6) 로깅/아티팩트/보관 정책

1. 로그 정책
- 로그 파일 회전 용량/백업 개수 점검
- 민감정보 기록 금지 규칙 확정

2. 아티팩트 정책
- 결과 JSON은 항상 저장
- 입력 이미지는 정책 기반 저장

3. 보관 기간(TTL)
- 예: 30일 보관 후 자동 삭제
- 디스크 임계치 초과 방지(cleanup job)

4. 감사/추적
- `request_id` 기준으로 요청-결과 추적 가능해야 함

---

## 7) 헬스체크/모니터링/알람

1. 헬스체크
- `/health` 응답 모니터링
- queue size / queue maxsize 수집

2. 메트릭
- QPS
- p95/p99 latency
- error rate
- queue depth
- GPU memory usage

3. 알람
- 오류율 급증
- 지연 급증
- 디스크 사용량 임계치 초과

---

## 8) 배포 전 테스트

1. 기능 테스트
- REST: `/health`, `/ocr/base64`, `/ocr/upload`
- MCP-HTTP: `test_mcp_http.py` 실행

2. 부하 테스트(최소)
- 동시 요청 N개에서 latency/오류율/큐 증가 확인

3. 실패 시나리오 테스트
- 잘못된 이미지 입력
- 큰 파일 입력
- 큐 full 유도 후 응답 확인

4. 회귀 테스트
- 기존 정상 OCR 케이스 출력 비교

---

## 9) 배포 절차(runbook)

1. 배포 전
- 코드/설정 확정
- 의존성 설치 확인
- 환경변수 반영

2. 배포
- 신규 버전 기동
- 헬스체크 통과 확인
- smoke test 실행

3. 배포 후
- 초기 30~60분 집중 모니터링
- 오류율/지연/디스크 체크

4. 롤백 계획
- 이전 버전 실행 절차 사전 준비
- 실패 시 즉시 되돌릴 명령/절차 문서화

---

## 10) 지금 리포에서 바로 추가 권장 항목

우선순위 순:

1. API Key 인증 미들웨어
2. 업로드/요청 크기 제한
3. 디스크 TTL cleanup 스크립트
4. 기본 부하 테스트 스크립트(k6 또는 locust)
5. systemd 서비스 파일 템플릿

---

## 부록: 빠른 운영 점검 명령

```bash
# 서버 헬스
curl http://127.0.0.1:8765/health

# SSH 터널 상태
lsof -iTCP:8765 -sTCP:LISTEN -n -P

# 로그 추적
tail -f /var/log/varco-ocr/server.log

# 아티팩트 확인
find /var/log/varco-ocr/artifacts -type f | tail -n 20
```

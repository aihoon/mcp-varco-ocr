# pycharm remote server 개발/디버깅 가이드

이 문서는 `mcp-varco-ocr`를 PyCharm으로 원격 서버에서 개발/디버깅할 때의 실제 작업 순서를 정리한 것입니다.
설정 절차, 실행 절차, 자주 한 실수와 복구 방법을 포함합니다.

---

## 1) 목표 구조

- 로컬: PyCharm IDE
- 원격: `/home/aihoon/Workspace/mcp-varco-ocr`
- 코드 수정: 로컬에서 편집
- 실행/디버깅: 원격 Python 인터프리터로 실행
- 파일 동기화: PyCharm Deployment(자동 업로드 또는 수동 업로드)

---

## 2) 최초 설정 순서

## 2.1 원격 Python 환경 준비

원격 서버에서:

```bash
cd /home/aihoon/Workspace/mcp-varco-ocr
pipenv --rm            # 기존 깨진 venv가 있으면 제거
pipenv --python 3.11   # 프로젝트용 virtual env 생성
pipenv shell           # virtual env 진입
pipenv install
```

확인:

```bash
python --version
python -c "import torch, torchvision, accelerate, transformers; print('python deps ok')"
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
nvidia-smi
```

주의:
- `Pipfile`의 Python 요구 버전은 `3.11`처럼 minor 고정 권장
- `3.11.0`처럼 patch까지 고정하면 `3.11.15`와 불일치 경고가 뜰 수 있음

## 2.2 PyCharm Remote Interpreter 연결

1. `Settings > Python Interpreter > Add Interpreter > On SSH`
2. 원격 SSH 계정 선택
3. Existing interpreter 지정:
   - `/home/aihoon/Workspace/mcp-varco-ocr/.venv/bin/python` (또는 pipenv venv 경로)
4. Apply

문제 발생 시:
- 입력 불가/수정 불가 상태면 기존 interpreter를 제거 후 재등록이 가장 빠름

## 2.3 Deployment 매핑

1. `Settings > Build, Execution, Deployment > Deployment`
2. `Mappings`에서 로컬 프로젝트와 원격 경로를 1:1 매핑
3. `Tools > Deployment > Automatic Upload` 옵션 확인

핵심:
- Deployment가 살아 있어도 Interpreter 매핑이 끊기면 실행 실패 가능
- 반대로 Interpreter가 살아 있어도 Deployment 매핑이 틀리면 코드가 다른 경로로 업로드됨

---

## 3) 일상 개발 루틴

1. 로컬 코드 수정/저장
2. 자동 업로드 확인(또는 수동 Upload)
3. 원격 파일 반영 확인
   ```bash
   cd /home/aihoon/Workspace/mcp-varco-ocr
   ls -l server.py
   ```
4. PyCharm Remote Debug 실행
5. 오류 시 원격 로그/의존성 확인

---

## 4) 서버 실행 모드 체크

- REST: `python server.py --mode rest` (`8765`)
- MCP-HTTP: `python server.py --mode mcp-http` (`8766/mcp`)
- MCP-STDIO: `python server.py --mode mcp-stdio`

중요:
- REST 테스트 스크립트는 `8765`
- MCP-HTTP 테스트 스크립트는 `8766/mcp`
- 포트/모드 혼동 시 `RemoteProtocolError`, `ConnectError` 빈번

---

## 5) 실제로 자주 발생했던 실수와 해결

## 5.1 인터프리터 정보가 사라짐

증상:
- PyCharm에서 Remote Interpreter가 비어 있거나 수정 불가

원인:
- 프로젝트 SDK 엔트리 유실, `.idea` 변경, 업데이트 후 내부 ID mismatch

해결:
- 기존 interpreter Remove 후 `On SSH`로 재등록

## 5.2 코드가 원격으로 안 올라감

증상:
- 로컬 수정 반영이 원격 실행에 안 보임

원인:
- Deployment mapping 오류, 자동 업로드 OFF, Excluded path 설정

해결:
- `Deployment > Upload to...` 수동 업로드로 즉시 검증
- `Mappings` 경로 재확인
- `Excluded paths` 점검 (로컬 기준 제외 규칙임)

## 5.3 `ModuleNotFoundError: mcp`

원인:
- 설치한 Python과 PyCharm 실행 Python이 다름

해결:
```bash
pipenv run pip install mcp
pipenv run python -c "import mcp; print('ok')"
```
- PyCharm interpreter 경로 재확인

## 5.4 `FastMCP.run() got an unexpected keyword argument 'host'`

원인:
- `mcp` 버전과 코드 시그니처 불일치

해결:
- `mcp==1.27.1` 기준으로 고정
- `mcp-http` 실행 코드를 해당 시그니처에 맞게 수정

## 5.5 `ConnectError` / `RemoteProtocolError`

원인:
- 서버 미기동
- REST/MCP 포트 혼동
- 터널 미연결

해결:
```bash
lsof -iTCP:8765 -sTCP:LISTEN -n -P
lsof -iTCP:8766 -sTCP:LISTEN -n -P
curl http://127.0.0.1:8765/health
```

## 5.6 로그가 안 보임

원인:
- 상대경로 로그 경로 + working directory 차이

해결:
- `OCR_LOG_PATH`, `OCR_ARTIFACTS_DIR`를 절대경로로 지정
- 파일 로그와 컨테이너 stdout 로그는 source가 다르다는 점 인지

---

## 6) 디버깅 체크리스트

디버깅 전:

1. 현재 Run/Debug가 원격 interpreter를 가리키는지 확인
2. 최근 변경 파일이 원격 경로에 올라갔는지 확인
3. 서버 모드/포트가 테스트 대상과 일치하는지 확인

디버깅 중:

1. 앱 시작 로그 확인
2. 요청 전송 후 서버 로그(`server.log`) 확인
3. 실패 시 stack trace에서
   - import 문제인지
   - 연결 문제인지
   - 프로토콜/포트 문제인지 먼저 분류

---

## 7) 운영 전환 시 권장

- 로컬 원격 디버그 단계가 끝나면 Docker Compose 배포로 전환
- 배포/운영은 아래 문서 기준으로 수행
  - `docs/deployment.md`
  - `docs/deployment_tasks.md`

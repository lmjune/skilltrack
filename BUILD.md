# exe 빌드 (Windows)

```
.venv\Scripts\activate
pip install pyinstaller
pyinstaller skilltrack.spec
```

- 결과 `dist/mabiaura/` — `mabiaura.exe` + `_internal/` (파이썬 런타임·라이브러리·assets 포함). **받는 쪽은 파이썬 설치 불필요**
- 배포: `dist/mabiaura` 폴더를 zip. exe 만 따로 옮기면 안 됨
- 사용자 데이터는 exe 옆에 생김: `profiles/` (설정·레이아웃), `diag/` (진단 프레임), `mabiaura.log` (로그. 문제 생기면 이걸 보내달라고 할 것). 새 버전 zip 을 풀어 덮어써도 이 폴더는 남음
- 콘솔 창은 안 뜸 (`console=False`). 빌드 문제를 잡을 땐 spec 에서 잠깐 `True` 로
- 첫 빌드는 5~10분. 빠졌다는 모듈 오류가 나면 spec 의 `hiddenimports` 에 추가
- 백신 오탐: PyInstaller exe 는 흔히 걸림. 지인에게 예외 등록 안내. (코드 서명 인증서가 있으면 해결되지만 유료)
- 버전: `core/paths.py` 의 `VERSION` 올리고 빌드

## 확인 순서
1. `dist\mabiaura\mabiaura.exe` 더블클릭 → 홈 창 (콘솔 없음). `mabiaura.log` 생김
2. 홈 제목에 버전, 트레이 툴팁에 버전
3. 캐릭터 추가 → 영역 설정 → 켜기 까지 한 번 (assets 를 못 찾으면 여기서 죽음)
4. `dist\mabiaura\profiles\config.json` 이 생겼는지

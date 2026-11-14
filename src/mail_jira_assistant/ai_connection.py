"""Native auth readiness check: no secret export and no consumed model attempts."""

import os
import subprocess


def native_openai_ready(settings):
    if settings.ai_backend != "opencode":
        return True, "합성 FakeRunner · 실제 모델 판단 아님"
    if settings.ai_prefix or not (settings.classify_model or "").startswith("openai/"):
        return True, "설정된 OpenCode runner 사용"
    if os.environ.get("OPENAI_API_KEY"):
        return True, "Windows OpenCode · OpenAI 환경 인증 설정됨"
    try:
        result = subprocess.run(
            [settings.ai_executable, *settings.ai_global_args, "auth", "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return (
            False,
            "Windows OpenCode · 계정 연결 상태 확인 실패 (설치·인증 확인 필요)",
        )
    if result.returncode == 0 and "openai" in result.stdout.casefold():
        return True, "Windows OpenCode · OpenAI 계정 연결 확인"
    return False, "Windows OpenCode · OpenAI 계정 연결 대기 (인증 후 자동 재개)"

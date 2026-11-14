"""Exercise actual subprocess isolation, deadline and output contracts without a model."""

import json
import sys

import pytest

from mail_jira_assistant.ai import FakeRunner, OpenCodeRunner
from mail_jira_assistant.contracts import Request


def executable(tmp_path, code):
    p = tmp_path / "fake-opencode"
    p.write_text("#!" + sys.executable + "\n" + code)
    p.chmod(0o700)
    return str(p)


@pytest.mark.parametrize(
    "payload,exception,match",
    [
        ("print('not json')", ValueError, "Expecting value"),
        ("print('')", ValueError, "empty_output"),
        ("raise SystemExit(7)", RuntimeError, "nonzero_exit"),
        ("import time; time.sleep(10)", RuntimeError, "timeout"),
    ],
)
def test_runner_failure_modes(tmp_path, payload, exception, match):
    runner = OpenCodeRunner(executable(tmp_path, payload), timeout=0.25)
    with pytest.raises(exception, match=match):
        runner.classify(Request(source_ref="x", subject="test", body="question"))
    assert runner.last_log["duration"] < 4
    assert runner.last_log["kind"] == "classify"


def test_real_process_event_parser_and_redaction(tmp_path, monkeypatch):
    request = Request(source_ref="x", subject="test", body="question")
    result = FakeRunner().classify(request)
    event = json.dumps({"type": "text", "part": {"text": result.model_dump_json()}})
    monkeypatch.setenv("MAIL_JIRA_TEST_TOKEN", "synthetic-secret-12345")
    code = (
        "import sys,os\nprint("
        + repr(event)
        + ')\nprint(os.environ["MAIL_JIRA_TEST_TOKEN"],file=sys.stderr)\n'
    )
    runner = OpenCodeRunner(executable(tmp_path, code))
    assert runner.classify(request) == result
    assert "synthetic-secret-12345" not in json.dumps(runner.last_log)
    assert "[REDACTED]" in runner.last_log["stderr"]


def test_stdin_unicode_input_avoids_windows_argv_limit(tmp_path):
    request = Request(source_ref="x", subject="한글 공백", body="질문" * 18000)
    result = FakeRunner().classify(request)
    event = json.dumps({"type": "text", "part": {"text": result.model_dump_json()}})
    code = (
        "import sys\nprompt=sys.stdin.buffer.read().decode('utf-8')\nassert '한글 공백' in prompt\nprint("
        + repr(event)
        + ")\n"
    )
    # Python source itself also has an explicit UTF-8 encoding on Windows.
    script = tmp_path / "fake-stdin"
    script.write_text("#!" + sys.executable + "\n" + code, encoding="utf-8")
    runner = OpenCodeRunner(str(script), input_mode="stdin")
    assert runner.classify(request) == result


def test_windows_job_closes_owned_process_tree(tmp_path):
    import os

    if os.name != "nt":
        pytest.skip("Windows Job Object")
    import subprocess
    import time

    import win32api
    import win32event

    from mail_jira_assistant.ai import own_process

    marker = tmp_path / "child-pid"
    code = "import subprocess,sys,time;from pathlib import Path;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);Path(sys.argv[1]).write_text(str(p.pid));time.sleep(60)"
    process = subprocess.Popen([sys.executable, "-c", code, str(marker)])
    job = own_process(process)
    handle = None
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists()
        handle = win32api.OpenProcess(0x00100000, False, int(marker.read_text()))
        job.Close()
        process.wait(timeout=5)
        assert win32event.WaitForSingleObject(handle, 5000) == 0
    finally:
        job.Close()
        if handle:
            handle.Close()
        if process.poll() is None:
            process.kill()
            process.wait()

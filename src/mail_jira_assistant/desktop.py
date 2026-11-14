"""WorkTrail Windows host: local HTTP + WebView2, independent durable worker."""

import argparse
import json
import logging
import multiprocessing as mp
import os
import socket
import threading
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path


class SessionStop:
    """An OS Event cannot retain a Python condition lock after a worker is killed."""

    def __init__(self):
        self.name = "Local\\WorkTrail-stop-" + uuid.uuid4().hex
        self.handle = None
        self._get()

    def _get(self):
        if self.handle is None:
            import win32event

            self.handle = win32event.CreateEvent(None, True, False, self.name)
        return self.handle

    def __getstate__(self):
        return {"name": self.name}

    def __setstate__(self, state):
        self.name = state["name"]
        self.handle = None

    def set(self):
        import win32event

        win32event.SetEvent(self._get())

    def wait(self, timeout=None):
        import win32event

        milliseconds = (
            win32event.INFINITE if timeout is None else max(0, int(timeout * 1000))
        )
        return (
            win32event.WaitForSingleObject(self._get(), milliseconds)
            == win32event.WAIT_OBJECT_0
        )

    def is_set(self):
        return self.wait(0)


def user_data():
    return (
        Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        / "WorkTrail"
    )


def watch_parent(stop):
    def watch():
        parent = mp.parent_process()
        while parent and not stop.wait(1):
            if not parent.is_alive():
                stop.set()

    threading.Thread(target=watch, daemon=True).start()


def child_logging(settings, name):
    handler = RotatingFileHandler(
        Path(settings.runtime).parent / name,
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def backend(settings, stop, ready):
    watch_parent(stop)
    child_logging(settings, "backend.log")
    import uvicorn

    from .web import create_app

    server = uvicorn.Server(
        uvicorn.Config(
            create_app(
                settings.runtime,
                settings.knowledge,
                settings.jira_servers,
                sample_mode=settings.sample_mode,
            ),
            log_config=None,
        )
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    ready.send(sock.getsockname()[1])
    ready.close()

    def shutdown():
        stop.wait()
        server.should_exit = True

    threading.Thread(target=shutdown, daemon=True).start()
    server.run(sockets=[sock])


def tasks(settings, stop):
    watch_parent(stop)
    child_logging(settings, "worker.log")
    from .ai import FakeRunner, OpenCodeRunner
    from .service import poll, worker

    last_poll = 0

    class Runner:
        last_log = {}

        def run(self, kind, request):
            runner = OpenCodeRunner(
                settings.ai_executable,
                settings.classify_model if kind == "classify" else settings.draft_model,
                settings.ai_timeout,
                settings.ai_agent,
                prefix=settings.ai_prefix,
                global_args=settings.ai_global_args,
                input_mode=settings.ai_input,
            )
            try:
                return getattr(runner, kind)(request)
            finally:
                self.last_log = runner.last_log

        def classify(self, request):
            return self.run("classify", request)

        def draft(self, request):
            return self.run("draft", request)

    runner = Runner() if settings.ai_backend == "opencode" else FakeRunner()
    while not stop.is_set():
        try:
            if time.monotonic() - last_poll >= settings.poll_seconds:
                poll(
                    settings.runtime,
                    settings.inbox,
                    sent=settings.sent,
                    identity=settings.identity,
                    jira_servers=settings.jira_servers,
                    stable_seconds=settings.stable_seconds,
                    activate=not settings.history_only,
                    document_adapter=settings.document_adapter,
                    document_timeout=settings.document_timeout,
                    attachment_adapter=settings.attachment_adapter,
                )
                last_poll = time.monotonic()
            from .ai_connection import native_openai_ready
            from .storage import connect

            ready, status = native_openai_ready(settings)
            status_db = connect(settings.runtime)
            try:
                with status_db:
                    status_db.execute(
                        "INSERT OR REPLACE INTO meta VALUES('ai_connection_status',?)",
                        (status,),
                    )
            finally:
                status_db.close()
            if not ready:
                stop.wait(5)
                continue
            worker(
                settings.runtime,
                runner,
                settings.knowledge,
                settings.max_chars,
                lease_seconds=settings.lease_seconds,
                retry_delay=settings.retry_delay,
                automatic_drafts=settings.automatic_drafts,
            )
        except Exception:
            logging.exception("worker iteration failed")
        stop.wait(2)


def run():
    mp.freeze_support()
    parser = argparse.ArgumentParser(description="WorkTrail Windows desktop")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--samples", action="store_true")
    parser.add_argument("--smoke-seconds", type=int, default=0)
    args = parser.parse_args()
    root = (args.data_dir or user_data()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    import msvcrt

    lock = (root / "desktop.lock").open("a+b")
    try:
        lock.seek(0)
        lock.write(b"1")
        lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        if args.smoke_seconds:
            (root / "duplicate.json").write_text('{"duplicate":true}', encoding="utf-8")
            return
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            "WorkTrail이 이미 실행 중입니다. 기존 창을 확인하세요.",
            "WorkTrail",
            0,
        )
        return
    handler = RotatingFileHandler(
        root / "desktop.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    processes = []
    stop = SessionStop()
    try:
        from .settings import load

        config = args.config or root / "settings.toml"
        if not config.exists():
            config.write_text(
                'profile = "demo"\nai_backend = "fake"\nhistory_only = true\n',
                encoding="utf-8",
            )
        settings = load(config)
        settings.runtime = str(root / "runtime")
        for name in ("inbox", "sent", "knowledge"):
            if name == "sent" and not settings.sent:
                continue
            # Default package fixtures are only used with an explicit demo request.
            if not args.demo and (
                "/demo/" in str(getattr(settings, name)).replace("\\", "/")
            ):
                target = root / name
                target.mkdir(exist_ok=True)
                setattr(settings, name, str(target))
        from .storage import connect

        connect(settings.runtime).close()
        if args.samples:
            from .sample_data import install, prepare

            for key, value in prepare(root).items():
                setattr(settings, key, value)
            settings.sample_mode = True
            install(settings.runtime, settings)
        if args.demo:
            from .ai import FakeRunner
            from .service import enqueue, sync, worker

            sync(settings.runtime, settings.inbox)
            enqueue(settings.runtime)
            worker(settings.runtime, FakeRunner(), settings.knowledge)
        receiver, sender = mp.Pipe(False)
        server = mp.Process(target=backend, args=(settings, stop, sender))
        server.start()
        processes.append(server)
        sender.close()
        if not receiver.poll(30):
            raise RuntimeError("백엔드 시작 시간 초과")
        port = receiver.recv()
        receiver.close()
        import urllib.request

        for _ in range(100):
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/today", timeout=1
                ).close()
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("백엔드 응답 없음")
        worker_process = mp.Process(target=tasks, args=(settings, stop))
        worker_process.start()
        processes.append(worker_process)

        def supervise():
            current = worker_process
            while not stop.wait(2):
                if not current.is_alive():
                    logging.error(
                        "worker exited %s; restarting with durable leases",
                        current.exitcode,
                    )
                    current.join()
                    current = mp.Process(target=tasks, args=(settings, stop))
                    current.start()
                    processes.append(current)

        threading.Thread(target=supervise, daemon=True).start()
        import webview

        window = webview.create_window(
            "WorkTrail",
            f"http://127.0.0.1:{port}/today",
            width=1280,
            height=900,
            min_size=(800, 600),
            confirm_close=not bool(args.smoke_seconds),
        )
        window.events.closed += lambda: (logging.info("window closed"), stop.set())
        if args.smoke_seconds:

            def smoke():
                window.events.loaded.wait(30)
                time.sleep(2)
                report = {
                    "title": window.evaluate_js("document.title"),
                    "text": window.evaluate_js("document.body.innerText"),
                    "port": port,
                    "pid": os.getpid(),
                    "worker_pid": worker_process.pid,
                    "backend_pid": server.pid,
                    "pages": {},
                }
                for route in (
                    "/",
                    "/worklog",
                    "/projects",
                    "/?view=drafts",
                    "/operations",
                ):
                    window.load_url(f"http://127.0.0.1:{port}" + route)
                    for _ in range(50):
                        time.sleep(0.1)
                        if (
                            window.evaluate_js("location.pathname + location.search")
                            == route
                        ):
                            break
                    time.sleep(0.3)
                    report["pages"][route] = window.evaluate_js(
                        "document.body.innerText"
                    )
                window.load_url(f"http://127.0.0.1:{port}/worklog")
                (root / "smoke.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                time.sleep(args.smoke_seconds)
                logging.info("smoke closing window")
                window.destroy()
                logging.info("smoke destroy returned")

            threading.Thread(target=smoke, daemon=True).start()
        webview.start(
            gui="edgechromium", storage_path=str(root / "webview"), private_mode=False
        )
    except Exception:
        logging.exception("desktop failed")
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            "실행하지 못했습니다. desktop.log를 확인하세요. WebView2 Runtime이 필요합니다.",
            "WorkTrail",
            0,
        )
        raise
    finally:
        logging.info("desktop stopping children")
        stop.set()
        for proc in processes:
            logging.info("joining child %s", proc.pid)
            proc.join(5)
            if proc.is_alive():
                proc.terminate()
                proc.join(3)
        lock.close()
        logging.info("desktop shutdown complete")


if __name__ == "__main__":
    run()

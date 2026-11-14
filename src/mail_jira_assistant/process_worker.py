"""Spawn-safe bounded document subprocesses, also used by frozen applications."""

import multiprocessing as mp
import threading

# One authorized program call at a time. This never kills Office/Outlook.
COM_SERIAL = threading.Lock()


def _run(connection, operation, args):
    try:
        if operation == "extract":
            from .documents import _extract

            result = _extract(*args)
        else:
            from .document_access import read_in_worker

            result = read_in_worker(*args)
        connection.send(result)
    except BaseException as exc:
        connection.send(
            dict(
                status="extract_failed",
                text="",
                locations=[],
                warnings=[type(exc).__name__ + ": " + str(exc)[:500]],
            )
        )
    finally:
        connection.close()


def bounded(operation, args, timeout=15):
    context = mp.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    proc = context.Process(target=_run, args=(sender, operation, args), daemon=True)
    proc.start()
    sender.close()
    try:
        if receiver.poll(timeout):
            return receiver.recv()
        return dict(
            status="extract_failed",
            text="",
            locations=[],
            warnings=[
                "timeout: 권한 프로그램의 대화상자를 확인하고 다시 시도하세요. Office/Outlook은 종료하지 않았습니다."
            ],
        )
    except EOFError:
        return dict(
            status="extract_failed",
            text="",
            locations=[],
            warnings=["worker 종료: 재시도 필요"],
        )
    finally:
        receiver.close()
        if proc.is_alive():
            proc.terminate()  # Only this app's dedicated helper, never the COM server.
        proc.join(3)

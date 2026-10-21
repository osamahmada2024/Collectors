import json
import logging
import os
import signal
import threading
import time
from pathlib import Path
from typing import Any

from signalrcore.hub_connection_builder import HubConnectionBuilder

DEFAULT_HUB_URL = "https://backendgrad-production-8da8.up.railway.app/logs"
HUB_URL = os.getenv("SIGNALR_HUB_URL", "").strip() or DEFAULT_HUB_URL
HUB_METHOD = os.getenv("SIGNALR_HUB_METHOD", "sendLog").strip() or "sendLog"
LOG_FILE = Path(
    os.getenv(
        "TRACEE_LOG_FILE",
        str(Path(__file__).parent / "data" / "tracee-events.json"),
    )
)
RECONNECT_WAIT_SECONDS = 3
CONNECT_TIMEOUT_SECONDS = 30
ACK_TIMEOUT_SECONDS = 30

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("collector-agent")
connected = threading.Event()
stopping = threading.Event()


def extract_log(event: dict[str, Any]) -> dict[str, int | float | None]:
    """Convert one Tracee JSON event to the C# backend Log model."""
    aliases = {
        "processid": ("processId", "processid", "process_id"),
        "threadId": ("threadId", "thread_id"),
        "parentProcessId": ("parentProcessId", "parent_process_id"),
        "userId": ("userId", "user_id"),
        "mountNamespace": ("mountNamespace", "mount_namespace"),
        "eventId": ("eventId", "event_id"),
        "argsNum": ("argsNum", "args_num"),
        "returnValue": ("returnValue", "return_value"),
        "sus": ("sus",),
        "evil": ("evil",),
    }
    required = {
        "processid",
        "threadId",
        "parentProcessId",
        "userId",
        "mountNamespace",
        "eventId",
        "argsNum",
        "returnValue",
        "sus",
    }

    record: dict[str, int | float | None] = {}
    for target, names in aliases.items():
        value = next((event[name] for name in names if name in event), None)
        if value is None:
            if target in required:
                raise ValueError(f"missing required field: {target}")
            record[target] = None
            continue

        if target == "threadId":
            record[target] = float(value)
        elif target == "evil" and value is None:
            record[target] = None
        else:
            record[target] = int(value)

    return record


def iter_log_lines(path: Path):
    """Read existing JSONL records, then continue following appended records."""
    warned_missing = False
    while not stopping.is_set():
        if not path.exists():
            if not warned_missing:
                logger.warning("Waiting for log file: %s", path)
                warned_missing = True
            stopping.wait(1)
            continue

        warned_missing = False
        try:
            inode = path.stat().st_ino
            with path.open("r", encoding="utf-8") as log_file:
                while not stopping.is_set():
                    line = log_file.readline()
                    if line:
                        yield line
                        continue

                    stopping.wait(0.2)
                    if not path.exists():
                        logger.warning("Log file was removed; waiting for it to return")
                        break
                    if path.stat().st_ino != inode:
                        logger.info("Log file rotated; reading replacement: %s", path)
                        break
        except FileNotFoundError:
            logger.warning("Log file changed while opening; waiting for it to return")


def build_connection():
    hub = (
        HubConnectionBuilder()
        .with_url(HUB_URL)
        .configure_logging(logging.WARNING)
        .with_automatic_reconnect(
            {
                "type": "raw",
                "keep_alive_interval": 15,
                "reconnect_interval": RECONNECT_WAIT_SECONDS,
                "max_attempts": None,
            }
        )
        .build()
    )

    def on_open() -> None:
        connected.set()
        logger.info("Connected to SignalR hub: %s", HUB_URL)

    def on_close() -> None:
        connected.clear()
        if not stopping.is_set():
            logger.warning("SignalR connection closed; waiting for reconnect")

    hub.on_open(on_open)
    hub.on_close(on_close)
    hub.on_error(lambda error: logger.error("SignalR error: %s", error))
    return hub


def send_log(hub: Any, record: dict[str, int | float | None]) -> None:
    """Invoke the backend method and wait for its SignalR completion."""
    completed = threading.Event()
    errors: list[str] = []

    def on_invocation(messages: Any) -> None:
        if not isinstance(messages, (list, tuple)):
            messages = [messages]
        for message in messages:
            error = getattr(message, "error", None)
            if error:
                errors.append(str(error))
        completed.set()

    hub.invoke(HUB_METHOD, [record], on_invocation=on_invocation)
    if not completed.wait(ACK_TIMEOUT_SECONDS):
        raise TimeoutError("Timed out waiting for the backend to acknowledge the log")
    if errors:
        raise RuntimeError(f"Backend rejected the log: {errors[0]}")


def stop_agent(signum: int, _frame: Any) -> None:
    logger.info("Received shutdown signal %s", signum)
    stopping.set()


def run() -> None:
    signal.signal(signal.SIGINT, stop_agent)
    signal.signal(signal.SIGTERM, stop_agent)

    hub = build_connection()
    logger.info("Connecting to SignalR hub: %s", HUB_URL)
    if not hub.start():
        raise RuntimeError(f"Could not start SignalR connection to {HUB_URL}")
    if not connected.wait(CONNECT_TIMEOUT_SECONDS):
        hub.stop()
        raise TimeoutError(f"SignalR connection did not open: {HUB_URL}")

    logger.info("Reading JSONL logs from: %s", LOG_FILE)
    try:
        for line in iter_log_lines(LOG_FILE):
            if not line.strip():
                continue
            try:
                source_event = json.loads(line)
                if not isinstance(source_event, dict):
                    raise ValueError("each JSONL line must contain one event object")
                record = extract_log(source_event)
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                logger.error("Skipping invalid log record: %s", exc)
                continue

            while not stopping.is_set():
                if not connected.wait(1):
                    continue
                try:
                    send_log(hub, record)
                    logger.info("Backend acknowledged log processid=%s", record["processid"])
                    break
                except (TimeoutError, RuntimeError, OSError) as exc:
                    logger.error("Could not send log; will retry: %s", exc)
                    stopping.wait(RECONNECT_WAIT_SECONDS)
    finally:
        stopping.set()
        hub.stop()
        logger.info("Collector stopped")


if __name__ == "__main__":
    run()

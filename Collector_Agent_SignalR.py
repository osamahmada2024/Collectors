import hashlib
import json
import logging
import os
import signal
import threading
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from signalrcore.hub_connection_builder import HubConnectionBuilder

DEFAULT_HUB_URL = "https://backendgrad-production-8da8.up.railway.app/logs"
HUB_URL = os.getenv("SIGNALR_HUB_URL", "").strip() or DEFAULT_HUB_URL
HUB_METHOD = os.getenv("SIGNALR_HUB_METHOD", "sendLog").strip() or "sendLog"
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "").strip() or HUB_URL.rsplit("/", 1)[0]
LOG_FILE = Path(
    os.getenv(
        "TRACEE_LOG_FILE",
        str(Path(__file__).parent / "data" / "tracee-events.json"),
    )
)
CHECKPOINT_FILE = Path(
    os.getenv("COLLECTOR_CHECKPOINT_FILE", "/var/lib/collector/checkpoint.json")
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


def extract_log(event: dict[str, Any]) -> dict[str, Any]:
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
    }

    record: dict[str, Any] = {}
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

    record["eventName"] = event.get("eventName") or event.get("event_name")
    record["comm"] = event.get("processName") or event.get("comm")
    record["hostName"] = event.get("hostName") or event.get("hostname")
    record["timestamp"] = int(event["timestamp"]) if event.get("timestamp") is not None else None
    record["rawEvent"] = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return record


def file_identity(path: Path) -> str:
    """Identify a source file across container restarts and appended writes."""
    digest = hashlib.sha256(path.name.encode("utf-8"))
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_checkpoint() -> dict[str, Any] | None:
    try:
        checkpoint = json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
        if not isinstance(checkpoint, dict):
            raise ValueError("checkpoint must be a JSON object")
        source = checkpoint.get("source")
        offset = checkpoint.get("offset")
        if not isinstance(source, str) or not isinstance(offset, int) or offset < 0:
            raise ValueError("checkpoint source or offset is invalid")
        return checkpoint
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Could not read collector checkpoint; reconciling with backend history: %s", exc)
        return None


def write_checkpoint(source: str, offset: int) -> None:
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = CHECKPOINT_FILE.with_suffix(CHECKPOINT_FILE.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as checkpoint_file:
        json.dump({"source": source, "offset": offset}, checkpoint_file)
        checkpoint_file.flush()
        os.fsync(checkpoint_file.fileno())
    os.replace(temporary, CHECKPOINT_FILE)


def find_existing_offset(path: Path) -> int:
    """Resume after the newest event already stored by the backend on first boot."""
    request = Request(
        f"{BACKEND_API_URL.rstrip('/')}/api/logs?limit=1",
        headers={"Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            rows = json.loads(response.read().decode("utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"Could not read backend history before resuming: {exc}") from exc
    if not isinstance(rows, list):
        raise RuntimeError("Backend history response must be a JSON array")
    if not rows:
        return 0

    latest = rows[0]
    if not isinstance(latest, dict) or latest.get("processid") is None or latest.get("eventId") is None:
        raise RuntimeError("Backend history does not contain enough fields to resume safely")

    matching_offset = 0
    with path.open("rb") as source_file:
        while line := source_file.readline():
            try:
                event = json.loads(line.decode("utf-8"))
                if not isinstance(event, dict):
                    continue
                candidate = extract_log(event)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError):
                continue

            fields = ("processid", "eventId", "timestamp", "eventName", "comm", "hostName")
            if all(latest.get(field) is None or candidate.get(field) == latest.get(field) for field in fields):
                matching_offset = source_file.tell()

    if matching_offset:
        logger.info("Found newest backend event in source; resuming at byte %s", matching_offset)
    else:
        logger.info("Backend's newest event is not in this source file; reading from the beginning")
    return matching_offset


def iter_log_lines(path: Path):
    """Resume from the last committed byte, then follow appended JSONL records."""
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
            file_stat = path.stat()
            inode = file_stat.st_ino
            source = file_identity(path)
            checkpoint = read_checkpoint()
            if checkpoint and checkpoint["source"] == source:
                offset = checkpoint["offset"]
            else:
                offset = find_existing_offset(path)
                if offset:
                    write_checkpoint(source, offset)
            if offset > file_stat.st_size:
                offset = 0
            logger.info("Resuming %s at byte %s", path, offset)
            with path.open("rb") as log_file:
                log_file.seek(offset)
                while not stopping.is_set():
                    line = log_file.readline()
                    if line:
                        yield line, source, log_file.tell()
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
            stopping.wait(1)
        except (OSError, RuntimeError) as exc:
            logger.warning("Cannot initialize log resume point yet: %s", exc)
            stopping.wait(RECONNECT_WAIT_SECONDS)


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
        for line, source, next_offset in iter_log_lines(LOG_FILE):
            if not line.strip():
                write_checkpoint(source, next_offset)
                continue
            try:
                source_event = json.loads(line.decode("utf-8"))
                if not isinstance(source_event, dict):
                    raise ValueError("each JSONL line must contain one event object")
                record = extract_log(source_event)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as exc:
                logger.error("Skipping invalid log record: %s", exc)
                write_checkpoint(source, next_offset)
                continue

            while not stopping.is_set():
                if not connected.wait(1):
                    continue
                try:
                    send_log(hub, record)
                except (TimeoutError, RuntimeError, OSError) as exc:
                    logger.error("Could not send log; will retry: %s", exc)
                    stopping.wait(RECONNECT_WAIT_SECONDS)
                    continue
                write_checkpoint(source, next_offset)
                logger.info("Backend acknowledged log processid=%s", record["processid"])
                break
    finally:
        stopping.set()
        hub.stop()
        logger.info("Collector stopped")


if __name__ == "__main__":
    run()
# SignalR Collector Agent

This is a standalone service that connects to the SOC SignalR hub, reads
Tracee JSONL events from a file, and invokes the backend `sendLog` method.
The backend stores each log and broadcasts it as `newLog`.

## Input file

Put `tracee-events.json` in the `data/` directory. The file must contain one
JSON event object per line. The collector sends records already in the file
when it starts, then waits for additional lines to be appended.

Set `TRACEE_LOG_FILE` if the file is elsewhere. The input file is not included
in this template; add your own file before deployment. Avoid committing
sensitive logs or large files to GitHub.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:SIGNALR_HUB_URL = "https://backendgrad-production-8da8.up.railway.app/logs"
python collector.py
```

The hub URL defaults to the Railway URL above. The collector logs a
`Connected to SignalR hub` message after the WebSocket is open, then logs an
acknowledgement for each record accepted by the backend.

## Deploy as its own Railway service

Create a separate GitHub repository using the contents of this directory as
the repository root, then deploy that repository to Railway. Railway detects
the included Dockerfile. Add the input file at `data/tracee-events.json` before
deploying, or set the `TRACEE_LOG_FILE` Railway variable to its mounted path.

Configure these Railway variables if you need to override the defaults:

- `SIGNALR_HUB_URL`: backend SignalR URL; defaults to the Railway SOC backend.
- `SIGNALR_HUB_METHOD`: backend hub method; defaults to `sendLog`.
- `TRACEE_LOG_FILE`: JSONL file path; defaults to `/app/data/tracee-events.json`.
- `LOG_LEVEL`: Python logging level; defaults to `INFO`.

Railway cannot read a file on your Windows computer. If Tracee writes the
source file on your computer, run this collector there instead, or arrange a
separate way to upload/forward the file to Railway. A bundled file is read
once on startup; the service then stays running and waits for appended lines.

## Backend event contract

Each line must include `processId` (or `processid`), `threadId`,
`parentProcessId`, `userId`, `mountNamespace`, `eventId`, `argsNum`,
`returnValue`, and `sus`. `evil` is optional and may be `null`. The collector
maps these fields to the C# `Log` model and calls `sendLog` with one object.

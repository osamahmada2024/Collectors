# Collectors

SignalR collector that reads the JSONL dataset at `data/tracee-events.json` and
sends each event to the backend `sendLog` hub method. The dataset is included in
this repository.

By default, the collector reads the included file:

```text
data/tracee-events.json
```

Run locally from the repository root:

```powershell
python -m pip install -r requirements.txt
python Collector_Agent_SignalR.py
```

The Docker image copies the dataset to `/app/data/tracee-events.json`, which is
also the default path when running in the container. Deploying the repository
to Railway therefore includes the dataset; no separate file upload or
`TRACEE_LOG_FILE` setting is needed. Set `TRACEE_LOG_FILE` only when using a
different file path.

Optional variables: `TRACEE_LOG_FILE`, `SIGNALR_HUB_URL`,
`SIGNALR_HUB_METHOD`, and `LOG_LEVEL`.

The agent sends the complete source event as `rawEvent` alongside normalized fields. Set `SIGNALR_HUB_URL=http://localhost:5086/logs` for the local stack. The backend acknowledges after persistence and queues the SOC AI workflow separately, so AI response latency does not block log ingestion.

# Collectors

SignalR collector that reads `tracee-events.json` and sends each event to the
backend `sendLog` hub method.

The local Windows default is:

```text
C:\Users\osama\Downloads\38833FF26BA1D.UnigramPreview_g9c9v27vpyspw!App\tracee-events.json
```

Run locally:

```powershell
python -m pip install -r requirements.txt
python Collector_Agent_SignalR.py
```

To run on Railway, set `TRACEE_LOG_FILE` to the file path available inside the
Railway container (default: `/app/data/tracee-events.json`). Railway cannot
read files directly from your Windows computer. Keep private logs out of the
GitHub repository; provide the file separately to the running service.

Optional variables: `SIGNALR_HUB_URL`, `SIGNALR_HUB_METHOD`, and `LOG_LEVEL`.

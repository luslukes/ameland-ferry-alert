# ameland-ferry-alert

Monitor Ameland ferry departures and get notified when vehicle slots become available.

## Requirements

- Python 3.12
- Internet access to reach `https://api.wpd.nl`

## Installation

1. Clone or download this repository.
2. Create and activate a virtual environment (recommended):

   ```bash
   python3.12 -m venv .venv

   # Linux / macOS
   source .venv/bin/activate

   # Windows (PowerShell)
   .venv\Scripts\Activate.ps1
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

## Configuration

Edit `config.json` to set the dates and vehicle to monitor:

```json
{
  "dates": [
    "2026-09-11",
    "2026-09-12"
  ],
  "route": "HOAM",
  "licenseNumber": "K TW 3741",
  "vehicleLength": 5
}
```

| Field           | Description                                        |
|-----------------|----------------------------------------------------|
| `dates`         | List of travel dates to monitor (`YYYY-MM-DD`)     |
| `route`         | Ferry route code (e.g. `HOAM` for Holwerd–Ameland) |
| `licenseNumber` | Vehicle license plate as used on the WPD website   |
| `vehicleLength` | Vehicle length in metres                           |

The monitor reads all departures returned by the WPD API for each configured date. Departure times are taken from `startDate`, and availability from `isBookable`. The `07:15` departure is ignored because it was only used for testing.

## Execution

Run the checker from the project directory:

```bash
python checker.py
```

The script will:

1. Load `config.json`
2. Query the WPD API for each configured date and route
3. Read all returned departures and ignore `07:15`
4. Print availability for each detected departure
5. Update `state.json` to track notification status

### Exit codes

| Code | Meaning                                    |
|------|--------------------------------------------|
| `0`  | Successful execution                       |
| `2`  | Error (config, API, or notification failure) |

### Example output

```
2026-09-11 08:30 FULLY BOOKED
2026-09-11 09:45 FULLY BOOKED
2026-09-11 11:00 FULLY BOOKED
2026-09-12 08:30 AVAILABLE
2026-09-12 09:45 FULLY BOOKED
```

## Notifications

To send an ntfy notification when departures become available, run with `--notify`:

```bash
python checker.py --notify
```

Set this environment variable:

| Variable     | Description                          |
|--------------|--------------------------------------|
| `NTFY_TOPIC` | Your ntfy.sh topic name              |

Notifications are sent via HTTP POST to `https://ntfy.sh/<topic>` with this message:

```
🚢 Ameland Ferry Available

Available departures:

2026-09-12 08:30
2026-09-12 13:30

Route: HOAM
Dates: 2026-09-11, 2026-09-12
Vehicle: K TW 3741
```

Notifications are sent only when at least one departure is bookable and `notification_sent == false`. State is stored in `state.json`:

- When one or more departures become available, a single notification is sent and `notification_sent` is set to `true`.
- While any departure stays available, no further notifications are sent.
- When all departures are fully booked again, `notification_sent` resets to `false`, so a new notification is sent if availability returns.

## GitHub Actions

A workflow in `.github/workflows/monitor.yml` runs every 10 minutes and:

1. Checks all API departures for the configured dates
2. Sends one ntfy notification if any become available (using repository secrets)
3. Commits updated `state.json` to prevent duplicate notifications

### Required repository secret

- `NTFY_TOPIC`

## Error handling

The script handles common failure cases and writes details to the log:

- Missing or invalid `config.json`
- Network timeouts and connection errors
- HTTP errors from the API
- Invalid JSON responses
- Notification delivery failures (with `--notify`)

Errors are printed to `stderr` and the script exits with code `2`.

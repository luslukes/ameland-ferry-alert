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

Edit `config.json` to set the departures you want to monitor:

```json
{
  "date": "2026-09-04",
  "times": [
    "07:15",
    "08:30",
    "09:45",
    "11:00",
    "12:15",
    "13:30",
    "14:45",
    "16:00",
    "17:15"
  ],
  "route": "HOAM",
  "licenseNumber": "K TW 3741",
  "vehicleLength": 5
}
```

| Field           | Description                                        |
|-----------------|----------------------------------------------------|
| `date`          | Travel date in `YYYY-MM-DD` format                 |
| `times`         | List of departure times to monitor (`HH:MM`)       |
| `route`         | Ferry route code (e.g. `HOAM` for Holwerd–Ameland) |
| `licenseNumber` | Vehicle license plate as used on the WPD website   |
| `vehicleLength` | Vehicle length in metres                           |

## Execution

Run the checker from the project directory:

```bash
python checker.py
```

The script will:

1. Load `config.json`
2. Query the WPD API for departures on the configured date and route
3. Check every configured departure time
4. Print availability for each departure
5. Update `state.json` to track notification status

### Exit codes

| Code | Meaning                                    |
|------|--------------------------------------------|
| `0`  | Successful execution                       |
| `2`  | Error (config, API, or notification failure) |

### Example output

```
07:15 AVAILABLE
08:30 FULLY BOOKED
09:45 FULLY BOOKED
11:00 FULLY BOOKED
12:15 FULLY BOOKED
13:30 FULLY BOOKED
14:45 FULLY BOOKED
16:00 FULLY BOOKED
17:15 FULLY BOOKED
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

07:15
13:30

Route: HOAM
Date: 2026-09-04
Vehicle: K TW 3741
```

Notifications are sent only when at least one departure is bookable and `notification_sent == false`. State is stored in `state.json`:

- When one or more departures become available, a single notification is sent and `notification_sent` is set to `true`.
- While any departure stays available, no further notifications are sent.
- When all departures are fully booked again, `notification_sent` resets to `false`, so a new notification is sent if availability returns.

## GitHub Actions

A workflow in `.github/workflows/monitor.yml` runs every 15 minutes and:

1. Checks all configured departures
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
- Configured departure not found
- Notification delivery failures (with `--notify`)

Errors are printed to `stderr` and the script exits with code `2`.

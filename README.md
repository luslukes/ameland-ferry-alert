# ameland-ferry-alert

Monitor a specific Ameland ferry departure and get notified when a vehicle slot becomes available.

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

Edit `config.json` to set the departure you want to monitor:

```json
{
  "date": "2026-09-04",
  "time": "08:30",
  "route": "HOAM",
  "licenseNumber": "K CL 2815",
  "vehicleLength": 5
}
```

| Field           | Description                                        |
|-----------------|----------------------------------------------------|
| `date`          | Travel date in `YYYY-MM-DD` format                 |
| `time`          | Departure time in `HH:MM` format                   |
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
3. Find the departure matching the configured time
4. Print `AVAILABLE` or `FULLY BOOKED`
5. Update `state.json` to track notification status

### Exit codes

| Code | Meaning                                      |
|------|----------------------------------------------|
| `0`  | Departure is available (`isBookable == true`)  |
| `1`  | Departure is fully booked                    |
| `2`  | Error (config, API, or notification failure)   |

### Example output

```
AVAILABLE
```

or

```
FULLY BOOKED
```

## Notifications

To send an ntfy notification when the departure becomes available, run with `--notify`:

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

Route: HOAM
Date: 2026-09-04
Time: 08:30

The monitored ferry is available again.
```

Notifications are sent only when `isBookable == true` and `notification_sent == false`. State is stored in `state.json`:

- When the departure becomes available, a notification is sent and `notification_sent` is set to `true`.
- While the departure stays available, no further notifications are sent.
- When the departure becomes fully booked again, `notification_sent` resets to `false`, so a new notification is sent if it becomes available again.

## GitHub Actions

A workflow in `.github/workflows/monitor.yml` runs every 5 minutes and:

1. Checks the configured departure
2. Sends an ntfy notification if it becomes available (using repository secrets)
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

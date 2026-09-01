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

Edit `config.json` to set the routes, dates, and vehicle to monitor:

```json
{
  "trips": [
    {
      "route": "HOAM",
      "dates": ["2026-09-04"]
    },
    {
      "route": "AMHO",
      "dates": ["2026-09-11", "2026-09-12"]
    }
  ],
  "licenseNumber": "K TW 3741",
  "vehicleLength": 5
}
```

| Field           | Description                                        |
|-----------------|----------------------------------------------------|
| `trips`         | List of route/date combinations to monitor         |
| `trips[].route` | Ferry route code (`HOAM` outbound, `AMHO` return)    |
| `trips[].dates` | Travel dates for that route (`YYYY-MM-DD`)         |
| `licenseNumber` | Vehicle license plate as used on the WPD website   |
| `vehicleLength` | Vehicle length in metres                           |

For every configured date and route, the monitor queries the WPD API and reads all returned departures. Departure times come from `startDate`, and availability from `isBookable`.

## Execution

Run the checker from the project directory:

```bash
python checker.py
```

The script will:

1. Load `config.json`
2. Query the WPD API for each configured route and date
3. Read all returned departures
4. Print availability for each detected departure
5. Update `state.json` to track notification status

### Exit codes

| Code | Meaning                                    |
|------|--------------------------------------------|
| `0`  | Successful execution                       |
| `2`  | Error (config, API, or notification failure) |

### Example output

```
2026-09-04 08:30 HOAM FULLY BOOKED
2026-09-04 09:45 HOAM FULLY BOOKED
2026-09-11 08:30 AMHO FULLY BOOKED
2026-09-12 09:45 AMHO AVAILABLE
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

Notifications are sent via HTTP POST to `https://ntfy.sh/<topic>` when at least one **new** departure becomes available. The message lists **all** currently available departures, grouped by date and route:

```
🚢 Ameland Ferry Available

New availability detected.

Currently available departures:

2026-09-11 (AMHO)
06:00
07:15
16:00

Vehicle: K TW 3741
```

Notification state is stored in `state.json` as the set of currently available departures:

- When new departures become available, a notification is sent listing every currently available slot.
- If availability stays the same or departures disappear, no notification is sent.
- The stored `available_departures` list is always updated to match the current API result.

## GitHub Actions

A workflow in `.github/workflows/monitor.yml` runs every 15 minutes and:

1. Checks all API departures for the configured routes and dates
2. Sends an ntfy notification when new departures become available (using repository secrets)
3. Commits updated `state.json` with the current availability set

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

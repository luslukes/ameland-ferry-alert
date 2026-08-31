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
  "route": "HOAM"
}
```

| Field   | Description                                        |
|---------|----------------------------------------------------|
| `date`  | Travel date in `YYYY-MM-DD` format                 |
| `time`  | Departure time in `HH:MM` format                   |
| `route` | Ferry route code (e.g. `HOAM` for Holwerd–Ameland) |

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

## Email notifications

To send an email when the departure becomes available, run with `--notify`:

```bash
python checker.py --notify
```

Set these environment variables:

| Variable        | Description                    |
|-----------------|--------------------------------|
| `SMTP_HOST`     | SMTP server hostname           |
| `SMTP_PORT`     | SMTP port (default: `587`)     |
| `SMTP_USER`     | SMTP username                  |
| `SMTP_PASSWORD` | SMTP password                  |
| `EMAIL_FROM`    | Sender email address           |
| `EMAIL_TO`      | Recipient email address        |

Notifications are sent only once per availability period. State is stored in `state.json`:

- When the departure becomes available, an email is sent and `notification_sent` is set to `true`.
- While the departure stays available, no further emails are sent.
- When the departure becomes fully booked again, `notification_sent` resets to `false`, so a new email is sent if it becomes available again.

## GitHub Actions

A workflow in `.github/workflows/monitor.yml` runs every 5 minutes and:

1. Checks the configured departure
2. Sends an email if it becomes available (using repository secrets)
3. Commits updated `state.json` to prevent duplicate notifications

### Required repository secrets

- `SMTP_HOST`
- `SMTP_PORT` (optional, defaults to `587`)
- `SMTP_USER`
- `SMTP_PASSWORD`
- `EMAIL_FROM`
- `EMAIL_TO`

## Error handling

The script handles common failure cases and writes details to the log:

- Missing or invalid `config.json`
- Network timeouts and connection errors
- HTTP errors from the API
- Invalid JSON responses
- Configured departure not found
- Email delivery failures (with `--notify`)

Errors are printed to `stderr` and the script exits with code `2`.

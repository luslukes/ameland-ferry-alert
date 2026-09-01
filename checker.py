#!/usr/bin/env python3
"""Monitor Ameland ferry departures via the WPD API."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any

import requests
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import RequestException, Timeout

API_URL = "https://api.wpd.nl/api/v1/Departures/available"
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
STATE_PATH = Path(__file__).resolve().parent / "state.json"
REQUEST_TIMEOUT_SECONDS = 30
IGNORED_DEPARTURE_TIME = time(7, 15)

REQUIRED_CONFIG_KEYS = ("dates", "route", "licenseNumber", "vehicleLength")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when config.json is missing or invalid."""


class ApiError(Exception):
    """Raised when the WPD API returns an error response."""


class NotificationError(Exception):
    """Raised when an ntfy notification cannot be sent."""


@dataclass(frozen=True)
class DepartureResult:
    """Availability result for a departure returned by the API."""

    date_label: str
    time_label: str
    available: bool
    departure: dict[str, Any]

    @property
    def label(self) -> str:
        return f"{self.date_label} {self.time_label}"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Monitor Ameland ferry departures."
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Send an ntfy notification when departures become available.",
    )
    return parser.parse_args()


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load and validate configuration from config.json."""
    logger.info("Loading configuration from %s", path)

    if not path.exists():
        raise ConfigError(f"Configuration file not found: {path}")

    try:
        with path.open(encoding="utf-8") as config_file:
            config = json.load(config_file)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in configuration file: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Unable to read configuration file: {exc}") from exc

    if not isinstance(config, dict):
        raise ConfigError("Configuration file must contain a JSON object.")

    missing_keys = [key for key in REQUIRED_CONFIG_KEYS if key not in config]
    if missing_keys:
        raise ConfigError(
            f"Missing required configuration value(s): {', '.join(missing_keys)}"
        )

    for key in ("route", "licenseNumber"):
        value = config[key]
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"Configuration value '{key}' must be a non-empty string.")

    dates = config["dates"]
    if not isinstance(dates, list) or not dates:
        raise ConfigError("Configuration value 'dates' must be a non-empty array.")

    validated_dates: list[str] = []
    for index, date_value in enumerate(dates):
        if not isinstance(date_value, str) or not date_value.strip():
            raise ConfigError(
                f"Configuration value 'dates[{index}]' must be a non-empty string."
            )
        parse_date(date_value)
        validated_dates.append(date_value)

    vehicle_length = config["vehicleLength"]
    if isinstance(vehicle_length, bool) or not isinstance(vehicle_length, (int, float)):
        raise ConfigError("Configuration value 'vehicleLength' must be a number.")
    if vehicle_length <= 0:
        raise ConfigError("Configuration value 'vehicleLength' must be greater than zero.")

    config["dates"] = validated_dates

    logger.info(
        "Configuration loaded: dates=%s, route=%s, vehicle=%s (%sm)",
        ", ".join(config["dates"]),
        config["route"],
        config["licenseNumber"],
        config["vehicleLength"],
    )
    return config


def load_state(path: Path = STATE_PATH) -> dict[str, Any]:
    """Load notification state from state.json."""
    if not path.exists():
        logger.info("State file not found, starting with empty state")
        return {"notification_sent": False, "last_status": None, "last_checked": None}

    try:
        with path.open(encoding="utf-8") as state_file:
            state = json.load(state_file)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in state file: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Unable to read state file: {exc}") from exc

    if not isinstance(state, dict):
        raise ConfigError("State file must contain a JSON object.")

    state.setdefault("notification_sent", False)
    state.setdefault("last_status", None)
    state.setdefault("last_checked", None)
    return state


def save_state(state: dict[str, Any], path: Path = STATE_PATH) -> None:
    """Persist notification state to state.json."""
    try:
        with path.open("w", encoding="utf-8") as state_file:
            json.dump(state, state_file, indent=2)
            state_file.write("\n")
    except OSError as exc:
        raise ConfigError(f"Unable to write state file: {exc}") from exc

    logger.info("State saved to %s", path)


def parse_date(value: str) -> datetime.date:
    """Parse a YYYY-MM-DD date string."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ConfigError(f"Invalid date format '{value}'. Expected YYYY-MM-DD.") from exc


def build_api_payload(config: dict[str, Any], date: str) -> dict[str, Any]:
    """Build the request body for the WPD departures endpoint."""
    return {
        "dateTime": date,
        "isAmendment": False,
        "isGroupBooking": False,
        "resources": [
            {"type": "A", "resourceType": "Ferry"},
            {"type": "A", "resourceType": "Ferry"},
            {"type": "I", "resourceType": "Ferry"},
            {"type": "I", "resourceType": "Ferry"},
            {
                "licenseNumber": config["licenseNumber"],
                "length": config["vehicleLength"],
                "resourceType": "Car",
            },
        ],
        "route": config["route"],
    }


def fetch_departures_for_date(
    config: dict[str, Any],
    date: str,
) -> list[dict[str, Any]]:
    """Call the WPD API and return departures for a single date."""
    payload = build_api_payload(config, date)
    logger.info("Requesting departures from %s for %s", API_URL, date)

    try:
        response = requests.post(
            API_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"Content-Type": "application/json"},
        )
    except Timeout as exc:
        raise ApiError("Request timed out while contacting the WPD API.") from exc
    except RequestsConnectionError as exc:
        raise ApiError("Network error while contacting the WPD API.") from exc
    except RequestException as exc:
        raise ApiError(f"Request failed: {exc}") from exc

    logger.info("API responded with HTTP %s for %s", response.status_code, date)

    if not response.ok:
        detail = response.text.strip() or "No response body"
        raise ApiError(
            f"API error for {date} (HTTP {response.status_code}): {detail[:500]}"
        )

    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        raise ApiError(f"API returned invalid JSON for {date}.") from exc

    if not isinstance(data, list):
        raise ApiError(f"Unexpected API response for {date}: expected a JSON array.")

    logger.info("Received %d departure(s) from API for %s", len(data), date)
    return data


def parse_departure_start(departure: dict[str, Any]) -> datetime | None:
    """Extract the departure start datetime from a departure record."""
    start_date = departure.get("startDate")
    if not isinstance(start_date, str):
        return None

    try:
        return datetime.fromisoformat(start_date)
    except ValueError:
        return None


def should_ignore_departure(start_dt: datetime) -> bool:
    """Ignore the 07:15 test departure."""
    return start_dt.time() == IGNORED_DEPARTURE_TIME


def collect_departure_results(config: dict[str, Any]) -> list[DepartureResult]:
    """Fetch and evaluate all API departures for the configured dates."""
    results: list[DepartureResult] = []

    for date in config["dates"]:
        departures = fetch_departures_for_date(config, date)

        for departure in departures:
            if not isinstance(departure, dict):
                logger.warning("Skipping non-object departure entry: %r", departure)
                continue

            if departure.get("route") != config["route"]:
                continue

            start_dt = parse_departure_start(departure)
            if start_dt is None:
                logger.warning("Skipping departure with invalid startDate: %s", departure)
                continue

            if should_ignore_departure(start_dt):
                logger.info("Ignoring test departure at %s", start_dt.strftime("%H:%M"))
                continue

            results.append(
                DepartureResult(
                    date_label=start_dt.strftime("%Y-%m-%d"),
                    time_label=start_dt.strftime("%H:%M"),
                    available=departure.get("isBookable") is True,
                    departure=departure,
                )
            )

    results.sort(key=lambda result: (result.date_label, result.time_label))
    logger.info("Collected %d monitored departure(s)", len(results))
    return results


def print_results(results: list[DepartureResult]) -> None:
    """Print availability for each detected departure."""
    for result in results:
        status = "AVAILABLE" if result.available else "FULLY BOOKED"
        print(f"{result.label} {status}")


def get_ntfy_topic() -> str:
    """Read the ntfy topic from environment variables."""
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        raise NotificationError("Missing environment variable: NTFY_TOPIC")
    return topic


def build_notification_message(
    config: dict[str, Any],
    available_departures: list[str],
) -> str:
    """Build the ntfy notification message body."""
    departures_block = "\n".join(available_departures)
    dates_block = ", ".join(config["dates"])
    return (
        "🚢 Ameland Ferry Available\n\n"
        "Available departures:\n\n"
        f"{departures_block}\n\n"
        f"Route: {config['route']}\n"
        f"Dates: {dates_block}\n"
        f"Vehicle: {config['licenseNumber']}"
    )


def send_availability_notification(
    config: dict[str, Any],
    available_departures: list[str],
) -> None:
    """Send an ntfy notification listing available departures."""
    topic = get_ntfy_topic()
    message = build_notification_message(config, available_departures)
    url = f"https://ntfy.sh/{topic}"

    logger.info("Sending availability notification to %s", url)

    try:
        response = requests.post(
            url,
            data=message.encode("utf-8"),
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )
    except Timeout as exc:
        raise NotificationError("Request timed out while sending ntfy notification.") from exc
    except RequestsConnectionError as exc:
        raise NotificationError("Network error while sending ntfy notification.") from exc
    except RequestException as exc:
        raise NotificationError(f"Failed to send ntfy notification: {exc}") from exc

    if not response.ok:
        detail = response.text.strip() or "No response body"
        raise NotificationError(
            f"ntfy error (HTTP {response.status_code}): {detail[:500]}"
        )

    logger.info("Availability notification sent successfully")


def update_state(
    state: dict[str, Any],
    *,
    results: list[DepartureResult],
    notify: bool,
    config: dict[str, Any],
) -> None:
    """Update state and send a notification when departures become available."""
    available_departures = [result.label for result in results if result.available]
    any_available = bool(available_departures)
    status = "available" if any_available else "fully_booked"

    if any_available and not state.get("notification_sent"):
        if notify:
            send_availability_notification(config, available_departures)
            state["notification_sent"] = True
            logger.info("Marked departures as notified")
    elif not any_available:
        state["notification_sent"] = False
        logger.info("All departures fully booked, notification flag reset")

    state["last_status"] = status
    state["last_available_departures"] = available_departures
    state["last_checked"] = datetime.now().isoformat(timespec="seconds")
    save_state(state)


def main() -> int:
    """Entry point for the ferry departure monitor."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        args = parse_args()
        config = load_config()
        state = load_state()
        results = collect_departure_results(config)

        print_results(results)

        update_state(
            state,
            results=results,
            notify=args.notify,
            config=config,
        )

        return 0
    except (ConfigError, ApiError, NotificationError) as exc:
        logger.error("%s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - top-level safety net
        logger.exception("Unexpected error")
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

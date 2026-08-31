#!/usr/bin/env python3
"""Monitor a specific Ameland ferry departure via the WPD API."""

from __future__ import annotations

import argparse
import json
import logging
import os
import smtplib
import sys
from datetime import datetime, time
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import requests
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import RequestException, Timeout

API_URL = "https://api.wpd.nl/api/v1/Departures/available"
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
STATE_PATH = Path(__file__).resolve().parent / "state.json"
REQUEST_TIMEOUT_SECONDS = 30

REQUIRED_CONFIG_KEYS = ("date", "time", "route")

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


class DepartureNotFoundError(Exception):
    """Raised when the configured departure cannot be found."""


class NotificationError(Exception):
    """Raised when an email notification cannot be sent."""


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Monitor a specific Ameland ferry departure."
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Send an email when the departure becomes available.",
    )
    return parser.parse_args()


def load_config(path: Path = CONFIG_PATH) -> dict[str, str]:
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

    for key in REQUIRED_CONFIG_KEYS:
        value = config[key]
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"Configuration value '{key}' must be a non-empty string.")

    parse_date(config["date"])
    parse_time(config["time"], "time")

    logger.info(
        "Configuration loaded: date=%s, time=%s, route=%s",
        config["date"],
        config["time"],
        config["route"],
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


def parse_time(value: str, field_name: str) -> time:
    """Parse an HH:MM time string."""
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise ConfigError(
            f"Invalid time format for '{field_name}': '{value}'. Expected HH:MM."
        ) from exc


def build_api_payload(config: dict[str, str]) -> dict[str, Any]:
    """Build the request body for the WPD departures endpoint."""
    return {
        "dateTime": config["date"],
        "isAmendment": False,
        "isGroupBooking": False,
        "resources": [{"type": "A", "resourceType": "Ferry"}],
        "route": config["route"],
    }


def fetch_departures(config: dict[str, str]) -> list[dict[str, Any]]:
    """Call the WPD API and return the list of departures."""
    payload = build_api_payload(config)
    logger.info("Requesting departures from %s", API_URL)

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

    logger.info("API responded with HTTP %s", response.status_code)

    if not response.ok:
        detail = response.text.strip() or "No response body"
        raise ApiError(
            f"API error (HTTP {response.status_code}): {detail[:500]}"
        )

    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        raise ApiError("API returned invalid JSON.") from exc

    if not isinstance(data, list):
        raise ApiError("Unexpected API response: expected a JSON array.")

    logger.info("Received %d departure(s) from API", len(data))
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


def find_departure(
    departures: list[dict[str, Any]],
    config: dict[str, str],
) -> dict[str, Any]:
    """Find the configured departure in the API response."""
    target_date = parse_date(config["date"])
    target_time = parse_time(config["time"], "time")
    target_route = config["route"]

    for departure in departures:
        if not isinstance(departure, dict):
            continue

        start_dt = parse_departure_start(departure)
        if start_dt is None:
            continue

        if (
            start_dt.date() == target_date
            and start_dt.time() == target_time
            and departure.get("route") == target_route
        ):
            logger.info("Found configured departure at %s %s", config["date"], config["time"])
            return departure

    raise DepartureNotFoundError(
        f"No departure found for {config['route']} on {config['date']} at {config['time']}."
    )


def is_available(departure: dict[str, Any]) -> bool:
    """A departure is available when isBookable is true."""
    return departure.get("isBookable") is True


def get_smtp_settings() -> dict[str, str]:
    """Read SMTP settings from environment variables."""
    required = ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_FROM", "EMAIL_TO")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise NotificationError(
            f"Missing email environment variable(s): {', '.join(missing)}"
        )

    return {
        "host": os.environ["SMTP_HOST"],
        "port": os.environ.get("SMTP_PORT", "587"),
        "user": os.environ["SMTP_USER"],
        "password": os.environ["SMTP_PASSWORD"],
        "email_from": os.environ["EMAIL_FROM"],
        "email_to": os.environ["EMAIL_TO"],
    }


def send_availability_email(config: dict[str, str], departure: dict[str, Any]) -> None:
    """Send an email notification that the departure is available."""
    settings = get_smtp_settings()
    ship_code = departure.get("shipCode", "unknown")
    available_weight = departure.get("availableWeight", "n/a")

    subject = (
        f"Ameland ferry available: {config['route']} "
        f"{config['date']} {config['time']}"
    )
    body = (
        "A vehicle slot is available on your monitored ferry departure.\n\n"
        f"Route: {config['route']}\n"
        f"Date: {config['date']}\n"
        f"Time: {config['time']}\n"
        f"Ship: {ship_code}\n"
        f"Available weight: {available_weight}\n"
    )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings["email_from"]
    message["To"] = settings["email_to"]
    message.set_content(body)

    logger.info("Sending availability email to %s", settings["email_to"])

    try:
        with smtplib.SMTP(settings["host"], int(settings["port"])) as smtp:
            smtp.starttls()
            smtp.login(settings["user"], settings["password"])
            smtp.send_message(message)
    except OSError as exc:
        raise NotificationError(f"Failed to send email: {exc}") from exc
    except smtplib.SMTPException as exc:
        raise NotificationError(f"SMTP error while sending email: {exc}") from exc

    logger.info("Availability email sent successfully")


def update_state(
    state: dict[str, Any],
    *,
    available: bool,
    notify: bool,
    config: dict[str, str],
    departure: dict[str, Any],
) -> None:
    """Update state and send a notification when the departure becomes available."""
    status = "available" if available else "fully_booked"

    if available and not state.get("notification_sent"):
        if notify:
            send_availability_email(config, departure)
            state["notification_sent"] = True
            logger.info("Marked departure as notified")
    elif not available:
        state["notification_sent"] = False
        logger.info("Departure unavailable, notification flag reset")

    state["last_status"] = status
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
        departures = fetch_departures(config)
        departure = find_departure(departures, config)
        available = is_available(departure)

        print("AVAILABLE" if available else "FULLY BOOKED")

        update_state(
            state,
            available=available,
            notify=args.notify,
            config=config,
            departure=departure,
        )

        return 0 if available else 1
    except (ConfigError, ApiError, DepartureNotFoundError, NotificationError) as exc:
        logger.error("%s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - top-level safety net
        logger.exception("Unexpected error")
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

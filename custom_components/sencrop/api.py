"""Client for the Sencrop cloud API.

This module must not import Home Assistant so it can be extracted into a
standalone library later.
"""

import base64
import binascii
import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

API_BASE = "https://api.sencrop.com/v1"
ID_BASE = "https://id.sencrop.com"
TOKENIZE_AS = "jwt_session_dev"
REQUEST_TIMEOUT = 30
TOKEN_REFRESH_MARGIN = timedelta(minutes=5)
RAW_SIZE = 10

LEGACY_MEASURES: dict[str, str] = {
    "RAIN_TIC": "RAIN_FALL",
    "WIND_MEAN": "WIND_SPEED",
    "WIND_MAX": "WIND_GUST",
    "RH_AIR_H1": "RELATIVE_HUMIDITY",
    "TEMP_AIR_H1": "TEMPERATURE",
}

# Measures accepted by `data/raw`; devices also list derived ones (DEW_POINT)
# that the endpoint rejects with E_NOT_IN_ENUM.
RAW_MEASURES: frozenset[str] = frozenset(
    {
        "RELATIVE_HUMIDITY",
        "TEMPERATURE",
        "WET_TEMPERATURE",
        "RAIN_FALL",
        "WIND_SPEED",
        "WIND_GUST",
        "WIND_DIRECTION",
        "LEAF_SENSOR_CONDUCTIVITY",
        "IRRADIANCE",
    }
)


class SencropError(Exception):
    """Base error for the Sencrop client."""


class SencropAuthError(SencropError):
    """Credentials or session rejected."""


class SencropConnectionError(SencropError):
    """Network error, timeout or server error."""


class SencropResponseError(SencropError):
    """Unexpected response payload."""


@dataclass(frozen=True)
class SencropDevice:
    """A Sencrop station visible from the account."""

    id: int
    name: str
    named: bool
    model: str | None
    serial: str | None
    firmware: str | None
    battery_mv: int | None
    link_quality: str | None
    measures: tuple[str, ...]
    last_status_update: datetime | None
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True)
class Measurement:
    """A single raw measure."""

    type: str
    value: float
    date: datetime


@dataclass(frozen=True)
class AggregateBucket:
    """An hourly or daily aggregate."""

    start: datetime
    values: dict[str, float]
    count: int


def _normalize(measure: str) -> str:
    return LEGACY_MEASURES.get(measure, measure)


def _parse_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_device(item: Any, raw: dict, models: dict) -> SencropDevice:
    device_id = int(raw.get("id") or item)
    model = models.get(str(raw.get("modelId"))) or {}
    model_name = (model.get("contents") or {}).get("name") or None
    name = ((raw.get("contents") or {}).get("name") or "").strip()
    status = raw.get("status") or {}
    location = raw.get("location") or {}
    measures = tuple(
        dict.fromkeys(
            _normalize(m)
            for m in (raw.get("measures") or {}).get("list") or []
            if isinstance(m, str)
        )
    )
    lqi = status.get("lqi")
    return SencropDevice(
        id=device_id,
        name=name or f"{model_name or 'Sencrop'} {device_id}",
        named=bool(name),
        model=model_name,
        serial=raw.get("serial"),
        firmware=status.get("firmware"),
        battery_mv=status.get("battery"),
        link_quality=lqi.lower() if isinstance(lqi, str) else None,
        measures=measures,
        last_status_update=_parse_date(status.get("lastStatusUpdateDate")),
        latitude=location.get("latitude"),
        longitude=location.get("longitude"),
    )


def parse_devices(payload: dict) -> dict[int, SencropDevice]:
    """Parse `GET /users/{id}/devices`, keeping the API order.

    A malformed device is skipped so that one odd station (the account also
    sees network stations it does not own) cannot break the others.
    """
    items = payload.get("items") if isinstance(payload, dict) else None
    raw_devices = payload.get("devices") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not isinstance(raw_devices, dict):
        raise SencropResponseError("Unexpected devices payload")
    models = payload.get("models") or {}
    devices = {}
    for item in items:
        try:
            device = _parse_device(item, raw_devices[str(item)], models)
        except (KeyError, TypeError, ValueError, AttributeError) as err:
            _LOGGER.warning("Skipping unexpected Sencrop device entry: %r", err)
            continue
        devices[device.id] = device
    return devices


def parse_me(payload: dict) -> int:
    """Return the Sencrop user id from `GET /me`."""
    try:
        return int(payload["item"])
    except (KeyError, TypeError, ValueError) as err:
        raise SencropResponseError("Unexpected /me payload") from err


def parse_session_token(payload: dict) -> str:
    """Return the session token of an Ory native login response."""
    token = payload.get("session_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise SencropResponseError("No session token in login response")
    return token


def parse_whoami(payload: dict) -> tuple[str, datetime]:
    """Return the JWT of an Ory `whoami` response and its expiry."""
    token = payload.get("tokenized") if isinstance(payload, dict) else None
    if not isinstance(token, str):
        raise SencropResponseError("No JWT in whoami response")
    try:
        claims_part = token.split(".")[1]
        padded = claims_part + "=" * (-len(claims_part) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
        expires_at = datetime.fromtimestamp(int(claims["exp"]), UTC)
    except (IndexError, KeyError, TypeError, ValueError, binascii.Error) as err:
        raise SencropResponseError("Malformed JWT in whoami response") from err
    return token, expires_at


def parse_latest(payload: list) -> dict[str, Measurement]:
    """Keep the most recent non-discarded value of each measure."""
    if not isinstance(payload, list):
        raise SencropResponseError("Unexpected raw data payload")
    latest: dict[str, Measurement] = {}
    try:
        for item in payload:
            if item.get("discarded") or item.get("value") is None:
                continue
            measurement = Measurement(
                type=_normalize(item["type"]),
                value=float(item["value"]),
                date=datetime.fromisoformat(item["date"]),
            )
            current = latest.get(measurement.type)
            if current is None or measurement.date > current.date:
                latest[measurement.type] = measurement
    except (KeyError, TypeError, ValueError, AttributeError) as err:
        raise SencropResponseError(f"Unexpected raw data item: {err!r}") from err
    return latest


def parse_aggregates(payload: dict) -> list[AggregateBucket]:
    """Parse an hourly/daily statistics payload, sorted by bucket start."""
    try:
        data = payload["measures"]["data"]
        buckets = []
        for bucket in data:
            values = {
                _normalize(key): float(value["value"])
                for key, value in bucket.items()
                if isinstance(value, dict) and value.get("value") is not None
            }
            buckets.append(
                AggregateBucket(
                    start=datetime.fromtimestamp(bucket["key"] / 1000, UTC),
                    values=values,
                    count=int(bucket.get("docCount", 0)),
                )
            )
    except (KeyError, TypeError, ValueError, AttributeError) as err:
        raise SencropResponseError(f"Unexpected aggregates payload: {err!r}") from err
    return sorted(buckets, key=lambda bucket: bucket.start)


def _format_date(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _error_code(payload: Any) -> str:
    """Extract a non-sensitive error code from an error body."""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("code") or error.get("id") or "unknown")
        if "code" in payload:
            return str(payload["code"])
    return "unknown"


class _SessionExpired(Exception):
    """The Ory session token is no longer valid."""


class SencropClient:
    """Authenticated access to the Sencrop API with the app credentials."""

    def __init__(
        self, session: aiohttp.ClientSession, email: str, password: str
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._session_token: str | None = None
        self._jwt: str | None = None
        self._jwt_expires_at: datetime | None = None
        self._user_id: int | None = None

    @property
    def user_id(self) -> int | None:
        """Sencrop user id, known once logged in."""
        return self._user_id

    async def async_login(self) -> int:
        """Open an Ory session, get a JWT and resolve the user id."""
        await self._ory_login()
        await self._tokenize()
        self._user_id = parse_me(await self._api("GET", "/me"))
        return self._user_id

    async def async_get_devices(self) -> dict[int, SencropDevice]:
        """Return the devices visible from the account."""
        user_id = await self._ensure_user()
        return parse_devices(await self._api("GET", f"/users/{user_id}/devices"))

    async def async_get_latest(
        self, device_id: int, measures: Iterable[str], now: datetime
    ) -> dict[str, Measurement]:
        """Return the latest value of each raw measure of a device."""
        raw_measures = [m for m in measures if m in RAW_MEASURES]
        if not raw_measures:
            return {}
        user_id = await self._ensure_user()
        params = [("beforeDate", _format_date(now)), ("size", str(RAW_SIZE))]
        params += [("measures", m) for m in raw_measures]
        payload = await self._api(
            "GET", f"/users/{user_id}/devices/{device_id}/data/raw", params
        )
        return parse_latest(payload)

    async def async_get_hourly(
        self,
        device_id: int,
        measures: Sequence[str],
        days: int,
        time_zone: str,
        now: datetime,
    ) -> list[AggregateBucket]:
        """Return hourly aggregates."""
        return await self._aggregates(
            "hourly", device_id, measures, days, time_zone, now
        )

    async def async_get_daily(
        self,
        device_id: int,
        measures: Sequence[str],
        days: int,
        time_zone: str,
        now: datetime,
    ) -> list[AggregateBucket]:
        """Return daily aggregates (keys are local dates at 00:00 UTC)."""
        return await self._aggregates(
            "daily", device_id, measures, days, time_zone, now
        )

    async def _aggregates(
        self,
        scale: str,
        device_id: int,
        measures: Sequence[str],
        days: int,
        time_zone: str,
        now: datetime,
    ) -> list[AggregateBucket]:
        user_id = await self._ensure_user()
        params = [
            ("beforeDate", _format_date(now)),
            ("days", str(days)),
            ("timeZone", time_zone),
        ]
        params += [("measures", m) for m in measures]
        payload = await self._api(
            "GET", f"/users/{user_id}/devices/{device_id}/data/{scale}", params
        )
        return parse_aggregates(payload)

    async def _ensure_user(self) -> int:
        if self._user_id is None:
            return await self.async_login()
        return self._user_id

    async def _ory_login(self) -> None:
        status, flow = await self._request(
            "GET", f"{ID_BASE}/self-service/login/api", params=[("refresh", "true")]
        )
        if status != 200 or not isinstance(flow, dict) or "id" not in flow:
            raise SencropResponseError(f"Cannot open login flow (HTTP {status})")
        status, payload = await self._request(
            "POST",
            f"{ID_BASE}/self-service/login",
            params=[("flow", flow["id"])],
            json={
                "method": "password",
                "identifier": self._email,
                "password": self._password,
            },
        )
        if status in (400, 401, 403):
            raise SencropAuthError("Invalid Sencrop credentials")
        if status != 200:
            raise SencropResponseError(f"Unexpected login response (HTTP {status})")
        self._session_token = parse_session_token(payload)

    async def _tokenize(self) -> None:
        status, payload = await self._request(
            "GET",
            f"{ID_BASE}/sessions/whoami",
            params=[("tokenize_as", TOKENIZE_AS)],
            headers={"X-Session-Token": self._session_token or ""},
        )
        if status in (401, 403):
            self._session_token = None
            raise _SessionExpired
        if status != 200:
            raise SencropResponseError(f"Unexpected whoami response (HTTP {status})")
        self._jwt, self._jwt_expires_at = parse_whoami(payload)

    async def _ensure_token(self) -> str:
        expires_at = self._jwt_expires_at
        if (
            self._jwt is None
            or expires_at is None
            or expires_at - datetime.now(UTC) < TOKEN_REFRESH_MARGIN
        ):
            if self._session_token is not None:
                try:
                    await self._tokenize()
                except _SessionExpired:
                    _LOGGER.debug("Sencrop session expired, logging in again")
            if self._session_token is None:
                await self._ory_login()
                await self._tokenize()
        assert self._jwt is not None
        return self._jwt

    async def _api(
        self, method: str, path: str, params: list[tuple[str, str]] | None = None
    ) -> Any:
        for attempt in range(2):
            token = await self._ensure_token()
            status, payload = await self._request(
                method,
                f"{API_BASE}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            if status in (401, 403):
                _LOGGER.debug(
                    "Sencrop API rejected the token (attempt %s)", attempt + 1
                )
                self._jwt = None
                continue
            if status >= 400:
                raise SencropResponseError(
                    f"Sencrop API error {status}: {_error_code(payload)}"
                )
            return payload
        raise SencropAuthError("Sencrop API rejected the credentials")

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: list[tuple[str, str]] | None = None,
        json: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        try:
            async with self._session.request(
                method,
                url,
                params=params,
                json=json,
                headers={"Accept": "application/json", **(headers or {})},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                status = response.status
                if status >= 500:
                    raise SencropConnectionError(f"Sencrop server error {status}")
                try:
                    payload = await response.json(content_type=None)
                except ValueError as err:
                    raise SencropResponseError("Invalid JSON from Sencrop") from err
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SencropConnectionError(f"Cannot reach Sencrop: {err!r}") from err
        _LOGGER.debug("Sencrop %s %s -> HTTP %s", method, _log_path(url), status)
        return status, payload


def _log_path(url: str) -> str:
    """Return the URL path with numeric ids masked, for logging."""
    path = url.split("?", 1)[0].removeprefix(API_BASE).removeprefix(ID_BASE)
    return "/".join("<id>" if part.isdigit() else part for part in path.split("/"))

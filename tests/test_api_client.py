"""Tests for the Sencrop HTTP client."""

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.sencrop.api import (
    SencropAuthError,
    SencropClient,
    SencropConnectionError,
    SencropResponseError,
)

from .common import load_fixture, make_jwt

EMAIL = "user@example.com"
PASSWORD = "s3cr3t-password"
SESSION_TOKEN = "ory_st_session_token_value"

FLOW_URL = re.compile(r"^https://id\.sencrop\.com/self-service/login/api\?")
LOGIN_URL = re.compile(r"^https://id\.sencrop\.com/self-service/login\?flow=")
WHOAMI_URL = re.compile(r"^https://id\.sencrop\.com/sessions/whoami\?")
ME_URL = re.compile(r"^https://api\.sencrop\.com/v1/me$")
DEVICES_URL = re.compile(r"^https://api\.sencrop\.com/v1/users/12345/devices$")
RAW_URL = re.compile(r"^https://api\.sencrop\.com/v1/users/12345/devices/1012/data/raw")
DAILY_URL = re.compile(r"/devices/1012/data/daily\?")
HOURLY_URL = re.compile(r"/devices/1012/data/hourly\?")
NOW = datetime(2026, 10, 17, 23, 0, tzinfo=UTC)


def fresh_jwt() -> str:
    return make_jwt(int(time.time()) + 86400)


def sequence(*responses: dict):
    """Side effect answering each call with the next response (last one repeats)."""
    remaining = list(responses)

    async def side_effect(method, url, data):
        spec = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        if "exc" in spec:
            raise spec["exc"]
        return AiohttpClientMockResponse(
            method, url, status=spec.get("status", 200), json=spec.get("json")
        )

    return side_effect


def mock_login(mock: AiohttpClientMocker, *whoami: dict) -> str:
    """Register a working Ory login; extra `whoami` responses follow the first."""
    jwt = fresh_jwt()
    mock.get(FLOW_URL, json={"id": "flow-id"})
    mock.post(LOGIN_URL, json={"session_token": SESSION_TOKEN})
    mock.get(WHOAMI_URL, side_effect=sequence({"json": {"tokenized": jwt}}, *whoami))
    mock.get(ME_URL, json=load_fixture("me"))
    return jwt


def calls(mock: AiohttpClientMocker, method: str, pattern: str) -> list:
    """Return (url, data, headers) of the recorded calls matching a URL part."""
    return [
        (str(url), data, headers)
        for call_method, url, data, headers in mock.mock_calls
        if call_method.upper() == method and pattern in str(url)
    ]


@pytest.fixture
def mock() -> AiohttpClientMocker:
    return AiohttpClientMocker()


@pytest.fixture
async def client(mock: AiohttpClientMocker) -> AsyncIterator[SencropClient]:
    session = mock.create_session(asyncio.get_running_loop())
    yield SencropClient(session, EMAIL, PASSWORD)
    await session.close()


async def test_login_success(client: SencropClient, mock: AiohttpClientMocker) -> None:
    jwt = mock_login(mock)

    assert await client.async_login() == 12345

    assert client.user_id == 12345
    ((_, login_body, _),) = calls(mock, "POST", "/self-service/login")
    assert login_body == {
        "method": "password",
        "identifier": EMAIL,
        "password": PASSWORD,
    }
    ((whoami_url, _, whoami_headers),) = calls(mock, "GET", "/sessions/whoami")
    assert whoami_headers["X-Session-Token"] == SESSION_TOKEN
    assert "tokenize_as=jwt_session_dev" in whoami_url
    ((_, _, me_headers),) = calls(mock, "GET", "/v1/me")
    assert me_headers["Authorization"] == f"Bearer {jwt}"


async def test_login_invalid_credentials(
    client: SencropClient, mock: AiohttpClientMocker
) -> None:
    mock.get(FLOW_URL, json={"id": "flow-id"})
    mock.post(
        LOGIN_URL,
        status=400,
        json={"ui": {"messages": [{"id": 4000006, "type": "error"}]}},
    )

    with pytest.raises(SencropAuthError):
        await client.async_login()


async def test_login_flow_unexpected(
    client: SencropClient, mock: AiohttpClientMocker
) -> None:
    mock.get(FLOW_URL, status=404, json={})

    with pytest.raises(SencropResponseError):
        await client.async_login()


async def test_lazy_login(client: SencropClient, mock: AiohttpClientMocker) -> None:
    mock_login(mock)
    mock.get(DEVICES_URL, json=load_fixture("devices"))

    devices = await client.async_get_devices()

    assert devices[1012].name == "Raincrop jardin"
    assert len(calls(mock, "POST", "/self-service/login")) == 1


async def test_jwt_retokenized_before_expiry(
    client: SencropClient, mock: AiohttpClientMocker
) -> None:
    mock.get(FLOW_URL, json={"id": "flow-id"})
    mock.post(LOGIN_URL, json={"session_token": SESSION_TOKEN})
    mock.get(
        WHOAMI_URL,
        side_effect=sequence(
            {"json": {"tokenized": make_jwt(int(time.time()) + 240)}},
            {"json": {"tokenized": fresh_jwt()}},
        ),
    )
    mock.get(ME_URL, json=load_fixture("me"))
    await client.async_login()
    mock.get(DEVICES_URL, json=load_fixture("devices"))

    await client.async_get_devices()

    assert len(calls(mock, "GET", "/sessions/whoami")) == 2
    assert len(calls(mock, "POST", "/self-service/login")) == 1


async def test_session_expired_relogin(
    client: SencropClient, mock: AiohttpClientMocker
) -> None:
    mock.get(FLOW_URL, json={"id": "flow-id"})
    mock.post(LOGIN_URL, json={"session_token": SESSION_TOKEN})
    mock.get(
        WHOAMI_URL,
        side_effect=sequence(
            {"json": {"tokenized": make_jwt(int(time.time()) + 60)}},
            {"status": 401, "json": {"error": {"id": "session_inactive"}}},
            {"json": {"tokenized": fresh_jwt()}},
        ),
    )
    mock.get(ME_URL, json=load_fixture("me"))
    await client.async_login()
    mock.get(DEVICES_URL, json=load_fixture("devices"))

    await client.async_get_devices()

    assert len(calls(mock, "POST", "/self-service/login")) == 2


async def test_api_401_retried_once(
    client: SencropClient, mock: AiohttpClientMocker
) -> None:
    mock_login(mock, {"json": {"tokenized": fresh_jwt()}})
    mock.get(
        DEVICES_URL,
        side_effect=sequence(
            {"status": 401, "json": {"code": "E_UNAUTHORIZED"}},
            {"json": load_fixture("devices")},
        ),
    )

    assert 1012 in await client.async_get_devices()
    assert len(calls(mock, "GET", "/sessions/whoami")) == 2


async def test_api_401_twice_raises_auth_error(
    client: SencropClient, mock: AiohttpClientMocker
) -> None:
    mock_login(mock, {"json": {"tokenized": fresh_jwt()}})
    mock.get(DEVICES_URL, status=401, json={})

    with pytest.raises(SencropAuthError):
        await client.async_get_devices()

    assert len(calls(mock, "GET", "/users/12345/devices")) == 2


@pytest.mark.parametrize(
    "failure",
    [
        {"exc": aiohttp.ClientConnectionError()},
        {"exc": TimeoutError()},
        {"status": 500, "json": {}},
    ],
)
async def test_connection_errors(
    client: SencropClient, mock: AiohttpClientMocker, failure: dict
) -> None:
    mock_login(mock)
    mock.get(DEVICES_URL, side_effect=sequence(failure))

    with pytest.raises(SencropConnectionError):
        await client.async_get_devices()


async def test_login_connection_error(
    client: SencropClient, mock: AiohttpClientMocker
) -> None:
    mock.get(FLOW_URL, exc=aiohttp.ClientConnectionError())

    with pytest.raises(SencropConnectionError):
        await client.async_login()


async def test_invalid_json(client: SencropClient, mock: AiohttpClientMocker) -> None:
    mock_login(mock)
    mock.get(DEVICES_URL, text="<html>oops</html>")

    with pytest.raises(SencropResponseError):
        await client.async_get_devices()


async def test_api_client_error_raises_response_error(
    client: SencropClient, mock: AiohttpClientMocker
) -> None:
    mock_login(mock)
    mock.get(DEVICES_URL, status=400, json={"error": {"code": "E_NOT_IN_ENUM"}})

    with pytest.raises(SencropResponseError, match="E_NOT_IN_ENUM"):
        await client.async_get_devices()


async def test_get_latest_query(
    client: SencropClient, mock: AiohttpClientMocker
) -> None:
    mock_login(mock)
    mock.get(RAW_URL, json=load_fixture("raw_rain8"))

    latest = await client.async_get_latest(
        1012,
        ["RAIN_FALL", "TEMPERATURE", "RELATIVE_HUMIDITY", "DEW_POINT"],
        NOW,
    )

    ((url, _, _),) = calls(mock, "GET", "/data/raw")
    assert "size=10" in url
    assert "beforeDate=2026-10-17T23:00:00.000Z" in url
    assert url.count("measures=") == 3
    assert "DEW_POINT" not in url
    assert latest["TEMPERATURE"].value == 11.15


async def test_get_latest_without_raw_measure_skips_call(
    client: SencropClient, mock: AiohttpClientMocker
) -> None:
    assert await client.async_get_latest(1012, ["DEW_POINT"], NOW) == {}
    assert mock.call_count == 0


async def test_get_daily_query(
    client: SencropClient, mock: AiohttpClientMocker
) -> None:
    mock_login(mock)
    mock.get(DAILY_URL, json=load_fixture("daily_rain8"))

    buckets = await client.async_get_daily(
        1012, ["RAIN_FALL", "TEMPERATURE_MIN"], 7, "Europe/Paris", NOW
    )

    ((url, _, _),) = calls(mock, "GET", "/data/daily")
    assert "days=7" in url
    assert "timeZone=Europe/Paris" in url
    assert "measures=RAIN_FALL" in url
    assert "measures=TEMPERATURE_MIN" in url
    assert len(buckets) == 8


async def test_get_hourly_query(
    client: SencropClient, mock: AiohttpClientMocker
) -> None:
    mock_login(mock)
    mock.get(HOURLY_URL, json=load_fixture("hourly_rain8"))

    buckets = await client.async_get_hourly(1012, ["RAIN_FALL"], 2, "Europe/Paris", NOW)

    ((url, _, _),) = calls(mock, "GET", "/data/hourly")
    assert "days=2" in url
    assert len(buckets) == 49


async def test_no_secret_in_logs(
    client: SencropClient,
    mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    jwt = mock_login(mock)
    mock.get(DEVICES_URL, status=401, json={})

    with pytest.raises(SencropAuthError):
        await client.async_get_devices()

    for secret in (EMAIL, PASSWORD, SESSION_TOKEN, jwt, "12345"):
        assert secret not in caplog.text

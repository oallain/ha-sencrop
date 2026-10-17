"""Tests for the Sencrop config and options flows."""

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sencrop.api import (
    SencropAuthError,
    SencropConnectionError,
    SencropResponseError,
    parse_devices,
)
from custom_components.sencrop.const import CONF_DEVICES, CONF_SCAN_INTERVAL, DOMAIN

from .common import load_fixture
from .conftest import setup_entry

CREDENTIALS = {CONF_EMAIL: "user@example.com", CONF_PASSWORD: "secret"}


@pytest.fixture
def flow_client() -> Generator[AsyncMock]:
    """Patch the client used by the config flow."""
    client = AsyncMock()
    client.async_login.return_value = 12345
    client.async_get_devices.return_value = parse_devices(load_fixture("devices"))
    with patch(
        "custom_components.sencrop.config_flow.SencropClient", return_value=client
    ):
        yield client


@pytest.fixture(autouse=True)
def mock_setup_entry(request: pytest.FixtureRequest) -> Generator[AsyncMock | None]:
    """Do not set the integration up when a flow creates an entry."""
    if "mock_client" in request.fixturenames:
        yield None
        return
    with patch(
        "custom_components.sencrop.async_setup_entry", return_value=True
    ) as mock:
        yield mock


async def _start_user_flow(hass: HomeAssistant) -> dict:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result


def _default(result: dict, key: str):
    for marker in result["data_schema"].schema:
        if marker == key:
            return marker.default()
    raise KeyError(key)


async def test_user_flow_success(hass: HomeAssistant, flow_client: AsyncMock) -> None:
    result = await _start_user_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "devices"
    assert _default(result, CONF_DEVICES) == ["1004", "1005", "1011", "1012"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICES: ["1011", "1012"]}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "user@example.com"
    assert result["data"] == CREDENTIALS
    assert result["options"] == {CONF_DEVICES: ["1011", "1012"], CONF_SCAN_INTERVAL: 5}
    assert result["result"].unique_id == "12345"


def test_device_labels() -> None:
    from custom_components.sencrop.config_flow import device_selector

    selector = device_selector(parse_devices(load_fixture("devices")))
    labels = {o["value"]: o["label"] for o in selector.config["options"]}

    assert labels["1012"] == "Raincrop jardin (Raincrop) — 18/10/2026"
    assert selector.config["multiple"] is True


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SencropAuthError, "invalid_auth"),
        (SencropConnectionError, "cannot_connect"),
        (RuntimeError, "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant, flow_client: AsyncMock, error: type[Exception], expected: str
) -> None:
    result = await _start_user_flow(hass)
    flow_client.async_login.side_effect = error

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}

    flow_client.async_login.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )
    assert result["step_id"] == "devices"


async def test_devices_step_requires_one(
    hass: HomeAssistant, flow_client: AsyncMock
) -> None:
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICES: []}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_devices"}


async def test_user_flow_already_configured(
    hass: HomeAssistant, flow_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await _start_user_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def _start_reauth(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    return result


async def test_reauth_success(
    hass: HomeAssistant, flow_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    result = await _start_reauth(hass, mock_config_entry)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-secret"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_PASSWORD] == "new-secret"


async def test_reauth_wrong_account(
    hass: HomeAssistant, flow_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    result = await _start_reauth(hass, mock_config_entry)
    flow_client.async_login.return_value = 99999

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-secret"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert mock_config_entry.data[CONF_PASSWORD] == "secret"


async def test_reauth_invalid_auth(
    hass: HomeAssistant, flow_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    result = await _start_reauth(hass, mock_config_entry)
    flow_client.async_login.side_effect = SencropAuthError

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "wrong"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


@pytest.mark.usefixtures("frozen_now")
async def test_setup_auth_error_starts_reauth(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_client.async_get_devices.side_effect = SencropAuthError

    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]


@pytest.mark.usefixtures("frozen_now")
async def test_runtime_auth_error_starts_reauth(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)
    mock_client.async_get_devices.side_effect = SencropAuthError

    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]


@pytest.mark.usefixtures("frozen_now")
async def test_options_flow(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert _default(result, CONF_DEVICES) == ["1005", "1011", "1012"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_DEVICES: ["1012"], CONF_SCAN_INTERVAL: 15}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {CONF_DEVICES: ["1012"], CONF_SCAN_INTERVAL: 15}
    assert set(mock_config_entry.runtime_data.data) == {1012}


@pytest.mark.usefixtures("frozen_now")
async def test_options_flow_errors(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_DEVICES: [], CONF_SCAN_INTERVAL: 5}
    )
    assert result["errors"] == {"base": "no_devices"}

    mock_client.async_get_devices.side_effect = SencropConnectionError("down")
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


@pytest.mark.usefixtures("frozen_now")
async def test_options_flow_entry_not_loaded(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    flow_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_client.async_get_devices.side_effect = SencropConnectionError("down")
    await setup_entry(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    flow_client.async_get_devices.assert_awaited()


@pytest.mark.usefixtures("frozen_now")
@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (SencropAuthError, "invalid_auth"),
        (SencropResponseError, "cannot_connect"),
    ],
)
async def test_options_flow_client_errors(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    error: type[Exception],
    reason: str,
) -> None:
    await setup_entry(hass, mock_config_entry)
    mock_client.async_get_devices.side_effect = error

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SencropAuthError, "invalid_auth"),
        (SencropConnectionError, "cannot_connect"),
        (SencropResponseError, "cannot_connect"),
    ],
)
async def test_user_flow_devices_errors(
    hass: HomeAssistant, flow_client: AsyncMock, error: type[Exception], expected: str
) -> None:
    result = await _start_user_flow(hass)
    flow_client.async_get_devices.side_effect = error

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}

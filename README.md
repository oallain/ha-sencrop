# Sencrop for Home Assistant

Unofficial integration that brings the measurements of your
[Sencrop](https://www.sencrop.com) weather stations into Home Assistant:
Raincrop rain gauge (rain, temperature, humidity) and Windcrop anemometer
(wind speed, gusts, direction).

[![Validate](https://github.com/oallain/ha-sencrop/actions/workflows/validate.yml/badge.svg)](https://github.com/oallain/ha-sencrop/actions/workflows/validate.yml)
[![Tests](https://github.com/oallain/ha-sencrop/actions/workflows/tests.yml/badge.svg)](https://github.com/oallain/ha-sencrop/actions/workflows/tests.yml)

## Requirements

- Home Assistant 2025.4 or newer.
- A Sencrop app account (email and password).

## Installation

### With HACS (recommended)

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=oallain&repository=ha-sencrop&category=integration)

Click the button above, or add the repository by hand:

1. In HACS, open the ⋮ menu and choose **Custom repositories**.
2. Add `https://github.com/oallain/ha-sencrop` with the **Integration** type.
3. Search for **Sencrop**, install it and restart Home Assistant.

### Manually

Copy the `custom_components/sencrop` folder into the
`config/custom_components/` folder of Home Assistant, then restart.

## Configuration

1. **Settings → Devices & services → Add integration → Sencrop**.
2. Enter the email and password you use in the Sencrop app.
3. Select the stations to add. Your account may also see neighbouring
   stations shared through the Sencrop network; the ones you named in the app
   are selected by default.

Each station becomes a Home Assistant device. A **Station Sencrop** weather
entity combines the latest values of the selected stations.

### Options

From **Configure** on the integration:

- **Devices**: stations exposed in Home Assistant.
- **Update interval**: 5 to 60 minutes (default 5). Stations report every 10
  to 15 minutes.

## Entities

| Entity | Stations | Unit | Notes |
|---|---|---|---|
| Temperature, Wet-bulb temperature, Dew point | Raincrop | °C | dew point computed (Magnus formula) |
| Humidity | Raincrop | % | |
| Rain | Raincrop | mm | latest measurement |
| Rain today | Raincrop | mm | since local midnight, long-term statistics |
| Rain last 24 hours, Rain last 7 days | Raincrop | mm | 7 days = today + the 6 previous days |
| Minimum / Maximum temperature today | Raincrop | °C | |
| Wind speed, Wind gust | Windcrop | km/h | |
| Wind direction | Windcrop | ° | |
| Battery voltage | all | mV | diagnostic |
| Link quality | all | — | diagnostic: excellent, good, average, limit |
| Last measurement | all | timestamp | diagnostic |
| Firmware | all | — | diagnostic, disabled by default |

Measurement entities become **unavailable** when a station has not reported
for more than 2 hours. Diagnostic entities stay available.

## Example: skip watering after rain

```yaml
automation:
  - alias: Garden watering
    triggers:
      - trigger: time
        at: "06:00:00"
    conditions:
      - condition: numeric_state
        entity_id: sensor.raincrop_jardin_rain_last_7_days
        below: 10
      - condition: numeric_state
        entity_id: sensor.raincrop_jardin_rain_last_24_hours
        below: 2
    actions:
      - action: switch.turn_on
        target:
          entity_id: switch.watering
```

Adapt the entity ids to your stations.

## Troubleshooting

- **Rejected credentials**: if you change your Sencrop password, Home
  Assistant asks you to re-authenticate.
- **Download the diagnostics** (⋮ menu of the integration) to attach to an
  issue: email, password, identifiers, station names, serial numbers and
  coordinates are redacted.
- Report issues on [GitHub](https://github.com/oallain/ha-sencrop/issues).

## Limitations

- **Unofficial** integration. It signs in the same way as the Sencrop app
  (Ory, `id.sencrop.com`), which the Sencrop developer guide does not
  document: a change on Sencrop's side may break it.
- Data is polled from the Sencrop cloud (`cloud_polling`); stations are not
  reachable locally.
- No forecasts and no Sencrop alerts.

## Removal

Delete the integration in **Devices & services**, then uninstall it from
HACS.

## Development

```bash
uv venv .venv -p 3.14
uv pip install -r requirements_test.txt --python .venv
.venv/bin/pytest --cov=custom_components.sencrop
```

Tests run against anonymized real API responses stored in `tests/fixtures/`.

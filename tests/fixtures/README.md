# Fixtures

Real Sencrop API responses captured on 2026-10-17 ~23:10 UTC, then anonymized
(ids remapped; personal data, station names, serials, coordinates and tokens
replaced; Ory identity/devices, organisations, places and device summaries
dropped).

| File | Source |
|---|---|
| `ory_login.json`, `ory_whoami.json` | Ory native login / `sessions/whoami` (trimmed) |
| `me.json` | `GET /me` (`item` = user id 12345) |
| `devices.json` | `GET /users/12345/devices` — 12 devices `1001`–`1012` |
| `raw_*.json` | `data/raw`, `size=10` |
| `hourly_*.json` | `data/hourly`, `days=2`, `timeZone=Europe/Paris` |
| `daily_*.json` | `data/daily`, `days=7`, `timeZone=Europe/Paris` (+ `TEMPERATURE_MIN/MAX`) |

Device mapping: `rain3` = 1005 "Pluviometre verger" (Raincrop, rain on the
17th), `rain8` = 1012 "Raincrop jardin" (Raincrop), `wind2` = 1004 "Anemometre verger"
(Windcrop), `wind4` = 1011 "Anemometre jardin" (Windcrop), `wind` = 1003
(guest access ended, empty raw response).

## Findings

- Auth: legacy `POST /users/sign_in` answers `E_NOT_VERIFIED`; the app logs in
  through Ory Kratos (`id.sencrop.com`). Ory session lasts 30 days, the JWT
  from `whoami?tokenize_as=jwt_session_dev` lasts 24 h (`exp - iat` = 1440
  min). JWT claims: `email, exp, iat, iss, jti, locale, nbf, phone_number,
  schema_id, sid, sub` — no Sencrop user id, hence `GET /me`.
- `size` on `data/raw` is **per measure** (size=10 with 3 measures → 30 items).
  Measures are not all reported at the same timestamp (rain and T/H differ).
- `data/raw` rejects `DEW_POINT` (listed by Raincrops) with `E_NOT_IN_ENUM`.
- Raincrop measures: `RAIN_FALL, TEMPERATURE, RELATIVE_HUMIDITY,
  WET_TEMPERATURE` (+ `DEW_POINT` listed). Windcrop: `WIND_SPEED, WIND_GUST,
  WIND_DIRECTION`. Windcrop reports every 10 min.
- `status.battery` is in mV (~3200–3700), `status.signal` is always 0,
  `status.lqi` ∈ `Excellent, Good, Average, Limit`.
- Aggregates: empty buckets are `{"<MEASURE>": {}, "docCount": 0}`. Hourly
  keys are real UTC bucket starts; daily keys are the local date at 00:00 UTC;
  `days=7` returns 8 daily buckets (today included).
- `/devices` also returns `deviceSummaries` with last values, but without
  `RAIN_FALL` for Raincrops, so `data/raw` is still needed.

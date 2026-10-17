# Intégration Home Assistant Sencrop — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** intégration custom HA `sencrop`, installable via HACS, qui expose les mesures, cumuls et diagnostics des capteurs Sencrop de l'utilisateur, plus une entité weather.

**Architecture :** client `aiohttp` embarqué (`api.py`, zéro import `homeassistant`) + fonctions de calcul pures (`derived.py`) + un `DataUpdateCoordinator` par compte qui alimente des entités `sensor` et `weather` générées selon les mesures de chaque capteur. Config flow email/mot de passe avec reauth et options.

**Tech Stack :** Python (version exigée par HA courant), Home Assistant 2025.x+, aiohttp, pytest + pytest-homeassistant-custom-component, aioresponses, ruff, GitHub Actions (hassfest, HACS).

**Spec :** `docs/superpowers/specs/2026-10-18-sencrop-ha-integration-design.md`

## Global Constraints

- Domaine `sencrop`, `iot_class: cloud_polling`, `config_flow: true`, version `0.1.0`, `codeowners: ["@oallain"]`, doc/issues `https://github.com/oallain/ha-sencrop`.
- Base API `https://api.sencrop.com/v1`, header `Authorization: Bearer <token>`, timeout 30 s par requête.
- `api.py` et `derived.py` n'importent rien de `homeassistant`.
- Polling par défaut 5 min, options 5–60 min ; agrégats rafraîchis si nouvelle mesure ou âge ≥ 30 min ; capteur périmé si dernière mesure > 2 h ; re-login si le token expire dans < 5 min.
- Jamais d'email, mot de passe, token ou userId dans les logs.
- Entités : `has_entity_name=True`, `unique_id = f"{device_id}_{key}"`, noms via traductions (`strings.json`, `translations/en.json`, `translations/fr.json`).
- Unités natives : °C, %, mm, km/h, °.
- Commits : une ligne, en anglais, sans préfixe de ticket, sans Co-Authored-By. Aucun push.
- Couverture de tests ≥ 90 % sur `custom_components/sencrop`.

## Review Focus

1. **Noms de mesures legacy** (`RAIN_TIC`, `WIND_MEAN`, `WIND_MAX`, `RH_AIR_H1`, `TEMP_AIR_H1`) dans `measures.list` d'un vieux capteur → normalisés vers les noms courants, entités créées normalement (test : Task 3).
2. **Frontière de jour / changement d'heure** : le compartiment « aujourd'hui » se choisit dans le fuseau de HA (Europe/Paris), y compris juste après minuit et le jour du passage à l'heure d'été (test : Task 5).
3. **Mesures brutes `discarded` ou non triées** → la valeur retenue est la plus récente non écartée (test : Task 3).
4. **Capteur partagé / `LimitedDevice`** sans `status`, `serial` ou `modelId` → pas d'exception, diagnostics à `None` (test : Task 3).
5. **Capteur hors ligne** (réponse raw vide ou dernière mesure > 2 h) → aucune exception, entités de mesure `unavailable`, diagnostics disponibles (tests : Task 6 et Task 8).

---

## Structure des fichiers

```
custom_components/sencrop/
  __init__.py      setup/unload, création client + coordinator, listener options
  manifest.json
  const.py         DOMAIN, clés de config, durées
  api.py           SencropClient, dataclasses, parseurs, exceptions
  derived.py       point de rosée, sélection de compartiments, sommes, péremption
  coordinator.py   SencropCoordinator, DeviceData
  config_flow.py   user, reauth, options
  entity.py        SencropEntity (DeviceInfo par capteur)
  sensor.py        descriptions + SencropSensor
  weather.py       SencropWeather
  diagnostics.py
  strings.json, translations/en.json, translations/fr.json, icons.json
scripts/probe.py   test réel, écrit des fixtures anonymisées
tests/
  conftest.py, fixtures/*.json
  test_api_parsing.py, test_api_client.py, test_derived.py,
  test_coordinator.py, test_init.py, test_config_flow.py,
  test_sensor.py, test_weather.py, test_diagnostics.py
hacs.json, README.md, pyproject.toml, requirements_test.txt, .gitignore
.github/workflows/validate.yml, .github/workflows/tests.yml
```

`derived.py` s'ajoute à la structure de la spec : il isole les calculs (point de rosée, cumuls, péremption) pour les tester sans HA.

---

### Task 1 : environnement de dev et squelette

**Files :**
- Create : `pyproject.toml`, `requirements_test.txt`, `.gitignore`, `hacs.json`, `custom_components/sencrop/manifest.json`, `custom_components/sencrop/const.py`, `custom_components/sencrop/__init__.py` (vide, docstring seulement), `tests/__init__.py`, `tests/conftest.py`, `tests/test_manifest.py`

**Interfaces :**
- Produces : `const.py` → `DOMAIN = "sencrop"`, `CONF_SCAN_INTERVAL = "scan_interval"`, `DEFAULT_SCAN_INTERVAL = 5`, `MIN_SCAN_INTERVAL = 5`, `MAX_SCAN_INTERVAL = 60` (minutes), `AGGREGATES_MAX_AGE = timedelta(minutes=30)`, `STALE_AFTER = timedelta(hours=2)`, `PLATFORMS = [Platform.SENSOR, Platform.WEATHER]`.
- Produces : `.venv/` fonctionnel ; `tests/conftest.py` contient la fixture autouse `auto_enable_custom_integrations(enable_custom_integrations)`.

- [ ] **Step 1 : déterminer la version Python requise** — `curl -s https://pypi.org/pypi/homeassistant/json | python3 -c "import json,sys; print(json.load(sys.stdin)['info']['requires_python'])"`. Installer `uv` (`pip3 install --user uv`) puis `uv venv .venv -p <version>`.
- [ ] **Step 2 : `requirements_test.txt`** : `pytest-homeassistant-custom-component` (dernière version, épinglée), `aioresponses`, `pytest-cov`, `ruff`. `uv pip install -r requirements_test.txt --python .venv`. Attendu : installation sans erreur.
- [ ] **Step 3 : version HA minimale** — vérifier la première version contenant `MEASUREMENT_ANGLE` : `curl -s https://raw.githubusercontent.com/home-assistant/core/<tag>/homeassistant/components/sensor/const.py | grep -c MEASUREMENT_ANGLE` pour `2025.2.0`, `2025.3.0`, puis les suivantes jusqu'au premier résultat non nul. Reporter cette version dans `hacs.json` (`{"name": "Sencrop", "homeassistant": "<version>", "render_readme": true}`).
- [ ] **Step 4 : test du manifest** (`tests/test_manifest.py`)

```python
def test_manifest_is_valid():
    manifest = json.loads((ROOT / "custom_components/sencrop/manifest.json").read_text())
    assert manifest["domain"] == "sencrop"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "cloud_polling"
    assert manifest["version"] == "0.1.0"
    assert manifest["codeowners"] == ["@oallain"]
    assert manifest["requirements"] == []
```

- [ ] **Step 5 : créer manifest, const, pyproject** (`[tool.pytest.ini_options] asyncio_mode = "auto"`, `testpaths = ["tests"]` ; `[tool.ruff]` target = version Python de l'étape 1, règles `E,F,I,UP,B,SIM,ASYNC`). `.gitignore` : `.venv/`, `__pycache__/`, `.coverage`, `.probe/`.
- [ ] **Step 6 : vérifier** — `.venv/bin/pytest -q` → `1 passed` ; `.venv/bin/ruff check . && .venv/bin/ruff format --check .` → propre.
- [ ] **Step 7 : commit** — `git add -A && git commit -m "Scaffold Sencrop integration and test tooling"`

---

### Task 2 : script de sonde et fixtures réelles (⚠ nécessite l'utilisateur)

**Files :**
- Create : `scripts/probe.py`, `tests/fixtures/sign_in.json`, `devices.json`, `raw_rain.json`, `raw_wind.json`, `raw_thermo.json`, `hourly_rain.json`, `daily_rain.json`, `daily_thermo.json`, `devices_with_measures.json`

**Interfaces :**
- Produces : fixtures JSON anonymisées, de même forme que les réponses réelles, consommées par les Tasks 3 à 10 ; constat écrit (en tête de `tests/fixtures/README.md`) sur : sémantique de `size`, présence des dernières valeurs dans `/devices?measures=…`, durée de vie du token, noms de mesures réellement listés par capteur, forme de `key` (ms UTC ou date).

- [ ] **Step 1 : écrire `scripts/probe.py`** (stdlib + aiohttp, exécutable avec `.venv/bin/python`). Lit `SENCROP_EMAIL` / `SENCROP_PASSWORD` dans l'environnement, sinon `input()`/`getpass()`. Enchaîne : `POST /users/sign_in` ; `GET /users/{id}/devices` ; `GET /users/{id}/devices?measures=TEMPERATURE&measures=RAIN_FALL&measures=WIND_SPEED` ; par capteur `data/raw` (`size=10` puis `size=100`, toutes les mesures du capteur, `beforeDate=now`), `data/hourly` (`days=2`), `data/daily` (`days=7`, + `TEMPERATURE_MIN`, `TEMPERATURE_MAX` si température). Anonymise avant écriture : `userId → 12345`, ids de capteurs → `1001, 1002, 1003` (mapping cohérent partout, y compris dans les clés de hash), `email`, `firstname`, `lastname`, `phone` → valeurs factices, `serial`/`identification` → `SERIAL-<n>`, `location` → `{latitude: 45.0, longitude: 5.0}`, `token`/`refreshToken` → `"REDACTED"`, `contents.name` conservé. Écrit dans `tests/fixtures/` et affiche un résumé (durée de vie du token en minutes, nombre d'items par réponse raw, mesures par capteur). N'affiche jamais de secret.
- [ ] **Step 2 : l'utilisateur lance la sonde dans son propre terminal** (pas via `!`, pour que le mot de passe n'arrive pas dans la conversation) : `cd semcrop && .venv/bin/python scripts/probe.py`. Attendu : fixtures écrites, résumé affiché.
- [ ] **Step 3 : relire les fixtures** — `grep -rniE "@|password|eyJ" tests/fixtures/` ne doit renvoyer que les valeurs factices. Rédiger `tests/fixtures/README.md` avec le constat. **Si une réponse contredit la spec** (par ex. `/devices?measures=` renvoie déjà les dernières valeurs, ou bien `size` compte par mesure), mettre à jour la section 2 de la spec et les interfaces des Tasks 3, 4 et 6 avant de continuer.
- [ ] **Step 4 : commit** — `git add scripts tests/fixtures && git commit -m "Add API probe script and anonymized fixtures"`

---

### Task 3 : modèles et parseurs de l'API

**Files :**
- Create : `custom_components/sencrop/api.py` (partie modèles et parseurs), `tests/test_api_parsing.py`

**Interfaces :**
- Consumes : fixtures de la Task 2.
- Produces :
  - `class SencropError(Exception)`, `SencropAuthError(SencropError)`, `SencropConnectionError(SencropError)`, `SencropResponseError(SencropError)`
  - `@dataclass(frozen=True) Session(token: str, user_id: int, expires_at: datetime)`
  - `@dataclass(frozen=True) SencropDevice(id: int, name: str, model: str | None, serial: str | None, firmware: str | None, battery: float | None, signal: float | None, measures: tuple[str, ...], latitude: float | None, longitude: float | None)`
  - `@dataclass(frozen=True) Measurement(type: str, value: float, date: datetime)`
  - `@dataclass(frozen=True) AggregateBucket(start: datetime, values: dict[str, float], count: int)`
  - `LEGACY_MEASURES: dict[str, str] = {"RAIN_TIC": "RAIN_FALL", "WIND_MEAN": "WIND_SPEED", "WIND_MAX": "WIND_GUST", "RH_AIR_H1": "RELATIVE_HUMIDITY", "TEMP_AIR_H1": "TEMPERATURE"}`
  - `parse_session(payload: dict) -> Session`
  - `parse_devices(payload: dict) -> dict[int, SencropDevice]` (ordre de `items`, mesures normalisées et dédupliquées, model = `models[modelId].contents.name`)
  - `parse_latest(payload: list) -> dict[str, Measurement]` (par type normalisé, la plus récente non `discarded`)
  - `parse_aggregates(payload: dict) -> list[AggregateBucket]` (`measures.data`, `start` = `key` ms → datetime UTC, `values[m] = bucket[m]["value"]`, triés par `start`)
  - Toute structure inattendue (clé requise absente, type faux) → `SencropResponseError`.

- [ ] **Step 1 : tests** (`tests/test_api_parsing.py`), avec chargement des fixtures :
  - `test_parse_session` : `user_id == 12345`, `expires_at` timezone-aware.
  - `test_parse_devices_from_fixture` : 3 capteurs `1001, 1002, 1003` dans l'ordre de `items` ; le pluviomètre a `"RAIN_FALL" in measures` ; `battery`, `firmware`, `model` non vides.
  - `test_parse_devices_normalizes_legacy_measures` : payload minimal avec `measures.list = ["RAIN_TIC", "RAIN_FALL", "TEMP_AIR_H1"]` → `("RAIN_FALL", "TEMPERATURE")`.
  - `test_parse_devices_limited_device` : device sans `status`, `serial` ni `modelId` → `battery is None`, `serial is None`, `model is None`.
  - `test_parse_latest_skips_discarded_and_unsorted` : `[{type: TEMPERATURE, value: 12.0, date: 10:00}, {…, value: 99.0, date: 10:15, discarded: true}, {…, value: 11.0, date: 09:45}]` → `12.0` à 10:00.
  - `test_parse_latest_empty` : `[] → {}`.
  - `test_parse_aggregates_from_fixture` : buckets triés, `values["RAIN_FALL"]` est un `float`, `start.tzinfo is not None`.
  - `test_parse_invalid_payloads` (paramétré) : `parse_devices({})`, `parse_aggregates({"measures": {}})`, `parse_session({"token": "x"})` → `SencropResponseError`.
- [ ] **Step 2 : lancer** `.venv/bin/pytest tests/test_api_parsing.py -v` → FAIL (import).
- [ ] **Step 3 : implémenter les dataclasses, exceptions et parseurs** dans `api.py`.
- [ ] **Step 4 : lancer** → PASS ; `ruff check` propre.
- [ ] **Step 5 : commit** — `git commit -m "Add Sencrop API models and response parsers"`

---

### Task 4 : client HTTP

**Files :**
- Modify : `custom_components/sencrop/api.py` (ajout de `SencropClient`)
- Create : `tests/test_api_client.py`

**Interfaces :**
- Consumes : parseurs et exceptions de la Task 3.
- Produces :
  - `API_BASE = "https://api.sencrop.com/v1"`, `REQUEST_TIMEOUT = 30`, `TOKEN_REFRESH_MARGIN = timedelta(minutes=5)`
  - `class SencropClient(session: aiohttp.ClientSession, email: str, password: str)`
    - `user_id: int | None` (propriété, `None` avant login)
    - `async def async_login(self) -> Session`
    - `async def async_get_devices(self) -> dict[int, SencropDevice]`
    - `async def async_get_latest(self, device_id: int, measures: Sequence[str], now: datetime) -> dict[str, Measurement]` (`data/raw`, `size` choisi d'après le constat de la Task 2, défaut 100)
    - `async def async_get_hourly(self, device_id: int, measures: Sequence[str], days: int, time_zone: str, now: datetime) -> list[AggregateBucket]`
    - `async def async_get_daily(self, device_id: int, measures: Sequence[str], days: int, time_zone: str, now: datetime) -> list[AggregateBucket]`
  - Les `measures` sont envoyées en paramètres répétés (`measures=A&measures=B`), `beforeDate` en ISO 8601 UTC.

- [ ] **Step 1 : tests** (`aioresponses`, session `aiohttp.ClientSession` réelle) :
  - `test_login_success` : POST `/users/sign_in` avec `{"email", "password"}` en JSON → `client.user_id == 12345`.
  - `test_login_invalid_credentials` : 400 et 401 → `SencropAuthError`.
  - `test_requests_send_bearer_token` : après login, `get_devices` envoie `Authorization: Bearer <token>` vers `/users/12345/devices`.
  - `test_lazy_login` : `get_devices` sans login préalable déclenche le login.
  - `test_relogin_before_expiry` : token qui expire dans 4 min → nouveau sign_in avant l'appel.
  - `test_relogin_once_on_401` : 401 puis 200 → succès, 2 sign_in ; 401 puis 401 → `SencropAuthError`, pas de 3e tentative.
  - `test_connection_errors` (paramétré) : `aiohttp.ClientConnectionError`, `asyncio.TimeoutError`, HTTP 500 → `SencropConnectionError`.
  - `test_invalid_json` : 200 avec un corps non JSON → `SencropResponseError`.
  - `test_get_latest_query` : l'URL contient `size=`, `beforeDate=` et un paramètre `measures` par mesure ; le résultat vient de `raw_rain.json`.
  - `test_get_daily_query` : `days=7`, `timeZone=Europe/Paris`.
  - `test_no_secret_in_logs` (`caplog` DEBUG) : ni email, ni mot de passe, ni token dans `caplog.text` après login + appel + erreur 401.
- [ ] **Step 2 : lancer** → FAIL.
- [ ] **Step 3 : implémenter `SencropClient`.** Une méthode privée `_request(method, path, *, params=None, json=None, auth=True)` centralise le timeout, le mapping des erreurs, le re-login avant expiration et le retry unique sur 401.
- [ ] **Step 4 : lancer** → PASS.
- [ ] **Step 5 : commit** — `git commit -m "Add Sencrop HTTP client with token renewal"`

---

### Task 5 : calculs dérivés

**Files :**
- Create : `custom_components/sencrop/derived.py`, `tests/test_derived.py`

**Interfaces :**
- Consumes : `Measurement`, `AggregateBucket` (Task 3).
- Produces :
  - `dew_point(temperature: float, humidity: float) -> float | None` (Magnus a=17.62, b=243.12, arrondi à 0,1 ; `None` si humidité ≤ 0)
  - `bucket_for_day(buckets: Sequence[AggregateBucket], day: date, tz: tzinfo) -> AggregateBucket | None` (bucket dont `start.astimezone(tz).date() == day`)
  - `sum_since(buckets: Sequence[AggregateBucket], measure: str, since: datetime) -> float | None` (somme des buckets avec `start >= since` qui contiennent la mesure ; `None` si aucun ; arrondi à 0,1)
  - `last_measurement_date(latest: Mapping[str, Measurement]) -> datetime | None`
  - `is_stale(latest: Mapping[str, Measurement], now: datetime, max_age: timedelta) -> bool` (`True` si vide ou plus ancienne mesure récente > max_age)

- [ ] **Step 1 : tests**
  - `test_dew_point` : `dew_point(20.0, 50.0) == 9.3` ; `dew_point(0.0, 100.0) == 0.0` ; `dew_point(10.0, 0.0) is None`.
  - `test_bucket_for_day_paris` : bucket `start = 2026-10-17T22:00Z` → jour `2026-10-18` en Europe/Paris.
  - `test_bucket_for_day_dst` : le 2026-03-29 (passage à l'heure d'été), bucket `start = 2026-03-28T23:00Z` → `2026-03-29` ; le 2026-10-25, bucket `start = 2026-10-24T22:00Z` → `2026-10-25`.
  - `test_bucket_for_day_missing` → `None`.
  - `test_sum_since` : 30 buckets horaires de 0,2 mm, `since = now - 24h` → `4.8` ; aucun bucket dans la fenêtre → `None`.
  - `test_is_stale` : mesure à `now - 1h59` → `False` ; `now - 2h01` → `True` ; `{}` → `True`.
- [ ] **Step 2 : lancer** → FAIL.
- [ ] **Step 3 : implémenter `derived.py`.**
- [ ] **Step 4 : lancer** → PASS.
- [ ] **Step 5 : commit** — `git commit -m "Add derived weather computations"`

---

### Task 6 : coordinator et setup de l'entrée

**Files :**
- Create : `custom_components/sencrop/coordinator.py`, `custom_components/sencrop/sensor.py` et `weather.py` (vides), `tests/test_coordinator.py`, `tests/test_init.py`
- Modify : `custom_components/sencrop/__init__.py`, `tests/conftest.py` (fixtures `mock_client` qui patche `custom_components.sencrop.SencropClient` avec un `AsyncMock` alimenté par les fixtures JSON parsées, et `mock_config_entry` : `MockConfigEntry(domain=DOMAIN, unique_id="12345", title="user@example.com", data={CONF_EMAIL: "user@example.com", CONF_PASSWORD: "secret"}, options={CONF_SCAN_INTERVAL: 5})`)

**Interfaces :**
- Consumes : `SencropClient` (Task 4), `derived.last_measurement_date` (Task 5), constantes (Task 1).
- Produces :
  - `@dataclass DeviceData(device: SencropDevice, latest: dict[str, Measurement], hourly: list[AggregateBucket], daily: list[AggregateBucket], aggregates_at: datetime | None)`
  - `type SencropConfigEntry = ConfigEntry[SencropCoordinator]`
  - `class SencropCoordinator(DataUpdateCoordinator[dict[int, DeviceData]])` : `__init__(hass, entry: SencropConfigEntry, client: SencropClient)`, `update_interval = timedelta(minutes=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))`, propriété `client`.
  - `async_setup_entry` / `async_unload_entry` dans `__init__.py` ; `entry.runtime_data = coordinator` ; listener d'options qui recharge l'entrée.

Règles de `_async_update_data` (issues de la spec) :
- `get_devices()`, puis `get_latest()` par capteur, avec toutes ses mesures.
- Agrégats re-fetchés si `aggregates_at is None`, ou `now - aggregates_at >= AGGREGATES_MAX_AGE`, ou `last_measurement_date(latest)` plus récente que lors du cycle précédent ; sinon ceux du cycle précédent sont conservés.
- Hourly (`days=2`, `["RAIN_FALL"]`) seulement si `RAIN_FALL` est dans les mesures. Daily (`days=7`) avec `RAIN_FALL` si pluie, plus `TEMPERATURE_MIN`/`TEMPERATURE_MAX` si température ; aucun appel daily si aucun des deux.
- `time_zone = hass.config.time_zone`.
- `SencropAuthError` → `ConfigEntryAuthFailed` ; `SencropConnectionError` → `UpdateFailed` ; `SencropResponseError` sur un capteur → log warning, le `DeviceData` précédent est conservé s'il existe, sinon le capteur est absent de ce cycle ; `SencropResponseError` sur `get_devices` → `UpdateFailed`.

- [ ] **Step 1 : tests coordinator**
  - `test_first_refresh_builds_device_data` : 3 entrées ; le pluviomètre a `hourly` et `daily` non vides ; l'anémomètre n'a ni hourly ni daily, et `get_hourly`/`get_daily` ne sont jamais appelés pour lui.
  - `test_aggregates_cached_when_no_new_measure` : 2 refresh à 5 min d'intervalle, mêmes dates → `get_daily` appelé une fois par capteur concerné.
  - `test_aggregates_refreshed_on_new_measure` : la 2e réponse raw a une date plus récente → `get_daily` rappelé.
  - `test_aggregates_refreshed_after_max_age` : `freezer.tick(timedelta(minutes=31))` → rappelé.
  - `test_device_parse_error_keeps_previous_data` : 2e `get_latest` du thermo lève `SencropResponseError` → `data[1003]` identique au cycle 1, les autres mis à jour.
  - `test_offline_device_empty_raw` : `get_latest` renvoie `{}` → `DeviceData.latest == {}`, pas d'exception.
  - `test_auth_error_starts_reauth` : `SencropAuthError` → un flow `reauth` présent dans `hass.config_entries.flow.async_progress()`.
  - `test_connection_error_update_failed` : `last_update_success is False`.
- [ ] **Step 2 : tests init** (`tests/test_init.py`)
  - `test_setup_and_unload` : `ConfigEntryState.LOADED` puis `NOT_LOADED`.
  - `test_setup_retry_on_connection_error` → `ConfigEntryState.SETUP_RETRY`.
  - `test_setup_auth_error` → `ConfigEntryState.SETUP_ERROR` et un flow reauth.
  - `test_options_update_reloads` : modifier `scan_interval` à 15 → `coordinator.update_interval == timedelta(minutes=15)` après rechargement.
- [ ] **Step 3 : lancer** → FAIL.
- [ ] **Step 4 : implémenter `coordinator.py` et `__init__.py`** (session `async_get_clientsession(hass)`, `await coordinator.async_config_entry_first_refresh()`, `async_forward_entry_setups(entry, PLATFORMS)`). Créer aussi `sensor.py` et `weather.py` avec un `async_setup_entry` qui n'ajoute aucune entité ; les Tasks 8 et 9 les complètent.
- [ ] **Step 5 : lancer** → PASS.
- [ ] **Step 6 : commit** — `git commit -m "Add data coordinator and config entry setup"`

---

### Task 7 : config flow (user, reauth, options)

**Files :**
- Create : `custom_components/sencrop/config_flow.py`, `custom_components/sencrop/strings.json`, `custom_components/sencrop/translations/en.json`, `custom_components/sencrop/translations/fr.json`, `tests/test_config_flow.py`

**Interfaces :**
- Consumes : `SencropClient`, exceptions (Task 4), constantes.
- Produces : `SencropConfigFlow(ConfigFlow, domain=DOMAIN)` avec `VERSION = 1`, `async_step_user`, `async_step_reauth`, `async_step_reauth_confirm`, `async_get_options_flow` → `SencropOptionsFlow` (`scan_interval`, `NumberSelector` de 5 à 60, pas 1, unité « min »).
- Titre de l'entrée = email ; `unique_id = str(user_id)`.
- Erreurs de formulaire : `invalid_auth`, `cannot_connect`, `unknown`. Abandons : `already_configured`, `reauth_successful`, `wrong_account`.

- [ ] **Step 1 : tests** (patch de `custom_components.sencrop.config_flow.SencropClient`) :
  - `test_user_flow_success` : `CREATE_ENTRY`, titre `user@example.com`, `unique_id == "12345"`, data = email + mot de passe.
  - `test_user_flow_errors` (paramétré) : `SencropAuthError → invalid_auth`, `SencropConnectionError → cannot_connect`, `Exception → unknown` ; puis le formulaire réussit à la 2e soumission.
  - `test_user_flow_already_configured` → abort `already_configured`.
  - `test_reauth_success` : nouveau mot de passe, même user_id → abort `reauth_successful`, `entry.data[CONF_PASSWORD]` mis à jour.
  - `test_reauth_wrong_account` : user_id 99999 → abort `wrong_account`.
  - `test_reauth_invalid_auth` → erreur `invalid_auth` sur le formulaire.
  - `test_options_flow` : `scan_interval = 15` → `entry.options == {CONF_SCAN_INTERVAL: 15}`.
- [ ] **Step 2 : lancer** → FAIL.
- [ ] **Step 3 : implémenter le flow et les chaînes.** Textes `strings.json` et `en.json` en anglais, `fr.json` en français, avec les mêmes clés. La description de l'étape user précise qu'il s'agit des identifiants de l'application Sencrop.
- [ ] **Step 4 : lancer** → PASS.
- [ ] **Step 5 : commit** — `git commit -m "Add config flow with reauth and options"`

---

### Task 8 : entités sensor

**Files :**
- Create : `custom_components/sencrop/entity.py`, `custom_components/sencrop/icons.json`, `tests/test_sensor.py`
- Modify : `custom_components/sencrop/sensor.py`, `strings.json`, `translations/en.json`, `translations/fr.json` (section `entity.sensor`)

**Interfaces :**
- Consumes : `SencropCoordinator`, `DeviceData` (Task 6), `derived.*` (Task 5).
- Produces :
  - `class SencropEntity(CoordinatorEntity[SencropCoordinator])` : `_attr_has_entity_name = True`, `__init__(coordinator, device_id: int, key: str)`, `unique_id = f"{device_id}_{key}"`, `DeviceInfo(identifiers={(DOMAIN, str(device_id))}, manufacturer="Sencrop", name=device.name, model=device.model, serial_number=device.serial, sw_version=device.firmware)`, propriété `device_data -> DeviceData | None`, `available` = `super().available and device_data is not None`.
  - `@dataclass(frozen=True, kw_only=True) SencropSensorEntityDescription(SensorEntityDescription)` : `value_fn: Callable[[DeviceData, datetime, tzinfo], StateType | datetime]`, `exists_fn: Callable[[SencropDevice], bool]`, `requires_fresh_data: bool = True`, `last_reset_fn: Callable[[datetime, tzinfo], datetime] | None = None`.
  - `SENSORS: tuple[SencropSensorEntityDescription, ...]` avec les `key` de la spec §4 : `temperature`, `humidity`, `wet_temperature`, `wind_speed`, `wind_gust`, `wind_direction`, `rain`, `rain_today`, `rain_24h`, `rain_7d`, `temperature_min_today`, `temperature_max_today`, `dew_point`, `battery`, `signal`, `firmware`, `last_measurement`.

Valeurs (spec §4.2) : `rain_today` = `bucket_for_day(daily, today).values["RAIN_FALL"]` ; `rain_24h` = `sum_since(hourly, "RAIN_FALL", now - 24h)` ; `rain_7d` = `sum_since(daily, "RAIN_FALL", minuit local de today - 6 j)` ; min/max = `bucket_for_day(daily, today)` sur `TEMPERATURE_MIN`/`_MAX` ; `dew_point` à partir de `latest`. Diagnostics : `requires_fresh_data=False`, `EntityCategory.DIAGNOSTIC`, `firmware` avec `entity_registry_enabled_default=False`. `signal` sans device_class (unité inconnue tant que la Task 2 ne l'a pas confirmée ; si ce sont des dBm, `SensorDeviceClass.SIGNAL_STRENGTH`). Disponibilité : `available` est faux si `requires_fresh_data` et `is_stale(latest, now, STALE_AFTER)`.

- [ ] **Step 1 : tests** (setup réel de l'entrée avec `mock_client` et `freezer` sur l'heure des fixtures, `snapshot` facultatif) :
  - `test_entities_created_per_capabilities` : le pluviomètre a `rain`, `rain_today`, `rain_24h`, `rain_7d` mais pas `temperature` ; l'anémomètre a `wind_speed`, `wind_gust`, `wind_direction` ; le thermo a `temperature`, `humidity`, `dew_point`, `temperature_min_today`, `temperature_max_today` ; chacun a `battery`, `signal`, `last_measurement`. Les entity_id suivent le nom du capteur et la traduction anglaise.
  - `test_measure_states` : valeurs égales à celles des fixtures, unités et device_class conformes à la spec §4.1 (`wind_direction` → `measurement_angle`).
  - `test_rain_aggregates` : `rain_today`, `rain_24h` et `rain_7d` égaux aux sommes calculées à la main sur les fixtures (valeurs écrites en dur dans le test) ; `rain_today` a `state_class: total` et `last_reset` = minuit local du jour en ISO.
  - `test_dew_point_state` : égal à `dew_point(temp, hum)` des fixtures.
  - `test_stale_device_unavailable` : `freezer.tick(timedelta(hours=3))` puis refresh avec les mêmes données → `temperature` `unavailable`, `battery` disponible.
  - `test_coordinator_failure_unavailable` : refresh qui lève `SencropConnectionError` → toutes les entités `unavailable`.
  - `test_device_info` : manufacturer `Sencrop`, `serial_number == "SERIAL-1"`, `sw_version` = firmware.
  - `test_firmware_disabled_by_default` : l'entrée du registre a `disabled_by == RegistryEntryDisabler.INTEGRATION`.
- [ ] **Step 2 : lancer** → FAIL.
- [ ] **Step 3 : implémenter `entity.py`, `sensor.py`, les traductions FR/EN des noms d'entité et `icons.json`** (`rain*` → `mdi:weather-rainy`, `wind_*` → `mdi:weather-windy`, `wind_direction` → `mdi:compass-outline`, `dew_point` → `mdi:thermometer-water`, `signal` → `mdi:signal`, `firmware` → `mdi:chip`).
- [ ] **Step 4 : lancer** → PASS.
- [ ] **Step 5 : commit** — `git commit -m "Add Sencrop sensor entities"`

---

### Task 9 : entité weather

**Files :**
- Modify : `custom_components/sencrop/weather.py`, chaînes FR/EN (`entity.weather.station.name`)
- Create : `tests/test_weather.py`

**Interfaces :**
- Consumes : `SencropCoordinator`, `DeviceData`, `derived.dew_point`, `derived.sum_since`, `derived.is_stale`.
- Produces : `SencropWeather(CoordinatorEntity[SencropCoordinator], WeatherEntity)`, `unique_id = f"station_{user_id}"`, device `identifiers={(DOMAIN, f"station_{user_id}")}`, nom « Station Sencrop », `native_temperature_unit = °C`, `native_wind_speed_unit = km/h`, `supported_features = 0`.

Règles (spec §4.5) : chaque grandeur vient du premier capteur non périmé, dans l'ordre de l'API, qui la fournit. `condition = ATTR_CONDITION_RAINY` si `sum_since(hourly du premier capteur pluie, "RAIN_FALL", (now - 1h) tronqué à l'heure pleine) > 0`, sinon `None`. `available` est faux si aucun capteur non périmé ne fournit `TEMPERATURE`.

- [ ] **Step 1 : tests**
  - `test_weather_attributes` : température et humidité du thermo, vent, rafales et direction de l'anémomètre, point de rosée cohérent.
  - `test_weather_condition_rainy` : hourly avec 0,4 mm dans l'heure → `rainy`.
  - `test_weather_condition_none` : 0 mm → état `unknown`.
  - `test_weather_without_thermo` : thermo périmé → entité `unavailable`.
  - `test_weather_device` : device « Station Sencrop », distinct des 3 capteurs.
- [ ] **Step 2 : lancer** → FAIL.
- [ ] **Step 3 : implémenter `weather.py`.**
- [ ] **Step 4 : lancer** → PASS.
- [ ] **Step 5 : commit** — `git commit -m "Add aggregated weather entity"`

---

### Task 10 : diagnostics

**Files :**
- Create : `custom_components/sencrop/diagnostics.py`, `tests/test_diagnostics.py`

**Interfaces :**
- Produces : `async_get_config_entry_diagnostics(hass, entry: SencropConfigEntry) -> dict` = `{"entry": async_redact_data(entry.as_dict(), TO_REDACT), "devices": async_redact_data(<dataclasses → dict via asdict, datetimes en ISO>, TO_REDACT)}`, avec `TO_REDACT = {CONF_EMAIL, CONF_PASSWORD, "title", "unique_id", "serial", "latitude", "longitude", "token"}`.

- [ ] **Step 1 : test** `test_diagnostics_redacted` : `get_diagnostics_for_config_entry` → `"user@example.com"`, `"secret"`, `"12345"`, `"SERIAL-1"` et `45.0` absents de `json.dumps(result)` ; les 3 devices sont présents avec `latest`.
- [ ] **Step 2 : lancer** → FAIL ; **Step 3 : implémenter** ; **Step 4 : lancer** → PASS.
- [ ] **Step 5 : commit** — `git commit -m "Add redacted diagnostics"`

---

### Task 11 : CI, README et vérification finale

**Files :**
- Create : `.github/workflows/validate.yml`, `.github/workflows/tests.yml`, `README.md`

- [ ] **Step 1 : `validate.yml`** (push, PR, cron hebdomadaire) : job `hassfest` (`home-assistant/actions/hassfest@master`) et job `hacs` (`hacs/action@main`, `category: integration`).
- [ ] **Step 2 : `tests.yml`** : `actions/setup-python` (version de la Task 1), `pip install -r requirements_test.txt`, `ruff check .`, `ruff format --check .`, `pytest --cov=custom_components.sencrop --cov-report=term-missing --cov-fail-under=90`.
- [ ] **Step 3 : README (FR)** : présentation, prérequis (compte Sencrop, version HA de `hacs.json`), installation HACS (« Dépôts personnalisés » → `https://github.com/oallain/ha-sencrop`, catégorie Intégration), configuration, tableau des entités, options, exemple d'automatisation (ne pas arroser si `sensor.<pluvio>_rain_7d` > 10 mm), diagnostics, limites (login via l'endpoint de l'app non documenté dans le guide, polling cloud, mesures toutes les ~15 min), désinstallation.
- [ ] **Step 4 : vérification locale complète**
  - `.venv/bin/ruff check . && .venv/bin/ruff format --check .` → propre.
  - `.venv/bin/pytest --cov=custom_components.sencrop --cov-fail-under=90 -q` → tous les tests passent, couverture ≥ 90 %.
  - hassfest en local : `docker run --rm -v "$PWD/custom_components:/github/workspace/custom_components" ghcr.io/home-assistant/hassfest` → aucune erreur.
  - Validation HACS : vérifier à la main les exigences de `hacs.json`, `manifest.json` et de la structure `custom_components/sencrop/` (l'action HACS exige un dépôt GitHub : elle tournera au premier push).
- [ ] **Step 5 : test réel par l'utilisateur** : copier `custom_components/sencrop` dans le `config/custom_components/` de son HA, redémarrer, ajouter l'intégration, puis vérifier les 3 capteurs, les valeurs comparées à l'app Sencrop et l'entité weather. Corriger les écarts (systematic-debugging) avant de livrer.
- [ ] **Step 6 : commit** — `git commit -m "Add CI workflows and README"`. La publication sur GitHub et la release `v0.1.0` restent à l'utilisateur.

# Intégration Home Assistant « Sencrop » — Design

Date : 2026-10-18
Dépôt : `github.com/oallain/ha-sencrop` (dépôt git local `fs25-welcome/semcrop`)

## 1. Objectif

Remonter dans Home Assistant les mesures des capteurs Sencrop de l'utilisateur
(pluviomètre Raincrop, anémomètre Windcrop, thermomètre-hygromètre), via une
intégration custom installable avec HACS.

Critères de succès :

- installation via HACS « dépôt personnalisé », configuration 100 % par l'UI ;
- chaque capteur Sencrop apparaît comme un device HA avec ses entités à jour
  (retard ≤ intervalle de polling après publication de la mesure par Sencrop) ;
- cumuls de pluie exploitables pour des automatisations d'arrosage ;
- robustesse : expiration de token, coupure réseau, capteur muet gérés sans
  intervention ; mot de passe changé → flux de réauthentification HA ;
- validation `hassfest` + HACS, tests automatisés (couverture ≥ 90 %).

Hors périmètre : prévisions, alertes Sencrop, import d'historique. Les mesures
sol/feuille/irradiance sont prévues dans le mapping mais non testées sur
matériel réel.

## 2. API Sencrop utilisée

Base : `https://api.sencrop.com/v1` (spec publique : `GET /openAPI`, v1.140.0).

| Usage | Endpoint | Notes |
|---|---|---|
| Login | `POST /users/sign_in` `{email, password}` | Renvoie `token`, `refreshToken`, `expirationDate`, `userId` |
| Capteurs | `GET /users/{userId}/devices` | Hash `devices` + `models` + `items` ; `status` (battery, signal, firmware), `measures.list`, `contents.name`, `serial` |
| Dernières mesures | `GET /users/{userId}/devices/{id}/data/raw` | `beforeDate` (now), `size` ∈ {10,50,100,500,1000}, `measures[]` ; items `{date, type, value, discarded?}` |
| Agrégats horaires | `GET /users/{userId}/devices/{id}/data/hourly` | `beforeDate`, `days` ∈ {1,2,7,20,31}, `measures[]`, `timeZone` |
| Agrégats journaliers | `GET /users/{userId}/devices/{id}/data/daily` | `beforeDate`, `days` ∈ {7,30,60,90}, `measures[]`, `timeZone` |

Authentification des appels : `Authorization: Bearer <token>`.
Agrégation côté Sencrop : moyenne (temp., humidité, vent), somme (pluie),
somme vectorielle (direction). Compartiments alignés sur le fuseau fourni.

Unités API : °C, %, mm, km/h, degrés [0, 360).

**Incertitudes levées par `scripts/probe.py` avant d'écrire le parsing** :
sémantique exacte de `size` (total vs par mesure), présence éventuelle des
dernières valeurs dans `/devices?measures=…`, forme réelle de `DeviceStatistics`
(`measures.interval`, `measures.data[].key`, valeurs par mesure, `docCount`),
noms des mesures min/max (`TEMPERATURE_MIN`/`_MAX`), durée de vie du token,
existence d'un endpoint de refresh. Les fixtures de test sont dérivées de ces
réponses réelles, anonymisées.

## 3. Architecture

Approche retenue : client API embarqué dans le composant (pas de librairie
PyPI). `api.py` n'importe rien de `homeassistant` afin de rester extractible.

```
custom_components/sencrop/
  __init__.py       setup/unload de l'entrée, création client + coordinator
  manifest.json     domain sencrop, cloud_polling, config_flow, version semver
  const.py          DOMAIN, intervalles, clés de mesures
  api.py            SencropClient (aiohttp), dataclasses, exceptions
  coordinator.py    SencropCoordinator (DataUpdateCoordinator)
  config_flow.py    user, reauth, options
  entity.py         SencropEntity (CoordinatorEntity + DeviceInfo)
  sensor.py         descriptions + entités capteurs
  weather.py        entité weather agrégée
  diagnostics.py    dump redacté
  strings.json, translations/en.json, translations/fr.json, icons.json
scripts/probe.py    CLI de test réel (SENCROP_EMAIL / SENCROP_PASSWORD en env)
tests/              pytest-homeassistant-custom-component
hacs.json, README.md, pyproject.toml, requirements_test.txt
.github/workflows/  validate.yml (hassfest + HACS), tests.yml (pytest + ruff)
```

### 3.1 Client (`api.py`)

- `SencropClient(session, email, password)` : utilise la session aiohttp de HA.
- `async_login()` → `userId`, token, expiration. Reconnexion automatique si le
  token expire dans moins de 5 min, et une seule fois sur réponse 401 avant
  de lever `SencropAuthError`.
- `async_get_devices()` → `dict[int, SencropDevice]`.
- `async_get_latest(device_id, measures)` → `dict[str, Measurement]` (valeur la
  plus récente non `discarded` par mesure).
- `async_get_hourly(device_id, measures, days, tz)` /
  `async_get_daily(...)` → `list[AggregateBucket]`.
- Dataclasses : `SencropDevice` (id, name, model, serial, firmware, battery,
  signal, measures, location, last_status_update),
  `Measurement` (type, value, date), `AggregateBucket` (start, values, count).
- Exceptions : `SencropError` ⊃ `SencropAuthError`, `SencropConnectionError`,
  `SencropResponseError`.
- Timeout 30 s par requête. Aucune donnée sensible (mot de passe, token,
  email) dans les logs.

### 3.2 Coordinator

Un `SencropCoordinator` par entrée de configuration. Intervalle par défaut
5 min, configurable de 5 à 60 min via les options (rechargement de l'entrée).

Cycle :

1. `get_devices()`.
2. Pour chaque device : `get_latest()` sur `device.measures`.
3. Agrégats rafraîchis si une mesure plus récente est apparue pour ce device,
   ou si les agrégats ont plus de 30 min :
   - device avec `RAIN_FALL` : hourly (2 jours) + daily (7 jours) pluie ;
   - device avec `TEMPERATURE` : daily min/max température.
   Le fuseau est celui de HA (`hass.config.time_zone`).
4. Résultat : `SencropData` = `{device_id: DeviceData(device, latest, derived)}`.

Une erreur sur un device (réponse illisible) est loguée et ce device garde ses
données précédentes ; une erreur globale (auth, réseau) remonte au coordinator.

Budget : ~4 appels / 5 min + ~3–6 appels d'agrégats au plus toutes les 15–30 min,
très en dessous de la limite indicative (~100 appels/min).

## 4. Entités

Un device HA par capteur Sencrop : `identifiers={(DOMAIN, device_id)}`, nom de
l'app, fabricant « Sencrop », modèle, `serial_number`, `sw_version` (firmware).
`has_entity_name=True`, `unique_id = f"{device_id}_{key}"`, noms traduits.
Entités créées uniquement si la mesure figure dans `device.measures`.

### 4.1 Mesures (dernière valeur)

| key | Mesure | device_class | state_class | Unité |
|---|---|---|---|---|
| temperature | TEMPERATURE | temperature | measurement | °C |
| humidity | RELATIVE_HUMIDITY | humidity | measurement | % |
| wet_temperature | WET_TEMPERATURE | temperature | measurement | °C |
| wind_speed | WIND_SPEED | wind_speed | measurement | km/h |
| wind_gust | WIND_GUST | wind_speed | measurement | km/h |
| wind_direction | WIND_DIRECTION | wind_direction | measurement_angle | ° |
| rain | RAIN_FALL | precipitation | measurement | mm |

### 4.2 Dérivées

| key | Source | device_class | state_class |
|---|---|---|---|
| rain_today | dernier compartiment daily (jour courant) | precipitation | total (`last_reset` = minuit local) |
| rain_24h | somme des 24 derniers compartiments hourly | precipitation | measurement |
| rain_7d | somme des 7 compartiments daily (aujourd'hui inclus) | precipitation | measurement |
| temperature_min_today / temperature_max_today | daily `TEMPERATURE_MIN` / `_MAX` du jour courant | temperature | measurement |
| dew_point | Magnus (a=17.62, b=243.12) depuis température + humidité | temperature | measurement |

`rain_today` utilise `total` + `last_reset` plutôt que `total_increasing` :
une révision à la baisse du cumul par Sencrop serait sinon interprétée comme
une remise à zéro et doublerait les statistiques long terme.

`dew_point` n'existe que si le device fournit température et humidité.

### 4.3 Diagnostic (`EntityCategory.DIAGNOSTIC`)

battery (%, device_class battery), signal, firmware (désactivé par défaut),
last_measurement (device_class timestamp).

### 4.4 Disponibilité

Entité `unavailable` si : dernier refresh du coordinator en échec, ou mesure
absente, ou dernière mesure du device plus vieille que 2 h (capteur muet).
Les diagnostics restent disponibles tant que l'API répond.

### 4.5 Entité weather

Une par entrée, sur un device virtuel « Station Sencrop »
(`identifiers={(DOMAIN, f"station_{user_id}")}`). Chaque grandeur provient du
premier device (ordre `items` de l'API) qui la fournit : température, humidité,
point de rosée, vent, rafales, direction. `condition` = `rainy` si la pluie
de la dernière heure (dernier compartiment hourly) > 0 mm, sinon `None`.
Pas de prévisions (`supported_features = 0`).

## 5. Configuration

- Étape `user` : email + mot de passe → login → `unique_id = str(userId)`,
  `_abort_if_unique_id_configured()`. Erreurs : `invalid_auth`,
  `cannot_connect`, `unknown`.
- Reauth : demande du mot de passe, vérification que le `userId` est identique
  (sinon abort `wrong_account`), mise à jour de l'entrée et rechargement.
- Options : `scan_interval` (minutes, 5–60, défaut 5).
- Stockage : email + mot de passe dans `entry.data` (pratique standard des
  intégrations cloud HA) ; le token reste en mémoire.

## 6. Gestion des erreurs

| Situation | Client | HA |
|---|---|---|
| Identifiants refusés | `SencropAuthError` | flow : `invalid_auth` ; runtime : `ConfigEntryAuthFailed` → reauth |
| 401 en cours d'usage | re-login unique puis `SencropAuthError` | idem |
| Timeout / 5xx / réseau | `SencropConnectionError` | `UpdateFailed` ; au setup `ConfigEntryNotReady` |
| JSON inattendu | `SencropResponseError` | `UpdateFailed` (global) ou device ignoré (local) |

Diagnostics : `async_redact_data` sur email, password, token, refreshToken,
userId, location, serial.

## 7. Tests et qualité

- `pytest-homeassistant-custom-component`, `aioresponses` pour le client.
- Fixtures JSON issues de `probe.py`, anonymisées.
- Couverture : client (login, re-login 401, parsing, erreurs), config flow
  (succès, invalid_auth, cannot_connect, already_configured, reauth, options),
  coordinator/sensor (création conditionnelle, cumuls, point de rosée,
  péremption, indisponibilité), weather, diagnostics. Objectif ≥ 90 %.
- `ruff` (lint + format), `hassfest`, HACS action en CI GitHub Actions.
- Version HA minimale : la première version qui fournit
  `SensorDeviceClass.WIND_DIRECTION` et `SensorStateClass.MEASUREMENT_ANGLE`,
  vérifiée sur la version de HA installée pour les tests, puis reportée dans
  `hacs.json`.

## 8. Livraison

- `hacs.json`, `manifest.json` (`codeowners: ["@oallain"]`, `documentation` et
  `issue_tracker` vers `github.com/oallain/ha-sencrop`), version `0.1.0`.
- README (FR) : installation HACS dépôt personnalisé, configuration, entités,
  exemple d'automatisation d'arrosage, limites (endpoint de login non documenté
  dans le guide Sencrop, polling cloud).
- Commits locaux uniquement, sur une ligne, en anglais et sans préfixe. Le push et la création
  de release restent à l'initiative de l'utilisateur.

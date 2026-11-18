# AndSolar for Home Assistant

Custom integration that shows AndSolar plants, rapid shutdown devices and module optimizers
in Home Assistant, and lets you switch them on and off. It talks to the AndSolar OpenAPI
(`https://ap.andsolartech.com`, production).

## Install

**HACS (custom repository):** HACS, Integrations, menu, Custom repositories, add this repo as
type "Integration", install "AndSolar", restart Home Assistant.

**Manual:** copy `custom_components/andsolar` into your Home Assistant `config/custom_components/`
folder and restart.

Then: Settings, Devices & services, Add integration, "AndSolar". Enter the OpenAPI username and
password you got from AndSolar. The server URL defaults to production; use
`https://monitor.andsolartech.com` for the test server.

Requires Home Assistant 2025.2 or newer.

## What you get

One Home Assistant device per plant, and one per rapid shutdown device / module optimizer
(linked to its plant).

| Entity | On | Notes |
|---|---|---|
| Daily energy, Total energy | plant | kWh, usable in the Energy dashboard |
| Power, voltage, current, temperature | device (per branch) | rapid shutdown devices have 1 or 2 branches |
| Output / input voltage and current, PCB / input / output temperature | module optimizer | |
| Daily energy, Total energy | device (per branch) | kWh |
| Status | device (per branch) | offline, warning, accident, healthy |
| Branch output switch | rapid shutdown | real state from the device (`mos`) |
| Output switch | module optimizer | state is assumed from the last command |
| Plant output switch | plant | **disabled by default**; switches the whole plant, state is assumed |

Polling interval defaults to 5 minutes (Configure on the integration page, 1 to 60 minutes).
Each update makes one request per device, so keep the interval sensible on large plants.

## Safety

The switches control real power equipment. Turning a rapid shutdown output off stops that
string's output. The plant-wide switch is disabled by default; enable it in the entity settings
only if you want it. Do not wire these switches to automations you have not tested.

## Known caveats

- **Device discovery** uses `GET /api/openapi/device/plantGroupStringTree`. The published docs
  show this endpoint with `localhost:8044/openapi/...` (no `/api` prefix), so the exact
  production path is an assumption. If it fails, plant sensors still work but no device
  entities appear, and a warning is logged. If you see that warning, try removing `/api` for
  that one path in `api.py`.
- The OpenAPI docs do not describe every response, so field handling follows the documented
  examples. Unknown or missing values show as unavailable instead of failing the update.
- Entity names are English only.

## Development

```
custom_components/andsolar/
  api.py          blocking HTTP client (standard library only), token handling
  parsing.py      pure helpers (unit-tested without Home Assistant)
  coordinator.py  polling, runs the client in an executor thread
  config_flow.py  setup, re-authentication and options
  sensor.py       sensors
  switch.py       switches
tests/            python -m unittest discover -s tests -v
```

The tests cover the client (against a local mock server) and the parsing helpers. They do not
import Home Assistant, so the integration code itself needs a manual check in a real Home
Assistant instance.

Credentials are never stored in the repo. Do not commit tokens or passwords.

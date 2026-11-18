# AndSolar for Home Assistant

Custom integration that shows AndSolar plants, rapid shutdown devices and module optimizers
in Home Assistant, and lets you switch them on and off. It talks to the AndSolar OpenAPI
(`https://ap.andsolartech.com`, production).

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=armyjam&repository=andsolar-ha&category=integration)

> **Unofficial project.** This integration is an independent, community-made project. It is
> **not affiliated with, endorsed by, or supported by AndSolar** or Home Assistant. "AndSolar" and
> any related names or logos are trademarks of their respective owners and are used here only to
> identify the product this integration works with. See [Disclaimer](#disclaimer).

## Requirements

- Home Assistant 2025.2 or newer
- [HACS](https://hacs.xyz) installed in Home Assistant (recommended install method)
- An **AndSolar OpenAPI** username and password, as provided by AndSolar. This is the API
  account, not necessarily the one you use in the AndSolar app or web portal.

## Install with HACS (recommended)

This integration is not in the default HACS store, so you add it once as a custom repository.

1. In Home Assistant open **HACS**. If you have not set HACS up yet, add it first from
   **Settings → Devices & services → Add integration → HACS** and sign in with GitHub.
2. Click the **⋮** menu (top right) and choose **Custom repositories**.
3. Enter the repository URL `https://github.com/armyjam/andsolar-ha`, set **Type** to
   **Integration**, and click **Add**.
   (Or use the "Open in HACS" button at the top of this page.)
4. Find **AndSolar** in HACS and click **Download**.
5. **Restart Home Assistant** (Settings → System → Restart).
6. Go to **Settings → Devices & services → Add integration**, search for **AndSolar** and
   enter your OpenAPI username and password.

The server URL defaults to production (`https://ap.andsolartech.com`). Use
`https://monitor.andsolartech.com` only if AndSolar gave you a test account.

### Updating

HACS shows an update on the AndSolar entry when a new version is published. Click **Update**
and restart Home Assistant afterwards. To see updates before they are released, enable beta
versions in the repository's HACS settings.

### Install manually (without HACS)

Copy the `custom_components/andsolar` folder of this repository into your Home Assistant
`config/custom_components/` folder, restart Home Assistant, then continue with step 6 above.
Manual installs are not updated automatically.

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

Polling interval defaults to 5 minutes (**Configure** on the integration page, 1 to 60
minutes). Each update makes one request per device, so keep the interval sensible on large
plants.

## Safety

The switches control real power equipment. Turning a rapid shutdown output off stops that
string's output. The plant-wide switch is disabled by default; enable it in the entity settings
only if you want it. Do not wire these switches to automations you have not tested.

Do not rely on this integration for anything safety-critical. Rapid shutdown and optimizer
functions exist to protect people and equipment: confirm their behavior on the device or in the
official AndSolar tools, not only in Home Assistant.

## Troubleshooting

**"Invalid username or password" when adding the integration.** The message is shown for any
login that the server does not accept, not only a wrong password. Check that you are using the
OpenAPI account and that no extra space was added to the fields. To see the server's actual
answer, enable debug logging (below) and try again.

**Debug logging.** Add this to `configuration.yaml`, restart, and look in
**Settings → System → Logs**:

```yaml
logger:
  default: warning
  logs:
    custom_components.andsolar: debug
```

Do not post logs publicly without checking them first.


**Switches take a while to react.** Commands go through the AndSolar cloud. The server may
execute a command before its response reaches Home Assistant, so a switch can briefly show the
old state; it settles on the next update.

## Known caveats

- The OpenAPI docs do not describe every response, so field handling follows the documented
  examples. Unknown or missing values show as unavailable instead of failing the update.
- Optimizer and plant-wide switch states are assumed from the last command, not read back from
  the device.
- Entity names are English only.

## Disclaimer

- **Use at your own risk.** The software is provided "as is", without warranty of any kind. The
  author is not liable for any damage, data loss, loss of generation, or equipment problems
  resulting from its use. This includes the switches, which send real commands to real
  equipment.
- **Not affiliated.** This is not an official AndSolar product. It was built against the AndSolar
  OpenAPI and may stop working if AndSolar changes or withdraws that API.
- **Your account, your responsibility.** Use only an OpenAPI account you are entitled to use, and
  make sure your use complies with the terms that came with it (for example limits on automated
  requests). Keep the polling interval reasonable.
- **Trademarks and images.** Product names, trademarks and logos belong to their respective
  owners. The MIT license below covers the source code only; it does not grant any rights to
  third-party names, logos or images.

## Privacy

Your OpenAPI username and password are stored in your Home Assistant configuration (the
integration's config entry) on your own system. They are sent only to the server URL you
configure (production by default). The integration has no telemetry and sends nothing to the
author. Do not share Home Assistant backups, diagnostics or logs without checking them first.

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 armyjam.

## Development

```
custom_components/andsolar/
  api.py          blocking HTTP client (standard library only), token handling
  parsing.py      pure helpers (unit-tested without Home Assistant)
  coordinator.py  polling, runs the client in an executor thread
  config_flow.py  setup, re-authentication and options
  sensor.py       sensors
  switch.py       switches
  brand/          icon shown in Home Assistant (2026.3 and newer)
tests/            python -m unittest discover -s tests -v
```

The tests cover the client (against a local mock server) and the parsing helpers. They do not
import Home Assistant, so the integration code itself needs a manual check in a real Home
Assistant instance.

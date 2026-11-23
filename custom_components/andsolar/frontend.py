"""Static frontend registration for the bundled AndSolar Lovelace card."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import CARD_FILENAME, DOMAIN, FRONTEND_URL_BASE, INTEGRATION_VERSION

_LOGGER = logging.getLogger(__name__)
_FRONTEND_REGISTERED_KEY = "frontend_registered"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the built-in Lovelace card JS and auto-load it into HA frontend."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_FRONTEND_REGISTERED_KEY):
        return

    frontend_dir = Path(__file__).parent / "frontend"
    card_path = frontend_dir / CARD_FILENAME
    if not card_path.is_file():
        _LOGGER.warning("AndSolar frontend card file missing at %s", card_path)
        return

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                url_path=FRONTEND_URL_BASE,
                path=str(frontend_dir),
                cache_headers=False,
            )
        ]
    )

    card_url = f"{FRONTEND_URL_BASE}/{CARD_FILENAME}?v={INTEGRATION_VERSION}"
    try:
        add_extra_js_url(hass, card_url)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not auto-register extra JS URL %s", card_url, exc_info=True)

    domain_data[_FRONTEND_REGISTERED_KEY] = True

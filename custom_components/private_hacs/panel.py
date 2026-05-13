"""Custom panel registration for Private HACS."""
from __future__ import annotations

import logging
import os

from homeassistant.components.panel_custom import async_register_panel
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PANEL_ICON, PANEL_TITLE, PANEL_URL

_LOGGER = logging.getLogger(__name__)

_PANEL_REGISTERED = False


async def async_setup_panel(hass: HomeAssistant) -> None:
    """Register the sidebar panel (idempotent)."""
    global _PANEL_REGISTERED
    if _PANEL_REGISTERED:
        return

    panel_dir = os.path.join(os.path.dirname(__file__), "frontend")
    panel_file = os.path.join(panel_dir, "panel.html")

    if not os.path.exists(panel_file):
        _LOGGER.error("Panel HTML not found at %s", panel_file)
        return

    # Serve the static HTML file
    hass.http.register_static_path(
        f"/private_hacs_panel",
        panel_dir,
        cache_headers=False,
    )

    await async_register_panel(
        hass,
        component_name="iframe",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        frontend_url_path=PANEL_URL,
        config={"url": "/private_hacs_panel/panel.html"},
        require_admin=True,
    )

    _PANEL_REGISTERED = True
    _LOGGER.info("Private HACS panel registered at /%s", PANEL_URL)


async def async_remove_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel."""
    global _PANEL_REGISTERED
    if not _PANEL_REGISTERED:
        return
    hass.components.frontend.async_remove_panel(PANEL_URL)
    _PANEL_REGISTERED = False

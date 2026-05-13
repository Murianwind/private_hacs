"""Custom panel registration for Private HACS."""
from __future__ import annotations

import logging
import os

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.panel_custom import async_register_panel
from homeassistant.core import HomeAssistant

from .const import PANEL_ICON, PANEL_TITLE, PANEL_URL

_LOGGER = logging.getLogger(__name__)

_REGISTERED_HASS_IDS: set[int] = set()

_PANEL_JS = """customElements.define('private-hacs-panel', class extends HTMLElement {
  connectedCallback() {
    if (this.shadowRoot) return;
    const shadow = this.attachShadow({ mode: 'open' });
    const iframe = document.createElement('iframe');
    iframe.src = '/private_hacs_panel/panel.html';
    iframe.style.cssText = 'width:100%;height:100%;border:none;display:block;';
    shadow.appendChild(iframe);

    iframe.addEventListener('load', () => {
      try {
        const token =
          window.hassConnection?.auth?.data?.access_token ||
          document.cookie.match(/ingress_token=([^;]+)/)?.[1] || '';
        iframe.contentWindow.postMessage({ type: 'ha_token', token }, '*');
      } catch(_) {}
    });
  }

  set hass(_) {}
});"""


def _write_panel_js_sync(path: str) -> None:
    """Blocking write — must be called via executor."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(_PANEL_JS)


async def async_setup_panel(hass: HomeAssistant) -> None:
    """Register the sidebar panel (idempotent per hass instance)."""
    hass_id = id(hass)
    if hass_id in _REGISTERED_HASS_IDS:
        return

    panel_dir = os.path.join(os.path.dirname(__file__), "frontend")
    panel_file = os.path.join(panel_dir, "panel.html")

    if not os.path.exists(panel_file):
        _LOGGER.error("Panel HTML not found at %s", panel_file)
        return

    js_dir = os.path.join(panel_dir, "js")
    os.makedirs(js_dir, exist_ok=True)

    # open()은 blocking이므로 executor에서 실행
    await hass.async_add_executor_job(
        _write_panel_js_sync, os.path.join(js_dir, "panel.js")
    )

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                url_path="/private_hacs_panel",
                path=panel_dir,
                cache_headers=False,
            ),
            StaticPathConfig(
                url_path="/private_hacs_panel/js",
                path=js_dir,
                cache_headers=False,
            ),
        ]
    )

    await async_register_panel(
        hass,
        webcomponent_name="private-hacs-panel",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        frontend_url_path=PANEL_URL,
        js_url="/private_hacs_panel/js/panel.js",
        require_admin=True,
    )

    _REGISTERED_HASS_IDS.add(hass_id)
    _LOGGER.info("Private HACS panel registered at /%s", PANEL_URL)


async def async_remove_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel."""
    hass_id = id(hass)
    if hass_id not in _REGISTERED_HASS_IDS:
        return
    hass.components.frontend.async_remove_panel(PANEL_URL)
    _REGISTERED_HASS_IDS.discard(hass_id)

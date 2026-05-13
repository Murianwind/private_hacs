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


def _write_panel_js_sync(path: str, panel_html: str) -> None:
    """Blocking write — must be called via executor."""
    # panel.html 내용을 JS 문자열로 escape해서 Web Component에 직접 삽입
    escaped = panel_html.replace('\\', '\\\\').replace('`', '\\`').replace('${', '\\${')
    js = f"""customElements.define('private-hacs-panel', class extends HTMLElement {{
  connectedCallback() {{
    if (this._initialized) return;
    this._initialized = true;
    this.attachShadow({{ mode: 'open' }});
    this.shadowRoot.innerHTML = `{escaped}`;
    this._initPanel();
  }}

  set hass(hass) {{
    this._hass = hass;
    if (!this._tokenSent && hass?.auth?.data?.access_token) {{
      this._tokenSent = true;
      const token = hass.auth.data.access_token;
      // 패널 내부 스크립트에 토큰 전달
      if (this._resolveToken) this._resolveToken(token);
    }}
  }}

  _initPanel() {{
    // 토큰 Promise를 shadow DOM의 window 컨텍스트에 노출
    const self = this;
    this.shadowRoot._getToken = () => new Promise((resolve, reject) => {{
      if (self._hass?.auth?.data?.access_token) {{
        resolve(self._hass.auth.data.access_token);
      }} else {{
        self._resolveToken = resolve;
        setTimeout(() => reject(new Error('hass 토큰 수신 시간 초과')), 5000);
      }}
    }});
  }}
}});"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(js)


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

    panel_html = await hass.async_add_executor_job(
        _read_file_sync, panel_file
    )

    await hass.async_add_executor_job(
        _write_panel_js_sync,
        os.path.join(js_dir, "panel.js"),
        panel_html,
    )

    await hass.http.async_register_static_paths(
        [
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


def _read_file_sync(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


async def async_remove_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel."""
    hass_id = id(hass)
    if hass_id not in _REGISTERED_HASS_IDS:
        return
    hass.components.frontend.async_remove_panel(PANEL_URL)
    _REGISTERED_HASS_IDS.discard(hass_id)

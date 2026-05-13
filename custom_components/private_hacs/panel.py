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

_PANEL_JS = r"""\
customElements.define('private-hacs-panel', class extends HTMLElement {
  connectedCallback() {
    if (this._initialized) return;
    this._initialized = true;
    this.style.cssText = 'display:block;width:100%;height:100%;';
    this.attachShadow({ mode: 'open' });
    this._loadHTML();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._tokenSent && hass?.auth?.data?.access_token) {
      this._tokenSent = true;
      if (this._resolveToken) this._resolveToken(hass.auth.data.access_token);
    }
  }

  async _loadHTML() {
    try {
      const resp = await fetch('/private_hacs_panel/panel.html');
      const html = await resp.text();

      // <style> 삽입
      const styleMatch = html.match(/<style>([\s\S]*?)<\/style>/);
      if (styleMatch) {
        const style = document.createElement('style');
        style.textContent = styleMatch[1];
        this.shadowRoot.appendChild(style);
      }

      // <body> 내용 삽입 (script 제외)
      const bodyMatch = html.match(/<body[^>]*>([\s\S]*?)<\/body>/);
      if (bodyMatch) {
        const div = document.createElement('div');
        div.style.cssText = 'min-height:100vh;';
        div.innerHTML = bodyMatch[1].replace(/<script[\s\S]*?<\/script>/gi, '');
        this.shadowRoot.appendChild(div);
      }

      // _getToken 주입 (script 실행 전에)
      const self = this;
      this.shadowRoot._getToken = () => new Promise((resolve, reject) => {
        if (self._hass?.auth?.data?.access_token) {
          resolve(self._hass.auth.data.access_token);
        } else {
          self._resolveToken = resolve;
          setTimeout(() => reject(new Error('hass 토큰 수신 시간 초과')), 5000);
        }
      });

      // <script> 실행 (_getToken 주입 후)
      const scriptMatches = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/gi)];
      for (const m of scriptMatches) {
        const script = document.createElement('script');
        script.textContent = m[1];
        this.shadowRoot.appendChild(script);
      }

    } catch (err) {
      this.shadowRoot.innerHTML =
        '<p style="color:red;padding:24px">패널 로드 실패: ' + err.message + '</p>';
    }
  }
});
"""


def _write_panel_js_sync(path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(_PANEL_JS)


async def async_setup_panel(hass: HomeAssistant) -> None:
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
    hass_id = id(hass)
    if hass_id not in _REGISTERED_HASS_IDS:
        return
    hass.components.frontend.async_remove_panel(PANEL_URL)
    _REGISTERED_HASS_IDS.discard(hass_id)

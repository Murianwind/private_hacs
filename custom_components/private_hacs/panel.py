"""Custom panel registration for Private HACS."""
from __future__ import annotations

import logging
import os
import time
import aiohttp  # 자동 다운로드를 위해 필요

from homeassistant.components.frontend import async_remove_panel as frontend_remove_panel
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.panel_custom import async_register_panel
from homeassistant.core import HomeAssistant

from .const import PANEL_ICON, PANEL_TITLE, PANEL_URL

_LOGGER = logging.getLogger(__name__)

_REGISTERED_HASS_IDS: set[int] = set()

# panel.js 내용 (수정 사항 없음)
_PANEL_JS = r"""
if (!customElements.get('private-hacs-panel')) {
  customElements.define('private-hacs-panel', class extends HTMLElement {
    connectedCallback() {
      if (this._initialized) return;
      this._initialized = true;
      this.style.cssText = 'display:block;width:100%;height:100%;overflow:auto;';
      this._loadHTML();
    }
    set hass(hass) {
      this._hass = hass;
      if (!this._tokenSent && hass && hass.auth && hass.auth.data && hass.auth.data.access_token) {
        this._tokenSent = true;
        if (this._resolveToken) this._resolveToken(hass.auth.data.access_token);
      }
    }
    async _loadHTML() {
      try {
        const resp = await fetch('/private_hacs_panel/panel.html?t=' + Date.now());
        if (!resp.ok) throw new Error('panel.html fetch failed');
        const html = await resp.text();
        const self = this;
        window.__privateHacsGetToken = function() {
          return new Promise(function(resolve, reject) {
            if (self._hass && self._hass.auth && self._hass.auth.data && self._hass.auth.data.access_token) {
              resolve(self._hass.auth.data.access_token);
            } else {
              self._resolveToken = resolve;
              setTimeout(() => reject(new Error('timeout')), 5000);
            }
          });
        };
        const styleMatch = html.match(/<style>([\s\S]*?)<\/style>/);
        if (styleMatch) {
          const style = document.createElement('style');
          style.textContent = styleMatch[1];
          this.appendChild(style);
        }
        const bodyMatch = html.match(/<body[^>]*>([\s\S]*?)<\/body>/);
        if (bodyMatch) {
          const div = document.createElement('div');
          div.innerHTML = bodyMatch[1].replace(/<script[\s\S]*?<\/script>/gi, '');
          this.appendChild(div);
        }
        window.__privateHacsPanel = this;
        if (!window.__privateHacsScriptLoaded) {
          window.__privateHacsScriptLoaded = true;
          const scriptRe = /<script[^>]*>([\s\S]*?)<\/script>/gi;
          let m;
          while ((m = scriptRe.exec(html)) !== null) {
            const script = document.createElement('script');
            script.textContent = m[1];
            document.head.appendChild(script);
          }
        } else {
          setTimeout(() => {
            if (typeof connectWS === 'function' && typeof loadData === 'function') {
              connectWS().then(() => loadData());
            }
          }, 150);
        }
      } catch(err) {
        this.innerHTML = '<p style="color:red;padding:24px">로드 실패: ' + err.message + '</p>';
      }
    }
  });
}
"""

async def _async_ensure_marked_js(hass: HomeAssistant, js_dir: str):
    """라이브러리 파일이 없으면 자동으로 다운로드합니다."""
    target = os.path.join(js_dir, "marked.min.js")
    if os.path.exists(target):
        return

    url = "https://cdn.jsdelivr.net/npm/marked/marked.min.js"
    _LOGGER.info("Private HACS: Downloading dependency marked.min.js...")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    def _write():
                        with open(target, "wb") as f:
                            f.write(content)
                    await hass.async_add_executor_job(_write)
                    _LOGGER.info("Private HACS: Successfully downloaded marked.min.js")
                else:
                    _LOGGER.error("Failed to download marked.min.js (Status: %s)", resp.status)
    except Exception as err:
        _LOGGER.error("Error downloading marked.min.js: %s", err)

def _write_panel_js_sync(path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(_PANEL_JS)

async def async_setup_panel(hass: HomeAssistant) -> None:
    hass_id = id(hass)
    if hass_id in _REGISTERED_HASS_IDS:
        return

    panel_dir = os.path.join(os.path.dirname(__file__), "frontend")
    js_dir = os.path.join(panel_dir, "js")
    os.makedirs(js_dir, exist_ok=True)

    # ⭐ 핵심: 라이브러리 자동 다운로드 실행
    await _async_ensure_marked_js(hass, js_dir)

    await hass.async_add_executor_job(
        _write_panel_js_sync, os.path.join(js_dir, "panel.js")
    )

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig("/private_hacs_panel", panel_dir, False),
            StaticPathConfig("/private_hacs_panel/js", js_dir, False),
        ]
    )

    await async_register_panel(
        hass,
        webcomponent_name="private-hacs-panel",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        frontend_url_path=PANEL_URL,
        js_url=f"/private_hacs_panel/js/panel.js?t={int(time.time())}",
        require_admin=True,
    )

    _REGISTERED_HASS_IDS.add(hass_id)

async def async_remove_panel(hass: HomeAssistant) -> None:
    hass_id = id(hass)
    if hass_id not in _REGISTERED_HASS_IDS:
        return
    frontend_remove_panel(hass, PANEL_URL)
    _REGISTERED_HASS_IDS.discard(hass_id)

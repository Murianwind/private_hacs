"""Custom panel registration for Private HACS."""
from __future__ import annotations

import logging
import os
import time
import aiohttp

from homeassistant.components.frontend import async_remove_panel as frontend_remove_panel
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.panel_custom import async_register_panel
from homeassistant.core import HomeAssistant

from .const import PANEL_ICON, PANEL_TITLE, PANEL_URL

_LOGGER = logging.getLogger(__name__)

_REGISTERED_HASS_IDS: set[int] = set()

# 외부 파일(src)도 정상적으로 로드하도록 수정된 panel.js
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
          const scriptRe = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi;
          let m;
          while ((m = scriptRe.exec(html)) !== null) {
            const attrs = m[1];
            const content = m[2];
            const script = document.createElement('script');
            const srcMatch = attrs.match(/src=["']([^"']+)["']/);
            if (srcMatch) {
              script.src = srcMatch[1];
            } else {
              script.textContent = content;
            }
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

    # 라이브러리 자동 다운로드
    await _async_ensure_marked_js(hass, js_dir)

    await hass.async_add_executor_job(
        _write_panel_js_sync, os.path.join(js_dir, "panel.js")
    )

    # 정적 경로 등록
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig("/private_hacs_panel", panel_dir, False),
            StaticPathConfig("/private_hacs_panel/js", js_dir, False),
            # ⭐ 추가: 각 컴포넌트의 brand/icon.png 파일을 불러오기 위한 아이콘 전용 경로
            StaticPathConfig(
                url_path="/private_hacs_icons",
                path=hass.config.path("custom_components"),
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

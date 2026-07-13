"""Custom panel registration for Private HACS."""
from __future__ import annotations

import logging
import os
import time

from homeassistant.components.frontend import async_remove_panel as frontend_remove_panel
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.panel_custom import async_register_panel
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import PANEL_ICON, PANEL_TITLE, PANEL_URL

_LOGGER = logging.getLogger(__name__)

_REGISTERED_HASS_IDS: set[int] = set()

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

async def _async_ensure_marked_js(hass: HomeAssistant, js_dir: str) -> None:
    """라이브러리 파일이 없으면 HA 공용 세션으로 다운로드합니다."""
    target = os.path.join(js_dir, "marked.min.js")
    if await hass.async_add_executor_job(os.path.exists, target):
        return
    url = "https://cdn.jsdelivr.net/npm/marked/marked.min.js"
    _LOGGER.info("Private HACS: Downloading dependency marked.min.js...")
    try:
        session = async_get_clientsession(hass)
        async with session.get(url, timeout=15) as resp:
            if resp.status == 200:
                content = await resp.read()
                def _write() -> None:
                    with open(target, "wb") as f:
                        f.write(content)
                await hass.async_add_executor_job(_write)
                _LOGGER.info("Private HACS: Successfully downloaded marked.min.js")
            else:
                _LOGGER.warning(
                    "Private HACS: Failed to download marked.min.js — HTTP %s", resp.status
                )
    except Exception as err:
        _LOGGER.error("Error downloading marked.min.js: %s", err)


def _write_panel_js_sync(path: str) -> None:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            if f.read() == _PANEL_JS:
                return
    with open(path, "w", encoding="utf-8") as f:
        f.write(_PANEL_JS)


async def async_ensure_frontend_assets(hass: HomeAssistant) -> None:
    """
    frontend/js/panel.js, marked.min.js를 생성/복구합니다.

    Private HACS가 자기 자신(component_id == DOMAIN)을 재설치하면
    download_and_install이 custom_components/private_hacs/ 전체를
    git 저장소 내용으로 덮어씁니다. 이 런타임 생성 파일들은 git
    저장소에 포함되어 있지 않으므로 그 과정에서 함께 삭제됩니다.

    async_setup_panel()의 정적 경로/사이드바 패널 등록은 hass당 1회만
    해야 하지만(_REGISTERED_HASS_IDS로 가드), 이 파일 생성 자체는
    몇 번이든 다시 호출해도 안전하므로 별도 함수로 분리했다.
    services.py의 _do_install이 self-install 직후 이 함수를 호출해,
    HA 재시작 없이도 패널이 즉시 복구되도록 한다.
    """
    panel_dir = os.path.join(os.path.dirname(__file__), "frontend")
    js_dir = os.path.join(panel_dir, "js")
    await hass.async_add_executor_job(os.makedirs, js_dir, 0o777, True)

    await _async_ensure_marked_js(hass, js_dir)

    await hass.async_add_executor_job(
        _write_panel_js_sync, os.path.join(js_dir, "panel.js")
    )


async def async_setup_panel(hass: HomeAssistant) -> None:
    hass_id = id(hass)
    if hass_id in _REGISTERED_HASS_IDS:
        return

    panel_dir = os.path.join(os.path.dirname(__file__), "frontend")
    js_dir = os.path.join(panel_dir, "js")

    await async_ensure_frontend_assets(hass)

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig("/private_hacs_panel", panel_dir, False),
            StaticPathConfig("/private_hacs_panel/js", js_dir, False),
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

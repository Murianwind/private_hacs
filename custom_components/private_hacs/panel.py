"""Custom panel registration for Private HACS."""
from __future__ import annotations

import logging
import os
import time

from homeassistant.components.frontend import async_remove_panel as frontend_remove_panel
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.panel_custom import async_register_panel
from homeassistant.core import HomeAssistant

from .const import PANEL_ICON, PANEL_TITLE, PANEL_URL

_LOGGER = logging.getLogger(__name__)

_REGISTERED_HASS_IDS: set[int] = set()

# panel.html을 fetch로 로드 — HTML을 JS에 직접 삽입하지 않으므로 이스케이프 문제 없음
_PANEL_JS = """\
// ⭐ 수정 1: 이미 태그가 등록되어 있는지 확인하여 중복 등록 오류(Error 2) 방지
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
        if (!resp.ok) throw new Error('panel.html fetch failed: ' + resp.status);
        const html = await resp.text();

        // _getToken을 window에 노출
        const self = this;
        window.__privateHacsGetToken = function() {
          return new Promise(function(resolve, reject) {
            if (self._hass && self._hass.auth && self._hass.auth.data && self._hass.auth.data.access_token) {
              resolve(self._hass.auth.data.access_token);
            } else {
              self._resolveToken = resolve;
              setTimeout(function() {
                reject(new Error('hass 토큰 수신 시간 초과'));
              }, 5000);
            }
          });
        };

        // style 추출 후 삽입
        const styleMatch = html.match(/<style>([\\s\\S]*?)<\\/style>/);
        if (styleMatch) {
          const style = document.createElement('style');
          style.textContent = styleMatch[1];
          this.appendChild(style);
        }

        // body 내용 삽입
        const bodyMatch = html.match(/<body[^>]*>([\\s\\S]*?)<\\/body>/);
        if (bodyMatch) {
          const div = document.createElement('div');
          div.innerHTML = bodyMatch[1].replace(/<script[\\s\\S]*?<\\/script>/gi, '');
          this.appendChild(div);
        }

        // 패널을 전역으로 노출 (Shadow DOM 탐색용)
        window.__privateHacsPanel = this;

        // ⭐ 수정 2: 스크립트 중복 주입 방지 (Identifier already declared 오류 방지)
        if (!window.__privateHacsScriptLoaded) {
          window.__privateHacsScriptLoaded = true;
          const scriptRe = /<script[^>]*>([\\s\\S]*?)<\\/script>/gi;
          let m;
          while ((m = scriptRe.exec(html)) !== null) {
            const script = document.createElement('script');
            script.textContent = m[1];
            document.head.appendChild(script);
          }
        } else {
          // 이미 스크립트가 메모리에 로드되어 있다면, 새로 만들어진 DOM에 데이터를 채우기 위해 초기화 함수만 다시 호출합니다.
          setTimeout(() => {
            if (typeof connectWS === 'function' && typeof loadData === 'function') {
              connectWS().then(() => loadData()).catch(e => console.warn('HACS Panel Reload:', e));
            }
          }, 150);
        }

      } catch(err) {
        this.innerHTML = '<p style="color:red;padding:24px">패널 로드 실패: ' + err.message + '</p>';
      }
    }
  });
}
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
        js_url=f"/private_hacs_panel/js/panel.js?t={int(time.time())}",
        require_admin=True,
    )

    _REGISTERED_HASS_IDS.add(hass_id)
    _LOGGER.info("Private HACS panel registered at /%s", PANEL_URL)


async def async_remove_panel(hass: HomeAssistant) -> None:
    hass_id = id(hass)
    if hass_id not in _REGISTERED_HASS_IDS:
        return
    frontend_remove_panel(hass, PANEL_URL)
    _REGISTERED_HASS_IDS.discard(hass_id)

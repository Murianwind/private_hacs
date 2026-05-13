"""Custom panel registration for Private HACS."""
from __future__ import annotations

import logging
import os
import time  # 추가: 캐시 방지를 위해 시간 모듈 임포트

from homeassistant.components.frontend import async_remove_panel as frontend_remove_panel
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.panel_custom import async_register_panel
from homeassistant.core import HomeAssistant

from .const import PANEL_ICON, PANEL_TITLE, PANEL_URL

_LOGGER = logging.getLogger(__name__)

_REGISTERED_HASS_IDS: set[int] = set()

# panel.html을 fetch로 로드 — HTML을 JS에 직접 삽입하지 않으므로 이스케이프 문제 없음
_PANEL_JS = """\
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
      // 수정: 캐시를 무시하고 항상 최신 html 파일을 가져오도록 Date.now() 파라미터 추가
      const resp = await fetch('/private_hacs_panel/panel.html?t=' + Date.now());
      if (!resp.ok) throw new Error('panel.html fetch failed: ' + resp.status);
      const html = await resp.text();

      // _getToken을 window에 노출 (script가 window 컨텍스트에서 실행됨)
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

      // body 내용 삽입 (script 태그 제외)
      const bodyMatch = html.match(/<body[^>]*>([\\s\\S]*?)<\\/body>/);
      if (bodyMatch) {
        const div = document.createElement('div');
        div.innerHTML = bodyMatch[1].replace(/<script[\\s\\S]*?<\\/script>/gi, '');
        this.appendChild(div);
      }

      // 수정: panel.html의 스크립트가 Shadow DOM 내의 요소를 찾을 수 있도록 패널을 전역으로 노출
      window.__privateHacsPanel = this;

      // script 태그를 추출해서 document.head에 추가 (window 컨텍스트 실행)
      const scriptRe = /<script[^>]*>([\\s\\S]*?)<\\/script>/gi;
      let m;
      while ((m = scriptRe.exec(html)) !== null) {
        const script = document.createElement('script');
        script.textContent = m[1];
        document.head.appendChild(script);
      }

    } catch(err) {
      this.innerHTML = '<p style="color:red;padding:24px">패널 로드 실패: ' + err.message + '</p>';
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
        # 수정: HA 시작 시마다 js URL을 새롭게 생성하여 브라우저의 강제 캐시를 무력화
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

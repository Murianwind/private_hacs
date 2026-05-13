"""Config flow for Private HACS."""
from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_GITHUB_TOKEN, CONF_REPOS, DOMAIN
from .github import GitHubClient

_LOGGER = logging.getLogger(__name__)

EXAMPLE_REPOS = json.dumps(
    [
        {
            "repo": "your-org/your-private-integration",
            "name": "My Private Integration",
            "component_id": "my_private_integration",
            "branch": "main",
        }
    ],
    indent=2,
    ensure_ascii=False,
)


def _parse_repos(raw: str) -> list[dict] | None:
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            return None
        for item in data:
            if not all(k in item for k in ("repo", "name", "component_id")):
                return None
        return data
    except (json.JSONDecodeError, TypeError):
        return None


class PrivateHacsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            token = user_input.get(CONF_GITHUB_TOKEN, "").strip()
            repos_raw: str = user_input.get(CONF_REPOS, "")

            repos = _parse_repos(repos_raw)
            if repos is None:
                errors[CONF_REPOS] = "invalid_repos_json"
            else:
                if token:
                    client = GitHubClient(token)
                    if not await client.validate_token():
                        errors[CONF_GITHUB_TOKEN] = "invalid_token"

                if not errors:
                    # Ensure only one instance
                    await self.async_set_unique_id(DOMAIN)
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title="Private HACS",
                        data={
                            CONF_GITHUB_TOKEN: token or None,
                            CONF_REPOS: repos,
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_GITHUB_TOKEN, default=""): str,
                    vol.Required(CONF_REPOS, default=EXAMPLE_REPOS): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return PrivateHacsOptionsFlow(config_entry)


class PrivateHacsOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        current_token = self._entry.data.get(CONF_GITHUB_TOKEN) or ""
        current_repos = self._entry.data.get(CONF_REPOS, [])

        if user_input is not None:
            token = user_input.get(CONF_GITHUB_TOKEN, "").strip()
            repos_raw: str = user_input.get(CONF_REPOS, "")

            repos = _parse_repos(repos_raw)
            if repos is None:
                errors[CONF_REPOS] = "invalid_repos_json"
            else:
                if token:
                    client = GitHubClient(token)
                    if not await client.validate_token():
                        errors[CONF_GITHUB_TOKEN] = "invalid_token"

                if not errors:
                    self.hass.config_entries.async_update_entry(
                        self._entry,
                        data={
                            **self._entry.data,
                            CONF_GITHUB_TOKEN: token or None,
                            CONF_REPOS: repos,
                        },
                    )
                    return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_GITHUB_TOKEN, default=current_token): str,
                    vol.Required(
                        CONF_REPOS,
                        default=json.dumps(current_repos, indent=2, ensure_ascii=False),
                    ): str,
                }
            ),
            errors=errors,
        )

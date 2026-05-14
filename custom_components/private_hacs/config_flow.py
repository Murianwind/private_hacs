"""Config flow for Private HACS."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_GITHUB_TOKEN, CONF_REPOS, DOMAIN
from .github import GitHubClient

_LOGGER = logging.getLogger(__name__)


class PrivateHacsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            token = user_input.get(CONF_GITHUB_TOKEN, "").strip()

            if token:
                session = async_get_clientsession(self.hass)
                client = GitHubClient(token=token, session=session)
                if not await client.validate_token():
                    errors[CONF_GITHUB_TOKEN] = "invalid_token"

            if not errors:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Private HACS",
                    data={
                        CONF_GITHUB_TOKEN: token or None,
                        CONF_REPOS: [],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Optional(CONF_GITHUB_TOKEN, default=""): str}
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

        if user_input is not None:
            token = user_input.get(CONF_GITHUB_TOKEN, "").strip()

            if token:
                session = async_get_clientsession(self.hass)
                client = GitHubClient(token=token, session=session)
                if not await client.validate_token():
                    errors[CONF_GITHUB_TOKEN] = "invalid_token"

            if not errors:
                self.hass.config_entries.async_update_entry(
                    self._entry,
                    data={**self._entry.data, CONF_GITHUB_TOKEN: token or None},
                )
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Optional(CONF_GITHUB_TOKEN, default=current_token): str}
            ),
            errors=errors,
        )

"""Config flow for JBL MA AVR integration."""
from __future__ import annotations

import asyncio
import socket
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant

from .const import CONF_SCAN_INTERVAL, DEFAULT_PORT, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

MODEL_MAP = {0x01: "MA510", 0x02: "MA710", 0x03: "MA7100HP", 0x04: "MA9100HP"}


async def _async_probe_device(host: str, port: int) -> dict:
    """Try to connect and run init handshake. Returns model info or raises."""
    loop = asyncio.get_running_loop()

    def _probe():
        s = socket.create_connection((host, port), timeout=5)
        s.settimeout(3)
        # Send init request: 23 50 01 f0 0d
        s.sendall(bytes([0x23, 0x50, 0x01, 0xF0, 0x0D]))
        import time
        time.sleep(0.3)
        resp = s.recv(256)
        s.close()
        return resp

    try:
        resp = await loop.run_in_executor(None, _probe)
    except Exception as err:
        raise ConnectionError(f"Cannot connect to {host}:{port}: {err}") from err

    # Parse response: 02 23 50 00 01 <model_code> 0d
    if len(resp) < 7 or resp[0] != 0x02 or resp[1] != 0x23 or resp[2] != 0x50:
        raise ConnectionError(f"Unexpected init response: {resp.hex()}")
    if resp[3] != 0x00:
        raise ConnectionError(f"Init failed, response code: 0x{resp[3]:02x}")

    model_code = resp[5]
    model_name = MODEL_MAP.get(model_code, f"Unknown (0x{model_code:02x})")
    return {"model_code": model_code, "model_name": model_name}


class JBLMAConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for JBL MA AVR."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        model_info: dict = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input.get(CONF_PORT, DEFAULT_PORT))
            name = user_input.get(CONF_NAME, "Theater JBL AV").strip()

            # Prevent duplicate entries for same host+port
            await self.async_set_unique_id(f"{host}_{port}")
            self._abort_if_unique_id_configured()

            try:
                model_info = await _async_probe_device(host, port)
            except ConnectionError as err:
                _LOGGER.warning("JBL MA probe failed: %s", err)
                errors["base"] = "cannot_connect"
            except Exception as err:
                _LOGGER.exception("Unexpected error probing JBL MA: %s", err)
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"{name} ({model_info['model_name']})",
                    data={
                        CONF_HOST: host,
                        CONF_NAME: name,
                        CONF_PORT: port,
                        CONF_SCAN_INTERVAL: int(user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default="192.168.1.134"): str,
                vol.Optional(CONF_NAME, default="Theater JBL AV"): str,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"model": model_info.get("model_name", "")},
        )

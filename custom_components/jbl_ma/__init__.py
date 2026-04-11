from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant

from .const import CONF_PORT, CONF_SCAN_INTERVAL, CONF_SOURCES, DEFAULT_PORT, DEFAULT_SCAN_INTERVAL, DEFAULT_SOURCES, DOMAIN

PLATFORMS: list[str] = ["media_player"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up jbl_ma from YAML configuration."""
    entries = config.get(DOMAIN, [])
    if isinstance(entries, dict):
        entries = [entries]
    hass.data.setdefault(DOMAIN, {})["yaml"] = []
    for item in entries:
        hass.data[DOMAIN]["yaml"].append(
            {
                CONF_HOST: item[CONF_HOST],
                CONF_NAME: item.get(CONF_NAME, "Theater JBL AV"),
                CONF_PORT: item.get(CONF_PORT, DEFAULT_PORT),
                CONF_SCAN_INTERVAL: item.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                CONF_SOURCES: item.get(CONF_SOURCES, DEFAULT_SOURCES),
            }
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up jbl_ma from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = dict(entry.data)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok

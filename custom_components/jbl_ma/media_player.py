from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta

import voluptuous as vol

from homeassistant.components.media_player import MediaPlayerEntity, PLATFORM_SCHEMA
from homeassistant.components.media_player.const import MediaPlayerEntityFeature, MediaPlayerState
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SOURCES,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SOURCES,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_NAME, default="Theater JBL AV"): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.Any(cv.time_period, vol.Coerce(int)),
        vol.Optional(CONF_SOURCES, default=DEFAULT_SOURCES): vol.All(cv.ensure_list, [cv.string]),
    }
)

START = 0x23
RESPONSE_PREFIX = (0x02, 0x23)
END = 0x0D
CMD_INIT = 0x50
CMD_POWER = 0x00
CMD_VERSION = 0x02
CMD_SOURCE = 0x05
CMD_VOLUME = 0x06
CMD_MUTE = 0x07
CMD_IR_SIMULATE = 0x04
REQ = 0xF0
MODEL_MA7100HP = 0x03
IR_POWER_ON = bytes([0x01, 0x0E, 0xD9])
IR_POWER_OFF = bytes([0x01, 0x0E, 0xF9])
IR_VOL_UP = bytes([0x01, 0x0E, 0xC9])
IR_VOL_DOWN = bytes([0x01, 0x0E, 0xE3])
IR_MUTE_TOGGLE = bytes([0x01, 0x0E, 0x74])

SOURCE_MAP = {
    "TV": 0x00,
    "HDMI1": 0x01,
    "HDMI2": 0x02,
    "HDMI3": 0x03,
    "HDMI4": 0x04,
    "HDMI5": 0x05,
    "HDMI6": 0x06,
    "Coax": 0x08,
    "Optical": 0x09,
    "Analog1": 0x0A,
    "Analog2": 0x0B,
    "Phono": 0x0C,
    "Bluetooth": 0x0D,
    "Network": 0x0E,
}
DEFAULT_SOURCES_ALL = list(SOURCE_MAP.keys())
REVERSE_SOURCE_MAP = {value: key for key, value in SOURCE_MAP.items()}


@dataclass
class JBLMAStatus:
    raw: bytes | None = None
    is_on: bool | None = None
    muted: bool | None = None
    volume_level: float | None = None
    source: str | None = None
    initialized: bool = False
    protocol_validated: bool = False
    ip_control_version: str | None = None
    model_code: int | None = None


class JBLMAProtocolError(Exception):
    pass


class JBLMAClient:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._validated = False
        self._lock = asyncio.Lock()
        self._model_code: int | None = None
        self._ip_control_version: str | None = None

    def _build_packet(self, cmd_id: int, data: bytes = b"") -> bytes:
        return bytes([START, cmd_id, len(data), *data, END])

    async def _open(self):
        return await asyncio.open_connection(self.host, self.port)

    def _split_frames(self, raw: bytes) -> list[bytes]:
        frames: list[bytes] = []
        idx = 0
        while idx < len(raw):
            if raw[idx] != RESPONSE_PREFIX[0] or idx + 1 >= len(raw) or raw[idx + 1] != RESPONSE_PREFIX[1]:
                raise JBLMAProtocolError(f"invalid response prefix: {raw.hex()}")
            if idx + 6 > len(raw):
                raise JBLMAProtocolError(f"short response frame: {raw.hex()}")
            data_len = raw[idx + 4]
            frame_len = 6 + data_len
            frame = raw[idx : idx + frame_len]
            if len(frame) != frame_len:
                raise JBLMAProtocolError(f"truncated response frame: {raw.hex()}")
            if frame[-1] != END:
                raise JBLMAProtocolError(f"invalid response terminator: {frame.hex()}")
            frames.append(frame)
            idx += frame_len
        return frames

    def _parse_frame(self, frame: bytes) -> tuple[int, int, bytes]:
        cmd_id = frame[2]
        rsp_code = frame[3]
        data_len = frame[4]
        data = frame[5 : 5 + data_len]
        if rsp_code != 0x00:
            raise JBLMAProtocolError(f"device returned error rsp=0x{rsp_code:02x} for cmd=0x{cmd_id:02x}")
        return cmd_id, rsp_code, data

    async def _exchange(self, cmd_id: int, data: bytes = b"") -> list[tuple[int, int, bytes]]:
        payload = self._build_packet(cmd_id, data)
        reader, writer = await self._open()
        try:
            writer.write(payload)
            await writer.drain()
            raw = await asyncio.wait_for(reader.read(256), timeout=3)
        finally:
            writer.close()
            await writer.wait_closed()
        if not raw:
            raise JBLMAProtocolError(f"empty response for cmd=0x{cmd_id:02x}")
        frames = self._split_frames(raw)
        parsed = [self._parse_frame(frame) for frame in frames]
        if parsed[0][0] != cmd_id:
            raise JBLMAProtocolError(
                f"command id mismatch, sent 0x{cmd_id:02x}, got 0x{parsed[0][0]:02x} raw={raw.hex()}"
            )
        return parsed

    async def async_validate_protocol(self) -> None:
        async with self._lock:
            if self._validated:
                return
            responses = await self._exchange(CMD_INIT, bytes([REQ]))
            _, _, data = responses[0]
            if not data:
                raise JBLMAProtocolError("initialization handshake returned empty payload")
            self._model_code = data[0]
            if self._model_code != MODEL_MA7100HP:
                _LOGGER.warning("JBL MA init returned model code 0x%02x", self._model_code)
            version_rsp = await self._exchange(CMD_VERSION, bytes([REQ]))
            version_data = version_rsp[0][2]
            if len(version_data) >= 2 and version_data[0] == REQ:
                self._ip_control_version = version_data[1:].decode("ascii", errors="ignore")
            self._validated = True

    async def async_get_status(self) -> JBLMAStatus:
        await self.async_validate_protocol()
        power = await self._exchange(CMD_POWER, bytes([REQ]))
        power_data = power[0][2]
        is_on = None
        if power_data:
            if power_data[0] == 0x00:
                is_on = False
            elif power_data[0] == 0x01:
                is_on = True

        muted = None
        volume_level = None
        source = None
        raw_parts = []
        for rsp in [power]:
            d = rsp[0][2]
            raw_parts.append(bytes([0x02, 0x23, rsp[0][0], rsp[0][1], len(d), *d, 0x0D]))

        try:
            mute_rsp = await self._exchange(CMD_MUTE, bytes([REQ]))
            mute_data = mute_rsp[0][2]
            raw_parts.append(bytes([0x02, 0x23, mute_rsp[0][0], mute_rsp[0][1], len(mute_data), *mute_data, 0x0D]))
            if mute_data:
                muted = mute_data[0] == 0x01
        except Exception as err:
            _LOGGER.debug("mute status read failed: %s", err)

        try:
            vol_rsp = await self._exchange(CMD_VOLUME, bytes([REQ]))
            vol_data = vol_rsp[0][2]
            raw_parts.append(bytes([0x02, 0x23, vol_rsp[0][0], vol_rsp[0][1], len(vol_data), *vol_data, 0x0D]))
            if vol_data:
                volume_level = max(0.0, min(1.0, vol_data[0] / 99.0))
        except Exception as err:
            _LOGGER.debug("volume status read failed: %s", err)

        try:
            src_rsp = await self._exchange(CMD_SOURCE, bytes([REQ]))
            src_data = src_rsp[0][2]
            raw_parts.append(bytes([0x02, 0x23, src_rsp[0][0], src_rsp[0][1], len(src_data), *src_data, 0x0D]))
            if src_data:
                source = REVERSE_SOURCE_MAP.get(src_data[0], f"unknown_0x{src_data[0]:02x}")
        except Exception as err:
            _LOGGER.debug("source status read failed: %s", err)

        return JBLMAStatus(
            raw=b"".join(raw_parts),
            is_on=is_on,
            muted=muted,
            volume_level=volume_level,
            source=source,
            initialized=True,
            protocol_validated=self._validated,
            ip_control_version=self._ip_control_version,
            model_code=self._model_code,
        )

    async def async_send_command(self, cmd_id: int, data: bytes = b"") -> None:
        await self.async_validate_protocol()
        await self._exchange(cmd_id, data)


async def async_setup_platform(hass: HomeAssistant, config, async_add_entities: AddEntitiesCallback, discovery_info=None) -> None:
    try:
        async_add_entities([await _build_entity(hass, dict(config))])
    except Exception as err:
        _LOGGER.error("JBL MA platform setup failed: %s", err, exc_info=True)
        raise


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    data = dict(entry.data)
    async_add_entities([await _build_entity(hass, data)])


async def _build_entity(hass: HomeAssistant, data: dict):
    host = data[CONF_HOST]
    port = data.get(CONF_PORT, DEFAULT_PORT)
    name = data.get(CONF_NAME, "Theater JBL AV")
    _si = data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    scan_interval = int(_si.total_seconds()) if hasattr(_si, "total_seconds") else int(_si)
    sources = data.get(CONF_SOURCES, DEFAULT_SOURCES)
    client = JBLMAClient(host, port)

    async def _async_update() -> JBLMAStatus:
        try:
            return await client.async_get_status()
        except Exception as err:
            raise UpdateFailed(f"JBL MA update failed: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"jbl_ma_{host}",
        update_method=_async_update,
        update_interval=timedelta(seconds=scan_interval),
    )
    try:
        await coordinator.async_refresh()
    except Exception as err:
        _LOGGER.warning("JBL MA initial refresh failed (will retry): %s", err)
    return JBLMAMediaPlayer(coordinator, client, name, host, port, sources)


class JBLMAMediaPlayer(CoordinatorEntity, MediaPlayerEntity):
    _attr_should_poll = False
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    def __init__(self, coordinator: DataUpdateCoordinator, client: JBLMAClient, name: str, host: str, port: int, sources: list[str]) -> None:
        super().__init__(coordinator)
        self._client = client
        self._attr_name = name
        self._attr_unique_id = f"jbl_ma_{host}_{port}"
        self._attr_source_list = sources
        self._host = host
        self._port = port
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{host}_{port}")},
            name=name,
            manufacturer="JBL / Harman International",
            model="MA7100HP",
            sw_version=None,
        )

    @property
    def state(self):
        status = self.coordinator.data
        if status.ip_control_version and self._attr_device_info:
            self._attr_device_info["sw_version"] = status.ip_control_version
        if status.is_on is True:
            return MediaPlayerState.ON
        if status.is_on is False:
            return MediaPlayerState.OFF
        return None

    @property
    def source(self):
        return getattr(self.coordinator.data, "source", None)

    @property
    def is_volume_muted(self):
        return getattr(self.coordinator.data, "muted", None)

    @property
    def volume_level(self):
        return getattr(self.coordinator.data, "volume_level", None)

    @property
    def extra_state_attributes(self):
        status = self.coordinator.data
        return {
            "jbl_raw": status.raw.hex() if status.raw else None,
            "protocol_validated": status.protocol_validated,
            "ip_control_version": status.ip_control_version,
            "model": "MA7100HP" if status.model_code == 0x03 else f"unknown_0x{status.model_code:02x}" if status.model_code else None,
            "host": self._host,
            "port": self._port,
        }

    async def async_turn_on(self) -> None:
        await self._client.async_send_command(CMD_POWER, b"\x01")
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        await self._client.async_send_command(CMD_POWER, b"\x00")
        await self.coordinator.async_request_refresh()

    async def async_volume_up(self) -> None:
        current = self.coordinator.data.volume_level
        if current is None:
            return
        new_vol = min(99, int(current * 99) + 3)
        await self._client.async_send_command(CMD_VOLUME, bytes([new_vol]))
        await self.coordinator.async_request_refresh()

    async def async_volume_down(self) -> None:
        current = self.coordinator.data.volume_level
        if current is None:
            return
        new_vol = max(0, int(current * 99) - 3)
        await self._client.async_send_command(CMD_VOLUME, bytes([new_vol]))
        await self.coordinator.async_request_refresh()

    async def async_set_volume_level(self, volume: float) -> None:
        raw_vol = max(0, min(99, int(volume * 99)))
        await self._client.async_send_command(CMD_VOLUME, bytes([raw_vol]))
        await self.coordinator.async_request_refresh()

    async def async_mute_volume(self, mute: bool) -> None:
        current = getattr(self.coordinator.data, "muted", None)
        if current is not None and current == mute:
            return
        await self._client.async_send_command(CMD_MUTE, b"\x01" if mute else b"\x00")
        await self.coordinator.async_request_refresh()

    async def async_select_source(self, source: str) -> None:
        source_code = SOURCE_MAP.get(source)
        if source_code is None:
            raise ValueError(f"unsupported JBL MA source: {source}")
        await self._client.async_send_command(CMD_SOURCE, bytes([source_code]))
        await self.coordinator.async_request_refresh()

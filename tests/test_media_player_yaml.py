"""YAML-platform tests for custom_components/jbl_ma/media_player.py.

Stdlib only: Home Assistant and voluptuous are stubbed, and the coordinator stub never
calls the update method, so no test opens a socket to the amp.

Run: python3 -m unittest discover -s tests -v
Point at another copy of the integration with JBL_MA_DIR=<path to jbl_ma dir>.
"""
from __future__ import annotations

import asyncio
import enum
import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path

JBL_MA_DIR = Path(
    os.environ.get("JBL_MA_DIR", Path(__file__).resolve().parents[1] / "custom_components" / "jbl_ma")
)


def _mod(name: str, **attrs) -> types.ModuleType:
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


def _install_stubs() -> None:
    ident = lambda *a, **k: (a[0] if a else None)  # noqa: E731
    _mod("voluptuous", Required=ident, Optional=ident, Any=ident, Coerce=ident, All=ident)

    class _Schema(dict):
        def extend(self, other):
            return _Schema({**self, **other})

    class Entity:
        _attr_device_info = None  # HA's Entity default

    class MediaPlayerEntity(Entity):
        pass

    class MediaPlayerEntityFeature(enum.IntFlag):
        TURN_ON = 1
        TURN_OFF = 2
        VOLUME_SET = 4
        VOLUME_STEP = 8
        VOLUME_MUTE = 16
        SELECT_SOURCE = 32

    class MediaPlayerState(str, enum.Enum):
        ON = "on"
        OFF = "off"

    class CoordinatorEntity:
        def __init__(self, coordinator):
            self.coordinator = coordinator

    class DataUpdateCoordinator:
        def __init__(self, hass, logger, name, update_method, update_interval):
            self.data = None  # amp not reached: first refresh produced no data
            self.update_method = update_method  # tests drive polls by hand
            self.last_update_success = False

        async def async_refresh(self):
            return None

    _mod("homeassistant")
    _mod("homeassistant.components")
    _mod("homeassistant.components.media_player", MediaPlayerEntity=MediaPlayerEntity, PLATFORM_SCHEMA=_Schema())
    _mod(
        "homeassistant.components.media_player.const",
        MediaPlayerEntityFeature=MediaPlayerEntityFeature,
        MediaPlayerState=MediaPlayerState,
    )
    _mod("homeassistant.const", CONF_HOST="host", CONF_NAME="name")
    _mod("homeassistant.core", HomeAssistant=object)
    _mod("homeassistant.config_entries", ConfigEntry=object)
    _mod("homeassistant.helpers")
    _mod(
        "homeassistant.helpers.config_validation",
        string=str, port=int, time_period=ident, ensure_list=ident,
    )
    _mod("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
    _mod("homeassistant.helpers.device_registry", DeviceInfo=dict)
    _mod(
        "homeassistant.helpers.update_coordinator",
        CoordinatorEntity=CoordinatorEntity,
        DataUpdateCoordinator=DataUpdateCoordinator,
        UpdateFailed=Exception,
    )


def _load_media_player():
    _install_stubs()
    pkg = "jbl_ma_under_test"
    for name in [n for n in sys.modules if n == pkg or n.startswith(pkg + ".")]:
        del sys.modules[name]
    pkg_mod = types.ModuleType(pkg)
    pkg_mod.__path__ = [str(JBL_MA_DIR)]
    sys.modules[pkg] = pkg_mod
    for sub in ("const", "media_player"):
        spec = importlib.util.spec_from_file_location(f"{pkg}.{sub}", JBL_MA_DIR / f"{sub}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"{pkg}.{sub}"] = mod
        spec.loader.exec_module(mod)
    return sys.modules[f"{pkg}.media_player"]


YAML_CONFIG = {"platform": "jbl_ma", "host": "192.168.1.134", "port": 50000}


def _yaml_entity():
    mp = _load_media_player()
    added = []
    asyncio.run(mp.async_setup_platform(object(), dict(YAML_CONFIG), added.extend))
    assert len(added) == 1, added
    return mp, added[0]


class YamlPlatformTests(unittest.TestCase):
    def test_yaml_entity_has_no_device_info(self):
        _, ent = _yaml_entity()
        self.assertIsNone(getattr(ent, "_attr_device_info", None))

    def test_yaml_entity_unique_id_unchanged(self):
        _, ent = _yaml_entity()
        self.assertEqual(ent._attr_unique_id, "jbl_ma_192.168.1.134_50000")

    def test_state_is_none_while_coordinator_has_no_data(self):
        _, ent = _yaml_entity()
        self.assertIsNone(ent.coordinator.data)
        self.assertIsNone(ent.state)

    def test_state_with_version_does_not_create_device_info(self):
        mp, ent = _yaml_entity()
        ent.coordinator.data = mp.JBLMAStatus(is_on=True, ip_control_version="1.5")
        self.assertEqual(ent.state, "on")
        self.assertIsNone(getattr(ent, "_attr_device_info", None))


class _FakeClient:
    """Stands in for JBLMAClient: async_get_status returns or raises what the test queues."""

    results: list = []

    def __init__(self, host, port):
        pass

    async def async_get_status(self):
        r = _FakeClient.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class StaleGraceTests(unittest.TestCase):
    """A ~25 s Ethernet link bounce (switch port 9 link down/up) must not make the entity unavailable."""

    def setUp(self):
        self.mp = _load_media_player()
        self.mp.JBLMAClient = _FakeClient
        self.clock = [1000.0]
        self.mp._now = lambda: self.clock[0]
        added = []
        asyncio.run(self.mp.async_setup_platform(object(), dict(YAML_CONFIG), added.extend))
        self.poll = added[0].coordinator.update_method

    def test_one_missed_poll_keeps_last_state(self):
        good = self.mp.JBLMAStatus(is_on=True, source="HDMI2")
        _FakeClient.results = [good, asyncio.TimeoutError()]
        self.assertIs(asyncio.run(self.poll()), good)
        self.clock[0] += 35  # next poll lands inside the bounce
        self.assertIs(asyncio.run(self.poll()), good)

    def test_two_missed_polls_still_inside_grace(self):
        good = self.mp.JBLMAStatus(is_on=True)
        _FakeClient.results = [good, OSError("no route"), OSError("no route")]
        asyncio.run(self.poll())
        self.clock[0] += 35
        asyncio.run(self.poll())
        self.clock[0] += 31  # 66 s since the last good poll
        self.assertIs(asyncio.run(self.poll()), good)

    def test_outage_longer_than_grace_goes_unavailable(self):
        good = self.mp.JBLMAStatus(is_on=True)
        _FakeClient.results = [good, asyncio.TimeoutError()]
        asyncio.run(self.poll())
        self.clock[0] += self.mp.STALE_GRACE_SECONDS + 1
        with self.assertRaises(Exception) as cm:
            asyncio.run(self.poll())
        self.assertIn("TimeoutError", str(cm.exception))

    def test_failure_with_no_good_poll_yet_raises(self):
        _FakeClient.results = [asyncio.TimeoutError()]
        with self.assertRaises(Exception):
            asyncio.run(self.poll())


class CommandRetryTests(unittest.TestCase):
    def setUp(self):
        self.mp = _load_media_player()
        self.calls = 0
        self._real = (asyncio.open_connection, asyncio.sleep)

        async def fake_open(host, port):
            self.calls += 1
            if self.calls <= self.fail_first:
                raise OSError("Host is down")
            return ("reader", "writer")

        async def no_sleep(_s):
            return None

        asyncio.open_connection = fake_open
        asyncio.sleep = no_sleep

    def tearDown(self):
        asyncio.open_connection, asyncio.sleep = self._real

    def test_open_retries_through_a_bounce(self):
        self.fail_first = 2
        c = self.mp.JBLMAClient("192.168.1.134", 50000)
        self.assertEqual(asyncio.run(c._open(self.mp.COMMAND_CONNECT_ATTEMPTS)), ("reader", "writer"))
        self.assertEqual(self.calls, 3)

    def test_poll_open_does_not_retry(self):
        self.fail_first = 1
        c = self.mp.JBLMAClient("192.168.1.134", 50000)
        with self.assertRaises(OSError):
            asyncio.run(c._open())
        self.assertEqual(self.calls, 1)

    def test_send_command_uses_command_attempts(self):
        c = self.mp.JBLMAClient("192.168.1.134", 50000)
        c._validated = True
        seen = []

        async def fake_exchange(cmd_id, data=b"", attempts=1):
            seen.append(attempts)
            return []

        c._exchange = fake_exchange
        asyncio.run(c.async_send_command(self.mp.CMD_POWER, b"\x01"))
        self.assertEqual(seen, [self.mp.COMMAND_CONNECT_ATTEMPTS])


if __name__ == "__main__":
    unittest.main()

# JBL MA AVR — Home Assistant Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/HA-2024.1%2B-blue.svg)](https://www.home-assistant.io/)

Custom Home Assistant integration for **JBL MA Series AV receivers** (MA510, MA710, MA7100HP, MA9100HP) using the JBL IP Control protocol over TCP.

No cloud. No DLNA. Direct binary protocol control over your local network.

## Features

- **Power** on/off
- **Volume** set (absolute 0–99), step up/down, mute toggle
- **Source selection** across all inputs: TV, HDMI1–6, Coax, Optical, Analog1–2, Phono, Bluetooth, Network
- **Config flow** — add via the HA UI (Settings → Devices → Add Integration)
- **YAML configuration** also supported
- **Protocol validation** on startup (init handshake + model detection)
- **Polling** with configurable interval (default 30s)
- **Extra attributes**: raw protocol hex, IP control version, model, protocol validation status

## Supported Models

| Model | Code | Status |
|---|---|---|
| MA510 | `0x01` | Should work (untested) |
| MA710 | `0x02` | Should work (untested) |
| **MA7100HP** | `0x03` | ✅ Fully tested |
| MA9100HP | `0x04` | Should work (untested) |

The JBL MA series all share the same IP Control protocol (v1.5). This integration should work with any model in the series, but has been fully validated on the MA7100HP.

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu → **Custom repositories**
3. Add `https://github.com/ANG-Ventures/ha-jbl-ma` with category **Integration**
4. Search for "JBL MA AVR" and install
5. Restart Home Assistant
6. Go to **Settings → Devices & Services → Add Integration → JBL MA AVR**

### Manual

1. Copy the `custom_components/jbl_ma` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant
3. Go to **Settings → Devices & Services → Add Integration → JBL MA AVR**

## Configuration

### UI (Config Flow)

The integration will prompt for:
- **Host**: IP address of your JBL receiver (e.g., `192.168.1.134`)
- **Name**: Display name (default: "Theater JBL AV")
- **Port**: TCP port (default: `50000`)
- **Polling interval**: How often to query state, in seconds (default: `30`)

The config flow probes the device on submission and verifies it responds to the JBL IP Control init handshake.

### YAML

```yaml
media_player:
  - platform: jbl_ma
    host: 192.168.1.134
    name: Theater JBL AV
    port: 50000
    scan_interval: 30
    sources:
      - TV
      - HDMI1
      - HDMI2
      - HDMI3
      - HDMI4
      - Network
      - Bluetooth
```

## Entity

Creates a `media_player` entity with:

| Attribute | Description |
|---|---|
| `state` | `on` / `off` |
| `source` | Current input (e.g., `HDMI2`, `Network`, `Bluetooth`) |
| `source_list` | All configured sources |
| `volume_level` | 0.0–1.0 (maps to 0–99 on the receiver) |
| `is_volume_muted` | `true` / `false` |
| `jbl_raw` | Raw hex of last protocol response (for debugging) |
| `protocol_validated` | `true` if init handshake succeeded |
| `ip_control_version` | Firmware IP control version string |
| `model` | Detected model name |

## Source Map

| Source Name | Protocol Code | Notes |
|---|---|---|
| TV | `0x00` | ARC/eARC input |
| HDMI1 | `0x01` | |
| HDMI2 | `0x02` | |
| HDMI3 | `0x03` | |
| HDMI4 | `0x04` | |
| HDMI5 | `0x05` | |
| HDMI6 | `0x06` | |
| Coax | `0x08` | |
| Optical | `0x09` | |
| Analog1 | `0x0A` | |
| Analog2 | `0x0B` | |
| Phono | `0x0C` | |
| Bluetooth | `0x0D` | |
| Network | `0x0E` | AirPlay / Chromecast |

> **Note:** The physical HDMI port labels on the back of the receiver may be offset by +1 from the API source names. For example, the port labeled "HDMI 1" on the receiver may correspond to `HDMI2` in the API, because the TV/ARC input occupies `HDMI1` in the protocol. Verify your mapping by switching inputs and checking the `source` attribute.

## Protocol Reference

This integration implements the **JBL IP Control Protocol v1.5** — a binary TCP protocol on port 50000.

- [Official JBL IP Control Spec (PDF)](https://www.jbl.com/on/demandware.static/-/Sites-masterCatalog_Harman/default/dw786f5b64/pdfs/IPControl_MA_Series_v15.pdf)

### Frame Format

**Request:** `0x23 <CmdID> <DataLen> [Data...] 0x0D`

**Response:** `0x02 0x23 <CmdID> <RspCode> <DataLen> [Data...] 0x0D`

- `RspCode` `0x00` = success
- Query byte: `0xF0` (read current value)

### Commands Used

| Function | CmdID | Query | Write |
|---|---|---|---|
| Power | `0x00` | `0xF0` → `0x00` off / `0x01` on | `0x01` on / `0x00` off |
| IP Control Version | `0x02` | `0xF0` → ASCII version string | — |
| Source | `0x05` | `0xF0` → source code byte | source code byte |
| Volume | `0x06` | `0xF0` → `0x00`–`0x63` | `0x00`–`0x63` (0–99) |
| Mute | `0x07` | `0xF0` → `0x00` off / `0x01` on | `0x01` on / `0x00` off |
| Init/Model | `0x50` | `0xF0` → model code byte | — |

## Troubleshooting

- **Cannot connect**: Ensure the receiver is powered on and reachable at the configured IP. The receiver must be on the same network. Port 50000 must not be firewalled.
- **State not updating**: Check that polling interval isn't too long. Default 30s is recommended.
- **Wrong source names**: See the HDMI offset note above. Verify by switching inputs.
- **Debug logging**: Add to `configuration.yaml`:
  ```yaml
  logger:
    default: warning
    logs:
      custom_components.jbl_ma: debug
  ```

## License

MIT

## Credits

Built by [@angalexg](https://github.com/angalexg). Protocol reverse-engineered from the [JBL IP Control spec v1.5](https://www.jbl.com/on/demandware.static/-/Sites-masterCatalog_Harman/default/dw786f5b64/pdfs/IPControl_MA_Series_v15.pdf).

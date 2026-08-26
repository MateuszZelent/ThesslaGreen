# Thessla Green Home Assistant integration

The custom integration supports two mutually exclusive deployment modes:

- **Direct Modbus** (recommended): Home Assistant owns the selected RTU port. No FastAPI URL,
  token, separate service or manual Python installation is required.
- **External gateway**: an already running Thessla Green FastAPI gateway owns Modbus and Home
  Assistant acts as its HTTP client.

Never configure both modes, the built-in Home Assistant Modbus integration, or another Thessla
Green integration against the same serial adapter at the same time.

## Direct setup

1. Make the FTDI/RS-485 adapter visible to the Home Assistant runtime. Prefer its stable
   `/dev/serial/by-id/...` path.
2. Install this repository through HACS as an **Integration** and restart Home Assistant.
3. Open **Settings -> Devices & services -> Add integration -> Thessla Green**.
4. Select **Direct Modbus (recommended)**.
5. Confirm the detected serial path, Modbus unit ID `10`, baud rate `9600` and the read-only
   identity result.
6. Open **Thessla Green** in the sidebar. The bundled animation uses authenticated Home Assistant
   API calls; it does not need a token or a separate HTTP port.

## Dashboard card

After restarting Home Assistant, edit any dashboard and select **Add card**. Search for
**Thessla Green AirPack**. The card automatically selects the configured AirPack and embeds the
same live airflow diagram, fan-speed control, operating modes and special-mode buttons as the
sidebar panel.

If the visual card picker still has an older frontend cache, reload the browser with `Ctrl+F5`.
The equivalent manual YAML is:

```yaml
type: custom:thessla-green-card
height: 1200
```

`height` accepts 620–1600 pixels. With multiple integration entries, add the optional `entry_id`.

If the port is not listed, it is not visible inside the Home Assistant runtime. Map the USB device
to the container/VM or fix host permissions before retrying. A `port_busy` error means another
process still owns the adapter.

## External-gateway setup

Select **External FastAPI gateway** only after separately starting the gateway. Enter its base URL
and `THESSLA_API_TOKEN` if configured. In this mode the integration never opens Modbus.

## Entities and Google Home

The integration creates one coordinated device with:

- a `fan` entity supporting ON/OFF, 10-100% and Polish special-mode presets;
- Polish `select` options for Automatic/Manual/Temporary and special modes;
- two writable `number` entities for the manual and temporary 10-100% setpoints;
- temperature, airflow and demand sensors;
- physical bypass, FPX and built-in ERV heater binary sensors;
- the last confirmed command/read-back sensor.

The official Home Assistant Google Assistant integration supports the `fan`, `select`, and
temperature-sensor domains. The free manual Cloud-to-Cloud procedure is documented in
[`docs/GOOGLE_HOME.md`](../../docs/GOOGLE_HOME.md). Do not install **Google Assistant SDK** for
this purpose.

The vendor protocol does not expose RPM. Airflow is therefore the physical reaction signal shown
by the panel. Registers 274/275 provide the panel-compatible target flow, while Constant Flow
measurements from 256/257 remain separate and unavailable when raw value `0xffff` is reported.

## Scenes, automations and Node-RED

All controls are native Home Assistant entities and do not depend on the graphical card:

| Control | Entity domain | Home Assistant action |
| --- | --- | --- |
| Power and active fan percentage | `fan` | `fan.turn_on`, `fan.turn_off`, `fan.set_percentage` |
| Automatic / Manual / Temporary | `select` | `select.select_option` |
| Special mode | `select` or fan preset | `select.select_option`, `fan.set_preset_mode` |
| Stored manual setpoint | `number` | `number.set_value` |
| Stored temporary setpoint | `number` | `number.set_value` |
| Clear special mode | `button` | `button.press` |

The exact entity IDs include the configured device name and are visible under **Settings ->
Devices & services -> Thessla Green -> AirPack**. Do not hard-code the example suffix before
checking it on the target Home Assistant instance.

Example automation action selecting manual mode and 35%:

```yaml
actions:
  - action: number.set_value
    target:
      entity_id: number.airpack4_nastawa_reczna_wentylacji
    data:
      value: 35
  - action: select.select_option
    target:
      entity_id: select.airpack4_tryb_pracy
    data:
      option: Ręczny
```

For temporary operation, first set `number.airpack4_nastawa_chwilowa_wentylacji`, then select
`Chwilowy`. Selecting that mode performs the documented atomic activation block and uses the
duration configured on the physical Air++ controller. The same actions can be called from a
Node-RED **Action** node.

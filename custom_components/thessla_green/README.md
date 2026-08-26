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

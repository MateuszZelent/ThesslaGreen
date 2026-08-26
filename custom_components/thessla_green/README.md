# Thessla Green Home Assistant integration

This custom integration connects Home Assistant to the local Thessla Green FastAPI gateway.
It does not open Modbus and must not be configured as a second Modbus owner for the same unit.

## Setup

1. Install the repository as a custom integration through HACS.
2. Install and configure the `thessla-green` gateway separately.
3. In Home Assistant, add **Thessla Green** and enter the gateway URL, for example
   `http://192.168.1.20:8000`.
   If `THESSLA_API_TOKEN` is configured on the gateway, enter the same bearer token in the flow.
4. Expose only the resulting fan and sensor entities that you want to Google Assistant.

The integration uses one coordinator snapshot and sends only typed commands (`fan`, operating
mode, and special mode). It exposes a connectivity diagnostic and never exposes arbitrary register
writes.

The fan entity shows the confirmed manual or temporary percentage. Its attributes include the
instantaneous supply/exhaust airflow in m³/h and the last command's read-back result. The vendor
protocol does not expose RPM; airflow is therefore the physical reaction signal shown by the UI.
Separate sensors expose the current supply and exhaust demand from input registers 272/273. When
The panel-compatible target flow rates come from registers 274/275. Constant Flow measurements
remain separate; when CF is inactive, raw airflow `0xffff` is exposed as unavailable rather than
65535 m³/h.
The integration also creates an `Ostatnie potwierdzone polecenie` sensor with the requested and
read-back values.

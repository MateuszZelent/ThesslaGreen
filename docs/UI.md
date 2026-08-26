# Panel webowy i integracja HACS

## Panel lokalny

Gateway serwuje prosty panel bez dodatkowego procesu Node/React:

```bash
python -m thessla_green serve
```

Otwórz `http://127.0.0.1:8000/`. Panel:

- pobiera jeden snapshot `/api/v1/state` i opcje `/api/v1/control/options`;
- odświeża stan co pięć sekund;
- pozwala zmienić tryb, nastawę manualną/chwilową, tryb specjalny oraz ON/OFF;
- wysyła typowane komendy z `request_id` i `expected_revision`;
- pokazuje read-back (`requested_value`, `confirmed_value`, numer audytu);
- pokazuje chwilowy przepływ nawiewu i wywiewu jako sygnał fizycznej reakcji centrali.

Po komendach zmiany trybu/prędkości/ON-OFF odpowiedź zawiera także `result.airflow_observation`:
wartości po read-backu oraz informację, czy przepływ zmienił się względem snapshotu sprzed komendy.
Brak zmiany w pojedynczej próbce nie jest błędem nastawy — wentylator może reagować z opóźnieniem;
protokół nie raportuje RPM.

Dla opóźnionej reakcji można ustawić `THESSLA_AIRFLOW_OBSERVATION_SECONDS` większe od zera.
Gateway wykona wtedy kolejne read-only próbki co `THESSLA_AIRFLOW_OBSERVATION_INTERVAL_SECONDS`
i zwróci `changed_within_window`, `observation_window_seconds` oraz `samples`. Read-back nastawy
pozostaje niezależnym, wymaganym potwierdzeniem zapisu.

Historia snapshotów jest dostępna dla klienta mobilnego przez
`GET /api/v1/devices/{device_id}/telemetry?from=&to=&limit=`. Gateway zapisuje ją lokalnie w
SQLite (`THESSLA_DATABASE_URL`), z ograniczoną retencją; awaria zapisu historii nie blokuje
odczytu ani sterowania.

Panel nie raportuje RPM, bo dokument protokołu udostępnia przepływ w m³/h, a nie prędkość
obrotową wentylatora. Wymaga tego samego jedynego gatewaya co HACS i klient mobilny.

Jeżeli ustawiono `THESSLA_API_TOKEN`, wpisz go w polu tokenu panelu. Jest przechowywany tylko w
`localStorage` tej przeglądarki i wysyłany jako nagłówek Bearer.

Przy panelu hostowanym pod innym originem ustaw po stronie gatewaya `THESSLA_API_CORS_ORIGINS`
na dokładny adres panelu (lista rozdzielona przecinkami). Pusta wartość wyłącza dostęp
cross-origin. Nie ustawiaj `*` dla API chronionego tokenem.

Jeżeli gateway nie ma jeszcze skonfigurowanego endpointu, panel pokazuje sekcję **Discovery**.
Przycisk uruchamia wyłącznie `POST /api/v1/discovery`, pokazuje stabilne aliasy serialowe,
fingerprint AirPack, firmware, serial i status `is_selectable`. Panel wyświetla gotową linię
`THESSLA_SERIAL_PORT=...`, ale nie zapisuje `.env` ani nie przejmuje magistrali automatycznie.

Do testu panelu i kontraktu API bez zajmowania portu RS-485 służy symulator:

```bash
python -m thessla_green serve --demo --host 127.0.0.1 --port 8000
```

Symulator przechodzi ten sam read-only fingerprint, walidację zapisu, read-back i odświeżenie
przepływu co transport PyModbus. Jego przepływ jest modelem testowym (`procent × współczynnik`),
nie pomiarem rzeczywistej centrali.

## Home Assistant przez HACS

1. W HACS wybierz **Custom repositories** i dodaj repozytorium jako typ **Integration**.
2. Zainstaluj `Thessla Green` i zrestartuj Home Assistant.
3. W **Settings → Devices & services → Add integration** wybierz **Thessla Green**.
4. Podaj URL gatewaya i token, jeśli jest włączony.
5. Dodaj do dashboardu encję `fan` oraz sensory przepływu.

Integracja tworzy jeden coordinator i jedną grupę urządzenia. `fan` prezentuje potwierdzoną
nastawę, `select` tryb pracy/tryb specjalny, a sensor `Ostatnie potwierdzone polecenie` zawiera
szczegóły read-backu. Integracja HACS nie importuje `pymodbus` i nie może działać równolegle z
bezpośrednią integracją Modbus tej samej centrali.

# Pierwszy zakres sterowania

## Polityka automatyki

`src/thessla_green/control/policy.py` zawiera frameworkowo niezależny arbiter intencji. Reguły
automatyki proponują wyłącznie typed commands (`set_fan_speed`, `set_mode`, itd.); arbiter wybiera
jedną intencję według priorytetu, czasu utworzenia i źródła, a dopiero gateway wykonuje walidację,
zapis i read-back. Moduł nie zna adresów Modbus i nie może pisać rejestrów.

Priorytety są uporządkowane: `safety` → `manual` → `special` → `air_quality` → `temperature` →
`schedule`. Aktywny manual override wygasający o określonym czasie blokuje niższe priorytety, ale
nie blokuje zabezpieczenia. Każda decyzja zawiera wybraną intencję, odrzucone kandydatury i powód,
więc może trafić do audytu lub UI.

Pierwsza implementowana ścieżka sterowania korzysta wyłącznie z udokumentowanych rejestrów
`R/W` z `docs/ProtokolModbusRTU_AirPack4.pdf`. Każdy zapis jest wykonywany przez
`AirPackController`, który najpierw wymaga potwierdzonej identyfikacji read-only, serializuje
polecenia i odczytuje rejestr ponownie.

## Tryby pracy

Rejestr holding `4208` (`0x1070`, `mode`):

| Wartość | Nazwa | Znaczenie |
|---:|---|---|
| 0 | `automatic` | harmonogram automatyczny skonfigurowany w Air++ |
| 1 | `manual` | ręczna intensywność z rejestru 4210, bez limitu czasu |
| 2 | `temporary` | chwilowa intensywność przez czas skonfigurowany w Air++ |

## Intensywność wentylacji

Rejestr holding `4210` (`0x1072`, `airFlowRateManual`) przyjmuje `10–100%`. Ustawienie
intensywności nie przełącza automatycznie trybu pracy; aplikacja powinna jawnie wysłać najpierw
`set_mode: manual`, jeżeli użytkownik oczekuje natychmiastowego użycia tej nastawy.

Rejestr `4211` (`0x1073`, `airFlowRateTemporary`) również przyjmuje `10–100%` i jest nastawą
używaną, gdy `mode` ma wartość `temporary`. API udostępnia ją jako `set_temporary_fan_speed`.

Samo zapisanie `mode=2` nie jest poprawną aktywacją chwilową. PDF wymaga jednej operacji Function
16 na rejestrach `4400–4402`: `[2, procent, 1]`. API realizuje ją typowaną komendą
`activate_temporary_mode`; read-back potwierdza potem tryb i intensywność w `4208–4211`.
Dokument nie publikuje rejestru czasu trwania - używany jest czas skonfigurowany w Air++.

## Tryby specjalne

Rejestr holding `4224` (`0x1080`, `specialMode`):

| Wartość | Nazwa API | Znaczenie z protokołu |
|---:|---|---|
| 0 | `none` | brak funkcji specjalnej |
| 1 | `hood` | okap |
| 2 | `fireplace` | kominek |
| 3 | `airing_button` | wietrzenie — przełącznik dzwonkowy |
| 4 | `airing_switch` | wietrzenie — przełącznik ON/OFF |
| 5 | `airing_humidity` | wietrzenie — higrostat |
| 6 | `airing_air_quality` | wietrzenie — czujnik jakości powietrza |
| 7 | `airing_manual` | wietrzenie — aktywacja ręczna |
| 8 | `airing_automatic` | wietrzenie — automatyczne |
| 9 | `airing_schedule` | wietrzenie — harmonogram manualny |
| 10 | `open_windows` | otwarte okna |
| 11 | `empty_house` | pusty dom |

Wartości 3–9 opisują także źródło aktywacji w centrali. To, czy dany firmware pozwala wymusić
każdy wariant zapisem, trzeba potwierdzić na konkretnym urządzeniu. Dlatego domyślne UI pokazuje
wyłącznie opcje bezpieczne do ręcznego wywołania (`none`, `hood`, `fireplace`, `airing_manual`,
`open_windows`, `empty_house`), a kasowanie funkcji odbywa się przez wartość 0. Pełna mapa
pozostaje dostępna w rdzeniu do odczytu stanu i diagnostyki.

## API

```text
GET  /api/v1/control/options
POST /api/v1/commands {"type":"set_mode","parameters":{"mode":"manual"}}
POST /api/v1/commands {"type":"set_fan_speed","parameters":{"percentage":60}}
POST /api/v1/commands {"type":"set_temporary_fan_speed","parameters":{"percentage":80}}
POST /api/v1/commands {"type":"activate_temporary_mode","parameters":{"percentage":80}}
POST /api/v1/commands {"type":"set_special_mode","parameters":{"mode":"fireplace"}}
POST /api/v1/commands {"type":"set_special_mode","parameters":{"mode":"none"}}
GET  /api/v1/audit
```

Koperta może zawierać `request_id` (idempotentne ponowienie) i `expected_revision` (ochrona
przed zapisaniem na podstawie nieaktualnego snapshotu):

```json
{
  "type": "set_fan_speed",
  "parameters": {"percentage": 60},
  "request_id": "mobile-2026-08-26-001",
  "expected_revision": 12
}
```

Powtórzenie tej samej koperty zwraca `replayed: true` bez kolejnego zapisu. Cache identyfikatorów
jest zapisywany w SQLite, ograniczony domyślnie do 256 wpisów i wygasa po 24 godzinach
(`THESSLA_COMMAND_CACHE_RETENTION_ROWS`, `THESSLA_COMMAND_CACHE_TTL_SECONDS`). Dzięki temu retry
po restarcie gatewaya nie wykonuje drugiego zapisu.

API nie udostępnia surowego zapisu rejestru. Po każdym poleceniu odpowiedź zawiera wartość żądaną,
wartość potwierdzoną, adres rejestru, źródło, numer zdarzenia audytowego i stan urządzenia.
Dziennik zdarzeń można odczytać przez `GET /api/v1/audit`; gateway zapisuje go w lokalnym SQLite
z ograniczoną retencją, a awaria historii nie zatrzymuje sterowania. Adapter HACS wysyła nagłówek
`X-Thessla-Source: home_assistant`; klient
mobilny może użyć `mobile`, a automatyka `automation`.

W Home Assistant encja `fan` pokazuje potwierdzoną nastawę procentową. Jej atrybuty zawierają
również `supply_airflow_m3h` i `extract_airflow_m3h` — chwilowe przepływy z rejestrów 256/257 —
oraz `last_command` z read-backiem. Nastawa jest potwierdzeniem przyjęcia wartości przez sterownik;
reakcję wentylatorów obserwujemy przez przepływy, odświeżane domyślnie co 5 sekund. Protokół nie
raportuje obrotów RPM, więc nie nazywamy przepływu obrotami.
Integracja tworzy również sensor `Ostatnie potwierdzone polecenie`, którego atrybuty zawierają
`requested_value`, `confirmed_value`, `confirmed` i numer audytu.

Do pierwszego wyboru transportu służą również `GET /api/v1/discovery/serial-ports` oraz
`POST /api/v1/discovery`. Ten drugi endpoint jest blokowany, gdy gateway już posiada aktywne
połączenie, aby skanowanie nie konkurowało z normalną pracą centrali.

Wynik `permission_denied` oznacza uprawnienia systemu Linux do urządzenia, a nie brak odpowiedzi
Modbus. Wynik `device_not_found` oznacza nieistniejącą ścieżkę, `unknown_modbus_device` oznacza
poprawną odpowiedź Modbus bez potwierdzonego fingerprintu AirPack, a `port_busy` oznacza, że inny
proces ma otwarte urządzenie na wyłączność. Dla USB-RS485 preferuj alias `/dev/serial/by-id/...`
i uruchamiaj proces jako użytkownik należący do `dialout` (lub `uucp`).
Pole `modbus_verified` w JSON oznacza, że transport/gateway odpowiedział poprawną ramką Modbus;
sterowanie jest możliwe dopiero dla wyniku `airpack` z `is_selectable: true`.

Gateway ma również lokalną blokadę procesu dla wybranego endpointu. Drugi proces tego projektu
zatrzyma się przed połączeniem z komunikatem `endpoint is already owned`; blokada znika
automatycznie po zakończeniu pierwszego procesu.

Zamiast kilku osobnych kontroli można zebrać raport diagnostyczny:

```bash
python -m thessla_green doctor --json
```

`doctor` nie zapisuje rejestrów. Pokazuje lokalne aliasy, wyniki bounded discovery, potwierdzenie
fingerprintu i wskazówki dla uprawnień, blokady portu oraz braku odpowiedzi.

Te same operacje można wykonać jednorazowo z CLI po ustawieniu endpointu w `.env`:

```text
python -m thessla_green control mode manual
python -m thessla_green control fan-speed 60
python -m thessla_green control special-mode fireplace
python -m thessla_green control special-mode none
python -m thessla_green control power on
python -m thessla_green serve
```

Endpoint można również wskazać tylko dla jednego odczytu lub polecenia, bez modyfikowania `.env`:

```bash
python -m thessla_green status \
  --serial-port /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_BG03ZCK6-if00-port0 --json
python -m thessla_green control \
  --serial-port /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_BG03ZCK6-if00-port0 \
  --json mode manual
python -m thessla_green control \
  --serial-port /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_BG03ZCK6-if00-port0 \
  --json fan-speed 40
```

Te same opcje `--host`, `--cidr`, `--tcp-port`, `--baudrate` i `--unit-id` można podać przy
`status`, `control` oraz `monitor`; skanowanie sieci pozostaje ograniczone do jawnie wskazanych
hostów/CIDR.

Gateway można uruchomić z takim override’em bezpośrednio. Dla RTU użyj `--serial-port`, a dla TCP
`--modbus-host`; `--host` pozostaje adresem nasłuchu HTTP:

```bash
python -m thessla_green serve --auto-discover \
  --serial-port /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_BG03ZCK6-if00-port0
python -m thessla_green serve --auto-discover \
  --modbus-host 192.168.1.50 --modbus-port 502 --unit-id 10
```

Do read-only discovery można wskazać stabilny port USB bez zapisywania `.env`:

```text
python -m thessla_green discover --serial-port \
  /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_BG03ZCK6-if00-port0 --json
```

Skanowanie bramki Modbus TCP można ograniczyć do jawnie podanych hostów lub sieci:

```bash
python -m thessla_green discover \
  --host 192.168.1.50 --tcp-port 502 --unit-id 10 --json
python -m thessla_green discover \
  --cidr 192.168.1.0/24 --tcp-port 502 --unit-id 10 --json
```

Opcje `--host`, `--cidr`, `--tcp-port`, `--baudrate` i `--unit-id` można powtarzać. Skanowanie
nie zapisuje rejestrów ani nie wybiera automatycznie właściciela; wynik `airpack` z
`is_selectable: true` trzeba jawnie zapisać w konfiguracji gatewaya.

Jeżeli konfiguracja ma być wyprowadzona jednorazowo z discovery, można uruchomić:

```bash
python -m thessla_green serve --auto-discover
```

Ta opcja wybiera urządzenie tylko przy dokładnie jednym potwierdzonym wyniku AirPack. Przy zerze
wyników albo wielu urządzeniach gateway zatrzymuje się i pokazuje raport discovery; nic nie jest
zapisywane do `.env`. Po wyborze nadal obowiązuje zasada jednego właściciela portu Modbus.

## Pierwszy test na fizycznym urządzeniu

Po zakończeniu discovery zapisz wybrany alias w `.env` i uruchom gateway jako jedynego właściciela
portu:

```bash
THESSLA_SERIAL_PORT=/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_BG03ZCK6-if00-port0 \
  python -m thessla_green serve
```

Jeżeli gateway nie działa, jednorazowy odczyt bieżącej nastawy wykonuje komenda:

```bash
python -m thessla_green status --json
```

Alternatywnie można użyć jednorazowego, fail-closed wyboru endpointu:

```bash
python -m thessla_green status --auto-discover --json
python -m thessla_green control --auto-discover --json mode manual
python -m thessla_green control --auto-discover --json fan-speed 40
```

Każde polecenie zatrzyma się przy zerze lub wielu potwierdzonych urządzeniach.

Do read-only testu stabilności uruchom osobny proces (nie równolegle z `serve`, bo oba procesy
muszą otworzyć ten sam port):

```bash
python -m thessla_green monitor --duration 86400 --interval 5 --jsonl \
  > thessla-monitor-$(date +%F).jsonl
```

Każdy wiersz jest snapshotem zapisanym także w SQLite. Po zakończeniu sprawdź, czy wszystkie
wiersze mają `online: true`, rosnący `revision`, jakość `complete` i brak luk większych niż
oczekiwany interwał. Monitor nie wykonuje zapisów Modbus.

W JSON szukaj `state.values.mode`, `manual_fan_speed`, `temporary_fan_speed`,
`supply_airflow` i `extract_airflow`. Gdy `serve` już działa, użyj `GET /api/v1/state` zamiast
uruchamiać `status`, ponieważ oba procesy próbowałyby otworzyć ten sam port.

W drugim terminalu sprawdź stan, a następnie wykonaj małą, jawnie potwierdzaną zmianę:

```bash
curl -s http://127.0.0.1:8000/health/ready
curl -s http://127.0.0.1:8000/api/v1/state
curl -s -X POST http://127.0.0.1:8000/api/v1/commands \
  -H 'Content-Type: application/json' \
  -H 'X-Thessla-Source: cli' \
  -d '{"type":"set_mode","parameters":{"mode":"manual"},"request_id":"first-mode-test"}'
curl -s -X POST http://127.0.0.1:8000/api/v1/commands \
  -H 'Content-Type: application/json' \
  -H 'X-Thessla-Source: cli' \
  -d '{"type":"set_fan_speed","parameters":{"percentage":40},"request_id":"first-speed-test"}'
```

W odpowiedzi sprawdź `result.confirmed == true`, zgodność `requested_value` i `confirmed_value`
oraz `state.values.manual_fan_speed`. Faktyczną reakcję wentylatorów obserwuj w kolejnych
snapshotach przez `supply_airflow` i `extract_airflow`; są to chwilowe m³/h, nie RPM. Nie uruchamiaj
`discover` równolegle z działającym gatewayem, bo port będzie prawidłowo zgłoszony jako `port_busy`.

Dla poleceń wentylatora, trybu i ON/OFF odpowiedź zawiera również
`result.airflow_observation`. Pole `supply_changed`/`extract_changed` oznacza zmianę względem
snapshotu sprzed zapisu; jest to sygnał reakcji fizycznej, nie pomiar obrotów.

Jeśli potrzebne jest krótkie okno na opóźnioną reakcję wentylatorów, ustaw w `.env`:

```dotenv
THESSLA_AIRFLOW_OBSERVATION_SECONDS=5
THESSLA_AIRFLOW_OBSERVATION_INTERVAL_SECONDS=1
```

Wtedy wynik zawiera także `changed_within_window` i listę próbek przepływu. Wartość
`result.confirmed` nadal oznacza wyłącznie potwierdzony read-back rejestru; brak zmiany przepływu
w oknie nie unieważnia przyjętej nastawy.

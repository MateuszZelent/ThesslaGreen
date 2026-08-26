# ThesslaGreen Controller

Niezależny, lokalny moduł do odczytu, sterowania i automatyzacji rekuperatora Thessla Green przez Modbus RTU lub Modbus TCP.

## Cel projektu

Projekt ma zapewnić:

- odczyt wszystkich dostępnych temperatur, przepływów, stanów, alarmów i parametrów pracy;
- bezpieczne sterowanie wydajnością wentylatorów, trybami, sezonem, bypassem i pracą centrali;
- inteligentne sterowanie na podstawie temperatury wewnętrznej i zewnętrznej, jakości powietrza, wilgotności oraz harmonogramu;
- panel WWW działający w sieci lokalnej;
- stabilne, wersjonowane API FastAPI dla aplikacji mobilnej Dart/Flutter;
- integrację Home Assistant instalowaną przez HACS;
- bezpieczne sterowanie z Google Home za pośrednictwem encji Home Assistant;
- historię danych, diagnostykę oraz ręczne przejęcie kontroli.

## Stan obecny

Repozytorium zawiera działający rdzeń, read-only discovery RTU/TCP, sterowanie z read-backiem
oraz samodzielną integrację HACS otwierającą Modbus bezpośrednio z Home Assistanta. Opcjonalny
gateway FastAPI pozostaje dostępny dla aplikacji mobilnej. Na testowanym urządzeniu discovery
potwierdziło AirPack4, firmware 4.85.16 i Modbus unit 10 przez stabilny alias USB-RS485. Przed
sterowaniem nadal trzeba wykonać pojedynczy, kontrolowany test read-back na tym urządzeniu.

## Architektura

```text
Profil HACS:    Google Home -> Home Assistant/HACS -> rdzeń -> Modbus -> Rekuperator
Profil mobilny: Flutter -> gateway FastAPI -> rdzeń -> Modbus -> Rekuperator
```

Domyślna instalacja HACS działa samodzielnie: Home Assistant jest jedynym właścicielem portu
Modbus i nie wymaga URL, tokenu ani procesu FastAPI. Jeżeli równocześnie potrzebne jest API dla
aplikacji mobilnej, należy uruchomić profil gatewaya i w kreatorze HACS wybrać ten sam gateway.
Profile są wzajemnie wykluczające dla jednego fizycznego portu — zawsze istnieje dokładnie jeden
właściciel Modbus.

Szczegóły: [architektura](docs/ARCHITECTURE.md), [plan prac](docs/ROADMAP.md),
[pierwszy zakres sterowania](docs/CONTROL.md), [panel UI i HACS](docs/UI.md),
[mapa rejestrów](docs/REGISTER_MAP.md), [Google Home](docs/GOOGLE_HOME.md) i
[kontrakt mobilny](docs/MOBILE_API.md).

## Proponowany stos

- Python 3.12+
- `pymodbus` — Modbus RTU i TCP
- FastAPI + WebSocket — API oraz dane na żywo
- OpenAPI — kontrakt i generowanie typowanego klienta Dart
- SQLite na start, PostgreSQL opcjonalnie — konfiguracja i historia
- Flutter/Dart — aplikacja mobilna na wspólnym kontrakcie API
- React/PWA — opcjonalny panel WWW
- custom integration Home Assistant — natywne encje i dystrybucja przez HACS
- Docker Compose — wdrożenie na Raspberry Pi, mini-PC lub serwerze domowym

Typed client Dart i pierwszy ekran Flutter znajdują się w katalogu [mobile](mobile/). Ekran pokazuje
stan, przepływy i potwierdzone sterowanie; secure storage tokenu oraz walidacja `flutter analyze`
pozostają kolejnym krokiem.

## Uruchomienie deweloperskie

Kod jest rozwijany etapami zgodnie z [roadmapą](docs/ROADMAP.md); zakresy niepotwierdzone na
fizycznym urządzeniu pozostają wyłączone z bezpiecznego API.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pytest
```

Na Linuxie lub w Condzie użyj odpowiednika:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
python -m thessla_green discover --json
```

Do zebrania jednego raportu diagnostycznego bez żadnego zapisu użyj:

```bash
python -m thessla_green doctor --json
```

Raport zawiera stabilne aliasy portów, wyniki fingerprintingu, podsumowanie statusów
`permission_denied`/`port_busy`/`device_not_found` oraz rekomendacje naprawcze. Discovery w tym
raporcie pozostaje wyłącznie read-only.

Układ `src/` oznacza, że samo wejście do katalogu repozytorium nie dodaje pakietu do `sys.path`.
Jednorazowe `pip install -e .` jest właściwym rozwiązaniem. Do szybkiego testu bez instalacji można
użyć `PYTHONPATH=src python3 -m thessla_green discover --json`.

Po instalacji można uruchomić bezpieczne, tylko-odczytowe wykrywanie skonfigurowanych kandydatów:

```bash
python -m thessla_green discover --json
```

Dla adaptera USB-RS485 ustaw stabilną ścieżkę `/dev/serial/by-id/...` zamiast
`/dev/ttyUSB0` (numer urządzenia może się zmienić po restarcie):

```bash
cp .env.example .env
sed -i 's#^THESSLA_SERIAL_PORT=.*#THESSLA_SERIAL_PORT=/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_BG03ZCK6-if00-port0#' .env
python -m thessla_green discover --json
```

Albo jednorazowo, bez edycji `.env`:

```bash
python -m thessla_green discover --serial-port \
  /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_BG03ZCK6-if00-port0 --json
```

Jeżeli wynik ma status `permission_denied`, sprawdź właściciela portu (`ls -l
/dev/serial/by-id/...`) i dodaj użytkownika uruchamiającego proces do grupy
`dialout` (na niektórych dystrybucjach `uucp`), po czym rozpocznij nową sesję
logowania. Nie naprawiaj tego stałym `chmod 666`.

Jeżeli status to `port_busy`, znajdź właściciela blokady i zatrzymaj tylko właściwą usługę:

```bash
sudo fuser -v /dev/ttyUSB0
sudo lsof /dev/ttyUSB0
```

Typowym powodem jest drugi gateway, Home Assistant albo `ModemManager` korzystający z tego samego
adaptera. Dla jednej centrali uruchom dokładnie jednego właściciela Modbus.

Gateway ma również lokalną blokadę procesu dla wybranego endpointu. Jeżeli drugi proces tego
projektu próbuje wystartować na tym samym endpointcie, zatrzyma się przed połączeniem z komunikatem
`endpoint is already owned`; blokada znika automatycznie po zakończeniu pierwszego procesu.

Po wybraniu i zapisaniu endpointu w `.env` gateway udostępnia API sterowania. Bieżący stan można
odczytać jednorazowo (gdy `serve` nie działa) przez:

```bash
python -m thessla_green status --json
```

Jeśli nie chcesz jeszcze zapisywać endpointu w `.env`, użyj fail-closed discovery:

```bash
python -m thessla_green status --auto-discover --json
python -m thessla_green control --auto-discover --json mode manual
python -m thessla_green control --auto-discover --json fan-speed 40
```

Każde z tych poleceń działa tylko przy dokładnie jednym potwierdzonym urządzeniu AirPack.

Bez zapisywania endpointu w `.env` można przekazać stabilny alias bezpośrednio do odczytu lub
sterowania:

```bash
python -m thessla_green status \
  --serial-port /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_BG03ZCK6-if00-port0 --json
python -m thessla_green control \
  --serial-port /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_BG03ZCK6-if00-port0 \
  --json fan-speed 40
```

Read-only test stabilności przez 24 godziny:

```bash
python -m thessla_green monitor --duration 86400 --interval 5 --jsonl \
  > thessla-monitor-$(date +%F).jsonl
```

Monitor może również jednorazowo wybrać urządzenie z discovery:

```bash
python -m thessla_green monitor --auto-discover --duration 86400 --interval 5 --jsonl \
  > thessla-monitor-$(date +%F).jsonl
```

Historię SQLite można skopiować bez zatrzymywania gatewaya i bez otwierania Modbusa:

```bash
python -m thessla_green backup --output ./backups/thessla-$(date +%F).db --json
```

Istniejący plik nie jest nadpisywany bez jawnego `--force`.

Podstawowe polecenia sterowania to `set_mode`, `set_fan_speed` oraz `set_special_mode`; ich zakres i read-back opisano w
[CONTROL.md](docs/CONTROL.md).

Uruchomienie lokalnego gatewaya FastAPI (po skonfigurowaniu endpointu i opcjonalnego tokenu):

```bash
python -m thessla_green serve
```

Można też uruchomić gateway z bezpiecznym automatycznym wyborem endpointu:

```bash
python -m thessla_green serve --auto-discover
```

Tryb startuje tylko przy dokładnie jednym potwierdzonym urządzeniu AirPack; przy braku lub wielu
wynikach zatrzymuje się z raportem i nie zapisuje konfiguracji.

Endpoint można przekazać bez edycji `.env`; `--host` nadal oznacza adres HTTP, dlatego endpoint TCP
ma osobną opcję `--modbus-host`:

```bash
python -m thessla_green serve --auto-discover \
  --serial-port /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_BG03ZCK6-if00-port0 \
  --unit-id 10
python -m thessla_green serve --auto-discover \
  --modbus-host 192.168.1.50 --modbus-port 502 --unit-id 10
```

API domyślnie nie zezwala na żądania przeglądarkowe z innych originów. Dla panelu uruchomionego
na osobnym hoście ustaw w `.env` dokładną, rozdzieloną przecinkami listę originów, np.
`THESSLA_API_CORS_ORIGINS=https://panel.example,https://phone.example`, i zrestartuj gateway.
Nie używaj `*` przy włączonym tokenie. Natywna aplikacja Android/iOS nie potrzebuje CORS;
ustawienie jest potrzebne głównie dla Flutter Web lub zewnętrznego panelu WWW.

Panel i API można też uruchomić bez centrali, na deterministycznym symulatorze:

```bash
python -m thessla_green serve --demo
```

Symulator nie otwiera żadnego portu systemowego; służy do sprawdzenia UI, kontraktu REST/WS,
read-backu i integracji HACS przed testem na sprzęcie.

Panel webowy jest dostępny pod adresem `http://127.0.0.1:8000/`. Pokazuje stan, aktywną nastawę,
chwilowe przepływy, tryby specjalne i wynik ostatniego read-backu. Panel korzysta wyłącznie z API
gatewaya; nie otwiera własnego połączenia Modbus.

Jeśli centrala reaguje z opóźnieniem, ustaw `THESSLA_AIRFLOW_OBSERVATION_SECONDS` (np. `5`) oraz
opcjonalnie `THESSLA_AIRFLOW_OBSERVATION_INTERVAL_SECONDS`. Odpowiedź polecenia pozostaje oparta
na read-backu rejestru, a `airflow_observation` dodatkowo zawiera próbki i informację, czy przepływ
zmienił się w zadanym oknie. Przepływ jest sygnałem reakcji w m³/h, nie pomiarem RPM.

FastAPI pozostaje opcjonalnym profilem dla aplikacji mobilnej lub instalacji, w której osobny
proces ma być właścicielem Modbus. Domyślna instalacja HACS może zamiast tego otworzyć port
bezpośrednio wewnątrz Home Assistanta. W obu profilach dokładnie jeden proces jest właścicielem
magistrali.

### HACS

W HACS dodaj to repozytorium jako **Custom repository** typu **Integration**, zainstaluj wersję
`0.3.0`, zrestartuj Home Assistant i dodaj integrację **Thessla Green** przez UI. Wybierz:

- **Bezpośredni Modbus (zalecane)** — kreator pokaże porty widoczne w Home Assistant, wykona
  read-only fingerprint i zapisze port, unit ID, baudrate oraz timeout. Nie podaje się URL ani
  tokenu i nie uruchamia FastAPI;
- **Zewnętrzny gateway FastAPI** — zachowany tryb zaawansowany, wymagający wcześniej uruchomionej
  usługi oraz jej URL/tokena.

Wyłącz starą integrację Modbus i każdy zewnętrzny gateway używający tego samego adaptera przed
wyborem trybu bezpośredniego. Dla Home Assistant Container/VM port USB musi być widoczny wewnątrz
kontenera lub maszyny wirtualnej, najlepiej jako `/dev/serial/by-id/...`.

Po konfiguracji integracja dodaje panel **Thessla Green** do bocznego menu Home Assistant. W trybie
bezpośrednim animacja używa uwierzytelnionego API HA i wspólnego koordynatora, więc nie potrzebuje
osobnego serwera ani tokenu. W trybie gatewaya nadal osadza publiczny panel `/ui/`; przy HTTPS po
stronie HA gateway również musi być dostępny po HTTPS.

Po dodaniu integracji HACS do dashboardu można dodać encję `fan` rekuperatora. Suwak pokazuje
potwierdzoną nastawę procentową, a atrybuty encji zawierają oba setpointy (`manual` i `temporary`),
chwilowy przepływ nawiewu/wywiewu w m³/h oraz ostatni wynik read-backu. PDF protokołu nie raportuje
RPM, dlatego reakcję wentylatorów oceniamy przez przepływy 256/257, odświeżane domyślnie co 5 sekund.

Bezpłatna integracja z Google Home nie wymaga licencji do tego projektu ani subskrypcji Home
Assistant Cloud. Wymaga ręcznej konfiguracji oficjalnej integracji `google_assistant`, publicznego
HTTPS i projektu Google Home Cloud-to-Cloud. Dokładna procedura znajduje się w
[docs/GOOGLE_HOME.md](docs/GOOGLE_HOME.md). Nie należy instalować `Google Assistant SDK`, ponieważ
jest to integracja do wysyłania poleceń w przeciwnym kierunku.

Konfigurację należy przechowywać w `.env` utworzonym na podstawie `.env.example`. Plik `.env` nie trafia do Git.

## Bezpieczeństwo sterowania

- Każdy zapis musi mieć walidację zakresu i odczyt potwierdzający.
- Po utracie czujników automatyka przechodzi do bezpiecznego, przewidywalnego trybu.
- Tryb ręczny ma pierwszeństwo i określony czas wygaśnięcia.
- Krytyczne zabezpieczenia fabryczne centrali nigdy nie są omijane.
- Dostęp spoza LAN wymaga uwierzytelnienia i TLS; nie wystawiamy Modbus bezpośrednio do Internetu.

## Repozytorium referencyjne

Inspiracją funkcjonalną jest [aLAN-LDZ/ThesslaGreen_HA](https://github.com/aLAN-LDZ/ThesslaGreen_HA). Na dzień przygotowania projektu repozytorium nie zawierało widocznego pliku licencji, dlatego nie kopiujemy z niego kodu. Adresy rejestrów traktujemy jako hipotezy techniczne do sprawdzenia z dokumentacją producenta i na urządzeniu.

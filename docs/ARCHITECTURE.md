# Architektura wielokanałowa

## Cel i granice systemu

Projekt udostępnia ten sam rekuperator trzema kanałami:

1. integracja Home Assistant instalowana przez HACS;
2. wersjonowane API FastAPI dla aplikacji mobilnej Dart/Flutter;
3. Google Home, w pierwszej kolejności przez encje wystawione z Home Assistant.

System działa lokalnie bez Internetu, nie omija zabezpieczeń fabrycznych centrali i oddziela
odczyt urządzenia od decyzji automatyki. Komunikacja z centralą może odbywać się przez Modbus
RTU (RS-485/USB) albo Modbus TCP.

Najważniejszy niezmiennik: **dla jednej fizycznej centrali istnieje dokładnie jeden właściciel
połączenia Modbus i jeden wykonawca zapisów**. Aplikacja mobilna, Home Assistant i Google Home
nie zapisują rejestrów bezpośrednio.

Gateway dodatkowo utrzymuje lokalną dzierżawę procesu dla klucza endpointu. Drugi proces tego
samego projektu otrzymuje błąd właściciela jeszcze przed otwarciem transportu; blokada jest
advisory lockiem zwalnianym automatycznie przez system po zakończeniu procesu. Nie zastępuje to
zatrzymania obcej integracji HA, ale ogranicza przypadkowe uruchomienie dwóch naszych gatewayów.

## Podział na warstwy

```text
                         Google Home
                              ^
                              | encje HA: fan/sensor/binary_sensor
                              |
Flutter/Dart <---- HTTPS/WS ----+----> Integracja HACS
          \                    |           /
           \                   v          /
            +---------- FastAPI gateway --+
                              |
                 Application services
                 (polecenia, polityki, audyt)
                              |
                  Domain model + capabilities
                              |
                  Protocol (Modbus RTU/TCP)
                              |
                       Thessla Green
```

Warstwy wewnętrzne nie zależą od FastAPI ani Home Assistant:

- **Protocol** — połączenie, retry z backoff, grupowe odczyty, kodeki, bezpieczne zapisy i
  read-back;
- **Domain** — `DeviceState`, alarmy, możliwości danego modelu/firmware i typowane polecenia;
- **Application** — przypadki użycia, arbiter sterowania, walidacja, idempotencja i audyt;
- **Control policy** — deterministyczne intencje, priorytety i wygasający manual override bez
  znajomości Modbus;
- **Telemetry** — bieżący snapshot, historia, jakość komunikacji i zdarzenia;
- **Adapters** — FastAPI, Home Assistant oraz w przyszłości bezpośredni adapter Google.

Zależności biegną do środka: adaptery mogą znać warstwę aplikacyjną, ale domena nie importuje
FastAPI, Home Assistant, Pydantic ani klienta Google.

## Profile wdrożenia

### Profil A — Gateway (zalecany dla trzech kanałów)

Osobny proces `thessla-green-gateway` jest właścicielem Modbus. FastAPI udostępnia lokalne API,
a integracja HACS łączy się z gatewayem przez HTTP i WebSocket. Aplikacja Flutter korzysta z tego
samego kontraktu. To jedyny profil pozwalający bezpiecznie używać równocześnie aplikacji mobilnej
i Home Assistant bez rywalizacji o port szeregowy.

```text
centrala <--Modbus--> gateway/FastAPI <--LAN--> Flutter
                               ^
                               +--------> Home Assistant --> Google Home
```

Gateway może działać jako usługa systemd, kontener albo w przyszłości dodatek Home Assistant.
Dodatek HA i integracja HACS to dwa różne artefakty: HACS instaluje custom integration, nie usługę
systemową ani dowolną bibliotekę.

### Profil B — Direct HA (opcjonalny, późniejszy)

Integracja Home Assistant sama korzysta z biblioteki protokołu i jest właścicielem Modbus. Profil
jest wygodny dla użytkownika bez osobnego gatewaya, ale nie wolno w nim uruchamiać drugiego
backendu FastAPI podłączonego do tej samej centrali. Aplikacja mobilna powinna wtedy korzystać z
API Home Assistant albo profil należy przełączyć na Gateway.

Profile są wzajemnie wykluczające dla konkretnego urządzenia. Integracja powinna pokazywać
jednoznaczny `connection_mode` i diagnostykę właściciela magistrali.

## Integracja Home Assistant i HACS

HACS jest kanałem dystrybucji custom integration, a nie formatem biblioteki. Docelowy artefakt ma
strukturę zgodną z wymaganiami HACS:

```text
custom_components/thessla_green/
  __init__.py
  manifest.json
  config_flow.py
  coordinator.py
  api.py
  fan.py
  sensor.py
  binary_sensor.py
  select.py
  button.py
  diagnostics.py
  strings.json
  translations/
  www/panel.js
hacs.json
README.md
```

Zalecane jest osobne repozytorium dystrybucyjne integracji HACS, np.
`thessla-green-home-assistant`. Ten projekt może pozostać źródłem rdzenia i gatewaya. Dzięki temu
HACS pobiera tylko pliki integracji, a zależności biblioteczne mają niezależne wersjonowanie.

Wymagania funkcjonalne integracji:

- konfiguracja wyłącznie przez UI (`config_flow`) z testem połączenia i blokadą duplikatów;
- kreator po teście gatewaya pokazuje potwierdzony model/firmware, endpoint i unit ID Modbus oraz
  read-only listę portów widocznych na hoście; wybór i otwarcie magistrali pozostają po stronie
  wcześniej skonfigurowanego gatewaya;
- `manifest.json` z co najmniej domeną, nazwą, wersją, dokumentacją, trackerem błędów i
  `codeowners`; typ integracji: `hub` lub `device` zależnie od ostatecznego modelu;
- jeden `DataUpdateCoordinator` pobierający snapshot zamiast odpytywania osobno przez każdą
  encję;
- `DeviceInfo` grupujące encje pod jedną centralą i stabilne `unique_id` niezależne od adresu IP;
- encja `fan` dla włączenia i wydajności, sensory temperatur/przepływów, `binary_sensor` dla
  alarmów/łączności, `select` dla bezpiecznych trybów i `button` dla krótkiego boostu;
- encje niedostępne dla funkcji nieobsługiwanych przez dany model/firmware;
- reautoryzacja, ponowna konfiguracja hosta, tłumaczenia PL/EN, diagnostyka z redakcją sekretów;
- brak blokującego I/O w pętli Home Assistant oraz prawidłowe wyrejestrowanie subskrypcji;
- opcjonalny panel boczny osadza lokalny `/ui/` gatewaya, dzięki czemu animacja i sterowanie są
  współdzielone bez kopiowania logiki API do frontendu HA;
- walidacje HACS i Hassfest w CI oraz wersjonowane GitHub Releases.

W profilu Gateway integracja nie implementuje logiki Modbus ani automatyki. Mapuje stabilny
kontrakt API na natywne encje HA.

## FastAPI dla aplikacji Dart/Flutter

API jest adapterem warstwy aplikacyjnej, a nie miejscem reguł biznesowych. OpenAPI jest kontraktem
źródłowym dla generowanego, typowanego klienta Dart. Zmiany łamiące trafiają do nowej wersji API.

### Minimalny kontrakt v1

Pierwszy działający wycinek udostępnia poniższe endpointy (krótkie ścieżki pozostają dla
kompatybilności CLI, a ścieżki `devices/{device_id}` są kontraktem dla klienta mobilnego):

```text
GET  /health/live
GET  /health/ready
GET  /                                      # local dashboard
GET  /ui/                                   # static dashboard assets
GET  /api/v1/state                         # compatibility alias
GET  /api/v1/capabilities                  # compatibility alias
GET  /api/v1/devices
GET  /api/v1/devices/{device_id}
GET  /api/v1/devices/{device_id}/state
GET  /api/v1/devices/{device_id}/capabilities
GET  /api/v1/devices/{device_id}/telemetry?from=&to=&limit=
POST /api/v1/devices/{device_id}/commands
POST /api/v1/commands                      # compatibility alias
GET  /api/v1/control/options
GET  /api/v1/audit                         # persisted write evidence
GET  /api/v1/discovery/serial-ports
POST /api/v1/discovery
WS   /api/v1/events
```

Docelowe rozszerzenia kontraktu (telemetria, alarmy, historia, automatyka i statusy asynchronicznych
poleceń) są zaplanowane, ale nie są jeszcze udawane przez pierwszy wycinek:

```text
GET  /api/v1/devices/{device_id}/alarms
GET  /api/v1/commands/{command_id}
GET  /api/v1/automation/rules
PUT  /api/v1/automation/rules
```

Jedna koperta polecenia zastępuje mnożenie endpointów dla każdego rejestru. Pierwszy wycinek
egzekwuje pola `type` i `parameters`, a opcjonalnie przyjmuje `request_id` oraz
`expected_revision`:

```json
{
  "type": "set_fan_speed",
  "parameters": {"percentage": 60},
  "request_id": "mobile-2026-08-26-001",
  "expected_revision": 12
}
```

Odpowiedź pierwszego wycinka zawiera status `confirmed`, wynik read-back, źródło polecenia,
numer zdarzenia audytowego i potwierdzony snapshot. Powtórzenie tego samego `request_id` z tymi
samymi parametrami zwraca poprzednią odpowiedź z `replayed: true` bez kolejnego zapisu; ponowne
użycie identyfikatora z innym poleceniem oraz niezgodna `expected_revision` są odrzucane.
Idempotencja jest utrwalana w SQLite (domyślnie 256 żądań, TTL 24 godziny), podobnie jak snapshoty
i audyt z ograniczoną retencją. Endpoint statusu asynchronicznego pozostaje kolejnym krokiem
wdrożeniowym.

WebSocket przesyła zdarzenia z monotonicznym numerem sekwencji. Po przerwaniu połączenia klient
najpierw pobiera pełny snapshot REST, a następnie wznawia strumień. Push notification nie jest
zamiennikiem źródła prawdy; tylko informuje aplikację, by zsynchronizowała stan.

### Bezpieczeństwo API

- domyślnie nasłuch tylko w LAN; zdalny dostęp przez VPN albo reverse proxy z TLS;
- krótkotrwały access token i odnawialny refresh token przechowywany w bezpiecznym magazynie
  systemowym telefonu;
- role `viewer`, `operator`, `admin`; administracja użytkownikami i surowe zapisy poza zwykłym API;
- limitowanie żądań, limit rozmiaru wiadomości, jawny CORS i audyt każdego polecenia;
- sekrety poza repozytorium, redakcja logów i rotacja kluczy;
- nie wystawiamy Modbus ani ogólnego endpointu „zapisz rejestr”.

CORS jest jawnie opt-in: `THESSLA_API_CORS_ORIGINS` przyjmuje dokładne originy rozdzielone
przecinkami i domyślnie pozostaje pusty. Nie włączamy wildcardu razem z uwierzytelnieniem.
Natywne aplikacje mobilne nie podlegają ograniczeniu CORS; konfiguracja jest przeznaczona dla
Flutter Web i zewnętrznych paneli przeglądarkowych.

## Google Home

### Wariant 1 — przez Home Assistant (MVP, zalecany)

Integracja HACS tworzy natywne encje, które użytkownik selektywnie wystawia do Google Assistant
przez Home Assistant Cloud albo ręczną integrację Google Assistant. Encja `fan` mapuje włączenie,
procent prędkości i ewentualne preset modes. Do Google można również wystawić obsługiwane sensory,
np. temperaturę, wilgotność, CO2 i PM2.5.

Nie wystawiamy do sterowania głosowego:

- surowych rejestrów i ustawień serwisowych;
- kasowania alarmów oraz operacji diagnostycznych;
- funkcji o niepotwierdzonej semantyce, np. bypassu przed walidacją dla danego firmware;
- zatrzymania centrali, dopóki nie zostanie świadomie zatwierdzona polityka bezpieczeństwa.

Ten wariant zachowuje lokalny rdzeń projektu. Sama ścieżka Google nadal może wymagać Internetu,
ale awaria Google nie wpływa na lokalne API, HA ani automatykę.

### Wariant 2 — bezpośredni Google Cloud-to-cloud (dopiero produktowo)

Jest technicznie możliwy jako urządzenie typu `FAN` z cechami `OnOff` i `FanSpeed`, lecz wymaga:

- publicznie dostępnego fulfillmentu obsługującego `SYNC`, `QUERY`, `EXECUTE` i `DISCONNECT`;
- serwera OAuth 2.0 z Authorization Code Flow i account linking;
- Request Sync, Report State, monitoringu, polityki prywatności i obsługi kont;
- Google Home Test Suite, profilu firmy, przeglądu polityk i certyfikacji przed publikacją.

To osobny produkt chmurowy i domena zagrożeń, nie endpoint dopisany do lokalnego FastAPI. Nie
wchodzi do MVP. Matter bridge również pozostaje eksperymentem po ustabilizowaniu HA i API.

## Wspólny model stanu i poleceń

Odczyt Modbus tworzy niezmienny `DeviceState` z `revision`, czasem odczytu, jakością danych i
capabilities. Stan trafia równolegle do historii, brokerów zdarzeń i silnika sterowania. Silnik
generuje `ControlIntent`, ale zapis wykonuje wyłącznie `DeviceCommandService`, który:

1. sprawdza uprawnienia, capabilities, zakres i aktualność polecenia;
2. rozstrzyga priorytet oraz blokuje równoległe zapisy;
3. zapisuje rejestr i wykonuje read-back;
4. publikuje potwierdzony snapshot lub jednoznaczny błąd;
5. zapisuje wynik, autora i źródło (`mobile`, `home_assistant`, `automation`) w audycie.

Priorytety od najwyższego:

1. zabezpieczenia urządzenia i lokalny panel producenta;
2. awaryjne zatrzymanie lub bezpieczny profil;
3. czasowy tryb ręczny użytkownika;
4. tryby specjalne, np. kominek lub intensywne wietrzenie;
5. automatyka jakości powietrza i wilgotności;
6. automatyka temperatury i harmonogram bazowy.

## Docelowa struktura kodu

```text
src/thessla_green/
  protocol/          # klient RTU/TCP, kodeki, wersjonowana mapa rejestrów
  domain/            # stan, capabilities, alarmy i polecenia bez zależności frameworkowych
  application/       # przypadki użycia, arbiter, CommandService
  control/           # deterministyczne reguły automatyki
  telemetry/         # historia, zdarzenia i metryki
  api/               # adapter FastAPI, REST, WebSocket, auth
  config/            # ustawienia i migracje
mobile/
  lib/               # framework-light klient Dart REST/WebSocket
  generated/         # opcjonalny klient z zamrożonego OpenAPI (po wygenerowaniu)
tests/
  unit/
  contract/          # OpenAPI i kompatybilność klienta Dart/HA
  integration/
  simulator/         # symulator urządzenia Modbus
docs/
```

Repozytorium HACS zawiera wyłącznie adapter `custom_components/thessla_green` i jego testy. Jeśli
w przyszłości profil Direct HA będzie używał wspólnej biblioteki, integracja przypina jej dokładną
wersję z PyPI w `manifest.json`; nie zależy od kodu znajdującego się tylko w katalogu `src` tego
repozytorium.

## Dane i wdrożenie

Jedna usługa backendowa i SQLite w trybie WAL wystarczą dla jednej instalacji. Retencja surowej
telemetrii powinna być ograniczona, a starsze dane agregowane. PostgreSQL jest opcją dopiero dla
wielu instalacji lub większej skali.

Kontener musi jawnie otrzymać port szeregowy i trwały wolumen danych. Readiness oznacza gotowość
do obsługi żądań, ale stan `device_offline` jest stanem domenowym, a nie automatycznie awarią
procesu. Kopia konfiguracji nie może zawierać tokenów bez szyfrowania.

## Kryteria architektoniczne

- odłączenie Internetu nie przerywa lokalnego sterowania i zbierania danych;
- wszystkie adaptery prezentują ten sam potwierdzony stan i te same capabilities;
- tylko jeden proces posiada Modbus, co jest testowane także w dokumentacji wdrożenia;
- polecenia są idempotentne, audytowalne i kończą się potwierdzeniem albo jawnym timeoutem;
- kontrakt OpenAPI jest wersjonowany i testowany względem klienta Dart oraz adaptera HA;
- utrata Google Home, Home Assistant lub aplikacji mobilnej nie zatrzymuje gatewaya ani automatyki.

## Źródła wymagań integracyjnych

- [wymagania integracji HACS](https://hacs.xyz/docs/publish/integration/);
- [manifest integracji Home Assistant](https://developers.home-assistant.io/docs/creating_integration_manifest/);
- [config flow Home Assistant](https://developers.home-assistant.io/docs/core/integration/config_flow/);
- [udostępnianie encji HA do Google Assistant](https://www.home-assistant.io/integrations/google_assistant/);
- [Google Cloud-to-cloud](https://developers.home.google.com/cloud-to-cloud);
- [typ urządzenia Fan w Google Home](https://developers.home.google.com/cloud-to-cloud/guides/fan).

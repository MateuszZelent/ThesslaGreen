# Plan realizacji

Plan prowadzi od bezpiecznego dostępu do urządzenia do trzech kanałów użytkowych. Każdy etap ma
mierzalne kryterium zakończenia; integracje nie mogą wyprzedzić stabilnego modelu domenowego i
kontraktu urządzenia.

## Etap 0 — rozpoznanie sprzętu

- ustalenie modelu centrali, sterownika i wersji firmware;
- potwierdzenie RTU/TCP, parametrów portu i identyfikatora urządzenia;
- pozyskanie oficjalnej mapy Modbus;
- bezpieczny zrzut rejestrów tylko do odczytu;
- lista wartości nieobsługiwanych (`0x8000`, błędy, zakresy);
- nadanie urządzeniu stabilnego identyfikatora niezależnego od portu i adresu IP.
- opcjonalne `serve/status/control/monitor --auto-discover`, które wybierają endpoint tylko przy
  dokładnie jednym potwierdzonym urządzeniu i zatrzymują się przy niejednoznacznym wyniku.
- read-only komenda `doctor` zbierająca aliasy portów, statusy discovery i rekomendacje naprawcze.

**Gotowe, gdy:** odczyt temperatur i przepływów jest stabilny przez minimum 24 godziny bez wpływu
na pracę centrali. CLI `monitor` automatyzuje read-only zapis snapshotów do JSONL i SQLite; samo
kryterium pozostaje niezweryfikowane do czasu uruchomienia go na fizycznym AirPack4.

## Etap 1 — niezależny rdzeń i symulator

- asynchroniczny klient RTU/TCP z timeoutem, retry i automatycznym ponownym łączeniem;
- deklaratywna, wersjonowana mapa rejestrów;
- grupowe odczyty i normalizacja typów;
- frameworkowo niezależne modele `DeviceState`, `Capabilities`, `Alarm` i `Command`;
- symulator Modbus z profilem AirPack4, dynamicznym przepływem i opcjonalnym błędem read-backu;
- testy jednostkowe dekodowania, braków czujników i błędów komunikacji.

**Gotowe, gdy:** wszystkie potwierdzone parametry są odczytywane, model stanu nie importuje
FastAPI ani Home Assistant, a testy działają bez fizycznej centrali.

## Etap 2 — bezpieczne sterowanie i jeden właściciel Modbus

- `DeviceCommandService` jako jedyna ścieżka zapisu;
- ON/OFF, prędkość, tryb, sezon, bypass i ERV tylko tam, gdzie potwierdzają je capabilities;
- walidacja zakresów, blokada równoległych zapisów, read-back i wersja stanu;
- idempotencja przez `request_id` oraz odrzucanie nieaktualnej wersji stanu;
- tryb tylko do odczytu, ręczne przejęcie kontroli i bezpieczny fallback;
- blokada uruchomienia dwóch właścicieli tej samej magistrali w dokumentacji i diagnostyce.

**Gotowe, gdy:** każde polecenie ma jednoznaczny rezultat i potwierdzenie, a utrata łączności nie
powoduje niekontrolowanych ponowień ani oscylacji.

### Pierwszy wycinek zaimplementowany

Szkielet zawiera już `AirPackController` z walidacją i read-back dla:

- trybu `automatic` / `manual` (4208) oraz atomowej aktywacji `temporary` (4400–4402);
- intensywności manualnej 10–100% (4210);
- intensywności chwilowej 10–100% (4211);
- trybów specjalnych, w tym kominka, wietrzenia i otwartych okien (4224);
- ON/OFF centrali (4387).

Wycinek wymaga również capability profilu przed zapisem i przechowuje wynik każdego zapisu
(źródło, żądana wartość, read-back oraz błąd). `request_id` pozwala bezpiecznie ponowić żądanie
(trwały cache ostatnich 256 wpisów z TTL), a `expected_revision` chroni przed nadpisaniem
nowszego stanu. Audyt, snapshoty i cache poleceń są już zapisywane w SQLite z retencją.
Gateway utrzymuje również procesową dzierżawę endpointu, więc drugi proces tego projektu jest
odrzucany przed otwarciem transportu.

Przed użyciem na fizycznym urządzeniu trzeba potwierdzić model, firmware i mapę przez etap 0.

`thessla_green.control` dostarcza już bezpieczny, frameworkowo niezależny arbiter priorytetów i
manual override. Nie uruchamia on jeszcze reguł opartych o CO₂/wilgotność/PM2.5, dopóki konkretne
rejestry i capabilities nie zostaną potwierdzone w dokumentacji oraz na urządzeniu.

## Etap 3 — Gateway i kontrakt FastAPI v1

- fabryka aplikacji FastAPI oddzielona od cyklu życia klienta Modbus;
- endpointy urządzeń, capabilities, stanu, telemetrii, alarmów i poleceń;
- WebSocket ze snapshotem, numerem sekwencji i procedurą reconnect;
- OpenAPI zapisane jako wersjonowany artefakt `docs/openapi-v1.json` oraz automatyczna kontrola
  breaking changes;
- uwierzytelnienie, role, rate limiting, jawny CORS i redakcja sekretów;
- SQLite, migracje, retencja telemetrii i kopia zapasowa;
- obraz kontenera i jednostka systemd; port szeregowy przekazywany jawnie.

### Dostępny wycinek 0.2.0

Gateway serwuje również lokalny panel `/` z odczytem snapshotu, sterowaniem typowanymi komendami
i widocznym read-backiem. Panel jest statycznym adapterem API i nie posiada własnego właściciela
Modbus. Gateway zapisuje snapshoty i audyt w SQLite z ograniczoną retencją oraz udostępnia
`/api/v1/devices/{device_id}/telemetry`. CLI `status`, `control` i `monitor` przyjmują te same
jednorazowe, bounded overrides endpointu co discovery, a błędy transportu są raportowane bez
tracebacku. Zdarzenia WebSocket niosą `sequence` równy rewizji snapshotu. Opcjonalne okno
`THESSLA_AIRFLOW_OBSERVATION_SECONDS` pozwala zebrać opóźnioną reakcję przepływu po potwierdzonym
zapisie, bez przedstawiania jej jako pomiaru RPM.

Polecenie `backup` wykonuje spójny backup lokalnego SQLite bez przejmowania portu Modbus i wymaga
`--force` przed zastąpieniem istniejącego pliku.

**Gotowe, gdy:** wszystkie codzienne operacje można wykonać przez API, test kontraktowy sprawdza
idempotencję i błędy, a ponowne uruchomienie nie gubi konfiguracji ani audytu.

## Etap 4 — integracja Home Assistant dystrybuowana przez HACS

- osobne repozytorium zawierające dokładnie jedną integrację w
  `custom_components/thessla_green`;
- `hacs.json`, kompletny `manifest.json`, README, licencja i wersjonowane release'y;
- `config_flow` dla połączenia z gatewayem, walidacja danych, reauth i reconfigure;
- wspólny `DataUpdateCoordinator` oraz mapowanie na `fan`, `sensor`, `binary_sensor`, `select` i
  `button`;
- stabilne `unique_id`, `DeviceInfo`, availability i encje zależne od capabilities;
- diagnostyka z usuniętymi sekretami, tłumaczenia PL/EN i poprawne unload/reload;
- testy jednostkowe integracji, HACS Action i Hassfest w CI;
- test instalacji przez HACS jako custom repository, a później zgłoszenie do domyślnego katalogu.

### Dostępny wycinek 0.2.15

Repozytorium zawiera instalowalny pakiet `custom_components/thessla_green` z config flow,
coordinatorem, fanem, sensorami, trybami, diagnostyką, wykrywaniem informacji o gatewayu w kreatorze
oraz automatycznie rejestrowanym panelem bocznym osadzającym `/ui/`. Integracja łączy się wyłącznie
z gatewayem; przed publikacją do katalogu domyślnego pozostają Hassfest, pełny test na czystym HA i
release Git.

**Gotowe, gdy:** czysta instalacja Home Assistant dodaje integrację wyłącznie przez UI, wszystkie
encje odtwarzają stan gatewaya, a sterowanie z HA kończy się tym samym potwierdzonym poleceniem co
API.

## Etap 5 — aplikacja mobilna Dart/Flutter

- typowany klient wygenerowany z zamrożonego OpenAPI v1;
- logowanie, bezpieczny magazyn tokenów, odnowienie sesji i wylogowanie;
- ekran stanu, alarmów, sterowania, historii i diagnostyki połączenia;
- obsługa offline oraz resynchronizacja snapshot + WebSocket po powrocie sieci;
- czytelne statusy poleceń `accepted`, `confirmed`, `rejected`, `expired`;
- powiadomienia jako sygnał do synchronizacji, nie źródło stanu;
- testy kontraktowe klienta Dart na tej samej specyfikacji co backend i HACS.

### Dostępny wycinek 0.2.0

`mobile/lib/thessla_gateway_client.dart` zawiera mały typed client REST/WebSocket z obsługą
`request_id`, `expected_revision`, telemetryki i potwierdzonego read-backu. Pierwszy ekran Flutter
znajduje się w `mobile/lib/main.dart` i korzysta z REST/pollingu. Pozostają secure storage tokenu,
retry/reconnect UI, WebSocket w ekranie oraz uruchomienie `flutter analyze` w CI mobilnym.

**Gotowe, gdy:** telefon nie pokazuje optymistycznie niepotwierdzonej wartości, retry nie wykonuje
polecenia drugi raz, a aplikacja odzyskuje aktualny stan po utracie sieci.

## Etap 6 — Google Home przez Home Assistant

- zatwierdzenie bezpiecznej listy encji do ekspozycji;
- mapowanie rekuperatora przede wszystkim jako `fan` z ON/OFF, procentem i bezpiecznymi presetami;
- udostępnienie wyłącznie obsługiwanych sensorów temperatury/jakości powietrza;
- instrukcja dla Home Assistant Cloud i ręcznej integracji Google Assistant;
- test poleceń głosowych, synchronizacji urządzeń, nazw pomieszczeń i zachowania offline;
- potwierdzenie, że awaria Google nie wpływa na lokalny gateway, HA ani automatykę.

**Gotowe, gdy:** użytkownik może bezpiecznie odczytać stan oraz zmienić wydajność przez Google
Home, a funkcje serwisowe i ryzykowne nie są eksponowane.

## Etap 7 — automatyka i dojrzałość operacyjna

- harmonogram bazowy i scenariusze obecność/nieobecność/noc;
- reguły temperatury, CO2, wilgotności i PM2.5 z histerezą;
- free-cooling, boost po kąpieli i profil kominkowy;
- priorytety, wyjaśnienie decyzji, czas wygaśnięcia trybu ręcznego i fallback;
- metryki, alerty, eksport diagnostyki, backup/restore i procedura aktualizacji;
- testy na danych historycznych oraz długotrwały test na fizycznej centrali.

**Gotowe, gdy:** automatyka nie oscyluje, każda decyzja ma czytelne uzasadnienie, a aktualizacja
każdego adaptera nie łamie pozostałych kanałów.

## Po MVP — decyzje produktowe, nie zobowiązania

- profil Direct HA, w którym integracja jest właścicielem Modbus;
- dodatek Home Assistant uruchamiający gateway;
- bezpośrednia integracja Google Cloud-to-cloud z OAuth, fulfillmentem, Report State i
  certyfikacją;
- Matter bridge po ocenie kompatybilności typu urządzenia;
- PostgreSQL i obsługa wielu instalacji.

## Najbliższy sprint

1. Uruchomić gateway 0.2.0 na potwierdzonym AirPack4 (firmware 4.85.16, unit 10) i wykonać
   kontrolowany test `manual` + 40% z read-backiem.
2. Zainstalować integrację HACS 0.2.0, dodać encję `fan` do dashboardu i potwierdzić przepływ
   nawiewu/wywiewu po zmianie nastawy.
3. Zapisać 24-godzinny test stabilności snapshotów jako kryterium wejścia do automatyki.
4. Dodać agregację/backup i test odtworzenia trwałej historii telemetrycznej w SQLite; zapis
   snapshotów, audytu i endpoint historii są już dostępne bez naruszania jednego właściciela
   Modbus.
5. Wygenerować klienta Dart z `docs/openapi-v1.json` (pierwszy handwritten client i ekran są już
   dostępne); instrukcja Google Home przez encje HACS jest opisana w `docs/GOOGLE_HOME.md`.

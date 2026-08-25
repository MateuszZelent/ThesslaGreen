# Architektura

## Założenia

System działa lokalnie nawet bez Internetu, zachowuje fabryczne zabezpieczenia centrali i rozdziela odczyt urządzenia od decyzji automatyki. Komunikacja może odbywać się przez Modbus RTU (RS-485/USB) albo Modbus TCP.

## Moduły

1. **Protocol** — połączenie, ponawianie prób, grupowe odczyty, kodowanie wartości, bezpieczne zapisy i ich potwierdzanie.
2. **Device** — ujednolicony model stanu rekuperatora niezależny od RTU/TCP oraz wersji firmware.
3. **Telemetry** — bieżący stan, historia, metryki jakości komunikacji, alarmy i audyt poleceń.
4. **Control** — tryb ręczny, harmonogram, reguły temperaturowe, histereza, minimalny czas pomiędzy zmianami oraz strategia awaryjna.
5. **API** — wersjonowane REST API do poleceń i konfiguracji, WebSocket/SSE do aktualizacji na żywo oraz uwierzytelnienie.
6. **Web UI** — dashboard, wykresy, tryb ręczny, reguły automatyki, alarmy i diagnostyka.
7. **Integrations** — Home Assistant/MQTT i przyszła aplikacja mobilna, korzystające wyłącznie z API.

## Docelowa struktura katalogów

```text
src/thessla_green/
  protocol/       # klient RTU/TCP, kodeki, mapa rejestrów
  device/         # stan urządzenia i serwis poleceń
  control/        # reguły i arbiter trybów
  telemetry/      # historia, zdarzenia i metryki
  api/            # FastAPI, REST i WebSocket
  config/         # ustawienia i migracje konfiguracji
web/              # aplikacja React/PWA
tests/
  unit/
  integration/
  simulator/      # symulator urządzenia Modbus
docs/
```

## Przepływ danych

Odczyt Modbus tworzy niezmienny `DeviceState`. Stan trafia równolegle do historii, API i silnika sterowania. Silnik generuje `ControlIntent`, ale zapis wykonuje wyłącznie `DeviceCommandService`, który waliduje zakres, ogranicza częstotliwość zmian, zapisuje rejestr, odczytuje go ponownie i zapisuje wynik w audycie.

## Priorytety sterowania

Od najwyższego:

1. zabezpieczenia urządzenia i lokalny panel producenta;
2. awaryjne zatrzymanie lub bezpieczny profil;
3. czasowy tryb ręczny użytkownika;
4. tryby specjalne, np. kominek lub intensywne wietrzenie;
5. automatyka jakości powietrza i wilgotności;
6. automatyka temperatury i harmonogram bazowy.

## Inteligentne sterowanie

Pierwsza wersja powinna być deterministyczna i łatwa do wyjaśnienia. Przykład:

- podstawowy bieg zależy od harmonogramu obecności;
- wysoka wilgotność lub CO₂ zwiększa wentylację;
- przy korzystnej temperaturze zewnętrznej można użyć free-coolingu/bypassu;
- przy dużym mrozie ograniczamy agresywne zmiany i respektujemy ochronę wymiennika;
- histereza temperatury i minimalny czas utrzymania biegu zapobiegają ciągłemu przełączaniu.

Uczenie maszynowe ma sens dopiero po zebraniu wiarygodnej historii i nie powinno bezpośrednio omijać warstwy bezpieczeństwa.

## API v1 — planowany kontrakt

```text
GET  /api/v1/status
GET  /api/v1/telemetry/current
GET  /api/v1/telemetry/history
GET  /api/v1/alarms
PUT  /api/v1/control/mode
PUT  /api/v1/control/fan-speed
PUT  /api/v1/control/bypass
GET  /api/v1/automation/rules
PUT  /api/v1/automation/rules
GET  /api/v1/events/stream       # WebSocket lub SSE
```

Polecenia zmieniające stan powinny przyjmować identyfikator żądania, zwracać stan potwierdzony z urządzenia i trafiać do dziennika audytowego.

## Wdrożenie

Jedna usługa backendowa i baza SQLite wystarczą na początek. Panel WWW może być serwowany przez backend. Docker Compose upraszcza instalację, ale dostęp do portu szeregowego musi być jawnie przekazany do kontenera. Dla dostępu zdalnego preferowany jest VPN lub reverse proxy z TLS i silnym uwierzytelnieniem.


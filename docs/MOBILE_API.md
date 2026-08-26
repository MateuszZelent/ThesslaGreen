# Kontrakt dla aplikacji Dart/Flutter

FastAPI udostępnia wersjonowany kontrakt pod `/api/v1`. Aplikacja mobilna nie otwiera Modbusa i
nie zapisuje rejestrów; korzysta z tego samego gatewaya co HACS.

## Synchronizacja stanu

1. Po uruchomieniu pobierz `GET /api/v1/devices`, a następnie
   `GET /api/v1/devices/{device_id}/state`.
2. Używaj `state.revision` jako wersji snapshotu i wyświetlaj wartości tylko z potwierdzonego
   stanu.
3. Otwórz `WS /api/v1/events` po udanym REST. Zdarzenie `state` zawiera `sequence` równy rewizji
   snapshotu. Po reconnect zawsze ponów pełny snapshot REST, dopiero potem przyjmuj zdarzenia
   WebSocket.
4. Historię rysuj z `GET /api/v1/devices/{device_id}/telemetry?from=&to=&limit=`; wynik może być
   pusty, gdy retencja została przekroczona.

## Polecenia

Wysyłaj jedną kopertę typowaną:

```json
{
  "type": "set_fan_speed",
  "parameters": {"percentage": 40},
  "request_id": "phone-installation-uuid-0001",
  "expected_revision": 12
}
```

Obsługiwane typy pierwszego zakresu to `set_mode`, `set_fan_speed`,
`set_temporary_fan_speed`, `set_special_mode` i `set_power`. Odpowiedź `status: confirmed` zawiera
`result.confirmed`, read-back oraz nowy snapshot. Dla zmian wentylacji/trybu/ON-OFF zawiera także
`result.airflow_observation` z chwilowym przepływem 256/257 i ostrożną informacją o zmianie próbki.
Nie aktualizuj suwaka optymistycznie przed tą odpowiedzią.

`request_id` musi być stabilny podczas retry tego samego żądania. Powtórzenie tej samej koperty
zwraca `replayed: true` i nie wykonuje drugiego zapisu, także po restarcie gatewaya (domyślny TTL
cache to 24 godziny). Ponowne użycie identyfikatora z innymi parametrami jest konfliktem. Błąd
`409` oznacza konflikt polecenia albo nieaktualny `expected_revision`, a `422` błąd walidacji.

## Generowanie klienta

FastAPI publikuje schemat pod `/openapi.json`; wersjonowany artefakt tego kontraktu znajduje się w
`docs/openapi-v1.json`. Po zatwierdzeniu zmiany kontraktowej wygeneruj klienta w oddzielnym
pakiecie mobilnym, np.:

```bash
openapi-generator-cli generate \
  -i http://127.0.0.1:8000/openapi.json \
  -g dart-dio \
  -o mobile/generated
```

Kod Flutter powinien przechowywać token w systemowym secure storage, a nie w zwykłym pliku
konfiguracyjnym. Powiadomienie push może tylko wybudzić synchronizację; źródłem prawdy pozostaje
REST/WebSocket gatewaya.

Natywny Android/iOS nie wymaga CORS. Jeśli ten sam klient jest budowany jako Flutter Web, dodaj
jego dokładny origin do `THESSLA_API_CORS_ORIGINS` po stronie gatewaya; pusta lista domyślnie
blokuje cross-origin żądania przeglądarkowe.

Pierwszy ekran znajduje się w `mobile/lib/main.dart`. Umożliwia konfigurację URL/tokena, odczyt
stanu, zmianę trybu, prędkości, presetów i ON/OFF oraz pokazuje przepływy. Dla prostoty odświeża
REST co pięć sekund; WebSocket i secure storage pozostają kolejnym krokiem. Wszystkie komendy
przekazują `expected_revision` i przyjmują stan dopiero z odpowiedzi `confirmed`.

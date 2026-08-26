# Dart/Flutter gateway client

This directory contains the first typed client for FastAPI v1. It is deliberately independent of
Flutter widgets so the same code can be used by a mobile UI, an integration test, or a background
sync task.

```bash
cd mobile
flutter create --platforms=android,ios,web .   # jednorazowo, generuje pliki platformowe
flutter pub get
flutter analyze
flutter run
```

Repozytorium przechowuje kod Dart i kontrakt klienta, ale nie przechowuje wygenerowanych plików
platformowych Fluttera. Jeśli potrzebujesz tylko analizy kodu, wystarczą `flutter pub get` i
`flutter analyze`.

`lib/main.dart` zawiera pierwszy prosty ekran: konfigurację URL/tokenu, stan centrali, tryb pracy,
nastawę manualną, aktualnie zadany nawiew/wywiew, tryby specjalne, ON/OFF oraz przepływy. Gdy
Ekran główny pokazuje zadane strumienie `supply_flowrate` i `extract_flowrate` zgodne z panelem
Air++. Chwilowe pomiary CF pozostają w `supply_airflow` i `extract_airflow`; gdy Constant Flow jest
nieaktywny, mają wartość niedostępną zamiast surowego `65535`. Po każdej
komendzie ekran przyjmuje
wyłącznie snapshot zwrócony przez gateway z potwierdzeniem read-back; nie zapisuje stanu
optymistycznie. Token jest obecnie używany tylko w pamięci procesu — bezpieczny magazyn systemowy
telefonu pozostaje kolejnym krokiem.

Na emulatorze `127.0.0.1` wskazuje emulator, nie komputer hosta. Użyj adresu hosta widocznego z
emulatora (np. `10.0.2.2` dla Android Emulator) albo adresu LAN gatewaya.

The client exposes state, capabilities, control options, telemetry, typed commands and the
WebSocket event stream. A command is considered applied only after `GatewayCommandResponse.confirmed`
is true. Keep the same `requestId` when retrying; the gateway persists it in SQLite and returns
`replayed: true` instead of writing twice.

The generated-client alternative remains supported: regenerate from
`../docs/openapi-v1.json` with `openapi-generator-cli -g dart-dio`. The handwritten client is kept
small for the first screen and avoids coupling the repository to a particular generator runtime.

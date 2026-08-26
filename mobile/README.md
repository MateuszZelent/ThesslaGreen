# Dart/Flutter gateway client

This directory contains the first typed client for FastAPI v1. It is deliberately independent of
Flutter widgets so the same code can be used by a mobile UI, an integration test, or a background
sync task.

```bash
cd mobile
flutter pub get
flutter analyze
flutter test
flutter build apk --release
```

## Budowa APK na Linuxie

`flutter pub get` pobiera biblioteki Darta, ale do APK potrzebne są jeszcze JDK 17 oraz
Android SDK. Samo ustawienie `ANDROID_HOME` nie instaluje SDK — ścieżka musi zawierać
`cmdline-tools`, platformę Android i build-tools.

Na Debianie/Ubuntu z uprawnieniami administratora:

```bash
sudo apt update
sudo apt install -y openjdk-17-jdk unzip curl
```

Następnie zainstaluj oficjalne Android Command-line Tools i wymagane pakiety SDK. Aktualny
plik dla Linuxa oraz sumę kontrolną można znaleźć na stronie
[Android Studio — Downloads](https://developer.android.com/studio#command-line-tools-only).
Przykład dla bieżącego pakietu:

```bash
mkdir -p /home/mateusz/Android/Sdk/cmdline-tools
cd /tmp
curl -fL -o commandlinetools-linux-15859902_latest.zip \
  https://dl.google.com/android/repository/commandlinetools-linux-15859902_latest.zip
echo '4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583  commandlinetools-linux-15859902_latest.zip' \
  | sha256sum -c -
mkdir -p /tmp/android-cli-tools
unzip -q commandlinetools-linux-15859902_latest.zip -d /tmp/android-cli-tools
mv /tmp/android-cli-tools/cmdline-tools /home/mateusz/Android/Sdk/cmdline-tools/latest

export ANDROID_SDK_ROOT=/home/mateusz/Android/Sdk
export ANDROID_HOME=/home/mateusz/Android/Sdk
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export PATH="/home/mateusz/flutter/flutter/bin:$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$ANDROID_SDK_ROOT/platform-tools:$PATH"

sdkmanager --sdk_root="$ANDROID_SDK_ROOT" \
  "platform-tools" "platforms;android-36" "build-tools;36.0.0"
yes | sdkmanager --sdk_root="$ANDROID_SDK_ROOT" --licenses
flutter config --android-sdk "$ANDROID_SDK_ROOT"
flutter doctor -v
```

Polecenie `sdkmanager` jest oficjalnym narzędziem do instalowania platform, build-tools i
licencji ([dokumentacja Androida](https://developer.android.com/tools/sdkmanager)). Po poprawnym
przejściu `flutter doctor -v` zbuduj aplikację:

```bash
cd /home/mateusz/git/ThesslaGreen/mobile
flutter pub get
flutter analyze
flutter test
flutter build apk --release
```

Wynik znajdzie się w `build/app/outputs/flutter-apk/app-release.apk`. Jeśli `sdkmanager` zgłosi,
że `build-tools;36.0.0` nie istnieje, uruchom `sdkmanager --list` i wybierz najnowszą dostępną
wersję `build-tools` oraz platformę `android-36` lub nowszą.

Katalog `android/` jest częścią aplikacji, aby można było zbudować instalowalny APK bez
generowania platformy w ostatniej chwili. Jeśli potrzebujesz tylko analizy kodu, wystarczą
`flutter pub get` i `flutter analyze`.

Manifest release zawiera `INTERNET` i zezwala na lokalny HTTP, ponieważ gateway może działać
pod adresem `http://...` w LAN. Nie wystawiaj takiego gatewaya bezpośrednio do Internetu; dla
dostępu spoza zaufanej sieci użyj VPN albo HTTPS.

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

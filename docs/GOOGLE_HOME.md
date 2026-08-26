# Google Home bez płatnej subskrypcji

Stan instrukcji: 26 sierpnia 2026. Procedura została sprawdzona z aktualną oficjalną dokumentacją
Home Assistant. Bezpłatny wariant nie wymaga Home Assistant Cloud ani dodatkowej licencji do
Thessla Green. Wymaga jednak własnego publicznego adresu HTTPS Home Assistanta i ręcznej
konfiguracji projektu Google Cloud-to-Cloud.

Nie instaluj integracji **Google Assistant SDK**. Służy ona do wysyłania poleceń i komunikatów
z Home Assistanta do urządzeń Google, a nie do udostępniania encji Home Assistanta w Google Home.
Do rekuperatora potrzebna jest wbudowana integracja YAML **Google Assistant** (`google_assistant`).

## Architektura

W zalecanym trybie HACS Home Assistant jest jedynym właścicielem portu Modbus:

```text
Google Home -> HTTPS -> Home Assistant -> Thessla Green HACS -> Modbus RTU -> AirPack
```

Google nigdy nie otrzymuje dostępu do Modbus. Steruje natywną encją `fan`, która przechodzi przez
ten sam koordynator, walidację i read-back co panel Home Assistanta.

## Co jest potrzebne

1. Działająca integracja HACS Thessla Green w trybie **Bezpośredni Modbus** albo działający
   zewnętrzny gateway wybrany świadomie w kreatorze.
2. Home Assistant dostępny z Internetu pod stałą nazwą DNS i poprawnym certyfikatem TLS, np.
   `https://ha.twojadomena.pl`. Sam adres `http://192.168.x.x:8123` nie wystarczy.
3. Konto Google używane również w aplikacji Google Home.
4. Dostęp do [Google Home Developer Console](https://console.home.google.com/) i
   [Google Cloud Console](https://console.cloud.google.com/).

Home Assistant Cloud jest opcjonalną, płatną drogą automatyczną. Poniższa procedura jest drogą
ręczną bez tej subskrypcji. DNS, domena lub reverse proxy mogą mieć własne koszty zależne od
wybranego dostawcy; protokół i integracja nie wymagają płatnej licencji.

## 1. Sprawdzenie encji Thessla Green

W Home Assistant otwórz **Narzędzia deweloperskie -> Stany** i znajdź rzeczywiste identyfikatory:

- `fan...` o nazwie **Rekuperator**;
- opcjonalnie `select...` o nazwie **Tryb pracy**;
- sensory temperatur, które chcesz odczytywać głosowo.

Najpierw sprawdź w HA:

1. włączenie i wyłączenie `fan`;
2. ustawienie np. 40%;
3. preset **Okap**, **Kominek** lub **Wietrzenie**;
4. zmianę `select` **Tryb pracy** na Automatyczny/Ręczny/Chwilowy.

Encja `fan` używa funkcji oficjalnie obsługiwanych przez Google Assistant: ON/OFF, procent
prędkości i preset. Nazwy presetów oraz opcji `select` są po polsku. Nie udostępniaj przycisków
serwisowych ani diagnostyki, których nie chcesz wywoływać głosem.

## 2. Publiczny HTTPS

Z sieci komórkowej telefonu sprawdź, czy otwiera się:

```text
https://ha.twojadomena.pl
```

Certyfikat musi być zaufany publicznie. Nie wystawiaj portu Modbus ani panelu FastAPI do Internetu.
Jeżeli używasz reverse proxy, kieruje ono ruch wyłącznie do Home Assistanta, zwykle na port 8123.

## 3. Projekt Google Home Cloud-to-Cloud

1. Otwórz [Google Home Developer Console](https://console.home.google.com/).
2. Wybierz **Create a project**, nadaj nazwę i zapisz `Project ID`.
3. Wybierz **Add a Cloud-to-Cloud integration**.
4. Przejdź przez **Next: Develop -> Next: Setup** i wybierz typy urządzeń.
5. Dodaj ikonę 144 x 144 px.
6. W sekcji **Account Linking** ustaw:

   - OAuth Client ID:
     `https://oauth-redirect.googleusercontent.com/r/TWOJ_PROJECT_ID`
   - Client Secret: dowolny ciąg bez znaków specjalnych;
   - Authorization URL: `https://ha.twojadomena.pl/auth/authorize`
   - Token URL: `https://ha.twojadomena.pl/auth/token`
   - Cloud fulfillment URL: `https://ha.twojadomena.pl/api/google_assistant`
   - scopes: osobno `email` oraz `name`;
   - opcję przesyłania Client ID/Secret w nagłówku HTTP Basic pozostaw wyłączoną.

7. Zapisz integrację. Może pozostać w stanie **Draft**; dla własnego konta nie trzeba jej
   publikować ani przechodzić certyfikacji produktu.

## 4. Konto serwisowe i HomeGraph API

1. Z projektu przejdź do **Google Cloud Console -> APIs & Services -> Credentials**.
2. Utwórz **Service account**.
3. Nadaj rolę **Service Accounts -> Service Account Token Creator**.
4. Otwórz utworzone konto, wybierz **Keys -> Add key -> Create new key -> JSON**.
5. Pobrany plik nazwij `SERVICE_ACCOUNT.json` i umieść w katalogu konfiguracji Home Assistanta,
   obok `configuration.yaml`. Nie dodawaj go do Git ani nie publikuj jego zawartości.
6. W tym samym projekcie wyszukaj i włącz **HomeGraph API**.

## 5. Konfiguracja Home Assistanta

W `configuration.yaml` dodaj konfigurację z rzeczywistymi identyfikatorami encji. Poniższe nazwy
są przykładami — sprawdź je w **Narzędzia deweloperskie -> Stany**:

```yaml
google_assistant:
  project_id: TWOJ_PROJECT_ID
  service_account: !include SERVICE_ACCOUNT.json
  report_state: true
  expose_by_default: false
  entity_config:
    fan.rekuperator:
      name: Rekuperator
      aliases:
        - Wentylacja
        - Centrala wentylacyjna
      room: Dom
      expose: true
    select.tryb_pracy:
      name: Tryb rekuperatora
      room: Dom
      expose: true
    sensor.temperatura_zewnetrzna:
      name: Temperatura zewnętrzna
      room: Dom
      expose: true
    sensor.temperatura_nawiewu:
      name: Temperatura nawiewu
      room: Dom
      expose: true
```

Użycie `expose_by_default: false` jest celowe: Google zobaczy tylko jawnie wymienione encje.
Najpierw uruchom **Sprawdź konfigurację**, a następnie zrestartuj Home Assistant.

Test endpointu z przeglądarki lub `curl`:

```text
https://ha.twojadomena.pl/api/google_assistant
```

Odpowiedź `405 Method Not Allowed` dla zwykłego GET potwierdza, że endpoint istnieje. `404`
oznacza, że integracja nie została załadowana lub reverse proxy nie przekazuje tej ścieżki.

## 6. Dodanie w aplikacji Google Home

1. Otwórz Google Home na koncie użytym w Developer Console.
2. Wejdź w **Urządzenia -> + Dodaj -> Działa z Google Home**.
3. Wybierz pozycję **[test] nazwa Twojej integracji**.
4. Zaloguj się do Home Assistanta i zaakceptuj powiązanie konta.
5. Przypisz rekuperator do pomieszczenia.
6. Powiedz „OK Google, zsynchronizuj moje urządzenia” albo uruchom w Home Assistant akcję
   `google_assistant.request_sync`.

Jeżeli skrót Home Assistanta został dodany do ekranu głównego telefonu jako aplikacja PWA,
oficjalna instrukcja zaleca chwilowe usunięcie go przed account linkingiem; inaczej przekierowanie
do Google Home może otworzyć PWA zamiast przeglądarki.

## 7. Testy głosowe

Najpierw sprawdź podstawowe komendy:

- „Włącz rekuperator”.
- „Ustaw rekuperator na 40 procent”.
- „Wyłącz rekuperator”.
- „Jaka jest temperatura nawiewu?”.

Presety wentylatora i encja `select` są domenami obsługiwanymi przez Google, ale dokładne polskie
frazy mogą zależeć od wersji Google Home. Jeżeli komenda trybu nie jest rozpoznawana, ustaw go
z aplikacji Google Home albo utwórz w HA prosty skrypt/scenę o jednoznacznej nazwie i wystaw ten
skrypt do Google jako scenę.

Po poleceniu sprawdź w Home Assistant encję **Ostatnie potwierdzone polecenie**. Komunikat Google
nie zastępuje odczytu zwrotnego urządzenia.

## Rozwiązywanie problemów

- Brak `[test] ...` w Google Home: konto Google nie ma dostępu do projektu albo projekt utworzono
  na innym koncie.
- Błąd 403 przy synchronizacji: zwykle nie włączono HomeGraph API.
- Błąd account linking: sprawdź publiczny HTTPS oraz trzy adresy `/auth/authorize`, `/auth/token`
  i `/api/google_assistant`.
- Nowe encje się nie pojawiają: wywołaj `google_assistant.request_sync`.
- Projekt testowy może okresowo wymagać odświeżenia synchronizacji; sterowanie istniejącymi
  urządzeniami zwykle nadal działa.

Źródło procedury: [oficjalna dokumentacja Google Assistant w Home Assistant](https://www.home-assistant.io/integrations/google_assistant/).

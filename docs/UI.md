# Panel webowy i integracja HACS

## Panel lokalny

Gateway serwuje prosty panel bez dodatkowego procesu Node/React:

```bash
python -m thessla_green serve
```

Otwórz `http://127.0.0.1:8000/`. Panel:

- pobiera jeden snapshot `/api/v1/state` i opcje `/api/v1/control/options`;
- odświeża stan co pięć sekund;
- pozwala zmienić tryb **Automatyczny**, **Ręczny** i **Chwilowy**, nastawę
  ręczną/chwilową, tryb specjalny oraz ON/OFF;
- prezentuje ręcznie dostępne tryby specjalne jako kafelki; najechanie, fokus klawiatury lub
  przytrzymanie dotykiem pokazuje opis, a zapis wymaga osobnego potwierdzenia przyciskiem;
- wysyła typowane komendy z `request_id` i `expected_revision`;
- pokazuje read-back (`requested_value`, `confirmed_value`, numer audytu);
- pokazuje nawiew i wywiew zgodny z panelem Air++: zadany strumień z rejestrów 274/275 w m³/h
  oraz intensywność z rejestrów 272/273 w %; chwilowy pomiar CF z 256/257 pozostaje osobnym
  parametrem diagnostycznym;
- ma zakładkę **Parametry** z filtrowaną tabelą wszystkich wartości bieżącego snapshotu,
  polskimi nazwami, jednostkami i kluczami API; nowe klucze pojawią się w tabeli automatycznie.

Motyw panelu korzysta z semantycznych tokenów CSS zdefiniowanych w jednym bloku `:root`:
granatowych powierzchni, niebieskiego akcentu, kolorów stanów oraz osobnych kolorów przepływów.
Komponenty i elementy SVG nie zawierają własnych literałów kolorów, co pozwala zmienić paletę bez
przeszukiwania całego arkusza. Test zasobów UI pilnuje tej zasady.

Schemat rozróżnia zezwolenie na bypass (`bypass_off=0`) od jego faktycznej aktywności
(`bypass_mode=1` dla freeheating albo `2` dla freecooling). Dopiero aktywny status zmienia
animowaną trasę nawiewu na kanał omijający wymiennik. `bypass_mode=0` pokazuje zamkniętą klapę,
nawet gdy funkcja bypassu jest dozwolona.
Gateway odczytuje dodatkowo cewkę `9`, czyli fizyczny stan siłownika klapy. Gdy `bypass_mode`
żąda pracy, ale cewka nadal wskazuje zamknięcie, panel pokazuje stan oczekiwania i nie wygasza
wymiennika przed faktycznym otwarciem klapy. Jeśli starszy firmware nie udostępnia cewki, UI
wraca do statusu logicznego i oznacza ograniczenie w danych parametrów.
Na środku animacji stale widoczny jest wskaźnik `BP WŁĄCZONY`, `BP OCZEKUJE`, `BP NIEAKTYWNY`
albo `BP WYŁĄCZONY`. Aktywny stan ma pulsujący punkt, wyróżnioną plakietkę, wygaszony wymiennik
oraz animowany kanał obejściowy; stan oczekiwania nie wygasza wymiennika przed potwierdzeniem
otwarcia cewką. Ten sam stan jest powtórzony w górnym pasku schematu.

Na wyrzutni nie jest prezentowana zmyślona temperatura: publiczny protokół nie udostępnia
czujnika powietrza za wymiennikiem po stronie wyrzutni. `fpx_temperature` jest pokazywana przy
czerpni jako temperatura za nagrzewnicą wstępną FPX, a `ambient_temperature` jako temperatura
otoczenia centrali (np. strychu).

Pod schematem są dwa moduły diagnostyczne wbudowanych nagrzewnic wersji Enthalpy. Moduł FPX
pokazuje aktywność systemu, stopień `FPX1`/`FPX2` oraz temperatury `TZ1 → TZ2`. Producent zaznacza,
że aktywność systemu FPX nie jest jednoznacznym potwierdzeniem zasilenia samej grzałki, dlatego UI
nie opisuje jej jako bezwarunkowo „włączonej”. Moduł ERV pokazuje rzeczywisty stan nagrzewnicy
wtórnej z `postHeater_on`, jej skonfigurowany tryb i temperaturę nawiewu `TN1`.

Publiczny protokół nie zawiera pomiaru mocy wbudowanych nagrzewnic. UI pokazuje tę informację
jawnie jako niedostępną i nie wykorzystuje `dac_heater` (input 1282), ponieważ jest to sterowanie
0–10 V opcjonalnej zewnętrznej nagrzewnicy kanałowej.

Po komendach zmiany trybu/prędkości/ON-OFF odpowiedź zawiera także `result.airflow_observation`:
wartości po read-backu oraz informację, czy przepływ zmienił się względem snapshotu sprzed komendy.
Brak zmiany w pojedynczej próbce nie jest błędem nastawy — wentylator może reagować z opóźnieniem;
protokół nie raportuje RPM. Jeżeli Constant Flow jest nieaktywny, wartość `0xffff` nie jest
pokazywana jako przepływ, tylko jako niedostępny pomiar.

Dla opóźnionej reakcji można ustawić `THESSLA_AIRFLOW_OBSERVATION_SECONDS` większe od zera.
Gateway wykona wtedy kolejne read-only próbki co `THESSLA_AIRFLOW_OBSERVATION_INTERVAL_SECONDS`
i zwróci `changed_within_window`, `observation_window_seconds` oraz `samples`. Read-back nastawy
pozostaje niezależnym, wymaganym potwierdzeniem zapisu.

Panel sterowania nie pokazuje wyboru EKO/KOMFORT, ponieważ opisana instalacja nie ma kanałowej
nagrzewnicy ani chłodnicy. Rejestry `4304-4305` pozostają odczytywane diagnostycznie i widoczne
w tabeli parametrów, ale nie zajmują miejsca w podstawowym sterowaniu ani nie sugerują dostępności
niezamontowanego osprzętu.

W panelu suwak działa zależnie od wybranego trybu. Dla **Ręcznego** zapisuje rejestr 4210,
a dla **Chwilowego** atomowo aktywuje blok `4400–4402` z wybraną intensywnością. Czas trwania
pochodzi z ustawień Air++ - publiczny protokół nie udostępnia osobnego rejestru czasu. Jeżeli
wybrany jest **Automatyczny**, przycisk wyraźnie informuje, że zapis nastawy najpierw przełączy
centralę na tryb ręczny. Panel przyjmuje wybrany tryb dopiero po potwierdzonym snapshotcie.
Przed wysłaniem komendy panel pobiera świeży snapshot, aby zwykły polling nie powodował
fałszywego konfliktu rewizji. Jeśli inny klient zmieni stan w tym samym momencie, gateway nadal
odrzuca zapis i panel pokazuje szczegóły konfliktu.

Historia snapshotów jest dostępna dla klienta mobilnego przez
`GET /api/v1/devices/{device_id}/telemetry?from=&to=&limit=`. Gateway zapisuje ją lokalnie w
SQLite (`THESSLA_DATABASE_URL`), z ograniczoną retencją; awaria zapisu historii nie blokuje
odczytu ani sterowania.

Panel nie raportuje RPM, bo dokument protokołu udostępnia przepływ w m³/h, a nie prędkość
obrotową wentylatora. W profilu standalone korzysta z gatewaya, a w profilu HACS z jednego
koordynatora będącego bezpośrednim właścicielem Modbus.

Adresy zasobów panelu są wersjonowane razem z wydaniem gatewaya, więc po aktualizacji przeglądarka
nie powinna użyć starego JavaScriptu z cache. Po zmianie wersji zrestartuj gateway i wykonaj twarde
odświeżenie strony.

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
3. Wyłącz starą integrację Modbus lub gateway zajmujący ten sam adapter.
4. W **Settings → Devices & services → Add integration** wybierz **Thessla Green**.
5. Wybierz **Bezpośredni Modbus (zalecane)**. Kreator pokaże porty widoczne wewnątrz Home
   Assistanta, podpowie stabilny `/dev/serial/by-id/...` i wykona read-only fingerprint.
6. Pozostaw `unit ID = 10`, `baudrate = 9600` i `8N1`, o ile sterownik nie został skonfigurowany
   inaczej. Potwierdź wykryty model, firmware i numer seryjny.
7. Po zapisaniu konfiguracji w bocznym menu pojawi się panel **Thessla Green** z tą samą grafiką
   animacji i sterowaniem. Nie wymaga URL, tokenu ani uruchomionego FastAPI.
8. Opcjonalnie dodaj do własnego dashboardu encję `fan`, sensory zadanej intensywności oraz
   sensory przepływu.

Tryb **Zewnętrzny gateway FastAPI** pozostaje dostępny dla instalacji, w których osobny proces
obsługuje aplikację mobilną i jest właścicielem Modbus. Tych trybów nie wolno łączyć dla tego
samego portu.

Integracja tworzy jeden coordinator i jedną grupę urządzenia. `fan` prezentuje potwierdzoną
nastawę ręczną/chwilową, binary sensor `Klapa bypassu` pokazuje fizyczny stan cewki 9,
binary sensory `System FPX` i `Nagrzewnica wtórna ERV` pokazują dostępne stany wraz z temperaturami
i stopniem/trybem w atrybutach, a osobne sensory prezentują bieżące zadanie nawiewu i wywiewu,
`select` tryb pracy/tryb specjalny, a sensor `Ostatnie potwierdzone polecenie` zawiera
szczegóły read-backu. W trybie bezpośrednim integracja używa dołączonego rdzenia protokołu oraz
jednego transportu PyModbus. Nie może działać równolegle z inną integracją Modbus tej centrali.

Panel boczny w trybie bezpośrednim pobiera snapshot z uwierzytelnionego endpointu HA i nie wykonuje
osobnego odczytu Modbus — sprzęt odpytuje wyłącznie coordinator. Polecenia wracają do tego samego
runtime'u i przechodzą read-back. W trybie zewnętrznym panel nadal osadza UI gatewaya.

### Karta dashboardu

Integracja rejestruje kartę **Thessla Green AirPack** bez ręcznego dodawania zasobu JavaScript.
W edycji dashboardu wybierz **Dodaj kartę**, wyszukaj jej nazwę i zatwierdź. Przy jednej centrali
karta sama pobiera identyfikator wpisu przez uwierzytelniony endpoint HA. Pokazuje ten sam schemat,
kontrolę procentową, tryby pracy i tryby specjalne co panel boczny.

Konfiguracja YAML odpowiadająca selektorowi:

```yaml
type: custom:thessla-green-card
height: 1200
```

Opcjonalne `entry_id` wybiera konkretną centralę w instalacji wielourządzeniowej. Zakres wysokości
wynosi 620–1600 px. Po pierwszej instalacji albo aktualizacji wykonaj `Ctrl+F5`, jeżeli przeglądarka
nie załadowała jeszcze nowego modułu karty.

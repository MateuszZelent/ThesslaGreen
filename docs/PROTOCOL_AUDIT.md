# Audyt zgodności z protokołem AirPack4

Data audytu: 2026-08-26  
Źródło: `docs/ProtokolModbusRTU_AirPack4.pdf`, tabela `MODBUS_USER_AirPack_4_08.2022.01`  
Zakres: protokół, discovery, gateway, FastAPI, Web UI, Flutter i adapter Home Assistant.

## Podsumowanie

Podstawowe parametry RTU, adresy rejestrów, zakresy nastaw oraz atomowa aktywacja trybu chwilowego
były zgodne z PDF-em. Audyt wykrył błędy w interpretacji bieżącej intensywności, wartości specjalnej
przepływu, numeru seryjnego, fingerprintu urządzenia i przekazywaniu konfiguracji CLI do serwera.
Pierwsza seria poprawek trafiła do `0.2.2`; rozdzielenie przepływów panelu Air++ od chwilowych
pomiarów CF zostało uzupełnione w `0.2.4` po porównaniu z fizycznym panelem urządzenia.

## Ustalenia i rozwiązania

### 0. Strumienie m³/h panelu Air++

PDF rozdziela chwilowe pomiary Constant Flow `256-257` od zadanych strumieni `274-275`.
Pierwsza implementacja publikowała tylko pomiary CF, dlatego przy nieaktywnym CF Web UI pokazywał
brak wartości mimo poprawnego wskazania m³/h na panelu Air++.

Rozwiązanie w `0.2.4`: gateway czyta blok `271-275`, publikuje jawny status
`constant_flow_active`, intensywności oraz `supply_flowrate` i `extract_flowrate`. Web UI, Flutter
i Home Assistant pokazują wartości panelu Air++ z `274-275`, zachowując `supply_airflow` i
`extract_airflow` jako oddzielną diagnostykę chwilowych pomiarów CF.

### 1. Bieżąca intensywność nawiewu i wywiewu

PDF definiuje rejestry input `0x0110/272` (`supply_percentage`) i `0x0111/273`
(`exhaust_percentage`) jako aktualnie zadane intensywności. Aplikacja prezentowała zamiast nich
zapisane nastawy manualną lub chwilową z `4210/4211`. Było to błędne w automacie i podczas funkcji
specjalnych.

Rozwiązanie: gateway odczytuje `272-273`, API publikuje `supply_percentage` i
`extract_percentage`, a Web UI i Flutter pokazują obie wartości. Home Assistant otrzymuje dwa
osobne sensory, ponieważ jego encja `fan` obsługuje tylko jedną wartość `0-100%`, natomiast AirPack
może w funkcjach specjalnych zadać asymetrycznie do `150%`. Zapisane nastawy pozostają osobnymi
polami sterującymi.

### 2. Wartość `0xffff` przepływu

Dla rejestrów input `0x0100/256` i `0x0101/257` wartość `65535` oznacza nieaktywny system
Constant Flow, a nie przepływ `65535 m3/h`.

Rozwiązanie: kodek zamienia `0xffff` na `null`; snapshot zawiera również
`constant_flow_available`. Niedostępny pomiar nie może już stanowić potwierdzenia fizycznej reakcji
wentylatorów.

### 3. Fingerprint discovery

Poprzedni fingerprint sprawdzał głównie człon major firmware i niepusty numer seryjny. Tak słabe
potwierdzenie mogło dopuścić zapis do innego urządzenia Modbus.

Rozwiązanie: discovery pozostaje całkowicie read-only i dodatkowo sprawdza długości bloków,
udokumentowane zakresy dnia tygodnia i okresu harmonogramu, temperatury `-999..999` lub `0x8000`,
format sześciu bajtów numeru seryjnego i format firmware. Dopiero komplet poprawnych dowodów daje
wynik `airpack` i udostępnia sterowanie.

### 4. Parametry `serve`

Zwykłe `serve --serial-port ...` tworzyło ustawienia z CLI, lecz uruchamiało globalną aplikację
zbudowaną ponownie z `.env`.

Rozwiązanie: każdy wariant `serve` przekazuje ten sam obiekt ustawień do `build_gateway()` i
`create_app()`. Jawny port, unit ID, baudrate i host Modbus nie są już tracone.

### 5. Numer seryjny

Przykład producenta łączy sześć wartości `001a 002b 003c 004d 005e 006f` w numer
`1a2b 3c4d 5e6f`. Poprzedni kodek wyświetlał sześć oddzielnych słów.

Rozwiązanie: publiczny numer seryjny ma format zgodny z PDF-em. Wewnętrzny `stable_id` nadal używa
dotychczasowego sześcioczłonowego tokenu, dzięki czemu aktualizacja nie duplikuje urządzenia i encji
w Home Assistant.

### 6. ON/OFF w aplikacji Flutter

Flutter porównywał numeryczne `power=0/1` bezpośrednio z wartością boolean.

Rozwiązanie: klient normalizuje zarówno `0/1`, jak i `false/true` przez właściwość `powerOn`.

### 7. Firmware testowy `9x.yz`

PDF opisuje firmware testowy jako `9x.yz`; poprzednia walidacja akceptowała tylko major równy `9`.

Rozwiązanie: fingerprint akceptuje udokumentowany zakres major `90-99` oraz produkcyjne `3` i `4`.

### 8. Ręczne wywoływanie trybów specjalnych

UI publikowało konserwatywny podzbiór trybów, lecz API i CLI przyjmowały też warianty opisujące
wejścia sprzętowe i harmonogram.

Rozwiązanie: polecenia API i CLI przyjmują wyłącznie podzbiór publikowany przez
`USER_SELECTABLE_SPECIAL_MODES`. Pełna mapa `0-11` nadal służy do poprawnego odczytu i diagnostyki
stanu centrali.

### 9. Override baudrate

Jednorazowy `--baudrate` dla `status` i `control` zmieniał listę discovery, ale nie baudrate
bezpośrednio budowanego endpointu.

Rozwiązanie: pojedynczy override aktualizuje równocześnie `baudrate` i `discovery_bauds`.

## Elementy potwierdzone jako zgodne

- RTU `9600 8/N/1`, domyślny adres urządzenia `10`.
- Firmware `0, 1, 4`, temperatury `16-22`, numer seryjny `24-29`.
- Chwilowe pomiary CF `256-257`, status CF `271`, bieżące intensywności `272-273` oraz zadane
  strumienie panelu Air++ `274-275`.
- Tryby `4208`, sezon `4209`, nastawy `4210-4211` i funkcje specjalne `4224`.
- EKO/KOMFORT `4304-4305`, bypass `4320/4330`, fizyczny siłownik bypassu (`coil 9`) i ON/OFF `4387`.
- Atomowy zapis Function 16 `[2, procent, 1]` do `4400-4402` dla trybu chwilowego.
- Brak surowego zapisu rejestru w API; zapisy są typowane, serializowane, audytowane i
  potwierdzane read-backiem.
- Discovery nie używa żadnej funkcji zapisu.

Wizualizacja od wersji `0.2.14` rozróżnia zezwolenie na pracę bypassu (`4320`), żądany tryb (`4330`)
oraz faktyczne położenie siłownika (`coil 9`). Nie przypisuje też `fpx_temperature` do wyrzutni: `TZ2` pozostaje na torze
czerpni, `TO` opisuje otoczenie centrali, a brak publicznego czujnika wyrzutni jest pokazany jawnie.

## Ograniczenia audytu

Audyt statyczny i testy symulatora nie zastępują próby na fizycznym AirPack4. W szczególności
rzeczywista reakcja Function 16 oraz zachowanie funkcji specjalnych powinny zostać sprawdzone na
urządzeniu przy wyłączonym innym właścicielu magistrali. Protokół nie publikuje RPM; fizyczną
reakcję można obserwować jako przepływ `m3/h` tylko wtedy, gdy Constant Flow jest aktywny.

## Walidacja wersji 0.2.14

- `pytest`: testy automatyczne zaliczone;
- `ruff`: bez błędów;
- `mypy`: bez błędów w 41 plikach;
- `git diff --check`: bez błędów;
- manifest HACS i artefakt OpenAPI: poprawny JSON, wersja `0.2.14`;
- wheel `thessla_green_controller-0.2.14-py3-none-any.whl`: zawiera zasoby Web UI.

Środowisko audytu nie zawierało Node.js ani Flutter SDK, dlatego nie wykonano `node --check` i
`flutter analyze`. Składnia oraz wymagane kontrakty tych adapterów są objęte testami statycznymi
repozytorium.

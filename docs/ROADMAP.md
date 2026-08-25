# Plan realizacji

## Etap 0 — rozpoznanie sprzętu

- ustalenie modelu centrali, sterownika i wersji firmware;
- potwierdzenie RTU/TCP, parametrów portu i identyfikatora urządzenia;
- pozyskanie oficjalnej mapy Modbus;
- bezpieczny zrzut rejestrów tylko do odczytu;
- lista wartości nieobsługiwanych (`0x8000`, błędy, zakresy).

**Gotowe, gdy:** odczyt temperatur i przepływów jest stabilny przez minimum 24 godziny bez wpływu na pracę centrali.

## Etap 1 — biblioteka urządzenia i pełna telemetria

- klient asynchroniczny RTU/TCP i automatyczne ponowne łączenie;
- deklaratywna, wersjonowana mapa rejestrów;
- grupowe odczyty i normalizacja typów;
- stan urządzenia, alarmy, diagnostyka i logowanie;
- symulator Modbus oraz testy bez fizycznej centrali.

**Gotowe, gdy:** wszystkie potwierdzone parametry są odczytywane i pokryte testami dekodowania.

## Etap 2 — bezpieczne sterowanie

- ON/OFF, prędkość, tryb, sezon, bypass i ERV (jeżeli dostępne);
- walidacja zakresów, blokada równoległych zapisów i read-back;
- tryb tylko do odczytu, ręczne przejęcie kontroli i audyt;
- testy na symulatorze, następnie kontrolowane testy na urządzeniu.

**Gotowe, gdy:** każde polecenie ma jednoznaczny rezultat, potwierdzenie i bezpieczne zachowanie po utracie łączności.

## Etap 3 — automatyka

- harmonogram bazowy i scenariusze obecność/nieobecność/noc;
- reguły temperatury domu i otoczenia z histerezą;
- opcjonalne CO₂, wilgotność, PM2.5 i sygnał otwarcia okien;
- free-cooling, boost po kąpieli i profil kominkowy;
- limity, priorytety, czas wygaśnięcia trybu ręcznego i fallback.

**Gotowe, gdy:** symulacja historycznych danych nie powoduje oscylacji, a każda decyzja ma czytelne uzasadnienie.

## Etap 4 — API i panel WWW

- FastAPI, OpenAPI, REST i strumień aktualizacji;
- dashboard stanu, wykresy, alarmy i historia;
- konfigurator reguł oraz sterowanie ręczne;
- użytkownicy, role, tokeny i zabezpieczenie przed nadużyciami.

**Gotowe, gdy:** wszystkie codzienne operacje wykonuje się bez konsoli i bez bezpośredniego dostępu do Modbus.

## Etap 5 — integracje i aplikacja mobilna

- PWA jako szybka wersja mobilna;
- MQTT/Home Assistant;
- stabilizacja i dokumentacja publicznego API;
- opcjonalnie aplikacja natywna korzystająca z tego samego API;
- powiadomienia o alarmach, filtrach i utracie łączności.

## Najbliższy sprint

1. Potwierdzić sprzęt i parametry Modbus.
2. Naprawić/ujednolicić kodowanie obecnego `main.py` i zamienić go w narzędzie diagnostyczne tylko do odczytu.
3. Zaimplementować klienta RTU z timeoutem, retry i odczytem pięciu temperatur.
4. Dodać surowy zrzut rejestrów do pliku JSONL oraz testy dekodowania `int16`.
5. Uruchomić 24-godzinny test stabilności.


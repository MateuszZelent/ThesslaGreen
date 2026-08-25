# ThesslaGreen Controller

Niezależny, lokalny moduł do odczytu, sterowania i automatyzacji rekuperatora Thessla Green przez Modbus RTU lub Modbus TCP.

## Cel projektu

Projekt ma zapewnić:

- odczyt wszystkich dostępnych temperatur, przepływów, stanów, alarmów i parametrów pracy;
- bezpieczne sterowanie wydajnością wentylatorów, trybami, sezonem, bypassem i pracą centrali;
- inteligentne sterowanie na podstawie temperatury wewnętrznej i zewnętrznej, jakości powietrza, wilgotności oraz harmonogramu;
- panel WWW działający w sieci lokalnej;
- stabilne API dla aplikacji mobilnej i innych systemów, np. Home Assistant;
- historię danych, diagnostykę oraz ręczne przejęcie kontroli.

## Stan obecny

Plik `main.py` jest zachowany jako pierwszy eksperyment komunikacji Modbus RTU po porcie szeregowym. Następny krok to potwierdzenie modelu centrali, interfejsu komunikacyjnego i mapy rejestrów na rzeczywistym urządzeniu.

## Architektura

```text
Rekuperator (Modbus RTU/TCP)
          |
          v
warstwa protokołu -> ujednolicony stan urządzenia -> silnik reguł
                              |                       |
                              +---- historia --------+
                              |
                         REST/WebSocket API
                         /                \
                    panel WWW         aplikacja mobilna
```

Najważniejsza zasada: tylko jedna usługa komunikuje się bezpośrednio z urządzeniem. UI, aplikacja mobilna i integracje korzystają z API, dzięki czemu nie konkurują o magistralę Modbus.

Szczegóły: [architektura](docs/ARCHITECTURE.md), [plan prac](docs/ROADMAP.md), [wstępna mapa rejestrów](docs/REGISTER_MAP.md).

## Proponowany stos

- Python 3.12+
- `pymodbus` — Modbus RTU i TCP
- FastAPI + WebSocket — API oraz dane na żywo
- SQLite na start, PostgreSQL opcjonalnie — konfiguracja i historia
- React/PWA — panel WWW i pierwszy interfejs mobilny
- Docker Compose — wdrożenie na Raspberry Pi, mini-PC lub serwerze domowym

## Uruchomienie deweloperskie

Na tym etapie repozytorium zawiera dokumentację i początkową definicję rejestrów. Kod produkcyjny będzie dodawany etapami zgodnie z roadmapą.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pytest
```

Konfigurację należy przechowywać w `.env` utworzonym na podstawie `.env.example`. Plik `.env` nie trafia do Git.

## Bezpieczeństwo sterowania

- Każdy zapis musi mieć walidację zakresu i odczyt potwierdzający.
- Po utracie czujników automatyka przechodzi do bezpiecznego, przewidywalnego trybu.
- Tryb ręczny ma pierwszeństwo i określony czas wygaśnięcia.
- Krytyczne zabezpieczenia fabryczne centrali nigdy nie są omijane.
- Dostęp spoza LAN wymaga uwierzytelnienia i TLS; nie wystawiamy Modbus bezpośrednio do Internetu.

## Repozytorium referencyjne

Inspiracją funkcjonalną jest [aLAN-LDZ/ThesslaGreen_HA](https://github.com/aLAN-LDZ/ThesslaGreen_HA). Na dzień przygotowania projektu repozytorium nie zawierało widocznego pliku licencji, dlatego nie kopiujemy z niego kodu. Adresy rejestrów traktujemy jako hipotezy techniczne do sprawdzenia z dokumentacją producenta i na urządzeniu.


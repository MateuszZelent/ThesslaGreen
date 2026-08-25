# Wstępna mapa rejestrów

Ta tabela jest hipotezą roboczą na podstawie obecnego eksperymentu i repozytorium referencyjnego. Przed włączeniem zapisów każdy adres, typ, zakres i znaczenie trzeba potwierdzić dla konkretnego modelu oraz firmware.

| Parametr | Obszar | Adres | Skala/zakres | Dostęp |
|---|---:|---:|---:|---|
| Temperatura zewnętrzna/czerpni | input | 16 | × 0,1 °C | odczyt |
| Temperatura nawiewu | input | 17 | × 0,1 °C | odczyt |
| Temperatura wywiewu | input | 18 | × 0,1 °C | odczyt |
| Temperatura za FPX | input | 19 | × 0,1 °C | odczyt |
| Temperatura PCB | input | 22 | × 0,1 °C | odczyt |
| Strumień nawiewu | holding | 256 | m³/h | odczyt |
| Strumień wywiewu | holding | 257 | m³/h | odczyt |
| Stan pracy | holding | 4208 | do ustalenia | odczyt |
| Sezon lato/zima | holding | 4209 | 0–1 | odczyt/zapis |
| Ręczna prędkość wentylatora | holding | 4210 | 0–100% | odczyt/zapis |
| Tryb specjalny | holding | 4224 | enum | odczyt/zapis |
| ECO/komfort | holding | 4304 | 0–1 | odczyt/zapis |
| Bypass | holding | 4320 | 0–1, semantyka do sprawdzenia | odczyt/zapis |
| Włączenie centrali | holding | 4387 | 0–1 | odczyt/zapis |
| Stan ERV | holding | 4704 | enum | odczyt |
| Tryb ERV | holding | 4711 | 0–2 | odczyt/zapis |

## Zasady walidacji

- Temperatury dekodujemy jako signed `int16`; `0x8000` może oznaczać brak czujnika.
- Nie zakładamy, że wartości logiczne mają wszędzie tę samą polaryzację — szczególnie dla bypassu.
- Pierwszy test każdego zapisu wykonujemy pojedynczo, z odczytem wartości przed i po oraz możliwością natychmiastowego powrotu.
- Nie skanujemy agresywnie całej przestrzeni rejestrów i nie zapisujemy do nieznanych adresów.


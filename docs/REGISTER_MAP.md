# Mapa rejestrów AirPack4

Poniższy wycinek został przepisany z dostarczonego dokumentu
`docs/ProtokolModbusRTU_AirPack4.pdf` (wersja tabeli 08.2022.01). Adresy są zapisane jako wartości
zero-based używane przez PyModbus. Dokument producenta podaje bazową komunikację RTU `9600 8/N/1`
i adres urządzenia `10`.

## Identyfikacja i telemetria — tylko odczyt

| Parametr | Obszar / funkcja | Adres hex | Adres dec. | Kodowanie | Dostęp |
|---|---|---:|---:|---|---|
| Firmware major (`MM`) | input / 04 | `0x0000` | 0 | uint16 | R/- |
| Firmware minor (`mm`) | input / 04 | `0x0001` | 1 | uint16 | R/- |
| Firmware patch (`pp`) | input / 04 | `0x0004` | 4 | uint16 | R/- |
| Temperatura zewnętrzna (`TZ1`) | input / 04 | `0x0010` | 16 | signed int16 × 0,1 °C | R/- |
| Temperatura nawiewu (`TN1`) | input / 04 | `0x0011` | 17 | signed int16 × 0,1 °C | R/- |
| Temperatura wywiewu (`TP`) | input / 04 | `0x0012` | 18 | signed int16 × 0,1 °C | R/- |
| Temperatura za FPX (`TZ2`) | input / 04 | `0x0013` | 19 | signed int16 × 0,1 °C | R/- |
| Temperatura za nagrzewnicą (`TN2`) | input / 04 | `0x0014` | 20 | signed int16 × 0,1 °C | R/- |
| Temperatura GWC (`TZ3`) | input / 04 | `0x0015` | 21 | signed int16 × 0,1 °C | R/- |
| Temperatura otoczenia (`TO`) | input / 04 | `0x0016` | 22 | signed int16 × 0,1 °C | R/- |
| Numer seryjny 1–6 | input / 04 | `0x0018–0x001D` | 24–29 | sześć słów hex | R/- |
| Chwilowy nawiew | input / 04 | `0x0100` | 256 | m³/h | R/- |
| Chwilowy wywiew | input / 04 | `0x0101` | 257 | m³/h | R/- |

Wartość `0x8000` w rejestrach temperatur oznacza brak odczytu czujnika. Nie należy zamieniać jej
na `-3276,8°C`.

## Podstawowe sterowanie — odczyt i zapis

| Parametr | Obszar / funkcja | Adres hex | Adres dec. | Zakres | Dostęp |
|---|---|---:|---:|---|---|
| Tryb pracy (`mode`) | holding / 03 | `0x1070` | 4208 | 0 auto, 1 manual, 2 chwilowy | R/W |
| Sezon (`seasonMode`) | holding / 03 | `0x1071` | 4209 | 0 lato, 1 zima | R/W |
| Intensywność manualna (`airFlowRateManual`) | holding / 03 | `0x1072` | 4210 | 10–100% | R/W |
| Intensywność chwilowa (`airFlowRateTemporary`) | holding / 03 | `0x1073` | 4211 | 10–100% | R/W |
| Tryb specjalny (`specialMode`) | holding / 03 | `0x1080` | 4224 | 0–11 | R/W |
| EKO/KOMFORT (`comfortModePanel`) | holding / 03 | `0x10D0` | 4304 | 0 EKO, 1 KOMFORT | R/W |
| Dezaktywacja bypassu (`bypassOff`) | holding / 03 | `0x10E0` | 4320 | 0 aktywny, 1 nieaktywny | R/W |
| ON/OFF centrali (`onOffPanelMode`) | holding / 03 | `0x1123` | 4387 | 0 OFF, 1 ON | R/W |
| Aktywacja chwilowa: tryb (`cfgMode1`) | holding / 16 | `0x1130` | 4400 | wartość 2 | R/W |
| Aktywacja chwilowa: intensywność | holding / 16 | `0x1131` | 4401 | 10–100% | R/W |
| Aktywacja chwilowa: flaga | holding / 16 | `0x1132` | 4402 | wartość 1 | R/W |

Aktywacja trybu chwilowego wymaga według producenta jednego zapisu Function 16 całego bloku
`4400–4402` z wartościami `[2, intensywność, 1]`. Nie wolno zastępować tej operacji trzema
niezależnymi zapisami. Publiczna mapa z PDF nie zawiera rejestru czasu trwania trybu chwilowego;
czas pozostaje ustawieniem sterownika/panelu Air++.

## Tryby specjalne

`specialMode` ma wartości: `0` brak, `1` okap, `2` kominek, `3` wietrzenie przełącznikiem
dzwonkowym, `4` wietrzenie przełącznikiem ON/OFF, `5` higrostat, `6` czujnik jakości powietrza,
`7` wietrzenie ręczne, `8` wietrzenie automatyczne, `9` wietrzenie harmonogramu, `10` otwarte okna,
`11` pusty dom.

## Zasady zapisu

- Automatyczne wykrywanie używa wyłącznie funkcji odczytu `04` i nie zmienia stanu centrali.
- Zwykły zapis wykonujemy pojedynczo, z odczytem wartości przed i po; udokumentowany blok
  aktywacji chwilowej zapisujemy atomowo Function 16 i potwierdzamy odczytem `4208–4211`.
- Nie zapisujemy do adresów nieznanych ani do rejestru poziomu dostępu podczas skanowania.
- Semantykę i zakres należy ponownie potwierdzić dla konkretnego modelu oraz firmware przed
  włączeniem produkcyjnego sterowania.

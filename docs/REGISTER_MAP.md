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
| Temperatura powietrza usuwanego z pomieszczeń (`TP`) | input / 04 | `0x0012` | 18 | signed int16 × 0,1 °C | R/- |
| Temperatura powietrza za nagrzewnicą wstępną FPX (`TZ2`) | input / 04 | `0x0013` | 19 | signed int16 × 0,1 °C | R/- |
| Temperatura za nagrzewnicą (`TN2`) | input / 04 | `0x0014` | 20 | signed int16 × 0,1 °C | R/- |
| Temperatura GWC (`TZ3`) | input / 04 | `0x0015` | 21 | signed int16 × 0,1 °C | R/- |
| Temperatura otoczenia centrali (`TO`, np. strych) | input / 04 | `0x0016` | 22 | signed int16 × 0,1 °C | R/- |
| Numer seryjny 1–6 | input / 04 | `0x0018–0x001D` | 24–29 | sześć bajtów w słowach, łączonych parami | R/- |
| Chwilowy nawiew | input / 04 | `0x0100` | 256 | m³/h | R/- |
| Chwilowy wywiew | input / 04 | `0x0101` | 257 | m³/h | R/- |
| Status Constant Flow | input / 04 | `0x010F` | 271 | 0 nieaktywny, 1 aktywny | R/- |
| Zadana intensywność nawiewu | input / 04 | `0x0110` | 272 | 0-150% | R/- |
| Zadana intensywność wywiewu | input / 04 | `0x0111` | 273 | 0-150% | R/- |
| Zadany strumień nawiewu (`supply_flowrate`) | input / 04 | `0x0112` | 274 | 0-4095 m³/h | R/- |
| Zadany strumień wywiewu (`extract_flowrate`) | input / 04 | `0x0113` | 275 | 0-4095 m³/h | R/- |
| System przeciwzamrożeniowy FPX (`antifreezMode`) | holding / 03 | `0x1060` | 4192 | 0 nieaktywny, 1 aktywny | R/- |
| Stopień systemu FPX (`antifreezStage`) | holding / 03 | `0x1066` | 4198 | 0 OFF, 1 FPX1, 2 FPX2 | R/- |
| Stan wbudowanej nagrzewnicy wtórnej ERV (`postHeater_on`) | holding / 03 | `0x1260` | 4704 | 0 nieaktywna, 1 aktywna; od firmware 4.85 | R/- |
| Konfiguracja nagrzewnicy wtórnej ERV (`cfgPostHeaterMode`) | holding / 03 | `0x1267` | 4711 | 0 wyłączona, 1 tryb 1, 2 tryb 2 | R/- |

Wartość `0x8000` w rejestrach temperatur oznacza brak odczytu czujnika. Nie należy zamieniać jej
na `-3276,8°C`.
Publiczna mapa nie zawiera czujnika temperatury wyrzutni za wymiennikiem. `TZ2` nie może być
używane jako jego zamiennik, ponieważ mierzy tor czerpni za nagrzewnicą FPX.

Wartość `0xffff` w rejestrach przepływu `256-257` oznacza nieaktywny Constant Flow i jest
publikowana przez gateway jako `null`, a nie `65535 m³/h`. Rejestry `272-273` opisują aktualnie
zadaną intensywność i nie są tym samym co zapisane nastawy manualna/chwilowa `4210-4211`.
Rejestry `274-275` zawierają zadany strumień m³/h prezentowany przez panel Air++. Nie należy
zastępować ich chwilowymi pomiarami CF z `256-257`; API publikuje obie pary osobno.

`antifreezMode` informuje o aktywności całego systemu FPX, a nie o rzeczywistym zasileniu elementu
grzejnego. `antifreezStage` pozwala pokazać stopień FPX1/FPX2, lecz również nie jest pomiarem mocy.
Stan wbudowanej nagrzewnicy wtórnej ERV można odczytać jednoznacznie z `postHeater_on`.
Publiczna mapa Modbus nie udostępnia procentowej ani elektrycznej mocy żadnej z tych wbudowanych
nagrzewnic. Rejestru input `1282` (`dac_heater`, sygnał 0–10 V) nie używamy, ponieważ dotyczy
zewnętrznej nagrzewnicy kanałowej, której ta instalacja nie posiada.

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

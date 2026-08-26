# Google Home przez Home Assistant

W MVP Google Home nie łączy się z Modbusem ani z gatewayem bezpośrednio. Używa encji z
integracji HACS, a gateway pozostaje jedynym właścicielem centrali:

```text
Google Home -> Home Assistant -> Thessla Green HACS -> FastAPI gateway -> Modbus
```

## Bezpieczna lista encji

Na początek wystaw tylko:

- encję `fan` rekuperatora — ON/OFF, procent wydajności i zweryfikowane presety;
- temperaturę zewnętrzną, nawiewu, wywiewu i otoczenia jako sensory tylko do odczytu.

Nie wystawiaj do Google surowych rejestrów, diagnostyki, przycisków serwisowych ani encji,
których semantyka nie została potwierdzona na konkretnym firmware. Presety dostępne w `fan` są
ograniczone do opcji ręcznie wywoływalnych przez rdzeń (`none`, `fireplace`, `airing_manual`,
`open_windows`, `empty_house` i `hood`); testuj je pojedynczo, zanim udostępnisz je domownikom.

## Konfiguracja

1. Najpierw dodaj i przetestuj integrację Thessla Green w Home Assistant. Z panelu HA wykonaj
   zmianę procentu i sprawdź `last_command`, `confirmed_value` oraz przepływ nawiewu/wywiewu.
2. W Home Assistant otwórz **Settings → Voice assistants → Expose** i zaznacz wyłącznie wybrane
   encje dla Google Assistant. Ekspozycja jest jawna — encje nie są automatycznie udostępniane.
3. Skonfiguruj oficjalną integrację Google Assistant: Home Assistant Cloud (najprostsze dla
   dostępu spoza LAN) albo ręczne konto Google Assistant z HTTPS, OAuth/account linking i
   publicznym fulfillmentem.
4. W aplikacji Google Home wykonaj synchronizację urządzeń, przypisz rekuperator do pomieszczenia
   i ustaw krótką nazwę oraz ewentualne aliasy.

Aktualne ekrany i wymagania integracji zmieniają się po stronie Home Assistant/Google, dlatego
korzystaj z ich dokumentacji:

- [Home Assistant: Google Assistant](https://www.home-assistant.io/integrations/google_assistant)
- [Home Assistant: ekspozycja encji dla asystentów](https://www.home-assistant.io/voice_control/voice_remote_expose_devices/)

## Test i awarie

Przetestuj kolejno „włącz rekuperator”, „ustaw 40 procent” i odczyt temperatury. Po każdym
poleceniu sprawdź w HA stan encji i `GET /api/v1/audit`; nie uznawaj samego komunikatu Google za
potwierdzenie zapisu. Przy braku odpowiedzi gatewaya encja powinna stać się niedostępna, a Google
nie może wykonywać ponowień poza `request_id` obsługiwanym przez gateway.

Utrata Internetu, Google Home lub Home Assistant nie może zatrzymać lokalnego gatewaya ani zmienić
jego polityki bezpieczeństwa. Bezpośredni Google Cloud-to-cloud, Report State, Request Sync i
certyfikacja pozostają osobnym etapem po ustabilizowaniu profilu HACS.

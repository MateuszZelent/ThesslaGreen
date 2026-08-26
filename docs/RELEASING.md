# Wydawanie wersji HACS

HACS powinien aktualizować instalacje z pełnych GitHub Releases, a nie z każdego commita na
`main`. Wydanie jest tworzone przez workflow **Publish HACS release**.

## Przygotowanie wersji

1. Zmień wersję w artefaktach sprawdzanych przez `scripts/verify_release_version.py`.
2. Uruchom lokalnie:

   ```bash
   python scripts/verify_release_version.py 0.3.1
   pytest -q
   ```

3. Zacommituj i wypchnij zmiany do `main`.
4. W GitHub otwórz **Actions -> Publish HACS release -> Run workflow**.
5. Wybierz gałąź `main`, podaj wersję bez prefiksu `v`, np. `0.3.1`, i uruchom workflow.

Workflow odrzuci wydanie z innej gałęzi lub z niespójnymi numerami. Następnie uruchomi testy,
Ruff, mypy, Hassfest i walidację HACS. Dopiero po ich powodzeniu utworzy tag `v0.3.1` oraz pełny
GitHub Release z automatycznie wygenerowanymi informacjami o zmianach.

GitHub udostępnia archiwum źródłowe release automatycznie. Ponieważ integracja znajduje się w
`custom_components/thessla_green`, HACS pobierze ją z tego archiwum bez dodatkowego pliku ZIP.

## Automatyczna instalacja w Home Assistant

Na docelowym Home Assistant działa automatyzacja
**Thessla Green - automatyczna aktualizacja HACS**. Po pojawieniu się nowej wersji encji
`update.thessla_green_update_2` automatyzacja:

1. tworzy lokalną kopię Home Assistanta;
2. wywołuje `update.install`;
3. odczekuje 30 sekund;
4. restartuje Home Assistant Core.

Automatyzacja dotyczy wyłącznie repozytorium `MateuszZelent/ThesslaGreen` i nie instaluje
automatycznie innych aktualizacji HACS.

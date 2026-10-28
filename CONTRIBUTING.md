# Współtworzenie AI Subtitle Studio

Rozwijamy prototyp lokalnego narzędzia do transkrypcji i review napisów. Obecny priorytet to trafność oryginalnego JP, porównania ASR oraz zachowanie czasów i ręcznych poprawek.

## Praca nad kodem

1. Przygotuj środowisko według [README](README.md) i zainstaluj `requirements-dev.txt`.
2. Utwórz gałąź dla swojej zmiany, np. `git switch -c improve-asr-review`.
3. Opisz problem i oczekiwany wynik. Zmiany zachowania powinny mieć odpowiednią weryfikację.
4. Uruchom `.\.venv\Scripts\python.exe -m pytest -q` i podaj wynik przy przekazywaniu poprawki.

Kod interfejsu i pipeline jest w `studio/`, testy w `tests/`, a narzędzia diagnostyczne i testy sprzętowe w `tools/`. Małe przykłady syntetyczne są w `samples/`.

W zmianach ASR zachowuj źródłowe wyniki i pochodzenie decyzji. Nie nadpisuj ręcznych poprawek ani nie przedstawiaj zgodności modeli jako dowodu poprawności. Oddzielaj test działania pipeline od pomiaru jakości na niezależnej referencji. Przy testach sprzętowych podaj model, runtime, backend, długość nagrania, czas wykonania i informację o użyciu cache.

## Zgłaszanie błędów

Podaj wersję Pythona, system, GPU, używany model i runtime, kroki odtworzenia oraz wynik oczekiwany i rzeczywisty. Dołącz krótki fragment logu po usunięciu prywatnych ścieżek i danych. Przy problemach z jakością ASR pomocny jest krótki fragment audio wraz z referencją, jeśli możesz go udostępnić.

Nie dodawaj do Git wag modeli, nagrań, cache, ustawień użytkownika ani baz prywatnych projektów. Przed commitem sprawdź `git status` i `git diff --cached`. Media oraz modele udostępniaj wyłącznie zgodnie z ich własnymi licencjami.

Wkład w oryginalny kod i dokumentację projektu jest przyjmowany na tej samej licencji MIT co projekt. Przy dodawaniu cudzego kodu zachowaj jego informacje o autorach i licencji.

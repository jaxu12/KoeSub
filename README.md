# AI Subtitle Studio

**Projekt open source • licencja MIT • działający prototyp na Windows**

Budujemy lokalną aplikację, która przeprowadzi nagranie od rozpoznawania mowy do sprawdzonych, czytelnych napisów. Obecnie skupiamy się na **japońskiej transkrypcji oryginału**: porównywaniu modeli, składaniu trafniejszych fragmentów i review przed tłumaczeniem.

Chcemy ograniczyć ręczne poprawianie, a jednocześnie pokazywać, skąd pochodzi tekst i gdzie modele się nie zgadzają. Projekt rozwijamy krok po kroku, sprawdzając go na prawdziwych nagraniach. To prototyp; automatyczny wynik nadal może wymagać odsłuchu.

## Co już działa

- Edytor napisów JP/EN z filmem, waveformem, odsłuchem fragmentów, cofaniem zmian i zapisem projektów w SQLite.
- Lokalna transkrypcja Whisper Large V3 przez whisper.cpp/CrispASR, VAD i jawny wybór backendu GPU. Inne modele mogą dostarczać pomocnicze hipotezy.
- Automatyczny przebieg JP: **audio → Large V3 → ponowienie podejrzanych wycinków → review fraz → układ → SRT i raport**.
- Porównanie fraz z kontekstem i czasami. Zgodne fragmenty ponowień mogą poprawić bazę; spory pozostają do odsłuchu. Czasy i ręcznie sprawdzone napisy są chronione.
- Review czytelności, czasów, nakładania i długości napisów; import/eksport SRT, ASS, SSA i TXT.
- Opcjonalne tłumaczenie lokalnym modelem GGUF przez llama.cpp. LM Studio jest dodatkowym backendem. Domyślny tryb JP pomija tłumaczenie i LLM.
- Logi, pochodzenie zmian, checkpointy, anulowanie i wznawianie etapów.

Zgodność modeli nie jest dowodem poprawności. Review porównuje teksty uzyskane z audio; nie ma niezależnej wiedzy o tym, co naprawdę powiedziano. Obsługa konkretnego modelu zależy również od jakości jego konwersji i wyrównania czasów.

## Uruchomienie

Testowane środowisko: **Windows, Python 3.12 x64**. Interfejs korzysta z PySide6. Modele i zewnętrzne silniki instaluje się osobno.

1. Pobierz kod i otwórz folder projektu.
2. Uruchom `Instaluj.bat`, a następnie `Uruchom.bat`.
3. W ustawieniach wskaż FFmpeg, właściwy runtime ASR i lokalne modele. Wybierz backend obsługiwany przez zainstalowany runtime.
4. Ustaw katalog cache na dysku z odpowiednim zapasem miejsca, np. `D:\models\.cache`.
5. Zaimportuj nagranie i wybierz preset **„Transkrypcja JP • Large V3 + wycinki”**. Na pierwszy test ustaw krótki fragment.

Instalator dodaje biblioteki aplikacji. **Nie pobiera wag modeli.** Do obejrzenia edytora bez modeli służy przycisk **Przykład**, korzystający z małych syntetycznych napisów w `samples/`.

Możesz też przygotować środowisko ręcznie:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements.txt
.\.venv\Scripts\python.exe -m studio
```

Konfigurację lokalnych silników i modeli opisuje [MODEL_SETUP.md](MODEL_SETUP.md). Dokument zawiera również ustawienia maszyny używanej do rozwoju; ścieżki należy dostosować do swojego komputera. Aktualne testy sprzętowe wykonujemy na CUDA.

## Modele, nagrania i miejsce na dysku

Repozytorium zawiera kod, dokumentację, testy i syntetyczne przykłady napisów. Modele, pliki wykonywalne silników, nagrania, cache i prywatne projekty nie są dołączone. Aplikacja korzysta z istniejących plików modeli bez kopiowania wag. Osobne skrypty `tools/fetch_*.py` służą do jawnego pobierania wybranych modeli; nie są uruchamiane automatycznie przez interfejs.

Przed zadaniem sprawdzany jest zapas miejsca. Cache nie ma jeszcze automatycznego limitu całkowitego rozmiaru. Materiały testowe i wagi mają własne zasady udostępniania — zobacz [THIRD_PARTY.md](THIRD_PARTY.md).

## Testy i wyniki

```powershell
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Obecny zestaw: **156 testów automatycznych**. Obejmuje edytor, zapis projektów, ochronę ręcznych zmian, porównania ASR, review fraz, kolejność etapów, eksport i wznowienie. Zwykłe testy nie wymagają modeli ani GPU. Oddzielne skrypty testów sprzętowych w `tools/` wymagają lokalnych modeli i mediów.

Przykłady rzeczywistych testów oraz ich ograniczenia:

- [Review oryginału i składanie fraz JP](JP_SOURCE_REVIEW.md)
- [Tryb JP, wycinki audio i referencje](JP_TRANSCRIPTION_AND_REFERENCES.md)
- [Kotoba i poprawki po pełnym przebiegu](KOTOBA_AND_FIXES.md)

Raporty rozwojowe zawierają historyczne wyniki i odnośniki do plików na komputerze testowym. Te lokalne artefakty nie są częścią repozytorium. Opis procedury i ograniczeń pozostaje dostępny w dokumentacji.

## Dalszy rozwój

Najbliższy kierunek to lepszy wybór fragmentów oryginalnej transkrypcji, kontrola na niezależnych referencjach i ograniczenie kosztu ponowień ASR. Później wracamy do jakości tłumaczenia i spójności całych napisów. Separacja głosu, automatyczna synchronizacja względem audio, kolejka filmów i instalator EXE pozostają do zrobienia.

Pomysły, poprawki i testy na kolejnych nagraniach są mile widziane. Zasady pracy i zgłaszania błędów: [CONTRIBUTING.md](CONTRIBUTING.md). Szczegółowe notatki z wcześniejszych etapów: [DEVELOPMENT_NOTES.md](DEVELOPMENT_NOTES.md).

## Licencja

Własny kod i dokumentacja projektu są udostępniane na licencji **[MIT](LICENSE)**. Zależności, zewnętrzne silniki, modele i materiały źródłowe zachowują własne licencje. Projekt nie jest oficjalnym produktem twórców używanych modeli ani Subtitle Edit.

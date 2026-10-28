# Testy AI Subtitle Studio — 28.10.2026

## Wynik

**94 testy automatyczne zaliczone (6,70 s).** Ponadto zaliczono rzeczywisty pełny pipeline GPU, panel propozycji AI, zapis SQLite, anulowanie lokalnego modelu, waveform, eksport i odtwarzanie filmu. Testy sprzętowe używały istniejących modeli i osobnych projektów. Nie pobierano nowych modeli.

## Znaleziony i naprawiony błąd

Pierwszy rzeczywisty przebieg ujawnił chwilowy `PermissionError` przy odczycie `manifest.json` na Windows. Obliczenia i eksport zakończyły się, ale interfejs zgłosił błąd odczytu checkpointu. Dotychczas ponawiany był atomowy zapis, nie odczyt.

Dodano współdzielony odczyt JSON z ograniczonym ponawianiem krótkich blokad Windows (kody 5/32/33), używany przez worker, interfejs i walidację wznowienia. Trwała odmowa dostępu nadal zgłasza błąd po ośmiu próbach; nieprawidłowy JSON zgłasza błąd od razu. Nie zwraca się starego stanu ani nie pomija walidacji. Dodano osiem przypadków regresji; cała pula wzrosła z 86 do 94. Powtórzony pełny przebieg zakończył się prawidłowo.

## Sprawdzone scenariusze

| Test | Wynik i zakres |
|---|---|
| `python -m pytest -q` | 94 zaliczone: edycja/cofanie, zapis, pochodzenie, formaty, czasy/czytelność, walidacja odpowiedzi, ochrona ręcznych tłumaczeń, pauza/wznowienie, blokada równoczesnego przebiegu, timeouty, procesy potomne, cache i GUI. |
| `python -m tools.verify_pipeline` | 20 s japońskiego audio; Whisper Large V3 i Qwen ASR na Vulkan; wybór JP; dwa profile EN lokalnego Qwen3-4B; wybór EN; pełne AI, próba poprawy i ponowna ocena; eksport. Wszystkie 12 etapów ukończone, 10 ścieżek zachowane, 5 końcowych napisów. Suma czasów etapów około 127 s, razem z ładowaniem modeli. |
| `python -m tools.verify_pipeline --audit …` | Ponownie odczytano pliki: sumy kontrolne wszystkich checkpointów, kompletność EN, poprawne granice czasu, zgodność każdego tekstu/czasu JP i EN po imporcie wyeksportowanych SRT oraz spójność raportu. Zaliczony także dla pierwszego przebiegu, którego UI zgłosił błąd. |
| `python -m tools.verify_qol` | 1000 szczytów waveformu dla 20 s audio; trzy rzeczywiste strukturalne oceny lokalnego modelu; istniejące EN pozostały niezmienione; ponowny import ASS i eksport TXT prawidłowe. Próbki JP/EN w tym teście są syntetyczne i nie są oceną zgodności z nagraniem. |
| `python -m tools.verify_gui_embedded` | GUI → lokalny GGUF → SQLite; następnie uruchomienie i anulowanie rzeczywistego zadania, zakończenie jego drzewa procesów i zapis statusu `cancelled`. |
| `python -m tools.smoke_ui` | Odtwarzanie istniejącego filmu testowego H.264/AAC, odczyt ścieżki audio, aktualizacja pozycji, podgląd napisów i zapis osobnego projektu. |
| `python -m tools.preview_qol` | Renderowanie edytora/panelu AI i okien podglądu poprawek; sprawdzenie przewijania przy 960×700. Obrazy obejrzano. |
| `python -m compileall -q studio tools` | Brak błędów kompilacji źródeł. |

## Jakość i ostrzeżenia

Końcowy pipeline ma status **`needs_review`**, ponieważ cztery z pięciu napisów wymagają kontroli. Raport zachowuje ostrzeżenia o długości wierszy, zbyt szybkim EN, różnicach między ASR i przycięciu ostatniego napisu do końca fragmentu. Poprawny eksport nie oznacza, że wszystkie napisy nadają się już do publikacji. Test nie mierzy WER/CER ani trafności przekładu względem ręcznie przygotowanej referencji i nie obejmuje długiego filmu z muzyką.

## Artefakty

- Udany przebieg: `D:\models\.cache\pipeline\ff5df83401a44940b34c7e17cdabf8d6\manifest.json`.
- SRT i raport: `D:\models\.cache\verification-pipeline-ui\projects\d4dfffc97eb44625982b0d313597da13\exports\ff5df83401a44940b34c7e17cdabf8d6`.
- Podgląd ukończonego pipeline: `D:\models\.cache\verification-pipeline-ui\pipeline-preview.png`.
- Waveform, propozycje i formaty: `D:\models\.cache\verification-qol`.
- Test tłumaczenia/anulowania: `D:\models\.cache\verification-gui-embedded`.

Testy GPU należy wykonywać pojedynczo, przy bezczynnym głównym oknie aplikacji. Polecenie `--audit` sprawdza istniejący przebieg bez ponownego uruchamiania modeli.

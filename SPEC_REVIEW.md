# Przegląd pierwotnej specyfikacji — 27.10.2026

Ponownie porównano aplikację z „AI Subtitle Studio — kompletna specyfikacja projektu dla Codexa”. Poniższy stan uwzględnia późniejsze decyzje użytkownika: wbudowany GGUF jako domyślny tłumacz, LM Studio opcjonalnie, modele i cache na D:, maksymalnie automatyczny pipeline.

## Wdrożone w tym przeglądzie

- Waveform rzeczywistej wybranej ścieżki audio, zoom, playhead, podgląd przedziałów napisów i zaznaczanie zakresu ASR/pipeline. Dekodowanie w osobnym procesie; tylko niewielki cache szczytów, bez kolejnego WAV i bez nowych modeli.
- Wyszukiwanie JP/EN/czasów/notatek, filtry ostrzeżeń, nieprzejrzanych, zakładek i brakującego EN, nawigacja klawiaturą. Trwałe oznaczenie ręcznej kontroli, zakładki i notatki nie zmieniają tekstu.
- Zatwierdzanie edytowanych pól przy zmianie napisu, przed zadaniem i przy zamknięciu. Nieprawidłowy czas blokuje odejście zamiast kasować edycję. Zmianę można odrzucić z menu Narzędzia.
- Podgląd typowych poprawek: białe znaki, konserwatywne scalanie mikronapisów, ograniczone techniczne propozycje czasu. Osobny podgląd przesunięcia wszystkich lub zaznaczonych napisów. Cofanie i pochodzenie pozostają zachowane.
- Ochrona częściowego EN: scalenie nie może po cichu usunąć istniejących tłumaczeń. Markery mówców blokują automatyczną propozycję scalenia; nie jest to rozpoznawanie mówców.
- Osobny panel propozycji AI: Fast / Full / Refusal Repair / Hallucination Review, uzasadnienie, propozycja, informacja o odsłuchu. Akceptacja wielu wyników, odrzucanie, edycja, cofanie i wznowienie ocen.
- Izolacja napisu docelowego od kontekstu, walidacja ID i danych, kontrolowana próba przekładu z samego JP przy braku propozycji oraz druga kontrola zgodności proponowanego EN z JP. Niepotwierdzona propozycja jest wstrzymana. Wynik jest oceną modelu tekstowego, nie dowodem poprawności.
- Opcjonalna pauza pipeline po niepewnym wyborze JP/EN. Można poprawić wskazaną ścieżkę i kontynuować bez powtarzania ASR. Poprzedni checkpoint jest zachowany jako kopia do audytu.
- Import ASS/SSA jako tekst i czasy; eksport SRT, ASS/SSA z domyślnym stylem oraz TXT z czasami. Style wejściowe ASS nie są zachowywane.
- Przeciąganie filmu, napisów lub projektu do okna; lista ostatnich projektów. Nowy film po poprzednim materiale z napisami otrzymuje osobny projekt.
- Limity czasu ręcznego ASR/FFmpeg, licznik czasu zadania, osobne rozróżnienie timeoutu i anulowania.
- Zarządzanie odbudowywalnym cache: wyłącznie rozpoznane pliki audio i waveformów. Modele, projekty, logi i checkpointy nie są oferowane do usunięcia. Pipeline odtwarza brakujący cache audio bez powtarzania ukończonych modeli.

## Stan całej specyfikacji

| Obszar | Stan i praktyczne ograniczenia |
|---|---|
| Import / odtwarzacz / wybór audio | Działa; napisy w panelu pod obrazem. Język ASR pozostaje JA. |
| Waveform | Działa, 50 szczytów/s; nie zastępuje spektrogramu ani forced alignment. |
| Whisper / CrispASR | Działają przez adaptery CLI, z kontrolą flag/backendu. Sprawdzone Large V3 i Qwen JA Anime na Vulkan/RTX 5060. XXL opcjonalny. |
| Zaawansowane presety ASR | Częściowo: stabilne konfiguracje i warianty VAD; pełne profile Maximum Recall / Clean Dialogue i wszystkie parametry VAD w GUI nadal do dodania. |
| Separacja / odszumianie | Niezaimplementowane. Brak MDX-Net/Kim Vocal 2 i odsłuchu A/B oczyszczonego sygnału. |
| Porównywanie JP | Działa według czasów z 1:N/N:1, ręcznym wyborem i wyborem tekstowym AI w pipeline. Duże przesunięcia wymagają korekty. |
| Edytor / techniczne poprawki | Działa; propozycje czasu są techniczne, nie potwierdzają granic mowy. Brak diarizacji i automatycznej synchronizacji do audio. |
| Tłumaczenie / kontekst / resume | Działa wbudowany Qwen3 Instruct i opcjonalny lokalny HTTP. Zakończone wyniki i ręczne EN są zachowywane. |
| Qwen3.5 / TranslateGemma | Brak natywnych dedykowanych profili. Qwen3.5 może wymagać ustawień LM Studio; TranslateGemma jest jawnie blokowana zamiast używania błędnego szablonu. |
| AI Review | Działa w pipeline i jako panel propozycji. Dodatkowa kontrola nadal korzysta z modelu tekstowego i nie jest niezależnym certyfikatem jakości. |
| Pipeline / wznawianie | Działa dla jednego materiału, 1–4 ASR i 1–4 EN, etapami i z pauzą do kontroli. Brak kolejki wielu filmów. |
| Pochodzenie / historia / projekty | SQLite, stabilne ID, rodzice, oryginały, checkpointy, decyzje. Cofnij/Ponów dotyczą bieżącej sesji; brak pełnego przeglądarkowego panelu historycznych rewizji. |
| Dysk / VRAM / stabilność | Modele/cache na D:, jeden ciężki proces, kontrolowane backendy, kończenie procesów i timeouty. Brak panelu telemetrii GPU/RAM i automatycznego limitu całego cache. |
| Eksport | SRT, ASS, SSA, TXT i raport pipeline. ASS/SSA mają styl domyślny i rozdzielczość czasu właściwą formatowi; nie zachowują stylów wejściowych. |
| Dystrybucja | Środowisko Python + pliki BAT; brak gotowego instalatora/przenośnego EXE. |

## Walidacja

86 testów automatycznych: formaty (również eksport pipeline), techniczne poprawki, zachowanie JP/EN, ochrona przed nieaktualną propozycją, zbiorcza akceptacja, ochrona ręcznych zmian, nawigacja, zaznaczanie waveformem, timeout, pauza i kontynuacja pipeline, bezpieczny wybór cache oraz jego odbudowa. Rzeczywisty test FFmpeg/modelu: `python -m tools.verify_qol`, na oddzielnym projekcie w `D:\models\.cache\verification-qol`.

Test modelu pokazał, dlaczego nie można utożsamiać poprawnego JSON z prawidłowym znaczeniem. Jeden błędny wariant udało się poprawić, inną propozycję druga kontrola uznała za niepewną i wstrzymała. Nie dopisywano ani nie nadpisywano EN automatycznie.

## Kolejne największe korzyści

1. Separacja audio z odsłuchem A/B i kontrolowanym budżetem dysku, potem porównanie oryginalnego/oczyszczonego ASR.
2. Forced alignment do ponownej synchronizacji już poprawionego JP i dokładniejsze granice podziału; nie zastępować go proporcją znaków.
3. Dedykowane profile Qwen3.5 / TranslateGemma po sprawdzeniu rzeczywistych szablonów silnika i VRAM, oraz zestaw ręcznie ocenionych przykładów JP→EN.
4. Kolejka filmów, przeglądarka rewizji i telemetria zasobów; następnie paczka Windows EXE.

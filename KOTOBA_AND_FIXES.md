# Poprawki po teście i Kotoba-Whisper — 28.10.2026

Wprowadzono poprawki obsługi ASR, review, czytelności i wydajności. Kotoba jest pobrana i dostępna jako trzeci wariant. Wszystkie rzeczywiste testy sprzętowe w tej serii wykonano na CUDA.

Pełny test filmu Easy Japanese 1 po zmianach zakończył się w **499,234 s, czyli 8 min 19 s**. Poprzedni przebieg trwał 25 min 22 s. To około 3× krótszy czas całego zadania, choć przebiegi nie są identycznym eksperymentem: nowy używał trzech prób ASR, dwóch poprawnych źródeł JP, 96 zamiast 98 napisów i dodatkowej kontroli poprawek.

## Co zmieniono

- **Wadliwy ASR jest odrzucany, a pozostałe modele mogą pracować dalej.** Błędy alignera i nieprawidłowe czasy nie trafiają do wyboru JP. Powód, model i log pozostają w raporcie, a interfejs pokazuje odrzucony wynik. Gdy wszystkie ASR zawiodą, tłumaczenie nie startuje. Błędy urządzenia, pamięci, konfiguracji i plików nadal zatrzymują proces. Można także wybrać zatrzymanie po pierwszym błędzie ASR.
- **Dodano preset „Porównawczy • 3 ASR / 2 EN + pełne AI”**: Large V3, Qwen i Kotoba. Dla wszystkich trzech włącza VAD. Kotoba używa istniejącego lokalnego alignera, ponieważ samo dekodowanie na tym filmie generowało dwa napisy o zerowej długości. Nie nadawano im sztucznych czasów.
- **Łączenie JP uwzględnia zgodność czasów.** Algorytm wybiera całe istniejące napisy, bez przesuwania granic. Minimalizuje zmiany decyzji tekstowych tak, aby nie tworzyć nakładania. Jeśli nie istnieje pełna zgodna kombinacja, zachowuje jedną ścieżkę źródłową i opisuje powód. Preferencje modelu i decyzje końcowe pozostają dostępne.
- **Model LLM pozostaje w pamięci między etapami.** Aplikacja sama uruchamia i zamyka lokalny silnik z obecnego pakietu llama.cpp. Nie wymaga LM Studio ani ręcznego uruchamiania serwera. Sesja startuje dopiero po ASR, słucha wyłącznie na 127.0.0.1 i działa w trybie offline. W razie zmiany modelu poprzedni jest zwalniany; zakończenie, błąd lub zabicie workera zwalnia jego proces. Runtime dostaje jawne urządzenie CUDA0.
- **Decyzje LLM są grupowane**, z kontrolą budżetu kontekstu, dokładnych ID i powrotem do pojedynczych pytań po błędnej partii. Checkpointy nadal pozwalają wznowić pracę.
- **Poprawki EN powstają na podstawie JP i są osobno sprawdzane względem samego źródła.** Dopiero wynik `faithful`, następnie wybór poprawki, pozwala ją zastosować. `uncertain` lub `incorrect` zachowuje poprzedni tekst. Ręczne tłumaczenia są chronione. Nowe tłumaczenia nie korzystają z angielskiego streszczenia jako źródła nazw; instrukcje zabraniają zgadywania pisowni oraz zmiany rozmówcy i niepewności.
- **Czytelność jest rzeczywiście poprawiana:** łamanie JP i EN oraz opcjonalne wydłużenie ekspozycji do 250 ms w wolnej przerwie. Początek pozostaje bez zmian, sąsiednie napisy i koniec filmu wyznaczają granice; ręczne czasy są chronione. Każde wydłużenie jest oznaczone jako zmiana ekspozycji, nie wyrównanie do mowy. Sam podział tekstu nie rozwiązuje zbyt wysokiego CPS.
- **Rejestrowany jest także czas nieudanego etapu.** Odrzucone ASR nie znikają z pomiarów.

Po ocenie pełnego wyniku dodano jeszcze wąską kontrolę deterministyczną: jawne pytanie JP nie może zostać automatycznie „poprawione” na EN bez znaku pytania, nawet gdy LLM akceptuje taki kandydat. Regresja sprawdza ten konkretny błąd. Pełne artefakty benchmarku zachowano z chwili ich ukończenia; tej ostatniej reguły nie przedstawia się jako ręcznej korekty zapisanych napisów ani ponownego pełnego benchmarku.

## Kotoba: plik, szybkość i jakość

Pobrano **jeden oficjalny plik FP16 Kotoba-Whisper v2.0 GGML**, 1 519 521 155 bajtów, około 1,42 GiB:

[D:\models\whisper\ggml-kotoba-whisper-v2.0.bin](D:/models/whisper/ggml-kotoba-whisper-v2.0.bin).

Repozytorium: [kotoba-tech/kotoba-whisper-v2.0-ggml](https://huggingface.co/kotoba-tech/kotoba-whisper-v2.0-ggml), rewizja `e3a0cf6a62b95911703cfb97d819292e058f12c3`. Sprawdzono rozmiar i SHA256 `eff70a8a236e731abba774ba71e1f6d0fce53302137208c32207e694e0bf4546`. [Manifest pobrania](D:/models/subtitle-studio-kotoba.json). Nie pobierano równocześnie drugiej kwantyzacji ani nowych wag alignera; nie tworzono kopii modelu na C:.

Wybrano natywny wariant v2.0. Według [dokumentacji v2.2](https://huggingface.co/kotoba-tech/kotoba-whisper-v2.2) ta nowsza wersja opiera się na v2.0 i dokłada stos postprocessingu, w tym diarization; nie instalowano całego dodatkowego stosu do obecnej aplikacji.

Porównanie na całym tym samym filmie 282,73 s, CUDA, FP16, beam 5, VAD, kolejność AB/BA:

| Model | Próba 1 | Próba 2 | Średnia |
|---|---:|---:|---:|
| Whisper Large V3 | 47,53 s | 45,20 s | **46,365 s** |
| Kotoba + wymagany aligner | 22,44 s | 15,83 s | **19,135 s** |

Kotoba była tu **2,42× szybsza**, wliczając ładowanie i wyrównanie. W obu udanych próbach miała 52 napisy o poprawnych przedziałach; Large V3 98. [Pomiary AB/BA](D:/models/.cache/benchmark-kotoba-cuda/timings.json). Nie jest to gwarancja takiego przyspieszenia na każdym nagraniu.

Sprawdzono też ten sam niezależny fragment rzeczywistego spotkania MCDC z istniejącym SRT: 112,3 s, 22 napisy referencyjne, 408 znaków po normalizacji.

| Model | Czas | CER względem SRT |
|---|---:|---:|
| Large V3 | 26,31 s | **6,13%** — 25 różnic |
| Kotoba + aligner | 17,00 s | **14,95%** — 61 różnic |

Kotoba była szybsza, ale na tym fragmencie **mniej dokładna**. Pozostaje opcjonalnym dodatkowym źródłem, a Large V3 nadal pierwszym modelem w presetach. CER mierzy różnicę względem społecznościowych napisów, które mogą same zawierać błędy; nie jest oceną tłumaczenia ani wynikiem dla całego filmu Easy Japanese.

[Porównanie CER i konkretne różnice](D:/models/.cache/benchmark-reference-cuda-kotoba/comparison.json) · [Czasy fragmentu referencyjnego](D:/models/.cache/benchmark-reference-cuda-kotoba/timings.json).

## Pełny przebieg Easy Japanese 1 po zmianach

| Etap | Czas |
|---|---:|
| Audio z cache | 0,00 s |
| Large V3 + VAD | 50,38 s |
| Qwen + VAD — wynik odrzucony | 42,09 s |
| Kotoba + VAD + aligner | 20,67 s |
| Wybór JP z dwóch poprawnych źródeł | 18,67 s |
| Dodatkowy slot łączenia — pominięty po odrzuceniu Qwena | <0,01 s |
| Kontekst filmu | 3,44 s |
| Dwa tłumaczenia EN | 41,50 + 42,36 s |
| Wybór EN | 20,08 s |
| Spójność filmu | 57,39 s |
| Review wszystkich napisów | 52,53 s |
| Generowanie, weryfikacja i wybór poprawek | 96,91 s |
| Ponowne review | 51,64 s |
| Formatowanie i eksport | 0,02 + 0,03 s |
| **Całość wraz z narzutem interfejsu** | **499,234 s** |

Sesja LLM: **jeden proces, 384 poprawne odpowiedzi**, pojedyncze uruchomienie trwające 9,407 s do gotowości. Proces zamknął się po przebiegu. Oddzielny test trzech krótkich zapytań potwierdził ten sam PID, czasy 2,469 / 0,109 / 0,125 s i brak procesu po wyjściu z sesji. [Test sesji](D:/models/.cache/verification-native-session/result.json).

Telemetria potwierdziła CUDA. Maksymalne zaobserwowane użycie całego GPU, razem z pulpitem: Qwen 7746 MiB, Kotoba 6680 MiB, Large V3 5422 MiB, etapy LLM do 4453 MiB. Po zakończeniu spadło do 1178 MiB. To pomiary co 2 s, nie osobne liczniki pamięci modelu. Nie testowano sprzętowo Vulkana.

Wynik: **96 napisów, 11 ścieżek, 30 zmian EN**, każda zastosowana zmiana ma zapisane `source_verification: faithful`. Finalny status nadal `needs_review`. Wszystkie 96 fragmentów mają jakieś ostrzeżenie, w dużej części informację o rozbieżnych ASR i tekstowym wyborze; nie oznacza to 96 potwierdzonych błędów treści.

Samo formatowanie zmieniło układ 24 napisów JP i wydłużyło 12 ekspozycji w ustalonych granicach. Liczba za szybkich EN spadła w tym przebiegu z 20 do 16, a JP z 16 do 15. Nakładania czasów: **0**. Nie wszystkie problemy z czytelnością zostały rozwiązane. Wcześniejszy finalny wynik miał 11 zbyt szybkich EN, więc nie wykazano ogólnej poprawy czytelności między różnymi konfiguracjami ASR.

## Porównanie treści: pozostałe ograniczenia

Wykorzystano te same 12 próbek wypalonych napisów autora i jedną dodatkową próbkę z poprzedniego testu; bez podawania referencji modelom i bez wyliczania pełnego CER dla tego filmu.

- „PuRiCuA” zmieniło się na „Pretty Cure”, ale całe zdanie o stylizacji nadal ma niewłaściwy niuans „thinking about”.
- Imię prowadzącej nadal jest błędne: „Kumagai Muna” zamiast Mona Kumagai. Streszczenie nadal potrafi zgadywać nazwę i płeć. Nowy tłumacz nie dostaje go jako źródła nazw, ale sam model również może się pomylić.
- Błędny JP o „poziomie rozwoju kraju” przy świeżych rybach pozostał w wyborze i przechodzi do EN. Tekstowy wybór ASR nie rozstrzygnął tu poprawnie audio.
- Pytanie do rozmówców o rzeczy nielubiane w Japonii nadal wyszło z błędną perspektywą i w formie stwierdzenia. Ten przypadek doprowadził do dodatkowej, przetestowanej reguły zachowania jawnych pytań; nie jest to pełne rozwiązanie niejawnych podmiotów w JP.
- Sendai, ogólny temat jedzenia oraz końcowe przeprosiny zachowały rozpoznawalny sens.

**Zmiany poprawiają odporność, kontrolę poprawek i wydajność. Nie dowiedziono ogólnej poprawy jakości treści.** Więcej ASR i więcej review tym samym małym modelem nie daje automatycznie najlepszego wyniku. Kotoba nie zastępuje Large V3 jako domyślnego modelu.

## Weryfikacja i pliki

Końcowy zestaw: **125 testów poprawnych**. Regresje obejmują odrzucanie wadliwych ASR, zatrzymanie gdy wszystkie zawiodą, brak ukrywania OOM, wznowienia i partie decyzji, niezależną weryfikację poprawek, zgodność czasów, ochronę ręcznych napisów, układ JP, granice ekspozycji, preset z VAD oraz zwalnianie sesji LLM po błędzie.

Pełny test Qt zakończył się poprawnie. Ponownie sprawdzono wszystkie digesty etapów, SQLite, oba wyeksportowane SRT, ich kompletne teksty i czasy w granicach filmu. Model źródłowy i główny projekt użytkownika nie zostały nadpisane.

- [Projekt po zmianach](D:/models/.cache/benchmark-easy-japanese-1-postfix/projects/3d5caa183fba40e1bd75ebd2c6e12902/project.sqlite).
- [Napisy EN](D:/models/.cache/benchmark-easy-japanese-1-postfix/projects/3d5caa183fba40e1bd75ebd2c6e12902/exports/509015c7bfe14d2991bc73933b450e69/English.srt).
- [Napisy JP](D:/models/.cache/benchmark-easy-japanese-1-postfix/projects/3d5caa183fba40e1bd75ebd2c6e12902/exports/509015c7bfe14d2991bc73933b450e69/Japanese.srt).
- [Pełne pomiary](D:/models/.cache/benchmark-easy-japanese-1-postfix/timings.json).
- [Metryki i sesja LLM](D:/models/.cache/benchmark-easy-japanese-1-postfix/summary.json).
- [Porównanie z klatkami autora](D:/models/.cache/benchmark-easy-japanese-1-postfix/reference-comparison.json).
- [Manifest i logi](D:/models/.cache/pipeline/509015c7bfe14d2991bc73933b450e69/manifest.json).

Próby pomocnicze pozostawiono do audytu: pierwsza Kotoba bez alignera miała dwa zerowe czasy; pierwszy test presetu trzeciego modelu miał wyłączone VAD i został świadomie przerwany po wykryciu konfiguracji. Udany końcowy przebieg używa VAD dla wszystkich trzech ASR i jawnego alignera Kotoby. Wagi i cache pozostają na D:.

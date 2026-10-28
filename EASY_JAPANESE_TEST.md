# Easy Japanese 1 — pełny test na rzeczywistym filmie

Test z 28.10.2026. Cały film **4:42,73**, bez skracania. Ukończono transkrypcję, kontekst całego JP, dwa tłumaczenia EN, wybór EN, kontrolę spójności, pełne review, poprawki, ponowną ocenę, formatowanie i eksport. Wynik: **98 napisów, 34 zmiany EN, status `needs_review`, 74 napisy z ostrzeżeniami**. Nie jest to wynik gotowy do publikacji bez kontroli.

Pierwotny wariant dwóch różnych ASR nie przeszedł testu. Qwen miał błędy alignera; Whisper bez VAD również wygenerował nieprawidłowe czasy. Ukończony przebieg korzysta z **jednego Whispera z VAD**, a nie z dwóch niezależnych transkrypcji. Wadliwe próby i logi zachowano osobno.

## Materiał i niezależna referencja

[Easy Japanese 1 — Typical Japanese, Easy Languages](https://www.youtube.com/watch?v=qzzweIQoIOU). Rozmowy uliczne w Sendai; różni rozmówcy, tło uliczne, muzyczne przejścia. Film ma wypalone napisy japońskie, romaji i angielskie.

YouTube odrzucił anonimowe pobranie HTTP 429 / komunikatem logowania. Pobrano publiczną kopię [tego samego odcinka na Bilibili, część 1](https://www.bilibili.com/video/BV1yt411N7mb/?p=1). Tytuł, długość i zawartość sprawdzono; nie stwierdzano identyczności bajtowej z plikiem YouTube. Nie używano konta ani cookies.

- Plik: [Easy_Japanese_1_Typical_Japanese.mp4](D:/models/test-media/easy-japanese-1/Easy_Japanese_1_Typical_Japanese.mp4), 1280×720, H.264/AAC, 55,03 MiB.
- SHA256: `796f132cc85ac3652157623d4387689b8d60ccb7bb97b426f6880eea0e044f1a`.
- [Pochodzenie i parametry pliku](D:/models/test-media/easy-japanese-1/source.json).
- Porównanie: 12 początkowych próbek napisów z obrazu oraz dodatkowa, celowo wybrana próbka 46,5 s po zauważeniu podejrzanego ASR. Referencję odczytano z oryginalnych klatek, nie wygenerowano jej modelem aplikacji.
- [Szczegółowe porównanie JP/EN i ścieżki do klatek](D:/models/.cache/benchmark-easy-japanese-1-final/reference-comparison.json).

Nie pozyskano pełnego niezależnego SRT. Próbki zawierają fragmenty zdań, a granice napisów autora mogą różnić się od granic wypowiedzi ASR. **Nie obliczano WER/CER ani procentowej poprawności całego filmu.** Tekstu referencyjnego nie podawano modelom podczas testu.

## Konfiguracja i czasy

RTX 5060 8 GB. ASR: Whisper Large V3 FP16 GGML + Silero VAD przez CrispASR CUDA. Tłumaczenia i review: wbudowany Qwen3-4B-Instruct-2507 Q4_K_M przez llama-completion CUDA, kontekst 4096, partie tłumaczenia po 6. Oba warianty EN używają tych samych wag i różnych instrukcji: naturalnej i wiernej. Nie są to dwa niezależne modele.

Wszystkie modele, cache oraz materiał testowy pozostały na D:. Nie pobierano nowych wag modeli. Dodano film oraz małe narzędzie yt-dlp, którego ostatecznie nie udało się użyć do pobrania tego odcinka; film pobrano przez publiczne API kopii.

| Etap ukończonego przebiegu | Czas |
|---|---:|
| Audio — wykorzystano istniejący WAV | 0,00 s |
| Whisper Large V3 + VAD | 48,45 s |
| Kontekst całego filmu | 20,73 s |
| Tłumaczenie naturalne | 82,05 s |
| Tłumaczenie wierne | 81,98 s |
| Wybór EN | 149,73 s |
| Spójność całego filmu | 100,17 s |
| Dokładne review wszystkich 98 napisów | 297,80 s |
| Próby poprawek i porównania kandydatów | 432,95 s |
| Ponowna ocena wszystkich 98 napisów | 307,41 s |
| Formatowanie | <0,01 s |
| Eksport | 0,05 s |
| **Cały ukończony przebieg** | **1521,725 s = 25 min 21,725 s** |

Czas całego przebiegu pochodzi z jego oryginalnych znaczników utworzenia i ukończenia. Nie obejmuje pobierania, wcześniejszych nieudanych prób ani późniejszego audytu/interfejsu. Pierwsza ekstrakcja audio w pierwotnym przebiegu trwała 0,28 s; końcowy przebieg wykorzystał ten cache.

Pomiar pokazał koszt częstego ładowania modelu: w 412 wywołaniach decyzji/review logi wykazały łącznie **637,063 s ładowania**, medianę 1,488 s. To około 42% czasu całego przebiegu, jeszcze bez wywołań tłumaczenia przechowywanych we wspólnym cache. Utrzymanie modelu LLM w pamięci między kolejnymi decyzjami jest konkretnym kierunkiem optymalizacji; nie zostało wdrożone w tym teście.

[Pełne czasy i metadane audytu](D:/models/.cache/benchmark-easy-japanese-1-final/timings.json) · [Zestawienie jakości, GPU i kosztu ładowania](D:/models/.cache/benchmark-easy-japanese-1-final/summary.json).

## CUDA i nieudane warianty ASR

Logi Whispera potwierdzają CUDA; proces LLM uruchamiał się z `--device CUDA0 --n-gpu-layers 99`. W trakcie pracy potwierdzono pojedynczy proces llama-completion, obciążenie GPU 86% i zajęte 4435 MiB. Telemetria co 2 sekundy nie zgłosiła błędów.

Największe zaobserwowane użycie pamięci w ukończonym przebiegu: **5380 MiB** podczas ASR. Dla etapów LLM: do **4865 MiB**. Są to pomiary całego GPU, razem z pulpitem i innymi procesami, a nie osobne liczniki pamięci modelu. Log CrispASR zawiera ostrzeżenie compiled CUDA 13.0 / runtime 13.5; nie usuwano go z diagnostyki.

| Nieudana próba | Wynik |
|---|---|
| Whisper + VAD w pierwotnym przebiegu | Poprawny, 47,55 s |
| Qwen + VAD, domyślne okna | Około 65,45 s do zatrzymania etapu; kod 31: brak czasów słów w jednym fragmencie i ostrzeżenie o collapse alignera |
| Qwen + VAD, okna 15 s / overlap 1 s | 36,64 s procesu, kod 0, ale ostrzeżenia alignera i napis o zerowym czasie; wynik odrzucony |
| Qwen bez VAD, okna 10 s / overlap 1 s | 33,77 s, kod 31: trzy fragmenty bez czasów słów |
| Whisper bez VAD | Około 58,44 s etapu; 138 fragmentów, w tym 12 o zerowym czasie i wielokrotne powtórzenia; wynik odrzucony |

Qwen rzeczywiście korzystał z CUDA, osiągając 99% obciążenia i zaobserwowane 7753 MiB całkowitego użycia GPU. Zgłoszony błąd dotyczył wyrównania, nie OOM. Ścisłej kontroli nie wyłączano i nie nadawano sztucznie czasów nieprawidłowym napisom.

Logi pierwotnej próby: [manifest](D:/models/.cache/pipeline/5c7a7cc914964c9f85ec84fd80f23d1d/manifest.json), [Qwen](D:/models/.cache/pipeline/5c7a7cc914964c9f85ec84fd80f23d1d/asr-1/engine.log). Próby krótszych okien są w podfolderach tego etapu. Whisper bez VAD: [manifest](D:/models/.cache/pipeline/c2e745302ce34ff5886ef0e08df454a5/manifest.json).

## Co rzeczywiście wyszło

| Miejsce | Porównanie z napisami autora |
|---|---|
| 00:03,5 — prowadząca | Autor: Mona Kumagai. ASR: `熊谷もなです`, ale EN: `Kuma Muna`. Ten sam błędny zapis jest w streszczeniu i obu wariantach tłumaczenia. Review zaakceptowało go bez ostrzeżenia. Nie wykonywano osobnego testu A/B, więc nie przypisuje się błędu wyłącznie wpływowi streszczenia. |
| 00:07 — Sendai | Miejsce i ogólny sens zachowane. |
| 00:44 — morze i ryby | Pierwsza część sensowna. Napis autora rozciąga myśl na sąsiednią wypowiedź; sam punkt czasowy nie wystarcza do oceny całego zdania. |
| **00:46,5 — dostępność ryb** | Autor mówi o łatwej dostępności świeżych ryb. ASR dodaje `国の開発度` — poziom rozwoju kraju; EN powtarza ten błąd. Review go nie naprawiło, ale finalnie pozostawiło flagę możliwej zmiany znaczenia. |
| 01:03 — zdrowa kuchnia | Ogólny sens zachowany; review skróciło sformułowanie EN. |
| 01:28 — długie czarne włosy | Ogólny sens zachowany; review usunęło wzmacniające `definitely`. |
| 01:57 — jedzenie i troska o innych | Sens myśli zachowany, ale finalny EN pozostaje bardzo długi. |
| 02:25 — śnieg | Zachowany rozpoznawalny fragment myśli; zdanie należy oceniać z następnymi napisami. |
| 02:52 — anime | Temat rozpoznany; EN `anime, right?` zmienia niuans względem odpowiedzi „chyba anime”. |
| **03:19 — Pretty Cure** | JP `プリキュア` jest poprawne. EN: `we're paying attention to PuRiCuA`, zamiast odniesienia do stylizacji inspirowanej Pretty Cure. Poprawki nie pomogły; flaga spójności pozostała. |
| **03:40 — czego nie lubią w Japonii** | Pytanie do rozmówców zamieniono na `Is there actually a place in Japan that I truly dislike?`, czyli pytanie o siebie i konkretne miejsce. Błędny punkt widzenia występował już przed poprawką. Finalne review pozostawiło flagę. |
| 04:03 — dawne „yabai” | Rozpoznawalny sens widocznego fragmentu zachowany; pełny wygenerowany napis obejmuje także dalszą część zdania. |
| 04:25 — przeprosiny | Sens zachowany: brak pomysłu, co powiedzieć. |

Kontekst odczytał główne tematy filmu: jedzenie, troskę o innych, język i anime. Przeanalizował dwa bloki JP, bez pominiętych bloków. Streszczenie przekręciło jednak imię i zakończyło się twierdzeniem o braku wyraźnych negatywnych opinii, mimo późniejszej krytycznej części rozmów. Jest użyteczną hipotezą, lecz nie wiarygodną referencją.

## Czy poprawki i review pomagają

34 napisy EN faktycznie zmieniono i zapisano wersje przed/po. Nie oznacza to 34 naprawionych błędów znaczenia: część zmian to skróty lub parafrazy. Dwa warianty tłumaczenia różniły się w 50 z 98 miejsc.

| Wskaźnik | Przed review — wybrane EN | Finalnie |
|---|---:|---:|
| Zbyt szybkie EN, limit 20 znaków/s | 13 | 11 |
| Zbyt szybkie JP, limit 8 znaków/s | 16 | 16 |
| Napisy z nakładaniem czasów | 0 | 0 |
| Napisy z dowolnym ostrzeżeniem | 61 | 74 |

Wzrost liczby ostrzeżeń uwzględnia dodane flagi AI; nie oznacza sam w sobie pogorszenia tekstu. Finalnie 50 napisów ma flagi AI, 7 przekracza limit długości wiersza EN, 24 limit wiersza JP, a 15 trwa krócej niż 834 ms. Kategorie nakładają się. Flagi AI zawierają również nietrafione wskazania — np. dosłownie poprawne `Japan's food is delicious` oznaczono jako możliwy problem znaczenia.

Końcowe JP i czasy są identyczne z prawidłowym Whisperem + VAD. Nie stosowano szacowanego automatycznego podziału ani ręcznej korekty testowego wyniku. Kontrola czasów i CPS działa, ale ten przebieg **nie naprawił automatycznie krótkich ekspozycji i pozostałych problemów z czytelnością**.

## Błędy aplikacji wykryte podczas testu

Obliczenia zakończyły się poprawnie, ale pierwsze uruchomienie testu Qt zakończyło się błędem asercji: interfejs raz dostał `PermissionError: [Errno 13]` przy odczycie `en-1/partial.json`. Wcześniejsze ponawianie odczytu obsługiwało tylko Windows `winerror`, a Python może zwracać sam `errno=EACCES`.

Dodano ograniczone ponawianie również tego wariantu na Windows, bez ukrywania trwałej odmowy dostępu lub błędnego JSON. Przy ponownym otwieraniu projektu ujawnił się też opóźniony callback usuniętego `QProcess` waveformu; dodano kontrolę ważności obiektu Qt.

Weryfikacja po poprawkach:

- **74 testy poprawne**: `tests/test_core.py`, `tests/test_pipeline.py`, `tests/test_ui.py`, w tym nowe regresje dla EACCES bez winerror, trwałej odmowy dostępu i usuniętego QProcess.
- Audyt wszystkich digestów ukończonych etapów, niepustych JP/EN, poprawnych czasów w granicach filmu oraz zgodności raportu z wynikiem.
- Ponowne wczytanie obu SRT i porównanie całych tekstów oraz czasów z finalną ścieżką: zgodne.
- Ponowne wczytanie wszystkich 12 ukończonych checkpointów przez interfejs i zapis/odczyt SQLite: poprawne, 9 ścieżek, 98 finalnych napisów.
- Nie powtarzano 25-minutowych obliczeń po poprawce odczytu; wczytano istniejące, sprawdzone artefakty. Nie przedstawia się szybkiego odtworzenia checkpointów jako czasu obliczeń.

## Wyniki do otwarcia

- [Projekt aplikacji — 9 ścieżek](D:/models/.cache/benchmark-easy-japanese-1-final/projects/12abf706c5e74b808a721f4f5f7023cc/project.sqlite).
- [Napisy EN](D:/models/.cache/benchmark-easy-japanese-1-final/projects/12abf706c5e74b808a721f4f5f7023cc/exports/c97c4289b82440f9a717f22735d5741d/English.srt).
- [Napisy JP](D:/models/.cache/benchmark-easy-japanese-1-final/projects/12abf706c5e74b808a721f4f5f7023cc/exports/c97c4289b82440f9a717f22735d5741d/Japanese.srt).
- [Raport szczegółowy i zmiany przed/po](D:/models/.cache/benchmark-easy-japanese-1-final/projects/12abf706c5e74b808a721f4f5f7023cc/exports/c97c4289b82440f9a717f22735d5741d/report.json).
- [Manifest ukończonego przebiegu](D:/models/.cache/pipeline/c97c4289b82440f9a717f22735d5741d/manifest.json).
- [Telemetria GPU](D:/models/.cache/benchmark-easy-japanese-1-final/gpu-telemetry.json).

Wynik jest odizolowany od głównego projektu użytkownika. Najważniejsze dalsze prace wynikające z testu: obsługa awarii alignera i bezpiecznego wyboru ASR, lepsza kontrola nazw i perspektywy rozmówców, naprawa czytelności powiązana z audio oraz ograniczenie wielokrotnego ładowania LLM. Samo zwiększanie liczby review obecnym modelem nie wystarczyło do usunięcia wykazanych błędów.

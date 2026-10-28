# Pełny test nagrania i porównanie z referencją — 28.10.2026

Poniższe pełne pomiary dotyczą wersji przed dodaniem osobnej analizy kontekstu całości i automatycznych poprawek w trybie zrównoważonym. Późniejsze zmiany i ich testy: [REVIEW_CONTEXT.md](REVIEW_CONTEXT.md).

## Zakres

Przetworzono **cały film Job Interview, 188,6 s (3:08,6)**, a nie tylko wcześniejszą próbkę 20 s. To japońska animacja z narracją, autor Simpleshow Japan, [źródło i CC BY-SA 4.0](https://commons.wikimedia.org/wiki/File:Job_Interview.webm). Dwa pełne przebiegi: Vulkan i CUDA, na NVIDIA GeForce RTX 5060 8 GB, sterownik 621.01.

Ustawienia: Whisper Large V3 FP16 GGML + Qwen3-ASR JA Anime Q8, oba z VAD; tekstowy wybór JP; Qwen3-4B Instruct Q4_K_M w profilach Naturalny/Wierny; wybór EN; pełne review AI, próba poprawy, ponowna ocena; formatowanie, JP/EN SRT i raport. Kontekst 4096, partie tłumaczenia po 6 napisów, opcjonalny szacowany podział zdań wyłączony. Surowe warianty zachowano. Pomiary obejmują ładowanie modeli i obsługę procesów.

## Czasy całego filmu

| Etap | Vulkan | CUDA |
|---|---:|---:|
| Odczyt metadanych | 0,36 s | 0,16 s |
| Audio z istniejącego cache | 0,02 s | <0,01 s |
| Whisper Large V3 | 39,59 s | 40,77 s |
| Qwen ASR | 56,08 s | 30,12 s |
| Porównanie / wybór JP | 50,78 s | 32,31 s |
| Tłumaczenie Naturalne | 55,50 s | 48,22 s |
| Tłumaczenie Wierne | 53,34 s | 46,23 s |
| Porównanie / wybór EN | 143,95 s | 102,00 s |
| Pełne review AI | 195,97 s | 150,03 s |
| Próba poprawy i porównanie | 106,88 s | 84,80 s |
| Ponowna ocena AI | 196,49 s | 144,59 s |
| Formatowanie | 0,01 s | <0,01 s |
| Raport i eksport | 0,02 s | 0,03 s |
| **Cały przebieg pipeline, czas ścienny** | **899,67 s — 15:00** | **680,09 s — 11:20** |

Odczyt metadanych jest mierzony osobno od czasu pipeline. Dodatkowy pomiar świeżego dekodowania całych 188,6 s do nowego WAV: **0,529 s**, bez użycia cache aplikacji; tymczasowy WAV usunięto. Nie resetowano cache systemu operacyjnego. Audio w dwóch głównych przebiegach było już przygotowane.

CUDA skróciła ten konkretny pełny przebieg o około **24,4%**. Whisper nie przyspieszył, Qwen ASR potrzebował około połowy czasu. To pojedyncze pomiary w kolejności Vulkan → CUDA; nie jest to benchmark uśredniony. Wybory modelu i końcowa segmentacja mogą się różnić, a pliki mogą być już w cache systemowym.

## Potwierdzenie CUDA i pamięci

- CrispASR CUDA 0.8.45 zgłasza `backends: cpu,cuda`, wykrywa RTX 5060, a Qwen wybiera `CUDA0`. Log Whispera potwierdza włączone GPU i bufory CUDA.
- Tłumacz używa osobnego oficjalnego llama.cpp b11935 CUDA, z `--device CUDA0 --n-gpu-layers 99`. Log silnika potwierdza backend CUDA z architekturą Blackwell. To nie jest wniosek wyłącznie z zaznaczonej opcji GUI.
- `nvidia-smi` próbkowano co około 2 s. Szczyt całej karty: **7725 MiB / 8151 MiB** podczas Qwena ASR, **5843 MiB** przy Whisperze, **4564 MiB** przy tłumaczeniu. Telemetria obejmuje również pulpit i inne procesy. Maksymalne próbkowane użycie GPU: 96%. Brak błędów odczytu telemetrii i brak awarii modelu.
- Pakiet CrispASR wypisuje ostrzeżenie o różnicy wersji podrzędnej: kompilacja CUDA 13.0, runtime 13.5. Testy inferencji zakończyły się prawidłowo. Po normalizacji tekst Whispera był taki sam na obu backendach; różnica Qwen CUDA/Vulkan wyniosła około 0,62% znaków. Nie ukryto ostrzeżenia w logach.
- Obecne domyślne ustawienia aplikacji wskazują **CUDA dla ASR i tłumacza**. Sprawdzono ich odczyt w nowym oknie Qt. Poprzednie ustawienia: `data/settings.before-cuda.json`; runtime’y Vulkan pozostają dostępne.
- Pobrano wyłącznie oficjalne runtime’y CUDA, zweryfikowano opublikowane SHA-256. Archiwa usunięto po rozpakowaniu. Istniejące wagi modeli wykorzystano z D: bez duplikowania. Przyrost danych na D: podczas całej tej serii to około 1,4 GiB, głównie runtime’y.

## Ocena wyniku i wykryte problemy

Oba przebiegi ukończyły wszystkie 12 etapów, zachowały 10 ścieżek i przeszły audyt zapisanych checkpointów, kompletności EN, granic czasów oraz zgodności tekstu/czasów po ponownym imporcie SRT. **To potwierdza działanie przebiegu, nie gotowość napisów do publikacji.**

| Wskaźnik końcowego wyniku | Vulkan | CUDA |
|---|---:|---:|
| Napisy | 52 | 55 |
| Napisy z co najmniej jednym ostrzeżeniem | 45 | 46 |
| EN powyżej 20 znaków/s | 6 | 6 |
| JP powyżej 8 znaków/s | 13 | 15 |
| Napisy uczestniczące w nakładaniu czasów | 2 — jedna para | 4 — dwie pary |
| Napisy oznaczone przez końcowe review AI | 8 | 13 |
| Tłumaczenia zmienione przez etap poprawek | 9 | 7 |

Ostrzeżenia obejmują też długość wierszy, małe przerwy oraz rozbieżności ASR. Jeden napis może mieć kilka ostrzeżeń. Ustawienia są celowo restrykcyjne; 46 ostrzeżeń nie oznacza 46 błędnych tłumaczeń.

**Konkretny problem do naprawienia:** oba surowe ASR w każdym przebiegu nie miały nakładających się napisów, a nakładanie pojawiło się dopiero po wyborze fragmentów z różnych wariantów. Krok mieszania JP potrzebuje kontroli zgodności czasów między sąsiednimi wybranymi grupami. Tego problemu nie zamaskowano przesuwaniem granic bez potwierdzenia w audio. Wynik pozostaje `needs_review`.

Review nie rozwiązuje wszystkich problemów znaczenia. Przykładowo w wyniku Vulkana pozostało podejrzane tłumaczenie metafory jako „clouds nesting in trees”; model sam oznaczył możliwą zmianę znaczenia. Nie wykonano pełnej ręcznej korekty ani odsłuchowej oceny wszystkich napisów. Dla Job Interview nie ma w tym teście niezależnej transkrypcji referencyjnej, więc nie podaje się jego „procentu poprawności ASR”.

**Wąskie gardło wydajności:** tylko decyzje i review (bez logów partii tłumaczenia przechowywanych w osobnym cache) uruchomiły LLM 172 razy na Vulkanie i 189 na CUDA. Z logów: samo ładowanie modelu zajęło odpowiednio około 440 s i 263 s. Kolejnym usprawnieniem powinno być przetwarzanie wielu decyzji w jednej partii przy zachowaniu walidacji ID i checkpointów; zwolnienie VRAM jest potrzebne między ciężkimi etapami, a ponowne ładowanie przy każdym pojedynczym werdykcie jest kosztowne.

## Film z istniejącą transkrypcją i rzeczywiste porównanie

Pobrano **MCDC Onboarding “Ask me Anything” — Japanese language**, rzeczywiste nagranie spotkania z 4 listopada 2022, **23:10**, około **20,9 MiB** w wersji 240p. Autor: TCappelletto (WMF), CC BY-SA 4.0. [Film](https://commons.wikimedia.org/wiki/File:MCDC_Onboarding_%22Ask_me_Anything%22_session_-_Japanese_language.webm), [istniejące napisy JP](https://commons.wikimedia.org/wiki/TimedText:MCDC_Onboarding_%22Ask_me_Anything%22_session_-_Japanese_language.webm.ja.srt), [istniejące napisy EN](https://commons.wikimedia.org/wiki/TimedText:MCDC_Onboarding_%22Ask_me_Anything%22_session_-_Japanese_language.webm.en.srt).

Zachowano oryginalne pliki napisów, ID rewizji, autorów edycji i sumy kontrolne. Przygotowana wersja JP ma 254 wpisy; EN ma 248 niepustych wpisów. Naprawiono wyłącznie separatory/numerację SRT; 10 pustych wpisów źródłowego EN pominięto z jawnym zapisem w `source.json`. Treści nie poprawiano naszą transkrypcją ani modelem.

Porównanie dotyczy **01:09.380–03:01.680**, czyli **112,3 s**, 22 kompletnych wpisów referencyjnych, 408 znaków po normalizacji. Nie przetworzono całego 23-minutowego nagrania. Na tym fragmencie sprawdzono dwa ASR; tłumaczenia i review tego drugiego materiału nie uruchamiano.

| ASR na CUDA | Czas etapu | Różnice znakowe względem referencji | CER |
|---|---:|---:|---:|
| Whisper Large V3 | 24,70 s | 25 / 408 | **6,13%** |
| Qwen3-ASR JA Anime | 22,55 s | 38 / 408 | **9,31%** |

Przygotowanie audio: 0,84 s. Cały test z porównaniem i zapisem: 48,38 s. CER liczono dokładną odległością Levenshteina po Unicode NFKC, usunięciu interpunkcji, spacji i oznaczeń muzyki; nie zrównywano kanji z kana ani różnych zapisów liczebników. Wyniki zawierają osobno zamiany/usunięcia/dodania i przykłady rozbieżności. Nie użyto procentu zgodności dwóch naszych modeli jako miary trafności.

**Wynik jest różnicą względem opublikowanych napisów społecznościowych, nie pewnym błędem względem audio.** Występują różnice zapisu imion, pomijane słowa i możliwe błędy samej referencji. Nie jest to niezależnie zatwierdzony zbiór wzorcowy ani pomiar jakości tłumaczenia. Na tym fragmencie Whisper był bliższy opublikowanym napisom.

## Pliki do sprawdzenia

- [Projekt całego łatwego filmu — CUDA](D:/models/.cache/benchmark-easy-cuda-full/projects/cb629c6ac27f47878fe905cc614e728f/project.sqlite).
- [Projekt referencja JP + Whisper + Qwen](D:/models/.cache/benchmark-reference-cuda/project.sqlite): gotowy do otwarcia w aplikacji i porównania ścieżek.
- [Nagranie referencyjne 23:10](D:/models/test-media/mcdc-japanese/MCDC-Japanese-23m-240p.webm), [JP SRT](D:/models/test-media/mcdc-japanese/reference.ja.srt), [EN SRT](D:/models/test-media/mcdc-japanese/reference.en.srt).
- [Czasy CUDA](D:/models/.cache/benchmark-easy-cuda-full/timings.json), [Vulkan](D:/models/.cache/benchmark-easy-full/timings.json), [pełne porównanie jakości i logów](D:/models/.cache/benchmark-easy-cuda-full/comparison-summary.json).
- [Telemetria CUDA](D:/models/.cache/benchmark-easy-cuda-full/gpu-telemetry.json), [wyniki CER i przykłady](D:/models/.cache/benchmark-reference-cuda/comparison.json).
- Manifest Vulkan: `D:\models\.cache\pipeline\3453c5f64d91402ebee141520c25963e\manifest.json`.
- Manifest CUDA: `D:\models\.cache\pipeline\a7e62c5e33794bf183c7573536c7e103\manifest.json`.
- Manifest referencji, tylko ASR: `D:\models\.cache\pipeline\c88c5cd80d8940d0b4d1e22a615ac464\manifest.json`.

## Powtórzenie pomiaru

```powershell
.\.venv\Scripts\python.exe -m tools.verify_pipeline --media samples\media\Job_Interview.webm --full --cuda --data-dir D:\models\.cache\benchmark-easy-cuda-full
.\.venv\Scripts\python.exe -m tools.verify_pipeline --media samples\media\Job_Interview.webm --full --vulkan --data-dir D:\models\.cache\benchmark-easy-full
.\.venv\Scripts\python.exe -m tools.verify_reference_asr --template D:\models\.cache\pipeline\a7e62c5e33794bf183c7573536c7e103\manifest.json --cuda
.\.venv\Scripts\python.exe -m pytest -q
```

Testy automatyczne po zmianach: **99 zaliczonych**. Obejmują jawny wybór CUDA/Vulkan/CPU, obliczanie CER i przygotowanie źródłowych napisów. Osobny test nowego okna Qt potwierdził odczyt zapisanych domyślnych ustawień CUDA.

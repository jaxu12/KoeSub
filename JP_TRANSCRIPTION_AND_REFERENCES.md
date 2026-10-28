# Transkrypcja JP, wycinki i baza referencyjna — 28.10.2026

Dodano tryb **„Tylko oryginalne napisy JP”** oraz preset **„Transkrypcja JP • Large V3 + wycinki”**. Nowe projekty zaczynają od tego trybu. Zapisane starsze konfiguracje pozostają dostępne. W tym trybie nie uruchamia się tłumaczenie, review EN, LM Studio ani wbudowany LLM. Eksport obejmuje wyłącznie JP i raport.

**Aktualizacja:** nowe przebiegi mają lokalne review fraz JP przed tłumaczeniem. Zastępuje ono historyczną decyzję o zamianie całego okna opisaną niżej. Na zapisanych wynikach tego filmu zastosowano 2 zmiany w 1 napisie bez zmiany czasów; 156 testów poprawnych. Szczegóły: [JP_SOURCE_REVIEW.md](JP_SOURCE_REVIEW.md).

## Jak działa nowy przebieg

1. **Large V3 + VAD jest bazą.** Kotoba i inne modele nie zastępują go przez tekstowe głosowanie.
2. Podejrzane miejsca są wskazywane przez niską pewność tokenów, powtórzenia i samą interpunkcję. Pewność jest wskaźnikiem ryzyka, nie dowodem błędu. Obecne progi to średnia poniżej 0,78 lub co najmniej 20% tokenów o pewności poniżej 0,4.
3. Program wycina audio z domyślnie 3 sekundami kontekstu przed i po. Granice obejmują całe sąsiednie napisy, wycinki nie nakładają się, pojedyncze okno ma maksymalnie 30 s. Domyślny limit to 12 wycinków.
4. Wycinek trafia ponownie do Large V3 i do wybranego modelu pomocniczego. Domyślnie jest nim Kotoba; dostępne są również testowe Qwen JA Anime/Galgame, Anime-Whisper i ReazonSpeech. Modele pracują kolejno, z jawnym wyborem CUDA i plikami na D:.
5. Automatyczna zamiana wymaga zgodności obu ponowień po normalizacji, poprawnych czasów, wystarczającej pewności ponowienia bazy oraz zachowania tekstu na granicach kontekstu. Sama Kotoba/Anime/Reazon/Qwen nie może przegłosować bazy. Nawet zastosowana zamiana pozostaje oznaczona do odsłuchu.
6. Rozbieżności zachowują bazę. Wszystkie propozycje, czasy prób, powody odrzucenia i logi są zapisywane. Checkpointy pozwalają wznowić bez powtarzania gotowych prób; zmienione źródła, granice i decyzje są wykrywane.

Przycisk **„Wycinki ASR • porównaj”** pokazuje tekst bazy, ponowienie Large V3, propozycję modelu pomocniczego i decyzję. Dwuklik odtwarza dany zakres filmu. Nie są przesuwane czasy bazy ani automatycznie zastępowany tekst ręcznie sprawdzony. Opcja układu JP łamie wiersze bez zmiany słów i czasów.

## Test na całym filmie

Easy Japanese 1, 282,73 s, CUDA:

| Etap | Czas |
|---|---:|
| Audio — istniejący cache | 0,00 s |
| Large V3 + VAD | 52,56 s |
| 9 podejrzanych wycinków, po 2 ponowienia | 252,50 s |
| Układ JP i eksport | 0,02 + 0,03 s |
| **Całość** | **305,984 s — 5 min 6 s** |

Wynik: **98 napisów, 3 ścieżki, 35 fragmentów z ostrzeżeniami**, brak tłumaczeń. Wybrano także wycinek z imieniem prowadzącej i wypowiedź o świeżych rybach. W tej ostatniej ponowienia nadal zawierały błędy. Żaden z 9 wycinków nie spełnił warunków bezpiecznej zamiany, więc **zastosowano 0 zmian tekstu**. To test działającego wykrywania i ponawiania, nie wykazana poprawa trafności.

Koszt ponowień obejmuje wielokrotne ładowanie ASR. Limit wycinków pozwala go ograniczyć. Nie wdrożono jeszcze utrzymywania modeli ASR w pamięci między wycinkami.

Pełny test interfejsu, SQLite, digestów etapów i ponownego odczytu JP SRT przeszedł poprawnie. [Czasy](D:/models/.cache/benchmark-jp-retry/timings.json), [manifest](D:/models/.cache/pipeline/841464cecf4343fa9f1217ed29d341fc/manifest.json), [raport z propozycjami](D:/models/.cache/benchmark-jp-retry/projects/aa0d7508eb3f44788313c3afd7cf662e/exports/841464cecf4343fa9f1217ed29d341fc/report.json).

## Jak korzystamy z referencji

Przygotowano **30 niepokrywających się wycinków**, łącznie 599,802 s audio FLAC, około 18,59 MiB. Audio jest zapisane raz i współdzielone przez przykłady ASR/review. Pochodzi z istniejącego nagrania MCDC i istniejącego japońskiego SRT.

- 19 wycinków ma etykietę `development`, 11 `control`.
- Pierwsze 5 tworzy stały rdzeń wstępnego porównania modeli: 22 napisy i 408 znaków po normalizacji.
- Wszystkie wycinki pochodzą z jednego nagrania. Podział jest rozłączny czasowo, ale **nie jest niezależny pod względem rozmówców ani źródła**. Do mocnej oceny generalizacji potrzebne będą kolejne nagrania.
- Tekst pochodzi ze społecznościowych napisów; nie został ręcznie sprawdzony przez odsłuch. Dane mają jawne `human_audio_verified: false` i `training_ready: false`.

**ASR dostaje tylko audio.** Dopiero po rozpoznaniu porównujemy jego tekst z referencją. CER mierzy różnicę znaków względem SRT, po usunięciu interpunkcji i odstępów oraz normalizacji Unicode. Nie zrównuje automatycznie kanji z hiraganą, więc część różnic może dotyczyć pisowni. Nie jest to bezbłędny pomiar zgodności z audio ani ocena tłumaczenia.

Podział roboczy/kontrolny pozwala zmieniać ustawienia na części roboczej, a potem sprawdzać wynik na kontrolnej. Wielokrotne wybieranie ustawień na podstawie kontroli zużywa jej niezależność — wtedy potrzeba nowego, odłożonego zbioru.

## Dane pod dostosowanie review i Whispera

Ta sama baza ma dwa zastosowania:

- **Whisper:** audio → poprawny JP. Plik `asr_examples.jsonl` zawiera 30 par, lecz etykiety wymagają kontroli przed zaufanym treningiem.
- **Review:** hipoteza ASR → ocena i ewentualna propozycja JP. Przygotowano 30 przykładów bez zmian, 30 ze sztucznie dodanym powtórzeniem i 5 rzeczywistych wyników Large V3. Przykłady sztuczne są wyraźnie oznaczone; różnice rzeczywistego ASR wobec SRT wymagają audytu, zamiast automatycznej etykiety „błąd”.

Łącznie zapisano **65 wejść review** bez poprawnych odpowiedzi oraz osobne **65 etykiet referencyjnych**. Pliku z etykietami nie wolno podawać modelowi podczas testu. Przykłady poprawne służą także pomiarowi niepotrzebnych zmian. Tekstowy LLM nie słyszy audio; propozycja językowa nie dowodzi, co powiedziano.

**Nie przeprowadzono douczania wag.** Przygotowano bazę, przykłady i pomiar obecnych modeli. Przed treningiem potrzebna jest kontrola etykiet i szerszy zbiór. Pliki GGML/GGUF służą tu inferencji; trening wymaga osobnego przygotowania źródłowych wag i środowiska.

Pliki:

- [Indeks 30 wycinków i pochodzenie](D:/models/datasets/subtitle-studio-references-v1/index.json).
- [Pary audio–JP dla ASR](D:/models/datasets/subtitle-studio-references-v1/asr_examples.jsonl).
- [Wejścia review bez odpowiedzi](D:/models/datasets/subtitle-studio-references-v1/review_inputs.jsonl).
- [Osobne odpowiedzi i oznaczenia jakości etykiet](D:/models/datasets/subtitle-studio-references-v1/review_labels.jsonl).
- [Rzeczywiste pary wynik ASR–referencja](D:/models/datasets/subtitle-studio-references-v1/review_real_asr_examples.jsonl).

## Nowe modele: co faktycznie sprawdzono

Porównanie tych samych pięciu wycinków, CUDA, bez podawania referencji jako promptu:

| Model w naszym runtime | CER całego rdzenia | Poprawne czasy napisów |
|---|---:|---:|
| Large V3 | **6,62%** | **5/5** |
| Kotoba + aligner | **10,78%** | **5/5** |
| ReazonSpeech NeMo v2 FP16 GGUF | **27,94%** dla tekstu | **1/5** |
| Anime-Whisper GGML FP16 | Brak pełnego porównywalnego wyniku | **3/5**; jedna próba miała uszkodzone UTF-8 |

Pomiar tekstu rozdzielono od poprawności czasów. ReazonSpeech miał czytelny tekst we wszystkich próbach, lecz w czterech zerowe czasy; pojedynczy dodatkowy test z alignerem i krótszymi oknami nie usunął problemu. Dla Anime nie wyliczano porównywalnego pełnego CER po odrzuceniu uszkodzonego tekstu. Wyniki dotyczą małej próbki oraz konkretnych konwersji/runtime’u, nie całej jakości oryginalnych modeli Python.

ReazonSpeech jest pobrany jako jeden zgodny z CrispASR plik [FP16 GGUF](D:/models/asr/reazonspeech-nemo-v2-f16.gguf), 1 240 435 584 bajty. [Źródło konwersji](https://huggingface.co/cstr/reazonspeech-nemo-v2-GGUF). Nie instalowano dużego środowiska NeMo/PyTorch. Pozostaje opcją testową.

Anime-Whisper jest pobrany jako jeden [plik GGML FP16](D:/models/whisper/ggml-anime-whisper.bin). Konwersja Aratako ma [opisany przez autora problem z tekstem](https://huggingface.co/Aratako/anime-whisper-ggml), który ujawnił się także w próbach. Nie zastępuje domyślnej Kotoby. Oryginalny [litagin/anime-whisper](https://huggingface.co/litagin/anime-whisper) opiera się na Kotobie i jest dostrojony do anime/gier; nie należy utożsamiać awarii tej konwersji z oceną oryginalnego modelu. Nie używano initial prompt, zgodnie z zaleceniem autora.

Qwen3-ASR 1.7B JA Anime/Galgame **był już pobrany**: [Q8_0 GGUF](D:/models/asr/qwen3-asr-1.7b-ja-anime-q8_0.gguf), 2 506 725 376 bajtów. Potwierdzono SHA256 `f173ceddb15b59177575a101491862bd362cd85f2e7a6bac811fbc53411596a1` i [pochodzenie Anime/Galgame](https://huggingface.co/cstr/qwen3-asr-1.7b-ja-anime-GGUF). Nie pobierano duplikatu. Jego wcześniejsze awarie alignera pozostają opisane w raportach.

[Kana-Whisper](https://huggingface.co/sbintuitions/kana-whisper) zwraca katakanową transkrypcję wymowy. Sprawdzono przeznaczenie: może służyć dodatkowej kontroli fonetycznej i Kana-CER, lecz nie daje zwykłych napisów z kanji. Nie został pobrany ani dodany jako zamiennik tekstowego JP.

[Surowe próby modeli](D:/models/datasets/subtitle-studio-references-v1/model-comparison/results.json) · [Porównanie tekstu i ważności czasów](D:/models/datasets/subtitle-studio-references-v1/model-comparison/summary.json).

## Weryfikacja i wynik do otwarcia

**138 testów automatycznych poprawnych**, m.in. tryb bez modeli tłumacza, brak wywołań LLM, JP-only eksport, ochrona bazy i ręcznych zmian, offsety wycinków, brak samodzielnego głosu modelu pomocniczego, utrata kontekstu, cache i wykrywanie zmienionych checkpointów, odrzucanie UTF-8 oraz porównanie/odsłuch w Qt.

- [Projekt JP z wycinkami](D:/models/.cache/benchmark-jp-retry/projects/aa0d7508eb3f44788313c3afd7cf662e/project.sqlite).
- [Japońskie SRT](D:/models/.cache/benchmark-jp-retry/projects/aa0d7508eb3f44788313c3afd7cf662e/exports/841464cecf4343fa9f1217ed29d341fc/Japanese.srt).

Wagi, nagrania i cache pozostają na D:. Nie zmieniono głównego projektu użytkownika ani nie uruchamiano testów Vulkana.

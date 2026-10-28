# Zestaw testowy na D: — 28.10.2026

Aktualizacja: domyślne ASR i tłumacz działają teraz na **CUDA**. Oficjalne runtime’y: `D:\models\.runtime\crispasr-v0.8.45-cuda13\crispasr-windows-x86_64-cuda13\crispasr.exe` oraz `D:\models\.runtime\llama-b11935-cuda13\llama-completion.exe`. Wykrycie CUDA i rzeczywista inferencja obu ASR oraz tłumacza zostały sprawdzone na RTX 5060. Sumy SHA-256 i dane wydań są w plikach `*.receipt.json` w tych folderach; podsumowanie wykrytych urządzeń w `D:\models\.runtime\cuda-runtimes.json`. Wersje Vulkan zachowano, poprzednia konfiguracja jest w `data/settings.before-cuda.json`. Pełne pomiary i wykryte ograniczenia: [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md).

Modele są zapisane bezpośrednio w `D:\models`, bez kopii w cache Hugging Face na C:. Pliki `.part` powstają obok pliku docelowego na D:, pobieranie sprawdza zapas miejsca, a ukończone pliki mają zweryfikowane opublikowane sumy SHA-256. Wersje repozytoriów i pełne sumy są w `D:\models\subtitle-studio-models.json`.

| Zastosowanie | Model / plik | Rozmiar |
|---|---|---:|
| Whisper Large V3 FP16 | `whisper/ggml-large-v3.bin` | 2,88 GiB |
| Japońskie ASR | `asr/qwen3-asr-1.7b-ja-anime-q8_0.gguf` | 2,33 GiB |
| Dopasowanie czasów | `asr/qwen3-forced-aligner-0.6b-q8_0.gguf` | 0,92 GiB |
| Wykrywanie mowy | `asr/ggml-silero-v6.2.0.bin` | 0,84 MiB |
| Tłumaczenie JA → EN | `lmstudio-community/Qwen3-4B-Instruct-2507-GGUF/Qwen3-4B-Instruct-2507-Q4_K_M.gguf` | 2,33 GiB |

Poprzedni runtime CrispASR v0.8.45 Vulkan jest w `D:\models\.runtime\crispasr-v0.8.45-vulkan`. Może służyć jako zapasowa opcja dla RTX 5060. Archiwa pobrane do D: zostały usunięte po weryfikacji i rozpakowaniu. Cache roboczy aplikacji wskazuje `D:\models\.cache`. Duże wejściowe filmy nadal pozostają tam, gdzie je użytkownik umieścił.

Wbudowany tłumacz ma własny silnik llama.cpp; wersja Vulkan pozostaje w `D:\models\.runtime\llama-b11935-vulkan\llama-completion.exe`, a aktualna wersja CUDA jest wskazana powyżej. Whisper używa backendu whisper.cpp w CrispASR; nie wymaga osobnego dużego runtime Faster Whisper. Starsze manifesty modeli: `D:\models\subtitle-studio-whisper.json` i `D:\models\subtitle-studio-embedded-llm.json`; bieżące ścieżki runtime sprawdzaj w ustawieniach aplikacji.

## Użycie

1. W aplikacji domyślnie wybrany jest **Whisper • whisper.cpp / GPU**, `ggml-large-v3.bin`, **cuda**. Alternatywnie wybierz **Qwen3-ASR • CrispASR**, JA Anime Q8. VAD i aligner mają wskazane konkretne lokalne pliki.
   Dostępne backendy są odczytywane z wybranego silnika: wydanie CUDA udostępnia CPU/CUDA, a wydanie Vulkan CPU/Vulkan. VAD może pracować na CPU niezależnie od głównego modelu.
2. Na początek użyj 20–60 sekund animacji albo bazowej wersji filmu. Wersja `noisy` jest testem skrajnym, a nie jedynym sprawdzianem jakości.
3. Po ASR w **Tłumaczenie i kontrola** pozostaw **Wbudowany • lokalny GGUF**, Qwen3-4B Instruct, i kliknij **Tłumacz / wznów aktywną ścieżkę**. Silnik uruchamia się automatycznie, bez HTTP i LM Studio. Wyniki są zapisywane, a pamięć zwalniana po partii oraz po anulowaniu.
4. Drugą opcją jest **LM Studio • opcjonalny serwer**: udostępnij model z D: i kliknij **Sprawdź serwer / modele**. Starszy **Uruchom_tlumacza_D.bat** jest opcjonalnym ręcznym serwerem llama.cpp; nie jest potrzebny do trybu wbudowanego.
5. Modele uruchomione w zewnętrznym serwerze zwalniaj tam przed kolejnym ASR. Tryb wbudowany robi to automatycznie. Sprawdź EN w edytorze i eksportuj SRT.

Wbudowany profil obsługuje obecnie Qwen3 Instruct. Osobny proces dla każdej partii (domyślnie 6 napisów, kontekst 4096 tokenów) pozwala zwalniać VRAM, ale ponowne ładowanie modelu ma koszt czasowy. CPU można wybrać jawnie; aplikacja nie przełącza urządzenia automatycznie po błędzie GPU.

Pełne modele rozpoznawania i tłumaczenia mają różne zadania. GGUF tłumacza nie może być wybrany jako model ASR. Prototyp filtruje te typy.

## Weryfikacja

Zestaw został sprawdzony rzeczywistą inferencją: ASR rozpoznał 20 sekund japońskiej mowy na RTX 5060 przez Vulkan, a Qwen3-4B przetłumaczył dwa wynikowe napisy do angielskiego. Wyniki przeszły walidację formatu/ID, czasy ASR były prawidłowe. Tymczasowy serwer testowy tłumacza zakończono. Nie jest to certyfikat jakości przekładu ani pełności transkrypcji.

Nowy Whisper Large V3 rozpoznał 20 sekund japońskiej mowy na Vulkan/RTX 5060: cztery poprawne czasowo segmenty. Dodatkowy test z GUI po poprawce backendów: 60 sekund, 16 napisów zapisanych w SQLite, bez fallbacku urządzenia (`verification-gui-asr-backend` w cache). Wbudowany Qwen3-4B przetłumaczył dwa napisy bez serwera. Pełny test GUI potwierdził zapis EN w SQLite i anulowanie procesu modelu. Logi: `D:\models\.cache\verification-whisper`, `verification-embedded` i `verification-gui-embedded`. Testy automatyczne aplikacji: **35 zaliczonych**, w tym zamykanie procesu potomnego po awarii workera.

## Źródła

- [Whisper GGML — ggerganov/whisper.cpp](https://huggingface.co/ggerganov/whisper.cpp)
- [llama.cpp b11935](https://github.com/ggml-org/llama.cpp/releases/tag/b11935)
- [Konwersja ASR JA Anime, cstr](https://huggingface.co/cstr/qwen3-asr-1.7b-ja-anime-GGUF)
- [Forced aligner, cstr](https://huggingface.co/cstr/qwen3-forced-aligner-0.6b-GGUF)
- [Silero VAD, ggml-org](https://huggingface.co/ggml-org/whisper-vad)
- [Qwen3-4B Instruct GGUF, LM Studio Community](https://huggingface.co/lmstudio-community/Qwen3-4B-Instruct-2507-GGUF)
- [Runtime CrispASR v0.8.45](https://github.com/CrispStrobe/CrispASR/releases/tag/v0.8.45)


## Kotoba-Whisper — opcjonalny trzeci model

Oficjalny Kotoba v2.0 GGML FP16 jest w D:/models/whisper/ggml-kotoba-whisper-v2.0.bin (1,42 GiB). Odtworzenie pobrania: `python -m tools.fetch_kotoba`; narzędzie ponownie używa zgodnego pliku i sprawdza SHA256 bez dodatkowego cache. Model korzysta z istniejącego alignera Qwen3 0.6B. W presecie 3 ASR włączone jest VAD, wymagane w sprawdzonej konfiguracji tego filmu.

Nowe przebiegi wbudowane używają sąsiedniego llama-server.exe z tego samego pakietu runtime: aplikacja uruchamia go automatycznie na loopback, utrzymuje model między etapami i zamyka po zadaniu. Nie wymaga osobnego LM Studio ani nowych wag. Gdy tego pliku nie ma, pozostaje dotychczasowy tryb llama-completion. Pełne wyniki CUDA i ograniczenia: [KOTOBA_AND_FIXES.md](KOTOBA_AND_FIXES.md).

# Zależności i materiały zewnętrzne

Licencja [MIT](LICENSE) dotyczy własnego kodu i dokumentacji AI Subtitle Studio. Nie obejmuje automatycznie bibliotek, wag modeli, zewnętrznych programów ani testowych nagrań.

## Biblioteki Pythona

Zależności i ich wersje są w `requirements.txt` oraz `requirements-dev.txt`. W zainstalowanym środowisku metadane deklarują:

| Pakiet | Licencja w metadanych pakietu |
|---|---|
| PySide6 Essentials i Addons / Qt for Python | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| pysubs2 | MIT |
| httpx | BSD-3-Clause |
| pytest — narzędzie do testów | MIT |

Pełne warunki i informacje o składnikach znajdują się w dystrybucjach odpowiednich pakietów. PySide6 Addons i biblioteki Qt mają własne pliki licencyjne; powyższa tabela nie zastępuje informacji dostarczanych z Qt. Repozytorium nie zawiera tych bibliotek ani gotowej paczki aplikacji z nimi.

## Silniki i modele

Aplikacja może korzystać z [CrispASR](https://github.com/CrispStrobe/CrispASR), [whisper.cpp](https://github.com/ggml-org/whisper.cpp), [llama.cpp](https://github.com/ggml-org/llama.cpp), [FFmpeg](https://ffmpeg.org/), lokalnej instalacji Subtitle Edit i opcjonalnego LM Studio. Programy te nie są dołączone do repozytorium i zachowują własne licencje oraz informacje o autorach. Warunki FFmpeg zależą także od użytej kompilacji.

Whisper, Kotoba, Qwen, Anime-Whisper, ReazonSpeech i ich konwersje mają oddzielne karty modeli i licencje. Dokumentacja oraz skrypty pobierania wskazują konkretne źródła. Sprawdź warunki wybranej wersji przed jej użyciem lub redystrybucją. MIT aplikacji nie zmienia warunków modelu.

## Materiały testowe

Syntetyczne przykłady `samples/japanese_a.srt` i `samples/japanese_b.srt` są częścią projektu. Filmy, audio, referencyjne napisy i zewnętrzne zbiory używane do testów nie są dołączone. Ich źródła opisują raporty oraz dokumenty w `samples/`; samo użycie materiału w teście nie nadaje mu licencji MIT.

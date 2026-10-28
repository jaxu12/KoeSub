# Stan prototypu — 28.10.2026

## Aktualnie: review stosujące poprawki i kontekst całości

Nowe przebiegi AI mają osobne **Sprawdź i popraw / Tylko sprawdź**. Poprawki działają również w trybie zrównoważonym. Panel AI automatycznie stosuje potwierdzone propozycje, chroni ręczne EN, pokazuje licznik i przed/po oraz obsługuje cofanie. Dodano opis tematu z całego dostępnego JP i kontrolę spójności JP/EN między fragmentami. Test wykrył utratę wcześniejszych faktów przy aktualizacji jednej pamięci; zastąpiono ją kompaktową analizą całości lub opisami części i ich wspólnym podsumowaniem.

**107 testów zaliczonych.** Na rzeczywistym CUDA poprawiono dwa celowo błędne EN i sprawdzono Cofnij/Ponów; nowy pipeline działał od ASR do eksportu. Osobno oceniono kontekst wszystkich 55 napisów pełnego filmu i otrzymano opis poradnika o rozmowie kwalifikacyjnej. Szczegóły i ograniczenia: [REVIEW_CONTEXT.md](REVIEW_CONTEXT.md).

## Poprzednio: pełny film, CUDA i referencja zewnętrzna

Przetworzono cały Job Interview (188,6 s): 15:00 na Vulkanie, 11:20 na CUDA, po dwa ASR i EN oraz pełne review/poprawki. Potwierdzono CUDA w obu ASR i tłumaczu na RTX 5060, zapisano telemetrię; domyślne ustawienia przestawiono na sprawdzone runtime’y CUDA. Poprzednie ustawienia i wersje Vulkan zachowano. Wagi modeli wykorzystano bez pobierania/kopiowania.

Wynik wymaga kontroli: CUDA 55 napisów, 46 z ostrzeżeniami; po mieszaniu wariantów JP powstają nakładania, których nie ma w surowych ASR. Wielokrotne ładowanie LLM jest dużym kosztem review. To konkretne problemy ujawnione przez test, nadal do poprawy.

Pobrano rzeczywiste 23-minutowe spotkanie MCDC z istniejącymi napisami JP/EN (około 21 MiB). Na 112,3 s, względem 408 znaków opublikowanej referencji: Whisper CER 6,13%, Qwen 9,31%; referencja społecznościowa nie jest niezależnie zatwierdzonym wzorcem. Projekt porównawczy gotowy do otwarcia. **99 testów zaliczonych.** Czasy, ograniczenia i linki do wyników: [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md).

## Poprzednio: testy i poprawka odczytu checkpointów Windows

**94 testy zaliczone.** Rzeczywisty test GPU wykrył chwilową blokadę odczytu manifestu, mimo poprawnie ukończonej inferencji. Naprawiono odczyt przez ograniczone ponawianie blokad Windows; dodano osiem przypadków regresji. Powtórzony pełny pipeline, audyt zapisanych SRT/checkpointów, panel propozycji AI, waveform, ASS/TXT, rzeczywiste anulowanie lokalnego modelu, zapis SQLite i odtwarzanie filmu zaliczone. Cztery napisy w próbce nadal mają ostrzeżenia jakościowe. Szczegóły i artefakty: [TEST_REPORT.md](TEST_REPORT.md). Poniżej historia wcześniejszych etapów.

## Poprzednio: ponowny audyt specyfikacji i usprawnienia obsługi

Ponownie przeczytano pierwotną specyfikację; wynik i pozostałe braki: [SPEC_REVIEW.md](SPEC_REVIEW.md). Dodano waveform z zoomem i zaznaczaniem zakresu, wyszukiwanie/filtry, status ręcznej kontroli, zakładki/notatki, skróty, zapis edycji przy zmianie wiersza, ostatnie projekty i przeciąganie plików. Typowe poprawki, scalanie mikronapisów i przesunięcie czasów mają podgląd i cofanie. Częściowy EN nie może zniknąć przy scaleniu.

Osobny panel propozycji AI: uzasadnienie, propozycja, decyzje pojedyncze/zbiorcze i ochrona przed zmianą kontekstu. Kontrola wyniku JP→EN wstrzymuje niepotwierdzone propozycje. JSON sam w sobie nie jest uznawany za dowód poprawnego przekładu. W teście jeden model mylił sąsiedni dialog, więc target jest obecnie wyodrębniony, kontekst zawiera JP, a propozycja przechodzi dodatkową kontrolę.

Pipeline: opcjonalna pauza po niepewnym wyborze, przyjęcie ręcznie sprawdzonej ścieżki i kontynuacja bez ponownego ASR. Adnotacje nie blokują wznowienia. Eksport SRT/ASS/SSA/TXT, odbudowa usuniętego cache audio, menu bezpiecznego czyszczenia wyłącznie rozpoznanych plików audio/waveformów. Ręczny ASR ma timeouty, procesy licznik czasu. Okno mieści się na mniejszych ekranach dzięki przewijaniu.

**86 testów zaliczonych** oraz rzeczywisty test waveformu, trzech ocen lokalnego AI i ASS/TXT (`tools.verify_qol`). Cache waveformu: około 0,25 MB/godz., bez kopii WAV. Brak nowych pobrań modeli. Podglądy: `D:\models\.cache\verification-qol`. Nadal nie ma separacji głosu, forced alignment do poprawy istniejących czasów, pełnych zaawansowanych presetów, dedykowanego TranslateGemma/Qwen3.5, kolejki filmów ani EXE. Poniżej historia wcześniejszych etapów.

## Aktualnie: „Zrób wszystko”

Dodano automatyczny sekwencyjny pipeline z 1–4 ASR, 1–4 wariantami EN, wyborem modeli i profili oraz trzema poziomami review. Domyślnie Whisper + Qwen-ASR, dwa profile Qwen3-4B i review podejrzanych miejsc. Pełny tryb wykonuje ocenę AI wszystkich napisów, próbę poprawy i ponowną ocenę. Wybór JP/EN korzysta z lokalnego modelu, zachowuje kandydatów i oznacza niepewność. Kolejne ciężkie procesy zwalniają GPU. Bez dodatkowych pobrań.

Presety, podgląd planu, automatyczne SRT i raport, opcjonalny podział dwóch zdań z oznaczonym szacowanym czasem, dźwięk zakończenia i otwieranie wyników. Manifesty, logi i checkpointy na D:. Wznowienie nie powtarza ukończonych etapów i zachowuje częściowy EN. Ochrona przed zmianą wejścia/modelu i ręcznych ścieżek po zatrzymaniu oraz blokada drugiego procesu tego samego przebiegu. Atomowy zapis odporny na krótkie blokady odczytu Windows.

**61 testów zaliczonych**. Rzeczywisty świeży test Qt: 20 s JA → dwa ASR na RTX 5060/Vulkan → wybór JP → dwa tłumaczenia → wybór EN → pełne AI + poprawki + ponowna ocena → formatowanie → JP/EN SRT i raport. 10 zachowanych ścieżek, 5 końcowych napisów, 4 ostrzeżenia. Przebieg: `D:\models\.cache\pipeline\7a974fa47b5241ca98e4056b66ddfb94`. Wcześniejszy przebieg sprawdził rzeczywiste wznowienie po przerwaniu. Podgląd: `D:\models\.cache\verification-pipeline-ui\pipeline-preview.png`.

Ograniczenie: AI porównuje tekst, nie weryfikuje odsłuchu. Zgodność dwóch modeli nie jest dowodem poprawności; różnice ASR i niepewne wybory pozostają w raporcie. Nadal brak kolejki wielu filmów i naprawy synchronizacji na podstawie audio. Szczegóły w README. Poniżej zachowano historię wcześniejszych etapów.

## Aktualnie: review czytelności i podgląd podziału

Dodano zakładkę **Review napisów**: CPS JP/EN, czas trwania, długości/liczbę wierszy, nakładanie, krótkie przerwy i koniec poza filmem. Limity są edytowalne i zapisane w projekcie; stare projekty używają domyślnych wartości. Uwagi są widoczne również w edytorze i tabeli tłumaczenia. Filtr ostrzeżeń, przejście do edycji i odsłuch ułatwiają sprawdzenie problemów.

Podgląd podziału zachowuje JP i EN, ma osobne punkty obu tekstów oraz edytowalny czas. Propozycja czasu jest heurystyką tekstową, nie wyrównaniem do audio. Osobny podgląd zawija EN bez zmiany słów i czasu. Obie operacje obsługują anulowanie, zapis i cofanie; podział nie usuwa już istniejącego EN. Sam podział nie jest przedstawiany jako naprawa wysokiego CPS. Brak semantycznego AI Review pozostaje aktualny.

**45 testów zaliczonych**, w tym granice czasów, zagnieżdżone nakładanie, metryki, zachowanie tekstu i ID/pochodzenia, zapis ustawień, podgląd/anulowanie/cofanie w Qt. Widoki sprawdzono na renderach `data/review-preview`. Szczegóły i źródła progów w README. Poniżej historia poprzednich etapów.

## Aktualnie: wbudowany tłumacz i Whisper na D:

Poprawiono wybór backendu ASR po odczytaniu logów użytkownika: kompilacja CrispASR ma CPU/Vulkan, a GUI pozwalało wybrać CUDA. Whisper mimo tego używał Vulkan; Qwen zgłaszał fallback. GUI wykrywa backendy z `--version`, blokuje niedostępne, poprawia zapisany niezgodny wybór na Vulkan i sprawdza zgodność ponownie przed ASR. Ustawienia XXL są nieaktywne w trybie whisper.cpp/Qwen. Test sprzętowy z GUI: 60 sekund japońskiego audio, Vulkan bez fallbacku, 16 napisów zapisanych w SQLite. Aktualny wynik: **35 testów zaliczonych**.

Domyślny tryb tłumaczenia uruchamia bezpośrednio lokalny `llama-completion.exe` z GGUF Qwen3-4B Instruct. Nie używa HTTP, LM Studio ani serwera. LM Studio pozostaje drugą opcją w interfejsie. Modele, własny runtime llama.cpp b11935 Vulkan i cache znajdują się na D:. Wyniki są walidowane i zapisywane; proces modelu kończy się po partii, przy anulowaniu oraz po awarii workera (Windows Job Object).

Pobrano i sprawdzono SHA-256 Whisper Large V3 FP16 GGML (2,88 GiB) do `D:\models\whisper`. Istniejący runtime CrispASR obsługuje go przez whisper.cpp/Vulkan. Rzeczywisty test japońskiego audio na RTX 5060 dał cztery segmenty SRT. Wbudowany Qwen przetłumaczył dwa napisy bez serwera; test GUI potwierdził wynik w SQLite i anulowanie kolejnego zadania. **31 testów automatycznych zaliczonych**. Szczegóły: [MODEL_SETUP.md](MODEL_SETUP.md).

Ograniczenia: wbudowany profil Qwen3 Instruct, ponowne ładowanie modelu po każdej partii, brak automatycznego limitu cache. Następne funkcje: semantyczny AI Review, waveform, wygodniejsze zatwierdzanie napisów i limity cache/VRAM. Poniżej zachowano wcześniejsze etapy przygotowania prototypu.

## Wcześniejsze etapy

Zaimplementowano funkcje opisane w sekcji „Co działa” w README. Interfejs jest aplikacją PySide6, nie makietą HTML. Brak pobierania modeli. Znalezione modele Subtitle Edit i LM Studio są tylko odczytywane w oryginalnych lokalizacjach.

Zweryfikowano odtwarzanie syntetycznego MP4, odczyt ścieżki audio przez FFmpeg, przesuwanie czasu, podgląd napisów oraz zapis projektu. Sprzętowy test Faster Whisper XXL na RTX 5060 użył istniejącego Large V3 Turbo i lokalnie wygenerowanej angielskiej mowy: wyjście SRT powstało, zawierało cztery segmenty z prawidłowymi przedziałami czasu. Ten test potwierdza integrację i inferencję, nie jakość japońskiej transkrypcji.

LM Studio nie udostępniał serwera na 127.0.0.1:1234 podczas przygotowywania prototypu. Integracja HTTP, odrzucanie błędnego ID/JSON, zapis postępu i wznowienie są sprawdzane testowym serwerem lokalnym; jakość przekładu rzeczywistym modelem pozostaje do sprawdzenia po włączeniu serwera.

Sprzętowy test CrispASR z istniejącym Qwen3-ASR JA Anime Q8, lokalnym VAD i lokalnym forced alignerem również zakończył się powodzeniem: trzy segmenty SRT i rozpoznana syntetyczna angielska wypowiedź. Nie pobrano modeli. Testy obejmują Qt, lokalny HTTP i ochronę przed zapisywaniem pełnej kopii historii dla każdego napisu.

Wynik końcowy: **22 testy zaliczone**. Środowisko aplikacji zajmuje około 333 MiB; modele pozostały w istniejących lokalizacjach. Aplikację uruchomiono przez `pythonw -m studio`; ponowne uruchomienie jest dostępne przez `Uruchom.bat`.

Istotne ustalenie: zainstalowany Faster Whisper XXL r245.4 nie przyjmuje pełnej ścieżki jako `--model`. Adapter przekazuje nazwę i istniejący folder nadrzędny `--model_dir`. Niezależnie od kodu wyjścia sprawdzana jest obecność i poprawność SRT, ponieważ to wydanie potrafi zwrócić kod 0 przy błędnej nazwie modelu.

Następne zadania: testy rzeczywistego nagrania JA i lokalnego tłumaczenia; wygodne zatwierdzanie/oznaczanie napisów; semantyczny AI Review z propozycjami; lepsze dopasowanie przesuniętych transkrypcji; waveform; zarządzanie limitem cache i budżetem VRAM. Potem adapter TranslateGemma, separacja audio, pipeline i dystrybucja EXE.

## Aktualizacja — modele usunięte przez użytkownika, nowy zestaw na D:

Na wyraźne polecenie użytkownika pobrano zestaw z [MODEL_SETUP.md](MODEL_SETUP.md) bezpośrednio do `D:\models`. W katalogach ASR Subtitle Edit nie było już także silników, dlatego na D: zainstalowano niewielki oficjalny runtime CrispASR v0.8.45 Vulkan. Nie odtwarzano ciężkich wcześniejszych zestawów na C:.

Wszystkie modele i archiwum silnika zostały zweryfikowane SHA-256 względem metadanych źródeł. Aligner i VAD są teraz wskazywane w ustawieniach po jawnych ścieżkach, więc mogą być poza katalogiem silnika. Dodano wybór backendu CrispASR w GUI. `data/settings.json` wskazuje modele i nowy cache na D:.

Rzeczywisty test nowego zestawu: 20 sekund japońskiej mowy z pobranej animacji dało pięć segmentów SRT z prawidłowymi czasami. Log potwierdza **Vulkan0 — NVIDIA GeForce RTX 5060**. Następnie istniejący `llama-server.exe` uruchomiono tymczasowo na wolnym porcie loopback, z GGUF Qwen3-4B Instruct na D:. Dwa japońskie segmenty zostały przetłumaczone do EN przez rzeczywisty model i przeszły walidację odpowiedzi. Serwer testowy został zatrzymany, aby zwolnić VRAM.

Wyniki tych testów: `D:\models\.cache\verification-japanese` i `D:\models\.cache\verification-translation`. To potwierdza integrację i działanie, nie pełną ocenę jakości. Zaszumiony klip filmowy traktujemy jako test skrajny; podstawową ocenę zaczynamy od słyszalnych kwestii i wersji bazowej. Końcowy zestaw automatyczny: **23 testy zaliczone**.

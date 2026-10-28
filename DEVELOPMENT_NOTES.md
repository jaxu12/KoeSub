# AI Subtitle Studio — szczegółowe notatki z rozwoju prototypu

Ten dokument zachowuje historię funkcji, lokalnych konfiguracji i kolejnych testów. Opisy starszych ustawień mogą różnić się od aktualnych domyślnych. Wprowadzenie i uruchomienie projektu: [README.md](README.md).

Lokalna aplikacja Windows do pracy z japońskimi napisami i tłumaczeniem EN.

Ponowny przegląd pierwszej specyfikacji i aktualne braki: [SPEC_REVIEW.md](SPEC_REVIEW.md).

Pełny test 3-minutowego filmu na CUDA/Vulkan, czasy etapów i porównanie z zewnętrzną transkrypcją: [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md).

## Uruchomienie

Na tym komputerze środowisko jest przygotowane. Otwórz **Uruchom.bat**.

Przygotowano Whisper Large V3 i Qwen3-4B Instruct na `D:\models`: zobacz [MODEL_SETUP.md](MODEL_SETUP.md). Domyślny tłumacz uruchamia lokalny silnik llama.cpp bez serwera. LM Studio pozostaje drugą opcją. Jawne skrypty pobrania są oddzielne od GUI; sama aplikacja nie pobiera modeli.

Instalacja na nowo: **Instaluj.bat** (Python 3.12 x64 albo runtime dostarczony z Codex). Instalowane są wyłącznie biblioteki aplikacji; nie modele AI. Instalator używa `--no-cache-dir`, aby nie zostawiać drugiej kopii paczek pip.

## Modele i miejsce

- Modele są odczytywane bezpośrednio z istniejących folderów Subtitle Edit i LM Studio. Aplikacja nie kopiuje, nie przenosi, nie usuwa i nie pobiera modeli.
- Domyślnie wykrywane są popularne lokalizacje Subtitle Edit, w tym `Desktop/SubtitleEdit-Windows-x64`, oraz `.lmstudio/models`.
- W **Modele i dysk → Ustawienia folderów** wskaż cache na wybranym dysku, np. `D:\AI-Subtitle-Cache`. Zmiana dotyczy nowych zadań i nie przenosi wcześniejszych plików. Folder powstaje przy użyciu.
- Przed ASR sprawdzany jest szacowany rozmiar audio PCM16 mono 16 kHz (~110 MiB/godz.) i zapas 2 GiB, osobno na dysku cache oraz wyników projektu.
- Audio jest tworzone dopiero przy ASR. Film pozostaje w oryginalnym miejscu. Identyczne wejście, ścieżka audio i fragment używają istniejącego cache.
- Foldery tymczasowe uruchamianych silników również trafiają do wybranego cache (`runtime-temp`), zamiast niejawnie zajmować systemowy TEMP na C:. Zapisy postępu tłumaczenia aktualizują bieżący stan bez tworzenia pełnej kopii projektu dla każdego napisu.
- Pliki `.partial.wav` po anulowaniu ekstrakcji są usuwane; ukończony cache pozostaje do ponownego użycia. Rozmiar cache nie ma jeszcze automatycznego limitu. Nie kasuj go podczas pracy. Przycisk **Otwórz cache** pozwala przejrzeć pliki ręcznie.
- Zmienna offline Hugging Face blokuje pobieranie przez Whisper. Adapter XXL wymaga kompletnego istniejącego modelu i przekazuje nazwę oraz jego rzeczywisty folder nadrzędny. CrispASR otrzymuje lokalne ścieżki modeli, własny folder cache i nie dostaje `--auto-download` ani `-m auto`.
- Lista pokazuje również modele GGUF, które nie są ASR. Plik GGUF nie zastępuje modelu CTranslate2. Aplikacja filtruje wybór silnika.

## Co działa

1. Import MP4/MKV/AVI/MOV/WEBM i audio, wybór ścieżki dźwiękowej, odtwarzanie oraz odsłuch pojedynczego napisu.
2. Import UTF-8 SRT/ASS/SSA, opcjonalne CP932 po błędzie kodowania; osobne ścieżki dla kolejnych wyników. ASS/SSA: tekst i czasy, bez zachowania stylów.
3. Edycja JP i EN, czasów, dodawanie, usuwanie, scalanie i podział z podglądem. Pola zapisują się przy zmianie napisu, przed zadaniem lub przez **Zastosuj / Ctrl+Enter**. Nieprawidłowy czas blokuje przejście zamiast kasować edycję; **Narzędzia → Odrzuć edycję pól** przywraca poprzednie wartości.
4. Cofanie/ponawianie zmian w bieżącej sesji, automatyczny zapis, ponowne otwarcie projektu, eksport JP/EN SRT. Niepełny EN oraz nieprawidłowe czasy blokują eksport.
5. Porównanie dwóch transkrypcji według czasu, grupy 1:N/N:1, podobieństwo treści, odsłuch, ręczny wybór i utworzenie nowej ścieżki. Tolerancja nie jest pełnym algorytmem synchronizacji; duże przesunięcia mogą dawać brak dopasowania.
6. Whisper GGML przez backend whisper.cpp w CrispASR, Qwen3-ASR przez CrispASR oraz opcjonalny Faster Whisper XXL z modelami CTranslate2. Parametry są sprawdzane przez `--help` konkretnego wydania. Wynik SRT i surowy JSON pozostają w folderze przebiegu.

Backendy GPU są wykrywane z `--version` konkretnego CrispASR. Wydanie Vulkan udostępnia CPU/Vulkan, a osobne wydanie CUDA — CPU/CUDA; niedostępne backendy są zablokowane na liście Qwen / whisper.cpp. Przed ASR zgodność jest sprawdzana ponownie. Wbudowany tłumacz ma jawny wybór CUDA, Vulkan lub CPU i wymaga zgodnego runtime llama.cpp. Błąd wybranego GPU przerywa zadanie. Pola urządzenia i precyzji Faster Whisper XXL są nieaktywne dla pozostałych silników. Pomocniczy VAD może działać na CPU; backend głównego modelu sprawdzaj we wpisach CUDA0/Vulkan0 w logu.

7. Tłumaczenie aktywnej ścieżki lokalnym GGUF Qwen3 Instruct: automatyczne uruchamianie silnika, partie domyślnie po 6 napisów, kontekst, walidacja JSON/ID, ponowienie błędnej partii pojedynczo i zapis wyników. Drugą opcją jest lokalne LM Studio, po jednym napisie. Ponowne uruchomienie pomija zakończone tłumaczenia o tej samej konfiguracji. Ręczne EN pozostają zachowane, dopóki zmiana JP nie oznaczy ich jako nieaktualne.
8. Statyczna kontrola czasów, nakładania, powtórzeń, potencjalnych odmów, japońskiego tekstu w EN i podejrzanej długości. To wskazówki do sprawdzenia, nie ocena zgodności z nagraniem.
9. Oddzielne procesy, logi, anulowanie drzewa procesów zadania i odzyskanie stanu po przerwaniu.

## Edytor, waveform i skróty

Waveform wybranej ścieżki audio powstaje w osobnym procesie FFmpeg. Klik przewija, kółko zmienia zoom, prawy klik pokazuje cały film. Przeciągnięcie ustawia zakres testu w ASR i pipeline. Fioletowe paski pokazują przedziały napisów, złote zakładki. Audio jest strumieniowane do szczytów 50 Hz, bez zapisywania kolejnego WAV; cache waveformu to około 0,25 MB/godz. Cache i pliki robocze pozostają na D: przy obecnej konfiguracji.

Wyszukiwanie obejmuje JP, EN, czasy i notatki. Filtry pokazują ostrzeżenia, nieprzejrzane, zakładki lub brakujące EN. Oznaczenie **Sprawdzony** nie usuwa technicznych ostrzeżeń. Notatki i zakładki są zapisane w SQLite i nie blokują wznowienia pipeline. Zmiany treści/czasów nadal są chronione przed nadpisaniem.

| Skrót | Działanie |
|---|---|
| Ctrl+F / F3 / Shift+F3 | Szukaj / następny / poprzedni wynik |
| F8 / Shift+F8 | Następny / poprzedni problem |
| Ctrl+Enter | Zastosuj edycję pól |
| Ctrl+Shift+Enter | Oznacz zaznaczone jako sprawdzone |
| Ctrl+M / Ctrl+Shift+M | Zakładka / notatka |
| Ctrl+L | Odsłuch bieżącego napisu |
| Ctrl+Shift+T | Przesuń czasy z podglądem |
| Ctrl+Shift+F | Typowe poprawki z podglądem |
| Ctrl+O / Ctrl+I / Ctrl+Shift+S | Projekt / film / Zapisz jako |
| F1 | Pomoc do skrótów i waveformu |

**Narzędzia → Typowe poprawki** pozwala uporządkować końce linii, zaproponować scalenie mikronapisów i niewielkie korekty czasu. Każda opcja ma podgląd, a całość można cofnąć. Niepewne czasy nie są naprawiane na siłę; techniczna korekta jest oznaczona do odsłuchu. Scalenie z częściowym EN jest blokowane, aby nie zgubić tłumaczeń. Wykryte markery mówców wykluczają automatyczną propozycję scalenia; nie jest to diarizacja.

Pliki można przeciągać do okna: jeden film wraz z napisami albo osobny projekt SQLite. Menu **Projekt → Ostatnie projekty** ułatwia powrót do pracy. Kolejny film po materiale z napisami otrzymuje osobny projekt. Mniejsze okna mają przewijanie zamiast uciętych elementów.

## Propozycje AI poza pipeline

W **Propozycje AI** wybierz lokalny model i tryb Fast / Full / Refusal Repair / Hallucination Review. Ocena zawiera JP, obecne EN, typ problemu, krótkie uzasadnienie, propozycję i informację o odsłuchu. Kontekst zawiera japońskie sąsiednie kwestie, a napis docelowy jest wskazany osobno.

Domyślny przycisk **Sprawdź i popraw** automatycznie stosuje zmienione propozycje potwierdzone osobną kontrolą JP→EN. Ręczne EN, niepewne propozycje i wyniki wymagające odsłuchu pozostają do decyzji. Licznik pokazuje faktyczne zmiany, a widok „Zaakceptowane” pokazuje EN przed i po. Automatyczna poprawka nie oznacza ręcznego sprawdzenia. **Cofnij/Ponów** działa także dla całego zestawu zmian. Po wyłączeniu automatycznego stosowania przycisk **Zbierz propozycje AI** zachowuje tryb ręcznej akceptacji.

Opcja **Uwzględnij cały film** buduje opis tematu i powracających terminów ze wszystkich dostępnych napisów JP, a następnie sprawdza spójność JP/EN pomiędzy fragmentami. Opis i otwarte pytania są widoczne nad tabelą. Dłuższy materiał jest dzielony według budżetu kontekstu; osobne opisy części są łączone zamiast wielokrotnego nadpisywania jednej pamięci. Streszczenie jest hipotezą z tekstu ASR, nie analizą obrazu lub odsłuchem. Nie uprawnia do dopisywania dialogu. Zmiana odległego fragmentu unieważnia oparte na nim propozycje. Szczegóły i testy: [REVIEW_CONTEXT.md](REVIEW_CONTEXT.md).

Wyniki są zapisywane po każdym napisie. Ponowne uruchomienie pomija niezmienione oceny; **Oceń ponownie zapisane** wymusza nowy przebieg. Cache i logi są w `D:\models\.cache\ai-review`. Doświadczenie z testu: model poprawnie zaproponował „No.” dla błędnego „House.”, ale inna propozycja została wstrzymana jako niepewna.

## Zrób wszystko — automatyczny pipeline

1. Zaimportuj film / audio w edytorze i wybierz ścieżkę dźwiękową.
2. Otwórz **Zrób wszystko**. Domyślnie: Whisper + Qwen-ASR, dwa warianty EN, kontekst całego dostępnego JP oraz review **Sprawdź i popraw**. Także tryb AI dla podejrzanych miejsc wykonuje teraz poprawki i ponowną ocenę. **Tylko sprawdź** wyłącza poprawki AI; szybkie reguły są jawnie oznaczone jako tryb bez poprawek AI. Możesz wybrać od 1 do 4 transkrypcji i od 1 do 4 tłumaczeń, ich modele/profile oraz model porównujący. Dla kolejnych ASR wybierz różne modele lub VAD; identyczne konfiguracje są odrzucane.
3. Wybierz preset Szybki / Zrównoważony / Dokładny albo własne ustawienia. Zakres domyślnie obejmuje cały pozostały film; na pierwszy test ustaw 20–60 sekund. **Pokaż plan** wyświetla etapy przed startem.
4. Kliknij **Zrób wszystko**. Kolejno powstaną ASR, wybrane JP, warianty EN, wybrane EN, review i wynik końcowy. Aplikacja zachowuje wszystkie warianty jako osobne ścieżki. Uruchamia jeden ciężki proces jednocześnie; własne procesy modeli kończą się przed kolejnym etapem.
5. **Otwórz wyniki** prowadzi do folderu `exports/<id-przebiegu>` obok projektu: JP/EN w wybranym formacie SRT/ASS/SSA/TXT oraz `report.json` i `report.md`. SRT jest domyślny; ASS/SSA mają styl domyślny. Nieprawidłowe czasy lub brak EN blokują odpowiedni eksport; raport nadal wyjaśnia przyczynę. Opcjonalny dźwięk informuje o zakończeniu.

Poziomy review:

| Tryb | Co wykonuje |
|---|---|
| Szybkie | Reguły czasu/wierszy/CPS i formatowanie EN |
| Dokładne | Reguły oraz semantyczne AI dla miejsc z ostrzeżeniami |
| Pełne | AI dla wszystkich napisów, próba poprawy błędów lub zbyt szybkiego EN, porównanie poprawki z poprzednią wersją i ponowna ocena AI |

Warianty EN mogą korzystać z różnych lokalnych GGUF lub tego samego modelu z profilami Naturalny / Wierny / Zwięzły / Kontekstowy. Dwa profile jednego modelu nie są dwiema niezależnymi opiniami modeli. LM Studio pozostaje drugim backendem; odczytaj jego modele w zakładce tłumaczenia. Uruchomione tam modele trzeba zwalniać w zewnętrznym serwerze.

Wybór JP porównuje grupy nakładających się czasowo napisów, uwzględniając różną segmentację. AI wybiera istniejącą hipotezę; nie tworzy nowej japońskiej wypowiedzi. Wybór EN porównuje warianty względem JP, z kontekstem. Ani zgodność modeli, ani wybór AI nie potwierdzają zgodności z audio. Rozbieżne lub niepewne miejsca są oznaczane w napisach i raporcie. Nieprawidłowa odpowiedź JSON / ID nie jest przyjmowana jako decyzja: pozostaje jawnie oznaczony wariant do kontroli.

Formatowanie EN nie zmienia słów. Opcja **Podział zdań • czas szacowany** dodatkowo rozdziela długie napisy zawierające dokładnie dwa zdania w obu językach, jeśli części mają wystarczający czas. Jest domyślnie wyłączona. Zachowuje tekst i pierwotny zakres czasu; każdy szacowany punkt jest oznaczony do odsłuchu. Nie jest to forced alignment. Końce ASR wychodzące do 100 ms poza granicę fragmentu są przycinane i odnotowane; większe błędy zatrzymują przebieg.

Postęp i parametry są w `D:\models\.cache\pipeline/<id>/manifest.json` przy aktualnym ustawieniu cache. Tłumaczenia i decyzje AI mają checkpointy, dzięki czemu **Wznów przerwany przebieg** pomija ukończone etapy i zachowuje częściowy EN. Wznowienie używa zapisanej konfiguracji; zmiana filmu/modelu/silnika lub ręczna edycja ścieżki pipeline wymaga nowego przebiegu. Blokada procesu chroni przed równoczesnym uruchomieniem tego samego przebiegu. Ustawienia panelu są zapisane w projekcie. Nie pobieramy dodatkowych modeli i nie tworzymy kopii wag; cache/logi rosną na wskazanym dysku i są kontrolowane rezerwą miejsca, bez automatycznego limitu całego cache.

Wyjątkiem dla ręcznej edycji jest opcja **Pauza na niepewnych wyborach**: pipeline zatrzymuje się po wyborze JP lub EN, jeżeli wykryto niepewność. Popraw aktywną wskazaną ścieżkę i kliknij **Kontynuuj po kontroli**. Zmieniony checkpoint zostanie przyjęty z zachowaniem kopii poprzedniej wersji; pozostałe ścieżki są nadal chronione. Domyślnie pauza jest wyłączona i niepewności trafiają do końcowego raportu.

**Narzędzia → Zarządzaj cache** pokazuje wyłącznie rozpoznane, odbudowywalne pliki audio i waveformów. Usuwanie wymaga zaznaczenia konkretnych plików. Modele, projekty, logi i checkpointy nie są usuwane. Brakujący cache audio jest odbudowywany przy wznowieniu pipeline bez ponownego uruchamiania ukończonych modeli.

## Review czytelności i podział

W zakładce **Review napisów** wybierz aktywną ścieżkę. Lista aktualizuje się po edycji, ASR i tłumaczeniu. Filtr **Tylko ostrzeżenia** pokazuje napisy wymagające kontroli; dwuklik otwiera wybrany napis w edytorze.

- Widać czas trwania, JP/EN w znakach na sekundę (CPS), liczbę wierszy i najdłuższy wiersz. Kontrola obejmuje za krótki/długi czas, nakładanie (także zagnieżdżone i nieposortowane napisy), krótkie przerwy oraz koniec poza długością filmu.
- **Limity review…** zapisuje własne progi w projekcie. Domyślne EN: 20 znaków/s, 42 znaki/wiersz; maksimum 2 wiersze i czas 0,834–7 s. Te wartości są punktem wyjścia z [wytycznych EN Netflix](https://partnerhelp.netflixstudios.com/hc/en-us/articles/30806198616339-English-UK-Timed-Text-Style-Guide) i [wymagań ogólnych](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617-Timed-Text-Style-Guide-General-Requirements), bez deklaracji pełnej zgodności z profilem dostawcy.
- JP ma własne robocze progi 8 znaków/s i 20 znaków/wiersz; liczymy znaki Unicode po normalizacji NFC, ze spacjami, bez nowych wierszy i znaczników formatowania. Nie jest to przeliczenie pełnej/połówkowej szerokości stosowane w [specyfikacji japońskiej Netflix](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215767517-Japanese-Timed-Text-Style-Guide). Przerwa 80 ms jest roboczym progiem aplikacji, nie regułą klatkową; styk 0 ms jest dozwolony dla ciągłego dialogu.
- **Podgląd wierszy EN…** proponuje zmiany białych znaków bez zmiany słów i czasu. Zachowuje istniejące podziały wypowiedzi. Nie rozcina długiego wyrazu; przekroczenie limitów po zawinięciu nadal jest sygnalizowane.
- **Podgląd podziału…** proponuje dwa napisy, pokazuje osobne punkty JP/EN, edytowalny czas i metryki obu części. Można odsłuchać całość i każdą część. Po zatwierdzeniu EN pozostaje zachowane z oznaczeniem do kontroli; podział ma własne ID i pochodzenie. **Cofnij** przywraca poprzedni stan. Z edytora można otworzyć ten sam podgląd, opcjonalnie z punktu kursora i odtwarzacza.

Proponowany czas jest proporcją obciążenia tekstem, nie wyrównaniem do audio. Sam podział nie obniża tempa czytania. Jeśli tekst jest za szybki, review podaje przybliżony potrzebny czas; skrócenie treści lub zmianę czasów trzeba ocenić po odsłuchu. Ręczna zakładka review nie zmienia napisów bez zatwierdzenia podglądu. Automatyczny pipeline wykonuje operacje wybrane w jego ustawieniach i zapisuje osobny wynik.

## Pierwszy test

1. **Przykład** otwiera dwa małe syntetyczne SRT bez modeli. Sprawdź edycję i zakładkę porównania.
2. **Nowy projekt → Importuj film / audio**, wybierz właściwą ścieżkę audio.
3. Cache jest ustawiony na `D:\models\.cache`. W **Transkrypcja** wybierz **Whisper • whisper.cpp / GPU**, model `ggml-large-v3.bin` i backend **cuda** przy aktualnym runtime. Pozostaw test 60 s. Długość 0 oznacza przetwarzanie do końca.
4. Po wyniku obejrzyj napisy. Możesz wykonać drugi przebieg innym modelem i porównać ścieżki.
5. W **Tłumaczenie i kontrola** pozostaw **Wbudowany • lokalny GGUF** i wybrany **Qwen3-4B-Instruct-2507**. Kliknij **Tłumacz / wznów aktywną ścieżkę**. Model zostanie załadowany automatycznie.
6. Sprawdź EN w edytorze i wyeksportuj SRT.

Opcjonalnie wybierz **LM Studio • opcjonalny serwer**, uruchom serwer w LM Studio i kliknij **Sprawdź serwer / modele**. Dla Qwen3.5 wyłącz thinking w LM Studio. Wbudowany profil obsługuje obecnie Qwen3 Instruct; inne rodziny wymagają dedykowanego profilu.

Wbudowany tłumacz zwalnia model po każdej partii, również po anulowaniu lub awarii procesu roboczego. Ponowne ładowanie w kolejnych partiach ma koszt czasowy. Aplikacja wykonuje jedno zadanie jednocześnie i nie przełącza sama na CPU. Modele załadowane ręcznie w zewnętrznym LM Studio trzeba zwolnić tam przed ASR.

## Zapis danych

`data/settings.json` zawiera ścieżki narzędzi i cache. Nowe projekty powstają w `data/projects/<id>/project.sqlite`; **Zapisz jako** pozwala wybrać inne miejsce. SQLite przechowuje aktywny stan, historię zapisów, stabilne ID, oryginalne importy, pochodzenie segmentów i zadania. Historia w bazie jest zachowana także po zamknięciu, ale przyciski Cofnij/Ponów obsługują bieżącą sesję.

W `runs/<id>/` obok projektu znajdują się parametry, pomoc CLI, log i surowe wyniki silnika. Ukończone tłumaczenia pozostają w projekcie po anulowaniu; ASR jest importowany dopiero po zakończeniu i weryfikacji pliku wynikowego. Wznowienie ASR używa cache audio, ale ponownie wykonuje rozpoznawanie wybranego fragmentu.

Pliki zadań tłumacza są w `D:\models\.cache\worker`, a prompty, schematy, wyjścia i logi silnika w `embedded-translation` wewnątrz tego samego cache. Wybranie GGUF nie tworzy kopii modelu.

## Ograniczenia pierwszej wersji

Brak separacji głosu, automatycznej naprawy synchronizacji względem audio, dedykowanego TranslateGemma, pełnych zaawansowanych presetów ASR, kolejki wielu filmów, telemetrii GPU/RAM i instalatora EXE. Review AI ocenia tekst i przekład, nie słyszy nagrania. Napisy są pokazywane pod obrazem. ASS/SSA nie zachowują stylów wejściowych. Jakość wymaga kontroli na docelowym materiale. Pipeline i ręczny ASR mają timeouty; nie są to detektory rzeczywistego postępu modelu.

## Testy

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Potrzebny pakiet `pytest` z `requirements-dev.txt`. Testy używają małych syntetycznych napisów i lokalnego serwera HTTP. Sprawdzają m.in. zapis/ponowne otwarcie, pochodzenie po scaleniu/podziale, porównanie różnej segmentacji, brak łańcuchowego dopasowania sąsiednich napisów, ochronę przed nieprawidłowym eksportem, dysk, lokalizacje modeli, walidację błędnych odpowiedzi, wznawianie oraz edycję i anulowanie w Qt. W sandboxie połączenia loopback mogą wymagać wykonania poza ograniczeniem sieci.

Zaliczone: **156 testów automatycznych**. Obejmują także propozycje i decyzje AI, ochronę przed nieaktualną poprawką, nawigację, waveform, techniczne poprawki, formaty, pauzę po niepewnych wyborach, timeouty i bezpieczne czyszczenie/odbudowę cache. Odczyt checkpointów ponawia krótkie blokady Windows; testy pilnują też limitu prób i jawnego błędu uszkodzonego JSON. Dodano sprawdzenie jawnego wyboru CUDA/Vulkan/CPU, licznika błędów znakowych CER i przygotowania zewnętrznej referencji bez zmiany jej tekstu. `tools.verify_qol` sprawdził rzeczywisty waveform FFmpeg, trzy strukturalne oceny lokalnego modelu bez nadpisania EN oraz ASS/TXT. `tools.preview_qol` renderuje nowe widoki i sprawdza okno 960×700.

`tools.verify_pipeline` wcześniej sprawdził rzeczywisty pełny przebieg Qt na 20 sekundach japońskiego audio: dwa ASR GPU, dwa warianty EN, wybór JP/EN, pełne review z poprawkami i oba SRT. Zachowano 10 ścieżek, końcowy wynik miał 5 napisów i 4 ostrzeżenia do kontroli. To test działania, nie ocena jakości. Sprawdzono również wznowienie rzeczywistego przebiegu bez powtarzania ukończonej inferencji.

`python -m tools.verify_pipeline --audit ŚCIEŻKA_DO_MANIFESTU` ponownie sprawdza zapisane wyniki bez uruchamiania modeli: sumy kontrolne checkpointów, zgodność tekstu/czasów obu SRT z końcową ścieżką i spójność ostrzeżeń raportu.

`tools.preview_review` renderuje zakładkę review, edytor i podgląd podziału na osobnym projekcie kontrolnym w `data/review-preview`; `tools.preview_pipeline` odświeża podgląd ukończonego projektu sprzętowego.

Dodatkowo sprawdzono rzeczywistą inferencję GPU: `tools.verify_whisper_cpp`, `tools.verify_embedded_translation`, `tools.verify_gui_embedded` (GUI → model → SQLite i anulowanie) oraz `tools.verify_gui_asr_backend` (wykrycie backendów → 60 sekund Whispera na Vulkan → zapis 16 napisów). Skrypty wymagają przygotowanych plików na D:; nie pobierają modeli. `tools.smoke_asr` pozostaje starszym testem opcjonalnego Faster Whisper XXL.


## Kotoba i poprawki po pełnym teście

Dodano preset 3 ASR (Large V3, Qwen, Kotoba), odrzucanie wadliwego wyrównania z kontynuacją na poprawnych źródłach, weryfikację poprawek EN względem samego JP, ochronę jawnych pytań oraz poprawki czytelności JP/EN. Wbudowany LLM pozostaje w pamięci między etapami i jest zamykany przez aplikację; LM Studio nadal jest opcjonalne.

Pełny test CUDA na filmie 4:43: **8 min 19 s** zamiast wcześniejszych 25 min 22 s. Kotoba z alignerem była średnio **2,42× szybsza** od Large V3, ale na osobnej próbce z SRT miała wyższy CER, dlatego pozostaje dodatkową opcją. Wynik nadal wymaga review. Konfiguracje i porównanie jakości: [KOTOBA_AND_FIXES.md](KOTOBA_AND_FIXES.md).


## Samo JP i wycinki referencyjne

Nowy preset „Transkrypcja JP • Large V3 + wycinki” pomija tłumaczenie i LLM. Large V3 + VAD pozostaje bazą; modele pomocnicze pracują tylko na podejrzanych zakresach audio. Review JP porównuje frazy przed tłumaczeniem i składa zgodne fragmenty ponowień. Wyniki oraz odsłuch są w przycisku „Review JP • porównaj frazy ASR”. Szczegóły i rzeczywisty przykład poprawki: [JP_SOURCE_REVIEW.md](JP_SOURCE_REVIEW.md). Referencje obejmują 30 wycinków oraz osobne wejścia/etykiety do review; nie wykonano fine-tuningu. Szczegóły testów CUDA, ograniczeń i nowych modeli: [JP_TRANSCRIPTION_AND_REFERENCES.md](JP_TRANSCRIPTION_AND_REFERENCES.md).

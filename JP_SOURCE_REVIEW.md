# Review transkrypcji oryginału — 28.10.2026

Nowe przebiegi mają etap **review JP przed tłumaczeniem**. W domyślnym trybie JP: Large V3 + VAD → ponowienia podejrzanych wycinków → porównanie i składanie fraz JP → układ → SRT. Bez tłumacza i bez LLM.

Dotychczas wymagano zgodności całego okna audio. Zgodna poprawka jednej frazy przepadała przez rozbieżność kilkanaście znaków dalej. Nowe review wyrównuje teksty lokalnie, porównuje fragmenty w kontekście i sprawdza, czy źródłowe napisy dotyczą tego samego czasu. Zmienia tylko tekst, zachowując czasy i segmentację bazy.

## Warunki automatycznej poprawki

- Ta sama fraza musi wystąpić w ponowieniu modelu bazowego oraz innym modelu. Każda dostępna poprawna hipoteza musi ją potwierdzić; trzecia rozbieżna blokuje zamianę. Dwa przebiegi tego samego pliku modelu nie wystarczają.
- Bazowy napis musi mieć sygnał niskiej pewności. Pewność napisu z ponowienia bazy musi wynosić co najmniej 0,8. To średnia prawdopodobieństw tokenów napisu, **nie skalibrowane prawdopodobieństwo poprawności frazy**.
- Potrzebne są dopasowania kontekstu po obu stronach i zgodność czasowa. Poprawka musi być dosłownym, ciągłym fragmentem jednego napisu ASR.
- Dodawanie tekstu, usuwanie całych wypowiedzi, zmiany przez granice napisów, nazwy/liczby łacińskie i duże różnice pozostają do odsłuchu. Ręczne i oznaczone jako sprawdzone napisy są chronione.
- Jednostki porównania rozszerzają się na ciągi hiragany, katakany lub kanji. To heurystyka, nie analizator morfologiczny. Zapobiega np. wybieraniu wspólnych znaków `配列` ze spornych słów `配列道` i `配列堂`.

Poprawka nadal ma status niesprawdzonej. Raport zachowuje tekst przed i po, zakres znaków, identyfikatory napisów źródłowych, modele, pewność i katalogi surowych wyników. Zgodne błędy modeli nadal mogą przejść te warunki.

Pełny tryb z tłumaczeniem również wykonuje etap JP po scaleniu i przed kontekstem/EN. Porównuje wybrany JP z surowymi ścieżkami i oznacza rozbieżności. Bez ponowienia modelu bazowego i jego pewności nie wykonuje automatycznych zamian fraz. Dotychczasowe wybieranie całych napisów w `merge-*` jest osobnym krokiem.

## Sprawdzenie na prawdziwym filmie

Ponownie oceniono zapisane wyniki CUDA z całego Easy Japanese 1 (282,73 s): 98 napisów, 9 okien audio, po dwa ponowienia Large V3/Kotoba. Nie uruchamiano ASR i nie pobierano modeli. Oryginalny przebieg pozostał bez zmian.

| Wynik | Wartość |
|---|---:|
| Rozbieżne jednostki do porównania | 28 |
| Zastosowane zmiany fraz | 2 |
| Zmienione napisy | 1 |
| Nierozstrzygnięte jednostki | 26 |
| Czas etapu review | 0,01 s |
| Review, układ, eksport i obsługa cache | 0,1161 s |
| Zmienione czasy napisów | 0 |

W napisie 44,12–47,51 s:

- `を得ても` → `いつでも`: oba ponowienia zgadzają się; `いつでも` widać w oryginalnym napisie filmu przy 44 s.
- `一番良` → `一番い`: z zachowaną końcówką powstaje `一番いいところですね`. To głównie zgodność zapisu z podpisem filmu, nie osobna naprawa znaczenia.
- `の開発度` pozostaje: propozycje `配列道` i `配列堂` są różne i nadal błędne. Oryginał mówi `手に入るっつうとこは…`. Review **nie naprawiło całego zdania**.

To celowany przykład poprawy, nie wynik na niezależnym zbiorze kontrolnym. Nie mamy pełnego niezależnego SRT do filmu, więc nie podajemy CER całego nagrania. Ostrzeżenia wzrosły z 35 do 47 napisów, bo nowe review ujawnia więcej różnic i zapisuje notatki; to nie jest liczba błędów rozpoznawania.

## Wyniki i weryfikacja

**156 testów poprawnych**: lokalne składanie mimo różnic poza frazą, blokowanie spornych kanji, trzeciej odmiennej hipotezy, zmian ręcznych i wadliwych czasów, brak LLM w trybie JP, kolejność przed EN, wznowienie i wykrywanie zmienionego artefaktu, porównanie/odsłuch w Qt. Audyt potwierdził sumy kontrolne, zgodność JP SRT z końcową ścieżką i raportem. Obejrzano wyrenderowany widok Qt.

- [Porównanie i czasy](D:/models/.cache/benchmark-jp-source-review/comparison.json)
- [Projekt](D:/models/.cache/benchmark-jp-source-review/projects/33acb427b2be416a9b1e570a97ba829a/project.sqlite)
- [Nowe SRT](D:/models/.cache/benchmark-jp-source-review/exports/54383235f39a4ac4a5933e58f77660da/Japanese.srt)
- [Raport z pochodzeniem fraz](D:/models/.cache/benchmark-jp-source-review/exports/54383235f39a4ac4a5933e58f77660da/report.json)

Przycisk **„Review JP • porównaj frazy ASR”** pokazuje źródło, wynik, alternatywy i decyzję. Dymek zawiera kontekst i katalogi prób; dwuklik odtwarza zakres. Starsze manifesty zachowują pierwotny plan. `tools.review_cached_asr` tworzy nowy przebieg ze zweryfikowanych wyników bez inferencji.

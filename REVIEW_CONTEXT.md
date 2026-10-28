# Review, poprawki i kontekst całości — 28.10.2026

## Zmiana zachowania

Domyślny tryb pipeline wcześniej oceniał podejrzane napisy bez uruchamiania etapu poprawek. Dopiero tryb pełny zmieniał EN. Osobny panel propozycji wymagał ręcznej akceptacji. Rozdzielono teraz dwie decyzje: zakres kontroli i to, czy stosować poprawki.

- **Zrób wszystko → Sprawdź i popraw**: domyślnie włączone dla nowych przebiegów AI. Po ocenie następuje próba poprawy EN, porównanie z poprzednią wersją i ponowna ocena. Działa również w trybie zrównoważonym. **Tylko sprawdź** pozostawia ocenę bez przepisywania EN. Szybkie reguły są jawnie opisane jako tryb bez poprawek AI.
- **Propozycje AI → Sprawdź i popraw**: po zebraniu ocen automatycznie stosuje propozycje potwierdzone kontrolą zgodności JP→EN, bez wymogu odsłuchu. Ręczne EN są chronione. Wyłączenie automatycznego stosowania przywraca zbieranie propozycji do ręcznej decyzji.
- **Review napisów → Sprawdź i popraw EN przez AI** uruchamia pełną ocenę i poprawki w panelu AI.
- W panelu są licznik faktycznych zmian i widok EN przed/po. Automatyczne zmiany można cofnąć/ponowić; nie oznaczają ręcznej kontroli. Pipeline zapisuje listę zmian `before`/`after` w raporcie i checkpointach oraz liczbę `review_changed_cues`.
- Starsze manifesty zachowują swój poprzedni plan przy wznowieniu. Nowe opcje dotyczą nowych przebiegów.

## Kontrola całych napisów

Opcjonalna analiza jest domyślnie włączona w trybach AI. Korzysta z wszystkich dostępnych napisów JP; jeśli rozpoznano tylko fragment filmu, opis dotyczy tego fragmentu.

1. Model przygotowuje opis tematu, najważniejszych informacji/wydarzeń, osób/ról i powracających terminów. Materiał mieszczący się w kontekście jest podawany razem, bez zbędnych ID każdego zdania. Dłuższy tekst dzielony jest według budżetu; opisy części są przechowywane i łączone hierarchicznie.
2. Przy tłumaczeniu w pipeline opis służy jako wskazówka kontekstowa, przekazywana jako dane. Nie jest instrukcją nadpisującą JP. Zmiana opisu unieważnia powiązany cache tłumaczenia.
3. Kontrola spójności przechodzi chronologicznie przez JP/EN, zachowując notatki o nazwach, terminach i otwartych pytaniach między częściami. Szuka zmian znaczenia, niespójnych nazw, ról, zaimków, chronologii i dialogów niepasujących do kontekstu.
4. Wyniki trafiają do zwykłego review i etapu poprawek. Opis oraz pytania o spójność są widoczne w aplikacji i zapisane w wynikach.

W osobnym panelu propozycje zależne od kontekstu całości są unieważniane również po zmianie odległego napisu. Walidacja wielu propozycji odbywa się przed zastosowaniem pierwszej zmiany.

To analiza tekstu ASR. Nie obejmuje oglądania obrazu, identyfikacji osób z głosu ani potwierdzenia mowy w audio. Opis może być błędny i nie uprawnia do dopisywania dialogu. Niepewne oceny pozostają oznaczone; nie stosuje się ich automatycznie w panelu propozycji. W pipeline kandydat poprawki musi wygrać porównanie z poprzednim EN; końcowe review może nadal zgłosić problem. Jeden mały model nie zapewnia niezależnej gwarancji jakości.

## Rzeczywiste sprawdzenie na CUDA

- **Kontrolowane błędy EN, pełna ścieżka GUI → model → zapis:** model zmienił `My name is Suzuki.` na `My name is Tanaka.` oraz `Today is Friday.` na `Today is Monday.`, zgodnie z JP. Ręczny EN pozostał niezmieniony. Sprawdzono SQLite oraz Cofnij/Ponów. Pierwszy pomiar: około 31 s. Wyniki: `D:\models\.cache\verification-review-changes\automatic-result.json`.
- **Pipeline z kontekstem i poprawkami w trybie zrównoważonym:** rzeczywiste 20 s japońskiego audio, oba ASR CUDA, dwa EN, opis kontekstu, spójność całości, review, poprawki, ponowna ocena i eksport. 5 końcowych napisów, 4 faktycznie zmienione EN, 4 napisy nadal z ostrzeżeniami. Około 138 s. Manifest: `D:\models\.cache\pipeline\59dd586797564b9fb3cd5f87d4f34392\manifest.json`. Ten pomiar był przed zmianą algorytmu streszczania długiej całości; nowy algorytm osobno sprawdzono na pełnych 55 napisach.
- **Całość Job Interview:** przeanalizowano wszystkie 55 napisów z poprzedniego pełnego przebiegu, bez ponownego ASR/tłumaczenia. Pierwsza próba aktualizowania jednego streszczenia gubiła wcześniejsze fakty; tę metodę zastąpiono osobnymi opisami części i ich łączeniem. W poprawionym przebiegu cały JP zmieścił się w jednym kompaktowym wejściu. Model rozpoznał poradnik o rozmowie kwalifikacyjnej, przygotowaniu, badaniu firmy, typowych pytaniach i sposobie wypowiadania się. Kontrola JP/EN przebiegła przez 10 partii; 33 napisy otrzymały uwagi lub niepewną ocenę. To wskazania modelu, nie 33 potwierdzone błędy. Opis i kontrola zajęły około 54 s. Wyniki: `D:\models\.cache\verification-review-changes\whole-result.json`.
- **107 testów automatycznych zaliczonych:** m.in. rzeczywiste stosowanie poprawek, ochrona ręcznego EN, brak fałszywego oznaczenia ręcznej kontroli, cofanie, odległy kontekst, zachowanie faktów z wszystkich części, wznowienie, raport przed/po i zgodność starszych planów.

Weryfikacja:

```powershell
.\.venv\Scripts\python.exe -m tools.verify_review_changes --whole
.\.venv\Scripts\python.exe -m tools.verify_pipeline --balanced --cuda --data-dir D:\models\.cache\verification-context-review
.\.venv\Scripts\python.exe -m pytest -q
```

Wyniki jakościowe poprzedniego pełnego pipeline i nadal istniejący problem nakładania czasów po mieszaniu ASR opisano w [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md). Nie naprawiano tego problemu przez dopasowywanie tekstu do streszczenia.

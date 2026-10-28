# Materiał do rzeczywistego testu japońskiego ASR

**Job Interview** — Simpleshow Japan, 20 kwietnia 2017.

- Źródło: https://commons.wikimedia.org/wiki/File:Job_Interview.webm
- Oryginał: https://upload.wikimedia.org/wikipedia/commons/e/ec/Job_Interview.webm
- Licencja: Creative Commons Attribution-ShareAlike 4.0 International, https://creativecommons.org/licenses/by-sa/4.0/
- Autor: Simpleshow Japan, https://commons.wikimedia.org/wiki/User:Simpleshow_Japan
- Materiał: japońska animacja edukacyjna o przygotowaniu do rozmowy kwalifikacyjnej.
- Długość wg źródła: 188,6 s, rozdzielczość 854 × 480, VP8/Opus.
- Plik źródłowy: 16 807 115 bajtów, SHA-1 `628f841a1c2a61bf25948da346981dfc393b3040`.
- Plik lokalny po pobraniu: `samples/media/Job_Interview.webm`.

Oryginalny film jest zachowany bez zmian. Ewentualne audio robocze i maszynowe napisy są osobnymi plikami testowymi. Autor filmu nie jest związany z aplikacją i jej nie rekomenduje.

Pobranie jest osobną, jawną operacją: `python -m tools.fetch_test_media`. Skrypt pobiera wyłącznie ten film, weryfikuje sumę kontrolną, wymaga zapasu miejsca i ogranicza pobieranie do 25 MiB. Nie pobiera modeli.

W aplikacji użyj **Importuj film / audio** i wskaż plik. Pierwszy przebieg: Turbo, początek 0 s, długość 60 s. Sprawdź odsłuchem zgodność tekstu, czasy, brak dopisków podczas ciszy i urwane wypowiedzi na końcu fragmentu. Potem można porównać z Large V3 lub Qwen3-ASR. Ten materiał sprawdza narrację; nie zastępuje testu szybkich rozmów, nakładających się głosów i muzyki w anime.

## Film aktorski i trudniejsze audio

**Sisters of the Gion / 祇園の姉妹 (1936)**, reżyser Kenji Mizoguchi.

- Źródło: https://commons.wikimedia.org/wiki/File:Sisters_of_the_Gion_(1936)_by_Kenji_Mizoguchi.webm
- Wikimedia Commons oznacza film jako domenę publiczną (PD-Japan-film, PD-1996).
- Pobrano jedynie pierwsze 12 MiB udostępnionej wersji 240p; pełny oryginał ~1,62 GB nie został pobrany.
- Zachowano fragment źródłowego filmu **02:00–04:00**. Wideo przekodowano do H.264; bazową ścieżkę audio Opus skopiowano z wersji Wikimedia bez dodatkowego przetwarzania. To nie jest dźwięk pobrany z oryginalnego nośnika filmu, tylko z udostępnionej kopii.
- `media/Sisters_of_Gion_02m00_04m00.mkv` — wariant bazowy, około 1,93 MiB.
- `media/Sisters_of_Gion_02m00_04m00_noisy.mkv` — ten sam fragment, celowo pogorszony: pasmo 250–3400 Hz, wzmocnienie mowy 0,7, dodany szum różowy z ustalonym seedem i kodowanie AAC 64 kb/s; około 1,89 MiB. Nie należy przedstawiać tego pliku jako oryginalnego dźwięku filmu.
- Tymczasowy pobrany fragment został usunięty. Dokładne URL-e i parametry zapisano w `media/gion-source.json`.

Oba klipy trwają około dwóch minut. Do testu porównawczego uruchom ten sam silnik i ustawienia na wersji bazowej oraz `noisy`, z długością ASR 0 (cały klip). Porównaj pominięcia, dopiski i synchronizację. W pierwszej kolejności odsłuchaj obie wersje, aby ocenić faktyczną trudność dialogu; wiek filmu sam w sobie nie określa jakości udostępnionej ścieżki.

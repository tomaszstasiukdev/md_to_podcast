# Podcast Generator — Markdown → MP3

Narzędzie do generowania podcastów audio (MP3) z plików Markdown. Jeden lektor / wykładowca, styl edukacyjny. Pipeline: wczytanie MD → czyszczenie treści → scenariusz mówiony (OpenAI) → TTS (OpenAI) → MP3.

## Wymagania

- Python 3.11+
- [ffmpeg](https://ffmpeg.org/) w PATH (do scalania fragmentów TTS oraz opcji `--merge-all`)
- Konto OpenAI z kluczem API

## Instalacja

1. Sklonuj lub skopiuj projekt, wejdź do katalogu:

   ```bash
   cd md_to_podcast
   ```

2. Utwórz wirtualne środowisko i zainstaluj zależności:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Skopiuj `.env.example` do `.env` i uzupełnij klucz API:

   ```bash
   cp .env.example .env
   # Edytuj .env i ustaw OPENAI_API_KEY=sk-...
   ```

## Konfiguracja (.env)

| Zmienna | Opis | Domyślnie |
|--------|------|-----------|
| `OPENAI_API_KEY` | Klucz API OpenAI | — (wymagany) |
| `INPUT_DIR` | Katalog z plikami `.md` | `md` (względem katalogu projektu) |
| `OUTPUT_DIR` | Katalog wyjściowy | `output` |
| `SCRIPT_MODEL` | Model do scenariusza | `gpt-4o-mini` |
| `TTS_MODEL` | Model TTS | `gpt-4o-mini-tts` |
| `TTS_VOICE` | Głos TTS (np. cedar, marin, onyx) | `cedar` |
| `MAX_SCRIPT_CHARS_PER_CHUNK` | Maks. znaków na fragment TTS | `4000` |
| `SECTIONS_PER_BATCH` | Ile sekcji MD w jednym wywołaniu API (2 = mniejsze partie, lepsze 1:1) | `2` |
| `MIN_SCRIPT_TO_SOURCE_RATIO` | Min. stosunek długości skryptu do źródła (poniżej = rozbudowa; 0.6 ≈ treść prawie 1:1) | `0.6` |
| `CHECK_COMPLETENESS_AFTER_BATCH` | Po każdej partii porównaj ze źródłem i dopisz brakujące (1/0) | `1` |
| `FILL_MISSING_FULL_PASS` | Drugie przejście: porównaj cały draft ze źródłem i dopisz brakujące (1/0) | `1` |
| `LOG_LEVEL` | Poziom logów | `INFO` |

Ścieżki mogą być względne (względem katalogu uruchomienia) lub bezwzględne.

### Generowanie skryptu (kompletność treści)

Skrypt jest generowany **sekcja po sekcji** (według nagłówków `##`): każda partia trafia do API z instrukcją **zachowania treści prawie 1:1** – usuwać tylko URL-e, odnośniki do grafik i składnię markdown; nie streszczać ani nie redukować szczegółów. **Po każdej partii** wykonywane jest porównanie ze źródłem: LLM sprawdza, czy w fragmencie scenariusza brakuje ważnej treści; jeśli tak – dopisuje brakujący tekst pod ten fragment (w tym samym stylu). Po złożeniu **całego** scenariusza (draft) uruchamiane jest **drugie przejście (Draft + uzupełnienie)**: jedno wywołanie API porównuje cały draft z całym źródłem i zwraca brakujące fragmenty do dopisania przed zakończeniem; te fragmenty są dopisywane do pliku. Sekcje drugorzędne (fabuła, zadanie, linki) są łączone w krótką wzmiankę. Na końcu, jeśli stosunek długości skryptu do źródła spadnie poniżej `MIN_SCRIPT_TO_SOURCE_RATIO` (domyślnie 0.6), uruchamiana jest globalna iteracja rozbudowy. Weryfikację po partii wyłącza `CHECK_COMPLETENESS_AFTER_BATCH=0`, drugie przejście – `FILL_MISSING_FULL_PASS=0`.

## Uruchomienie

Z katalogu projektu (`md_to_podcast`):

```bash
python -m podcast_generator.main
```

Albo z dowolnego miejsca, podając ścieżki:

```bash
python -m podcast_generator.main --input-dir /ścieżka/do/md --output-dir /ścieżka/do/output
```

### Przykładowe komendy

- **Wszystko (scenariusze + audio) dla całego folderu `md`:**

  ```bash
  python -m podcast_generator.main --input-dir ../md --output-dir ./output
  ```

- **Tylko scenariusze (bez TTS):**

  ```bash
  python -m podcast_generator.main --skip-audio
  ```

- **Tylko audio (zakładając, że scenariusze już są):**

  ```bash
  python -m podcast_generator.main --skip-script
  ```

- **Scalenie wszystkich wygenerowanych MP3 w jeden plik:**

  ```bash
  python -m podcast_generator.main --merge-all
  ```

  Lub najpierw wygeneruj odcinki, potem tylko scal:

  ```bash
  python -m podcast_generator.main --skip-script --skip-audio --merge-all
  ```
  (wymaga wcześniej wygenerowanych plików w `output/audio/`).

- **Nadpisanie istniejących plików:**

  ```bash
  python -m podcast_generator.main --force
  ```

- **Jeden plik (wzorzec):**

  ```bash
  python -m podcast_generator.main --pattern "s01e01*.md"
  ```

## Struktura wejścia i wyjścia

- **Wejście:** katalog `md/` (lub `INPUT_DIR`) — pliki `.md` (z opcjonalnym frontmatter YAML, obrazkami, linkami, kodem).
- **Wyjście (w `OUTPUT_DIR`):**
  - `scripts/` — scenariusze tekstowe `.txt` (jedna nazwa = slug z nazwy pliku MD).
  - `audio/` — pliki MP3 po jednym na odcinek.
  - `merged/` — opcjonalnie `podcast_all.mp3` po użyciu `--merge-all`.

Nazwy plików wynikowych pochodzą z nazwy pliku Markdown (bez rozszerzenia), np.:

- `s01e01-programowanie-interakcji-z-modelem-jezykowym-1773053098.md`  
  → `s01e01-programowanie-interakcji-z-modelem-jezykowym-1773053098.txt`,  
  → `s01e01-programowanie-interakcji-z-modelem-jezykowym-1773053098.mp3`.

## Pipeline

1. **Wczytanie** — znajdowanie wszystkich `.md` w `INPUT_DIR`, parsowanie frontmatter i body.
2. **Czyszczenie (etap 1)** — usunięcie obrazów, embedów, zbędnych linków, uproszczenie formatowania; bloki kodu → krótkie wzmianki.
3. **Scenariusz (etap 2)** — ekstrakcja sekcji z MD (`##`), generowanie partiami (po `SECTIONS_PER_BATCH` sekcji) z instrukcją „pełna adaptacja, nie streszczenie”; sklejenie fragmentów, intro/outro; walidacja długości i ewentualna rozbudowa.
4. **TTS** — podział długich scenariuszy na chunki, generacja MP3 per chunk, scalenie w jeden plik na odcinek (ffmpeg).
5. **Opcja --merge-all** — scalenie wszystkich `output/audio/*.mp3` w `output/merged/podcast_all.mp3` w kolejności alfabetycznej.

## Troubleshooting

- **Brak OPENAI_API_KEY** — ustaw w `.env` lub zmiennej środowiskowej.
- **ffmpeg not found** — zainstaluj ffmpeg (np. `brew install ffmpeg` na macOS) i upewnij się, że jest w PATH.
- **Błąd długości wejścia / timeout** — zmniejsz `MAX_SCRIPT_CHARS_PER_CHUNK` w `.env` (np. 3000).
- **Polskie znaki** — cały pipeline używa UTF-8 (odczyt/zapis plików, API).
- **Jeden plik się wywala** — pozostałe są dalej przetwarzane; na końcu wyświetlane jest podsumowanie (sukcesy i liczba błędów).
- **Chcesz tylko przetestować bez TTS** — użyj `--skip-audio` i sprawdź pliki w `output/scripts/`.
- **Porównanie ze starą wersją** — przed regeneracją skopiuj obecne skrypty do `output/scripts_previous/`. Po wygenerowaniu nowych uruchom `python compare_scripts.py` (linie i znaki: stare vs nowe).

## Licencja

Kod: MIT (plik [LICENSE](LICENSE)). Użycie API OpenAI podlega [regulaminowi OpenAI](https://openai.com/policies).

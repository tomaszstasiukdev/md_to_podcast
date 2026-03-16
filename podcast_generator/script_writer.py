"""
STEP 2: Turn content into a single-speaker podcast script.
Generate section by section with completeness checks and coverage validation.
"""

import logging
import re
from pathlib import Path

from openai import OpenAI

from . import config
from .markdown_loader import MarkdownDocument
from .markdown_cleaner import get_clean_text_for_script, clean_text_fragment
from .section_extractor import (
    extract_sections_from_body,
    Section,
    should_minimize_section,
)
from .utils import retry_with_backoff, count_urls, count_markdown_artifacts

logger = logging.getLogger(__name__)

# --- Prompts (Polish): content near 1:1, only remove links/graphics/syntax ---
SYSTEM_PROMPT_SECTIONS = """Jesteś autorem scenariusza edukacyjnego audio. Twoim jedynym zadaniem jest przekształcenie tekstu w wersję DO MÓWIENIA, zachowując treść prawie 1:1.

Co MUSISZ zachować (bez skracania i bez upraszczania):
- Wszystkie fakty, definicje, rozróżnienia i niuanse techniczne.
- Wszystkie przykłady, listy punktów i koncepcje w pełnym zakresie.
- Kolejność i strukturę myśli. Każdy akapit/idea ze źródła ma mieć odpowiednik w scenariuszu – nie łącz wielu idei w jedno zdanie.

Co USUWASZ lub ZASTĘPUJESZ (tylko to):
- Adresy URL i linki (np. https://...). Możesz zostawić wzmiankę „dokumentacja OpenAI” zamiast linku, ale nie czytaj adresów.
- Odniesienia do grafik (np. „na rysunku widać”, „ilustracja pokazuje”) – pomijasz lub mówisz „w materiałach wideo/graficznych jest to zilustrowane”.
- Składnię markdown: nagłówki ##, **pogrubienia**, [tekst](url), bloki kodu – zamieniasz na zwykły tekst mówiony; kod opisz słowami (co robi), nie czytaj linii kodu.

Forma wyjścia:
- Jeden wykładowca, bez dialogów. Zdania możesz nieco skrócić dla naturalności mówionej, ale NIE wolno redukować ilości informacji.
- Ton: profesjonalny, spokojny. Bez sztucznego nadęcia.
- Zwróć wyłącznie gotowy fragment scenariusza – bez nagłówków sekcji, bez numeracji, bez komentarzy.

Zakaz: streszczania, łączenia kilku akapitów w jeden, pomijania „mniej ważnych” szczegółów, upraszczania wyjaśnień technicznych."""

USER_PROMPT_BATCH_TEMPLATE = """Poniżej są {num_sections} sekcji materiału. Przekształć je w scenariusz do odczytu, zachowując treść prawie 1:1.

Wymagania:
- Długość Twojej odpowiedzi ma być zbliżona do długości materiału (licząc sam tekst merytoryczny). Akapit źródła → co najmniej jeden pełny akapit w scenariuszu. Nie skracaj ani nie kondensuj.
- Zachowaj każdy fakt, każdy przykład, każde rozróżnienie. Jeśli w źródle są trzy punkty – w scenariuszu mają być trzy punkty. Jeśli jest szczegół techniczny – ma zostać.
- Usuń tylko: adresy URL, odnośniki do „grafiki 1”/„rysunku”, surową składnię markdown. Reszta wiedzy bez zmian.
- Zakaz: „w skrócie”, „podsumowując tę część”, łączenie wielu myśli w jedno zdanie, pomijanie „szczegółów”.

---
{batch_text}
---"""

# Batch completeness check: compare source with fragment, append missing
SYSTEM_PROMPT_COMPLETENESS = """Jesteś recenzentem scenariusza edukacyjnego audio. Dostajesz fragment ŹRÓDŁA (materiał) oraz odpowiadający mu fragment SCENARIUSZA (wersja do mówienia).

Twoje zadanie: sprawdź, czy w scenariuszu brakuje ważnej treści ze źródła (fakty, definicje, przykłady, rozróżnienia, punkty list). Jeśli coś istotnego zostało pominięte lub nadmiernie skrócone, napisz TYLKO brakujący fragment scenariusza – w tym samym stylu (jeden wykładowca, polski), gotowy do dopisania pod istniejący fragment. Nie powtarzaj tego, co już jest w scenariuszu.

Jeśli scenariusz obejmuje źródło w pełni (nic ważnego nie brakuje), odpowiedz wyłącznie słowami: NIE_BRAKUJE"""

USER_PROMPT_COMPLETENESS_TEMPLATE = """Źródło (materiał do pokrycia):
---
{source_text}
---

Fragment scenariusza (wersja do mówienia):
---
{script_fragment}
---

Czy w scenariuszu brakuje ważnej treści ze źródła? Jeśli tak – podaj tylko brakujący fragment do dopisania (ten sam styl). Jeśli nie – napisz dokładnie: NIE_BRAKUJE"""

# Secondary sections (story, task, links): one short mention
USER_PROMPT_MINIMIZE_TEMPLATE = """Poniższe sekcje to materiały dodatkowe (fabuła kursu, zadanie, linki). Nie rozwijaj ich w pełnym wykładzie. Napisz jedną krótką wzmiankę na koniec (2–4 zdania), np. że na stronie lekcji są zadania, filmy i linki. Po polsku, jeden wykładowca.

---
{batch_text}
---"""

# Second pass (draft + fill): compare full episode to source, append missing fragments
SYSTEM_PROMPT_FILL_FULL = """Jesteś recenzentem scenariusza edukacyjnego audio. Dostajesz CAŁE ŹRÓDŁO lekcji oraz CAŁY wygenerowany scenariusz (draft).

Twoje zadanie: porównaj oba teksty i ustal, czy w scenariuszu brakuje ważnej treści ze źródła (fakty, definicje, przykłady, rozróżnienia, całe akapity lub sekcje). Szukaj zwłaszcza: pominiętych tematów, nadmiernie skróconych wyjaśnień, brakujących punktów z list, niuansów technicznych.

Jeśli coś istotnego brakuje: wypisz TYLKO te brakujące fragmenty w formie gotowego tekstu do mówienia (jeden wykładowca, polski, ten sam styl co scenariusz). Tekst ma być dopisany PRZED zakończeniem „Dziękuję za wysłuchanie”. Nie powtarzaj treści już obecnej w scenariuszu. Zachowaj kolejność logiczną (odpowiadającą źródłu).

Jeśli scenariusz obejmuje źródło w pełni (nic ważnego nie brakuje), odpowiedz wyłącznie: NIE_BRAKUJE"""

USER_PROMPT_FILL_FULL_TEMPLATE = """Źródło (cały materiał lekcji):
---
{source_text}
---

Scenariusz (draft, cały odcinek):
---
{script_text}
---

Czy w scenariuszu brakuje ważnej treści ze źródła? Jeśli tak – podaj tylko brakujące fragmenty jako gotowy tekst do dopisania (ten sam styl). Jeśli nie – napisz dokładnie: NIE_BRAKUJE"""

# Expand when script is too short
USER_PROMPT_EXPAND = """Scenariusz poniżej jest zbyt krótki – utracono szczegóły i głębokość materiału. Twoim zadaniem jest go ROZBUDOWAĆ do poziomu zbliżonego do źródła.

Wymagania rozbudowy:
- Zachowaj każdą sekcję z listy i dodaj brakujące fakty, przykłady, rozróżnienia oraz niuanse techniczne. Scenariusz ma mieć podobną GŁĘBIĘ jak materiał, nie tylko te same tematy.
- Nie streszczaj – tam gdzie źródło rozwija temat (kilka zdań, lista punktów), scenariusz też ma to rozwijać.
- Jeden wykładowca, naturalna mowa. Nie dodawaj informacji spoza materiału.
- Długość rozbudowanego scenariusza powinna być wyraźnie większa niż obecna (zbliżona do objętości materiału źródłowego).

Sekcje do pełnego pokrycia:
---
{section_titles}
---

Obecny (zbyt krótki) scenariusz do rozbudowy:
---
{short_script}
---

Zwróć wyłącznie rozbudowany scenariusz (bez komentarzy)."""

# Validation
MAX_URLS_IN_SCRIPT = 10
MAX_MARKDOWN_ARTIFACTS_PER_1K = 5
MIN_SCRIPT_LENGTH = 100


def _escape_for_format(s: str) -> str:
    """Escape braces in user content so str.format() does not interpret them."""
    return (s or "").replace("{", "{{").replace("}", "}}")


def _validate_script(script: str) -> tuple[bool, str]:
    """Returns (ok: bool, error_message: str)."""
    script = (script or "").strip()
    if len(script) < MIN_SCRIPT_LENGTH:
        return False, f"Scenariusz jest zbyt krótki (min. {MIN_SCRIPT_LENGTH} znaków)."
    urls = count_urls(script)
    if urls > MAX_URLS_IN_SCRIPT:
        return False, f"Scenariusz zawiera zbyt wiele URL-i: {urls} (max {MAX_URLS_IN_SCRIPT})."
    artifacts = count_markdown_artifacts(script)
    per_1k = artifacts / max(1, len(script) / 1000)
    if per_1k > MAX_MARKDOWN_ARTIFACTS_PER_1K:
        return False, f"Scenariusz zawiera zbyt wiele elementów składni markdown (ok. {artifacts})."
    return True, ""


def _call_openai(client: OpenAI, system: str, user: str) -> str:
    """Single API call. Returns generated text."""
    response = client.chat.completions.create(
        model=config.SCRIPT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    choice = response.choices and response.choices[0]
    if not choice or not choice.message or not choice.message.content:
        raise ValueError("Empty response from OpenAI.")
    return choice.message.content.strip()


def _build_batch_text(sections: list[Section], cleaned_contents: list[str]) -> str:
    """Join sections into one block with clear separators."""
    parts = []
    for i, (sec, content) in enumerate(zip(sections, cleaned_contents)):
        if not content.strip():
            continue
        parts.append(f"[Sekcja {i + 1}: {sec.title or 'Wprowadzenie'}]\n{content}")
    return "\n\n".join(parts)


def _check_and_fill_missing(
    client: OpenAI,
    source_batch_text: str,
    script_fragment: str,
) -> str:
    """
    Compare script fragment to source. If LLM finds something missing,
    return text to append below fragment. Otherwise return empty string.
    """
    if not source_batch_text.strip() or not script_fragment.strip():
        return ""
    user = USER_PROMPT_COMPLETENESS_TEMPLATE.format(
        source_text=_escape_for_format(source_batch_text),
        script_fragment=_escape_for_format(script_fragment),
    )
    try:
        response = retry_with_backoff(
            lambda: _call_openai(client, SYSTEM_PROMPT_COMPLETENESS, user),
            log=logger,
        )
    except Exception as e:
        logger.warning("Weryfikacja kompletności partii nie powiodła się (pomijam dopisywanie): %s", e)
        return ""
    response = (response or "").strip()
    # Uznaj „brak brakującej treści” tylko gdy odpowiedź to w istocie samo NIE_BRAKUJE (z ewent. interpunkcją)
    normalized = re.sub(r"[^\w]", "", response.upper())
    if normalized == "NIE_BRAKUJE":
        return ""
    return response


def _generate_script_sectional(
    doc: MarkdownDocument,
    client: OpenAI,
) -> str:
    """
    Generate script by section method: extract sections → batches → API → concatenate.
    """
    sections = extract_sections_from_body(doc.body)
    if not sections:
        # Fallback: single block
        full_clean = get_clean_text_for_script(doc)
        user = USER_PROMPT_BATCH_TEMPLATE.format(
            num_sections=1,
            batch_text=_escape_for_format(full_clean),
        )
        return retry_with_backoff(
            lambda: _call_openai(client, SYSTEM_PROMPT_SECTIONS, user),
            log=logger,
        )

    # Split sections into main and to-minimize
    main_sections: list[Section] = []
    minimize_sections: list[Section] = []
    for s in sections:
        if should_minimize_section(s.title):
            minimize_sections.append(s)
        else:
            main_sections.append(s)

    # Clean each section's content
    def clean_sec(sec: Section) -> str:
        return clean_text_fragment(sec.content)

    main_cleaned = [clean_sec(s) for s in main_sections]
    # Skip empty after cleaning
    main_with_content = [
        (sec, txt) for sec, txt in zip(main_sections, main_cleaned) if txt.strip()
    ]
    if not main_with_content:
        full_clean = get_clean_text_for_script(doc)
        user = USER_PROMPT_BATCH_TEMPLATE.format(
            num_sections=1, batch_text=_escape_for_format(full_clean)
        )
        return retry_with_backoff(
            lambda: _call_openai(client, SYSTEM_PROMPT_SECTIONS, user),
            log=logger,
        )

    # Generate in batches
    batch_size = max(1, config.SECTIONS_PER_BATCH)
    parts: list[str] = []
    section_titles_for_coverage: list[str] = []

    for i in range(0, len(main_with_content), batch_size):
        chunk = main_with_content[i : i + batch_size]
        secs = [c[0] for c in chunk]
        texts = [c[1] for c in chunk]
        batch_text = _build_batch_text(secs, texts)
        section_titles_for_coverage.extend([s.title or "Wprowadzenie" for s in secs])

        user = USER_PROMPT_BATCH_TEMPLATE.format(
            num_sections=len(secs),
            batch_text=_escape_for_format(batch_text),
        )
        fragment = retry_with_backoff(
            lambda u=user: _call_openai(client, SYSTEM_PROMPT_SECTIONS, u),
            log=logger,
        )
        # Compare batch to source and append missing content (if enabled)
        if config.CHECK_COMPLETENESS_AFTER_BATCH:
            addition = _check_and_fill_missing(client, batch_text, fragment)
        else:
            addition = ""
        if addition:
            logger.info("Appended missing content to batch (sections: %s)", [s.title for s in secs])
            fragment = fragment.strip() + "\n\n" + addition.strip()
        parts.append(fragment.strip())

    # Intro only at start of first fragment
    title = (doc.frontmatter or {}).get("title") or "tego odcinka"
    intro = f"Cześć! W tym odcinku omówimy: {title}. Zaczynajmy.\n\n"
    script = intro + "\n\n".join(parts)

    # Sections to minimize: one short mention
    if minimize_sections:
        minimize_cleaned = [clean_sec(s) for s in minimize_sections]
        minimize_text = _build_batch_text(minimize_sections, minimize_cleaned)
        if minimize_text.strip():
            user_min = USER_PROMPT_MINIMIZE_TEMPLATE.format(
                batch_text=_escape_for_format(minimize_text)
            )
            try:
                tail = retry_with_backoff(
                    lambda: _call_openai(client, SYSTEM_PROMPT_SECTIONS, user_min),
                    log=logger,
                )
                if tail.strip():
                    script = script.rstrip() + "\n\n" + tail.strip()
            except Exception as e:
                logger.warning("Failed to generate mention for secondary sections: %s", e)

    # Outro
    script = script.rstrip() + OUTRO_STR

    return script


def _check_coverage_and_length(
    script: str,
    source_len: int,
    section_titles: list[str],
) -> tuple[bool, str]:
    """
    Check length ratio and possible missing sections.
    Returns (ok, message).
    """
    if source_len <= 0:
        return True, ""
    ratio = len(script) / source_len
    if ratio < config.MIN_SCRIPT_TO_SOURCE_RATIO:
        return False, (
            f"Scenariusz jest zbyt krótki względem materiału "
            f"(stosunek {ratio:.2f}, min. {config.MIN_SCRIPT_TO_SOURCE_RATIO}). "
            "Wymagana rozbudowa."
        )
    # Simple coverage test: do section titles (or fragments) appear in script
    missing = []
    for t in section_titles:
        if not t or len(t) < 4:
            continue
        # Look for first words of title in script
        key = t[:30].strip() if len(t) > 30 else t
        if key.lower() not in script.lower():
            # Check at least first word
            first_word = key.split()[0] if key.split() else key
            if first_word.lower() not in script.lower():
                missing.append(t[:50])
    if missing:
        logger.info(
            "Sections with no clear reflection in script (may be OK): %s",
            missing[:5],
        )
    return True, ""


# Script ending (we insert appended content before this text)
OUTRO_STR = "\n\nDziękuję za wysłuchanie. Do usłyszenia w kolejnym odcinku."

# Max combined source + script length in one call (chars) to stay within context
MAX_FULL_PASS_CHARS = 100_000


def _full_pass_append_missing(
    client: OpenAI,
    source_text: str,
    script_text: str,
) -> str:
    """
    Second pass (draft + fill): compare full script to source,
    return missing fragments to append (or empty string).
    """
    src = (source_text or "").strip()
    scp = (script_text or "").strip()
    if not src or not scp:
        return ""
    # Truncate to fit context
    if len(src) + len(scp) > MAX_FULL_PASS_CHARS:
        half = MAX_FULL_PASS_CHARS // 2
        if len(src) > half:
            src = src[: half - 500] + "\n\n[... materiał skrócony ...]\n\n" + src[-500:]
        if len(scp) > half:
            scp = scp[: half - 500] + "\n\n[... scenariusz skrócony ...]\n\n" + scp[-500:]
    user = USER_PROMPT_FILL_FULL_TEMPLATE.format(
        source_text=_escape_for_format(src),
        script_text=_escape_for_format(scp),
    )
    try:
        response = retry_with_backoff(
            lambda: _call_openai(client, SYSTEM_PROMPT_FILL_FULL, user),
            log=logger,
        )
    except Exception as e:
        logger.warning("Second pass (fill) failed: %s", e)
        return ""
    response = (response or "").strip()
    if re.sub(r"[^\w]", "", response.upper()) == "NIE_BRAKUJE":
        return ""
    return response


def _expand_script_if_needed(
    client: OpenAI,
    short_script: str,
    section_titles: list[str],
) -> str:
    """One iteration of script expansion when it is too short."""
    section_list = "\n".join(f"- {t}" for t in section_titles[:50])
    user = USER_PROMPT_EXPAND.format(
        section_titles=_escape_for_format(section_list),
        short_script=_escape_for_format(short_script),
    )
    return retry_with_backoff(
        lambda: _call_openai(client, SYSTEM_PROMPT_SECTIONS, user),
        log=logger,
    )


def generate_script(
    doc: MarkdownDocument,
    client: OpenAI,
    output_scripts_dir: Path,
    slug: str,
    force: bool = False,
) -> tuple[bool, str | None]:
    """
    Generate script for one document (section method + validation).
    Saves to output_scripts_dir/{slug}.txt.
    """
    script_path = output_scripts_dir / f"{slug}.txt"
    if script_path.exists() and not force:
        logger.info("Script already exists (skipping): %s", script_path)
        return True, str(script_path)

    full_clean = get_clean_text_for_script(doc)
    if not full_clean.strip():
        logger.error("No content for script after cleaning: %s", doc.path)
        return False, None

    sections = extract_sections_from_body(doc.body)
    section_titles = [s.title or "Wprowadzenie" for s in sections if s.title or s.content.strip()]

    try:
        script = _generate_script_sectional(doc, client)
    except Exception as e:
        err_str = str(e).lower()
        if "length" in err_str or "context" in err_str or "token" in err_str:
            logger.error(
                "Material is likely too long for the model. Consider shortening file: %s",
                doc.filename,
            )
        logger.exception("Script generation failed for %s: %s", doc.filename, e)
        return False, None

    # Second pass (draft + fill): compare full draft to source, append missing fragments
    if config.FILL_MISSING_FULL_PASS:
        addition = _full_pass_append_missing(client, full_clean, script)
        if addition:
            logger.info("Appended missing content (second pass) to script: %s", doc.filename)
            if script.endswith(OUTRO_STR):
                script = script[: -len(OUTRO_STR)].rstrip() + "\n\n" + addition.strip() + OUTRO_STR
            else:
                script = script.rstrip() + "\n\n" + addition.strip()

    # Quality validation
    ok, err_msg = _validate_script(script)
    if not ok:
        logger.warning("Script validation failed: %s. Attempting fix.", err_msg)
        fix_prompt = (
            f"{script}\n\nPopraw powyższy scenariusz: usuń lub zamień URL-e na wzmianki słowne, "
            "usuń pozostałą składnię markdown. Zachowaj treść merytoryczną. Zwróć tylko poprawiony scenariusz."
        )
        try:
            script = retry_with_backoff(
                lambda: _call_openai(client, SYSTEM_PROMPT_SECTIONS, fix_prompt),
                log=logger,
            )
        except Exception as e2:
            logger.exception("Script fix failed: %s", e2)
            return False, None
        ok, _ = _validate_script(script)
        if not ok:
            logger.error("Validation still failing after fix.")
            return False, None

    # Check length vs source
    source_len = len(full_clean)
    ratio_ok, coverage_msg = _check_coverage_and_length(
        script, source_len, section_titles
    )
    if not ratio_ok and coverage_msg:
        logger.warning("Content coverage: %s", coverage_msg)
        try:
            script = _expand_script_if_needed(client, script, section_titles)
        except Exception as e3:
            logger.warning("Script expansion failed: %s", e3)

    try:
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(script, encoding="utf-8")
    except Exception as e:
        logger.exception("Failed to write script to %s: %s", script_path, e)
        return False, None

    logger.info("Saved script: %s (%d chars, source %d, ratio %.2f)", 
                script_path, len(script), source_len, len(script) / max(1, source_len))
    return True, str(script_path)

import re
from typing import Optional
from core.config import settings

# ---------------------------------------------------------------------------
# Stop-words used by the rule-based extractor.
# These are words that appear frequently in paper titles but are unlikely
# to represent a meaningful "core concept" for a BibTeX key.
# ---------------------------------------------------------------------------
_STOP_WORDS: frozenset[str] = frozenset({
    # Articles / determiners
    "a", "an", "the",
    # Conjunctions / prepositions
    "and", "or", "nor", "but", "yet", "so",
    "for", "of", "in", "on", "at", "by", "with", "from", "to",
    "via", "per", "as", "into", "through", "during",
    "before", "after", "above", "below", "between",
    # Auxiliary verbs
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "can",
    # Pronouns
    "its", "our", "their", "your", "you", "we", "they",
    "this", "that", "these", "those", "it",
    # Common filler adjectives / adverbs in titles
    "new", "novel", "large", "small", "fast", "efficient",
    "better", "improved", "enhanced", "advanced", "effective",
    "deep", "robust", "unified", "simple", "general",
    "high", "low", "weak", "strong", "hard", "soft",
    "well", "much", "many", "few", "more", "most",
    "all", "some", "any", "each", "every",
    # Common directional / relational words
    "towards", "toward", "beyond", "based", "using", "without",
    # Common verbs that are not technical terms
    "need", "follow", "show", "make", "build", "find", "get", "use", "know",
    # Generic NLP/ML nouns that are rarely the distinguishing concept
    "learning", "training", "evaluation", "analysis", "study",
    "approach", "method", "methods", "framework", "system",
    "model", "models", "scale", "scaling",
})


def _extract_core_concept_rule_based(title: str, raw_text: str = "") -> str:
    """
    Rule-based fallback for extracting the core technical concept from a paper title.

    Used automatically when the Gemini API is unavailable or returns an error.
    Mimics the LLM's goal: return a single lowercase alphanumeric keyword that
    represents the paper's model name, dataset name, or most important technical term.

    Extraction priority
    -------------------
    0. ``Name: subtitle`` pattern — single word before the colon is likely
       the model/system name (e.g. "Whisper: ...", "BERT: ..." is caught later by P1).
    1. ALL-CAPS acronym, optionally followed by a hyphenated suffix or version number
       (e.g. BERT, CNN, GPT-4, DALL-E).
    2. Word (including hyphenated tokens) containing ≥ 2 uppercase letters —
       catches mixed-case proper nouns such as ViT, LLaMA, ResNet, ImageNet,
       Few-Shot (F + S), while filtering out ordinary "Large-Scale"-style phrases.
    3. First capitalised word after the initial word that is not a stop-word —
       mid-title proper nouns (e.g. "Residual" in "Deep Residual Learning …").
    4. First meaningful word after ":" — the subtitle often names the key topic.
    5. Longest non-stop-word across the whole title — last resort.

    Parameters
    ----------
    title    : Paper title string.
    raw_text : (Unused in rule-based logic; kept for API compatibility.)

    Returns
    -------
    str
        Lowercase alphanumeric string, or ``"unknown"`` if nothing suitable is found.
    """
    if not title:
        return "unknown"

    # Titles with no ASCII letters (e.g. pure Japanese) cannot be processed.
    if not re.search(r"[a-zA-Z]", title):
        return "unknown"

    def clean(s: str) -> str:
        """Strip non-alphanumeric characters and lowercase."""
        return re.sub(r"[^a-zA-Z0-9]", "", s).lower()

    # ------------------------------------------------------------------
    # Priority 0: "Name: subtitle" — single token before the first colon.
    # Covers cases like "Whisper: Robust Speech …", "Claude: …".
    # (BERT, GPT-4 etc. are caught first by Priority 1.)
    # ------------------------------------------------------------------
    if ":" in title:
        before_colon = title.split(":", 1)[0].strip()
        if len(before_colon.split()) == 1:
            c = clean(before_colon)
            if c and len(c) > 2 and c not in _STOP_WORDS:
                return c

    # ------------------------------------------------------------------
    # Priority 1: ALL-CAPS acronym.
    # Pattern covers:
    #   - Plain acronyms:              BERT, CNN, NLP
    #   - Hyphenated acronyms:         DALL-E
    #   - Version-suffixed acronyms:   GPT-4, GPT-3.5, BERT-Large
    # ------------------------------------------------------------------
    caps_matches = re.findall(
        r"\b[A-Z]{2,}(?:-[A-Z]+)?(?:-?\d+(?:\.\d+)?)?\b", title
    )
    if caps_matches:
        return clean(caps_matches[0])

    # ------------------------------------------------------------------
    # Priority 2: Mixed-case token with ≥ 2 uppercase letters.
    # Catches: ViT (V+T), LLaMA (L+L+M+A), ResNet (R+N), ImageNet (I+N),
    #          Few-Shot (F+S as a hyphenated token).
    # Excludes ordinary hyphenated adjectives ("Large-Scale", "High-Quality")
    # by checking whether every hyphen-separated part is a common word.
    # ------------------------------------------------------------------
    raw_tokens = re.split(r"[\s()\[\]{}]", title)
    for rt in raw_tokens:
        if not rt:
            continue
        parts = rt.split("-") if "-" in rt else [rt]
        # Skip tokens where every part is either a stop-word or a plain
        # Title-Case word (first letter upper, rest lower) — these are
        # ordinary compound adjectives, not proper nouns.
        if len(parts) > 1:
            all_common = all(
                re.sub(r"[^a-zA-Z0-9]", "", p).lower() in _STOP_WORDS
                or (bool(p) and p[0].isupper() and p[1:].islower())
                for p in parts
                if re.sub(r"[^a-zA-Z0-9]", "", p)
            )
            if all_common:
                continue

        stripped = re.sub(r"^[^a-zA-Z]+|[^a-zA-Z0-9]+$", "", rt)
        if not stripped:
            continue
        if sum(c.isupper() for c in stripped) >= 2:
            c = clean(stripped)
            if c and len(c) > 2 and c not in _STOP_WORDS:
                return c

    # ------------------------------------------------------------------
    # Priority 3: First capitalised word after the opening word.
    # Covers mid-title proper nouns such as "Residual" in
    # "Deep Residual Learning for Image Recognition".
    # ------------------------------------------------------------------
    words = title.split()
    for w in words[1:]:
        c = clean(w)
        if c and len(c) > 2 and c not in _STOP_WORDS and w[0].isupper():
            return c

    # ------------------------------------------------------------------
    # Priority 4: First meaningful word in the subtitle (after ":").
    # ------------------------------------------------------------------
    if ":" in title:
        after_colon = title.split(":", 1)[1]
        for w in after_colon.split():
            c = clean(w)
            if c and len(c) > 2 and c not in _STOP_WORDS:
                return c

    # ------------------------------------------------------------------
    # Priority 5: Longest non-stop-word in the entire title.
    # Covers cases like "Attention Is All You Need" → "attention".
    # ------------------------------------------------------------------
    all_tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9]*", title)
    candidates = [
        t.lower() for t in all_tokens
        if t.lower() not in _STOP_WORDS and len(t) > 2
    ]
    if candidates:
        return max(candidates, key=len)

    return "unknown"


def extract_core_concept_via_llm(title: str, raw_text: str = "") -> str:
    """
    Extract the most representative keyword from a paper title.

    Tries the Gemini API first; automatically falls back to
    :func:`_extract_core_concept_rule_based` when:

    * ``GEMINI_API_KEY`` is not configured (empty string), or
    * The API raises any exception (``ValueError``, network error, quota
      exceeded, etc.).

    The rule-based fallback reproduces the LLM's intended output —
    a single lowercase alphanumeric word identifying the paper's model,
    dataset, or key technical concept — using heuristics based on
    capitalisation patterns and a curated stop-word list.

    Parameters
    ----------
    title    : Paper title string.
    raw_text : Raw reference text snippet (used as context by the LLM).

    Returns
    -------
    str
        Lowercase alphanumeric keyword, or ``"unknown"``.
    """
    if not title:
        return "unknown"

    # Fast path: no API key configured → skip the network call entirely.
    if not settings.gemini_api_key:
        print("[LLM Extractor] GEMINI_API_KEY is not set. Using rule-based fallback.")
        return _extract_core_concept_rule_based(title, raw_text)

    context = raw_text[:500] if raw_text else ""

    prompt = f"""
You are an academic paper bibliography information extraction assistant.
From the following paper title (and the beginning of the text), please extract the representative "model name", "dataset name", or "most important technical term" as a single word.

【Rules】
- Output only the extracted single word (alphanumeric).
- Do not include any additional explanation, symbols, or punctuation.
- If spaces are included, remove them and concatenate (e.g., "Vision Transformer" -> "VisionTransformer").
- If there is no specific unique model name, select one key technical term from the paper.

Title: {title}
Context: {context}
"""

    try:
        # Lazy import: avoids an ImportError / ValueError at module load time
        # when the google-genai package is not installed or the key is invalid.
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(
            model=settings.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=settings.temperature,
                max_output_tokens=settings.max_output_tokens,
                safety_settings=[
                    types.SafetySetting(
                        category="HARM_CATEGORY_HARASSMENT",
                        threshold="BLOCK_NONE",
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_HATE_SPEECH",
                        threshold="BLOCK_NONE",
                    ),
                ],
            ),
        )

        if not response.text:
            return _extract_core_concept_rule_based(title, raw_text)

        extracted = response.text.strip()
        cleaned = re.sub(r"[^a-zA-Z0-9]", "", extracted).lower()
        return cleaned if cleaned else _extract_core_concept_rule_based(title, raw_text)

    except Exception as e:
        print(f"[LLM Extractor] API error — falling back to rule-based: {e}")
        return _extract_core_concept_rule_based(title, raw_text)
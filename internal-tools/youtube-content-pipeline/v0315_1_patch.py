from __future__ import annotations

import copy
import difflib
import hashlib
import re
from collections import Counter, defaultdict
from typing import Any


PATCH_VERSION = "v0.3.15.1"

# Common sentence starters / function words that should not become protected entities.
_ENTITY_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "because", "before", "but", "by",
    "for", "from", "here", "how", "i", "if", "in", "is", "it", "its", "let", "lets",
    "my", "no", "not", "now", "of", "on", "or", "our", "so", "that", "the", "their",
    "then", "there", "these", "they", "this", "those", "to", "today", "use", "using",
    "we", "what", "when", "where", "which", "who", "why", "with", "you", "your",
    "video", "videos", "tool", "tools", "style", "styles", "folder", "folders", "file",
    "files", "free", "basic", "plan", "plans", "cost", "costs", "editing", "edit",
    "director", "creative", "art", "long", "short", "form", "example", "examples",
    "think", "also", "really", "every", "day", "edited", "into", "will", "can",
}

# Ordinary English phrases should be translated, not protected as entities.
_ENTITY_GENERIC = {
    "worst case", "best case", "sound effect", "sound effects", "motion graphic",
    "motion graphics", "raw file", "output file", "brand color", "brand kit",
    "open source", "full automatic editing", "automatic editing", "b-roll", "b-rolls", "b roll", "b rolls",
}

# v0.3.12: sentence-initial capitalization is NOT evidence of a proper name.
# These discourse/function words must stay translatable even when auto-captions capitalize them.
_ENTITY_STOPWORDS.update({
    "hold", "again", "anyways", "anyway", "all", "right", "okay", "ok", "wait",
    "well", "actually", "basically", "simply", "just", "like", "super", "simple",
    "trust", "see", "look", "yes", "yeah", "sure", "maybe", "probably", "literally",
    "first", "second", "next", "finally", "anyhow", "alright",
    "while", "some", "full", "read", "start", "after", "plus",
})
_ENTITY_GENERIC.update({
    "hold on", "all right", "alright", "trust me", "see this", "look at this",
    "by the way", "on the side note", "start to finish", "step by step",
})

# Words that are especially common as untranslated discourse leakage in Korean output.
# This is a detection list, not a translation dictionary: flagged rows are sent back to Qwen3
# with the full source so the model can translate the phrase contextually.
_COMMON_ENGLISH_LEAK_WORDS_V0312 = {
    "hold", "again", "anyways", "anyway", "all", "right", "alright", "okay", "ok", "wait",
    "well", "actually", "basically", "simply", "just", "like", "super", "simple", "trust",
    "see", "look", "yes", "yeah", "sure", "maybe", "probably", "literally", "first", "second",
    "next", "finally", "cool", "worst", "best", "case", "while", "some", "full",
}



def _plain_titlecase_token_v0312(token: str) -> bool:
    token = str(token or "")
    return bool(re.fullmatch(r"[A-Z][a-z]{2,}", token))


def _lowercase_surface_tokens_v0312(data: dict[str, Any]) -> set[str]:
    """Lowercase surface evidence is strong evidence that plain Titlecase was sentence casing.

    This is intentionally generic: it does not need to know that Some/Full/While are ordinary
    English in advance. If the same token exists lowercase elsewhere in the source, a plain
    sentence-initial Titlecase occurrence cannot become a protected entity on capitalization alone.
    """
    evidence = "\n".join(_trusted_metadata_texts(data) + _transcript_texts(data))
    return {
        m.group(1).lower()
        for m in re.finditer(r"(?<![A-Za-z0-9])([a-z][a-z0-9+#_-]{2,})(?![A-Za-z0-9])", evidence)
    }


def _entity_kind_is_strong_v0312(kinds: set[str]) -> bool:
    return bool(kinds & {
        "metadata", "metadata_token", "metadata_subphrase", "context_pattern",
        "trusted_root_phrase", "fuzzy_to_trusted_entity", "video_entity_audit",
    })


def _entity_is_output_verified_v0312(
    canonical: str,
    registry: dict[str, Any] | None,
) -> bool:
    """Return True only for entities strong enough to exempt from the final Latin gate.

    Crucially, being present in `registry[canonicals]` is not sufficient. This closes the
    v0.3.11 failure where sentence-cased ordinary words were accidentally registered and then
    removed before Latin-residue checking.
    """
    registry = registry or {}
    canonical = _clean_entity(canonical)
    if not canonical:
        return False
    low = canonical.lower()
    if low in _ENTITY_GENERIC or low in _ENTITY_STOPWORDS or low in _COMMON_ENGLISH_LEAK_WORDS_V0312:
        return False
    toks = _entity_tokens(canonical)
    if not toks:
        return False
    if any(t.lower() in _COMMON_ENGLISH_LEAK_WORDS_V0312 for t in toks):
        return False
    kinds = set((registry.get("source_kind", {}) or {}).get(canonical, []) or [])
    score = float((registry.get("score", {}) or {}).get(canonical, 0) or 0)
    lower_surface = set(registry.get("lowercase_surface_tokens", []) or [])

    technical_shape = any(
        t.isupper() or any(ch.isdigit() for ch in t) or any(ch.isupper() for ch in t[1:])
        for t in toks
    )
    if technical_shape and score >= 8:
        return True
    if _entity_kind_is_strong_v0312(kinds) and score >= 20:
        return True
    if len(toks) >= 2 and score >= 20 and not any(t.lower() in _ENTITY_STOPWORDS for t in toks):
        return True
    if len(toks) == 1 and _plain_titlecase_token_v0312(toks[0]):
        # A repeated plain Titlecase token can be a name, but only if the source never also
        # uses its lowercase form. This preserves repeated person/tool names while rejecting
        # sentence-case artifacts without a language-specific dictionary.
        if low not in lower_surface and "repeated_transcript" in kinds and score >= 20:
            return True
    return False


def _sanitize_entity_registry_v0312(registry: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    registry = copy.deepcopy(registry or {})
    registry["lowercase_surface_tokens"] = sorted(_lowercase_surface_tokens_v0312(data))
    kept = [
        c for c in (registry.get("canonicals", []) or [])
        if _entity_is_output_verified_v0312(c, registry)
    ]
    kept_set = set(kept)
    registry["canonicals"] = sorted(kept_set, key=lambda x: (-len(x), x.lower()))
    registry["variant_to_canonical"] = {
        variant: canonical
        for variant, canonical in (registry.get("variant_to_canonical", {}) or {}).items()
        if canonical in kept_set
    }
    return registry


def _suspicious_entity_phrases_v0312(data: dict[str, Any], limit: int = 80) -> list[str]:
    """Surface source phrases worth extra attention in the one-time video entity audit.

    These are only candidates shown to Qwen3; they are never automatically accepted. The
    existing safety gate still requires canonical components to be supported by video evidence.
    """
    joined = " ".join(_transcript_texts(data))
    found: list[str] = []
    patterns = [
        # Titlecased root followed by one/two lowercase-looking tokens: common ASR shape for
        # badly heard multi-part brands (e.g. a brand + product relation).
        r"(?<![A-Za-z0-9])([A-Z][A-Za-z'-]{2,}(?:\s+[a-z][A-Za-z'-]{2,}){1,2})(?![A-Za-z0-9])",
        # Apostrophe/split forms such as a badly heard single brand broken into two tokens.
        r"(?<![A-Za-z0-9])([A-Z][A-Za-z'-]{2,}'?\s+[A-Za-z][A-Za-z'-]{2,})(?![A-Za-z0-9])",
    ]
    for pat in patterns:
        for m in re.finditer(pat, joined):
            phrase = _clean_entity(m.group(1))
            toks = _entity_tokens(phrase)
            if not toks:
                continue
            first = toks[0].lower()
            if first in _ENTITY_STOPWORDS or first in _COMMON_ENGLISH_LEAK_WORDS_V0312:
                continue
            if all(t.lower() in _ENTITY_STOPWORDS for t in toks):
                continue
            if phrase not in found:
                found.append(phrase)
            if len(found) >= limit:
                return found
    return found


def _normalize_source_conditioned_surfaces_v0312(source: str, output: str) -> str:
    """Small deterministic surface normalizations only when source semantics prove the term.

    This is not a translation dictionary. It merely prevents mixed-script corruption of a term
    that is already explicit in the source (B-roll -> B-롤), so the Latin gate does not produce
    a false positive on the broken half-token.
    """
    out = str(output or "")
    if re.search(r"\bb[- ]?rolls?\b", str(source or ""), re.I):
        out = re.sub(r"(?<![A-Za-z0-9])B\s*[-–—]?\s*롤(?:스)?", "B-roll", out, flags=re.I)
    return out

_CAP_TOKEN = r"[A-Z][A-Za-z0-9+#_-]*(?:\.[A-Za-z0-9+#_-]+)*"
_CAP_PHRASE_RE = re.compile(rf"\b{_CAP_TOKEN}(?:\s+{_CAP_TOKEN}){{0,2}}\b")
_SINGLE_CAP_RE = re.compile(rf"\b{_CAP_TOKEN}\b")
_CONTEXT_ENTITY_RE = re.compile(
    r"\b(?i:called|by|using|use|uses|tried|try|like|recommend|from|with|via|into)\s+"
    rf"({_CAP_TOKEN}(?:\s+[A-Za-z][A-Za-z0-9+#_.-]*){{0,1}})"
)
_QUOTED_RE = re.compile(r"([\"'“”‘’])(.{0,400}?)\1")


def _clean_entity(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip(" \t\n\r.,:;!?()[]{}\"'“”‘’")
    return value


def _entity_tokens(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9+#_-]+(?:\.[A-Za-z0-9+#_-]+)*", value)


def _entity_candidate_ok(value: str) -> bool:
    value = _clean_entity(value)
    if not value or value.lower() in _ENTITY_GENERIC:
        return False
    tokens = _entity_tokens(value)
    if not tokens or len(tokens) > 4:
        return False
    low = [t.lower() for t in tokens]
    if all(t in _ENTITY_STOPWORDS for t in low):
        return False
    if len(tokens) == 1 and low[0] in _ENTITY_STOPWORDS:
        return False
    # Require some proper-name signal: uppercase, titlecase, digit or internal capital.
    return any(
        t.isupper()
        or (t[:1].isupper() and t[1:] != t[1:].lower())
        or (t[:1].isupper() and len(t) >= 3)
        or any(ch.isdigit() for ch in t)
        for t in tokens
    )


def _extract_cap_phrases(text: str) -> list[str]:
    out = []
    for match in _CAP_PHRASE_RE.finditer(str(text or "")):
        value = _clean_entity(match.group(0))
        toks = _entity_tokens(value)
        # Reject phrase if a sentence-starter/function token contaminates it.
        if len(toks) > 1 and any(t.lower() in _ENTITY_STOPWORDS for t in toks):
            continue
        if _entity_candidate_ok(value):
            out.append(value)
    return out


def _extract_context_entities(text: str) -> list[str]:
    out = []
    for match in _CONTEXT_ENTITY_RE.finditer(str(text or "")):
        value = _clean_entity(match.group(1))
        # Stop overly greedy capture on common continuation words.
        parts = value.split()
        kept = []
        for part in parts:
            if kept and part.lower() in _ENTITY_STOPWORDS:
                break
            kept.append(part)
        value = " ".join(kept)
        if _entity_candidate_ok(value):
            out.append(value)
    return out


def _trusted_metadata_texts(data: dict[str, Any]) -> list[str]:
    metadata = data.get("metadata", {}) or {}
    texts = [
        str(metadata.get("title") or ""),
        str(metadata.get("description_raw") or ""),
    ]
    for chapter in data.get("creator_chapters", []) or []:
        texts.append(str(chapter.get("label") or ""))
    return [x for x in texts if x.strip()]


def _transcript_texts(data: dict[str, Any]) -> list[str]:
    items = (data.get("transcript", {}) or {}).get("items", []) or []
    return [str(item.get("text") or "") for item in items if str(item.get("text") or "").strip()]



# ---------------------------------------------------------------------------
# v0.3.12 video-level entity audit
# ---------------------------------------------------------------------------
# The deterministic registry remains the first line of defense, but auto captions can
# distort a brand too heavily for character-level fuzzy matching (e.g. a multi-word
# homophone).  One short Qwen3 audit is therefore run once per video and cached.
# The model is NOT allowed to freely invent names: accepted repairs must point back to
# proper-name tokens already supported elsewhere in this video's metadata/transcript.
_VIDEO_ENTITY_AUDIT_CACHE_V0312: dict[str, dict[str, str]] = {}
_ACTIVE_ENTITY_AUDIT_MAP_V0312: dict[str, str] = {}

_AUDIT_DESCRIPTOR_TOKENS_V0312 = {
    "ai", "api", "app", "agent", "code", "ide", "studio", "model", "models",
    "tool", "tools", "field", "fields", "frame", "frames", "server", "servers",
    "mcp", "b", "roll", "rolls", "the", "a", "an", "s",
}


def _entity_audit_cache_key_v0312(data: dict[str, Any]) -> str:
    video_id = str(data.get("video_id") or data.get("metadata", {}).get("video_id") or "")
    transcript = "\n".join(_transcript_texts(data))
    digest = hashlib.sha1(transcript.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{video_id}:{len(transcript)}:{digest}"


def _entity_supported_tokens_v0312(data: dict[str, Any], registry: dict[str, Any]) -> set[str]:
    supported: set[str] = set()
    for canonical in registry.get("canonicals", []) or []:
        for tok in _entity_tokens(canonical):
            if tok.lower() not in _AUDIT_DESCRIPTOR_TOKENS_V0312:
                supported.add(tok.lower())

    # Exact mixed-case/all-caps/title-shaped tokens occurring elsewhere in the video's
    # own metadata/transcript are also admissible evidence.  This lets the audit combine
    # two already-supported names into a repaired phrase without opening the door to an
    # unrelated hallucinated brand.
    evidence_text = "\n".join(_trusted_metadata_texts(data) + _transcript_texts(data))
    for tok in re.findall(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9+#_-]{2,})(?![A-Za-z0-9])", evidence_text):
        if (
            tok.isupper()
            or any(ch.isupper() for ch in tok[1:])
            or any(ch.isdigit() for ch in tok)
            or tok.lower() in {t.lower() for c in (registry.get("canonicals", []) or []) for t in _entity_tokens(c)}
        ):
            if tok.lower() not in _ENTITY_STOPWORDS and tok.lower() not in _AUDIT_DESCRIPTOR_TOKENS_V0312:
                supported.add(tok.lower())
    return supported


def _entity_audit_prompt_v0312(data: dict[str, Any], registry: dict[str, Any]) -> str:
    metadata = data.get("metadata", {}) or {}
    title = str(metadata.get("title") or "")
    desc = str(metadata.get("description_raw") or "")
    chapters = " | ".join(str(c.get("label") or "") for c in (data.get("creator_chapters", []) or []))
    trusted = ", ".join(registry.get("canonicals", [])[:90])
    transcript = "\n".join(_transcript_texts(data))
    # Current videos are well below this; cap defensively for future long-form inputs.
    if len(transcript) > 32000:
        transcript = transcript[:16000] + "\n...[middle omitted for entity audit]...\n" + transcript[-16000:]

    return f"""자동 생성 자막 전체를 보고 브랜드·제품·서비스·모델·도구·사람 이름의 ASR 오기만 찾으세요.
이 단계는 번역이 아니라 '고유명사 철자 복원' 단계입니다.

절대 규칙:
- 일반 영어, 담화 표현, 업계 일반명사는 고치지 마세요.
- 이미 올바른 짧은 이름을 관련된 더 긴 이름으로 확장하지 마세요. 예: 정상적인 A를 A Product로 바꾸지 않습니다.
- 서로 다른 제품/하위 제품을 하나로 합치지 마세요.
- URL, 도메인, 파일명, slash command는 바꾸지 마세요.
- 확신이 높지 않으면 출력하지 마세요.
- SOURCE는 아래 TRANSCRIPT에 실제로 존재하는 원문 문자열이어야 합니다.
- CANONICAL은 공식 Latin 표기 또는, 영상 안에서 강하게 확인되는 공식 이름들의 자연스러운 소유격/띄어쓰기 조합이어야 합니다.
- 자막이 한 브랜드명을 띄어 쓰거나 아포스트로피를 끼워 넣은 경우도 한 이름으로 복원할 수 있습니다.
- 한 구절이 '브랜드의 제품명'을 심하게 잘못 인식한 경우, 영상 내 다른 곳에서 두 이름이 각각 확인된다면 올바른 소유 관계로 복원할 수 있습니다.
- 아래 TRUSTED_NAMES는 강한 참고 근거입니다. 이것과 영상 전체 문맥을 함께 사용하세요.

TITLE:
{title}

DESCRIPTION:
{desc[:5000]}

CREATOR_CHAPTERS:
{chapters}

TRUSTED_NAMES:
{trusted}

SUSPICIOUS_SOURCE_PHRASES (후보일 뿐이며 근거 없으면 수정 금지):
{chr(10).join(_suspicious_entity_phrases_v0312(data))}

TRANSCRIPT:
{transcript}

OUTPUT_FORMAT:
수정할 항목이 있을 때만 한 줄씩 아래 형식으로 출력하세요.
@@E001@@ SOURCE ||| CANONICAL
@@E002@@ SOURCE ||| CANONICAL
설명, 점수, 코드블록은 출력하지 마세요.
"""


def _parse_entity_audit_v0312(text: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for line in str(text or "").splitlines():
        m = re.match(r"\s*@@E\d+@@\s*(.*?)\s*\|\|\|\s*(.*?)\s*$", line)
        if not m:
            continue
        raw = _clean_entity(m.group(1))
        canonical = _clean_entity(m.group(2))
        if raw and canonical and raw.lower() != canonical.lower():
            items.append((raw, canonical))
    return items


def _audit_mapping_is_safe_v0312(
    raw: str,
    canonical: str,
    data: dict[str, Any],
    registry: dict[str, Any],
    supported_tokens: set[str],
) -> bool:
    raw = _clean_entity(raw)
    canonical = _clean_entity(canonical)
    if not raw or not canonical:
        return False
    if raw.lower() == canonical.lower():
        return False
    if re.search(r"https?://|(?:[A-Za-z0-9_-]+\.)+(?:com|ai|io|dev|app|net|org)|\{slash\}|(?<!\w)/[A-Za-z0-9_./-]+", raw, re.I):
        return False

    transcript = "\n".join(_transcript_texts(data))
    if raw.lower() not in transcript.lower():
        return False

    # If the source phrase is already an established canonical name, never expand or
    # rewrite it to a related name. This is the hard stop for Claude -> Claude Code.
    canonical_lowers = {c.lower() for c in registry.get("canonicals", []) or []}
    if raw.lower() in canonical_lowers:
        return False

    raw_key = _entity_fuzzy_key_v0312(raw)
    can_key = _entity_fuzzy_key_v0312(canonical)

    # Do not silently collapse a suspicious multi-part ASR phrase to only the easy
    # canonical substring.  Example shape: "X hyper frames" -> "HyperFrames" leaves
    # the unexplained X component behind.  A close spelling repair such as
    # "Hicks field" -> "Higgsfield" does not trigger because the canonical is not an
    # exact substring of the raw collapsed form.  Unresolved composites are sent to the
    # constrained composite audit / review path instead of being falsely marked clean.
    raw_tokens_for_collapse = _entity_tokens(raw)
    can_tokens_for_collapse = _entity_tokens(canonical)
    if len(raw_tokens_for_collapse) >= 2 and len(can_tokens_for_collapse) == 1 and raw_key and can_key and can_key in raw_key:
        unexplained = raw_key.replace(can_key, "", 1)
        if len(unexplained) >= 4:
            return False

    if raw_key and can_key and (can_key.startswith(raw_key) or raw_key.startswith(can_key)):
        if abs(len(raw_key) - len(can_key)) >= 4:
            return False

    significant = []
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9+#_-]*", canonical):
        low = tok.lower().rstrip("s") if tok.lower().endswith("'s") else tok.lower()
        if low == "s" or low in _AUDIT_DESCRIPTOR_TOKENS_V0312 or low in _ENTITY_STOPWORDS:
            continue
        significant.append(low)
    if not significant:
        return False
    # Every meaningful canonical component must be supported elsewhere in this video.
    # Allow a very close spelling/case/plural variant of an already-supported token so an
    # official form such as HyperFrames can be restored from HyperFrame/hyper frames without
    # allowing an unrelated invented brand.
    def supported_or_close(tok: str) -> bool:
        if tok in supported_tokens:
            return True
        for known in supported_tokens:
            if not tok or not known or tok[:1] != known[:1] or abs(len(tok) - len(known)) > 2:
                continue
            if difflib.SequenceMatcher(None, tok, known).ratio() >= 0.86:
                return True
        return False
    return all(supported_or_close(tok) for tok in significant)



def _is_partial_entity_collapse_v0313(raw: str, canonical: str) -> bool:
    raw_key = _entity_fuzzy_key_v0312(raw)
    can_key = _entity_fuzzy_key_v0312(canonical)
    rt, ct = _entity_tokens(raw), _entity_tokens(canonical)
    if len(rt) < 2 or len(ct) != 1 or not raw_key or not can_key or can_key not in raw_key:
        return False
    return len(raw_key.replace(can_key, "", 1)) >= 4


def _stylized_entity_surfaces_v0313(data: dict[str, Any], registry: dict[str, Any], limit: int = 120) -> list[str]:
    """Collect exact name-like surface forms so a constrained audit can preserve casing.

    This does not declare them correct by itself.  It merely shows the resolver forms that
    actually occur in metadata/transcript (e.g. an internal CamelCase spelling) alongside
    already-verified canonical roots.
    """
    out: list[str] = []
    for c in registry.get("canonicals", []) or []:
        if _entity_is_output_verified_v0312(c, registry) and c not in out:
            out.append(c)
    evidence = _trusted_metadata_texts(data) + _transcript_texts(data)
    pat = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Za-z0-9+#_-]*(?:[A-Z][A-Za-z0-9+#_-]*)?(?:\s+[A-Z][A-Za-z0-9+#_-]*){0,2})(?![A-Za-z0-9])")
    for text in evidence:
        for m in pat.finditer(str(text or "")):
            cand = _clean_entity(m.group(1))
            if not cand or not _entity_candidate_ok(cand):
                continue
            toks = _entity_tokens(cand)
            if all(t.lower() in _ENTITY_STOPWORDS for t in toks):
                continue
            if cand not in out:
                out.append(cand)
            if len(out) >= limit:
                return out
    return out


def _composite_entity_audit_prompt_v0313(data: dict[str, Any], registry: dict[str, Any], raw_phrases: list[str]) -> str:
    metadata = data.get("metadata", {}) or {}
    surfaces = _stylized_entity_surfaces_v0313(data, registry)
    transcript = "\n".join(_transcript_texts(data))
    if len(transcript) > 22000:
        transcript = transcript[:11000] + "\n...[middle omitted]...\n" + transcript[-11000:]
    return f"""Resolve ONLY the suspicious multi-part ASR proper-name phrases below.
A previous resolver tried to collapse part of each phrase to one known name but left another
source component unexplained.  Do not return a partial name.

Rules:
- CANONICAL must account for the whole suspicious phrase, not just an easy suffix.
- Use one or at most two high-confidence proper names/products supported by TRUSTED_SURFACES.
- A possessive relation such as Brand's Product is allowed only when the video context supports it.
- Preserve the strongest observed official-looking Latin casing from TRUSTED_SURFACES.
- Never invent a name that is not supported by the video evidence.
- If the full phrase cannot be resolved confidently, omit it entirely.
- Do not rewrite ordinary language.

TITLE: {metadata.get('title','')}
DESCRIPTION: {str(metadata.get('description_raw') or '')[:4500]}
TRUSTED_SURFACES: {', '.join(surfaces)}
SUSPICIOUS_PHRASES:
{chr(10).join(raw_phrases)}

TRANSCRIPT_REFERENCE:
{transcript}

OUTPUT (only confident items):
@@C001@@ SOURCE ||| CANONICAL
@@C002@@ SOURCE ||| CANONICAL
"""


def _parse_composite_entity_audit_v0313(text: str) -> list[tuple[str, str]]:
    out = []
    for line in str(text or "").splitlines():
        m = re.match(r"\s*@@C\d+@@\s*(.*?)\s*\|\|\|\s*(.*?)\s*$", line)
        if not m:
            continue
        raw, can = _clean_entity(m.group(1)), _clean_entity(m.group(2))
        if raw and can and raw.lower() != can.lower():
            out.append((raw, can))
    return out


def _resolve_video_entity_audit_v0312(
    core: Any,
    data: dict[str, Any],
    model_name: str,
    registry: dict[str, Any],
) -> dict[str, str]:
    key = _entity_audit_cache_key_v0312(data)
    if key in _VIDEO_ENTITY_AUDIT_CACHE_V0312:
        return copy.deepcopy(_VIDEO_ENTITY_AUDIT_CACHE_V0312[key])

    supported = _entity_supported_tokens_v0312(data, registry)
    try:
        text = core._generate_local_llm_text_v033(
            model_name,
            (
                "You are a conservative ASR proper-name resolver. "
                "Return only high-confidence corrections in the requested marker format. "
                "Never rewrite ordinary language and never invent unsupported brand names."
            ),
            _entity_audit_prompt_v0312(data, registry),
            max_tokens=1800,
        )
    except Exception:
        _VIDEO_ENTITY_AUDIT_CACHE_V0312[key] = {}
        return {}

    accepted: dict[str, str] = {}
    partial_rejected: list[str] = []
    for raw, canonical in _parse_entity_audit_v0312(text):
        if _audit_mapping_is_safe_v0312(raw, canonical, data, registry, supported):
            accepted[raw] = canonical
        elif _is_partial_entity_collapse_v0313(raw, canonical):
            partial_rejected.append(raw)

    # If the first audit recognized only the easy suffix of a suspicious multi-part name,
    # give Qwen3 one constrained chance to resolve the WHOLE phrase from verified video
    # surfaces.  If it cannot, leave the phrase unresolved so the final row is reviewable
    # instead of silently accepting a partial brand name.
    partial_rejected = list(dict.fromkeys(partial_rejected))
    if partial_rejected:
        try:
            ctext = core._generate_local_llm_text_v033(
                model_name,
                "Resolve whole multi-part ASR proper-name phrases from video evidence. Return only confident marker lines.",
                _composite_entity_audit_prompt_v0313(data, registry, partial_rejected),
                max_tokens=max(500, min(1200, 180 + len(partial_rejected) * 150)),
            )
            for raw, canonical in _parse_composite_entity_audit_v0313(ctext):
                if raw not in partial_rejected:
                    continue
                if _audit_mapping_is_safe_v0312(raw, canonical, data, registry, supported):
                    accepted[raw] = canonical
        except Exception:
            pass

    _VIDEO_ENTITY_AUDIT_CACHE_V0312[key] = copy.deepcopy(accepted)
    return accepted


def _apply_active_entity_audit_v0312(text: str) -> tuple[str, list[dict[str, str]]]:
    out = str(text or "")
    repairs: list[dict[str, str]] = []
    for raw, canonical in sorted(_ACTIVE_ENTITY_AUDIT_MAP_V0312.items(), key=lambda kv: len(kv[0]), reverse=True):
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(raw)}(?![A-Za-z0-9])", re.I)
        if pattern.search(out):
            before = out
            out = pattern.sub(canonical, out)
            if out != before:
                repairs.append({"source_text": raw, "canonical_text": canonical, "repair_source": "video_entity_audit"})
    return out, repairs



def _augment_registry_with_audit_canonicals_v0313(registry: dict[str, Any], audit_map: dict[str, str]) -> dict[str, Any]:
    """Make accepted audit canonicals first-class placeholders for exact spelling/casing.

    A composite repair chosen by the video-level audit must not be immediately downgraded by
    an older transcript-derived casing variant during placeholder restoration.
    """
    reg = copy.deepcopy(registry or {})
    canonicals = set(reg.get("canonicals", []) or [])
    variants = dict(reg.get("variant_to_canonical", {}) or {})
    score = dict(reg.get("score", {}) or {})
    source_kind = {k: list(v) for k, v in (reg.get("source_kind", {}) or {}).items()}
    for canonical in (audit_map or {}).values():
        canonical = _clean_entity(canonical)
        if not canonical:
            continue
        canonicals.add(canonical)
        variants[canonical] = canonical
        score[canonical] = max(float(score.get(canonical, 0) or 0), 200.0)
        kinds = set(source_kind.get(canonical, []) or [])
        kinds.add("video_entity_audit")
        source_kind[canonical] = sorted(kinds)
    reg["canonicals"] = sorted(canonicals, key=lambda x: (-len(x), x.lower()))
    reg["variant_to_canonical"] = variants
    reg["score"] = score
    reg["source_kind"] = source_kind
    return reg


def _entity_fuzzy_key_v0312(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _similar_entity(a: str, b: str) -> bool:
    """Conservative ASR-variant comparison.

    v0.3.12 deliberately avoids *entity expansion*: a valid shorter name must not be
    absorbed into a longer related name (Claude -> Claude Code, Sandy -> Sandy Lee).
    Multi-token phrases are compared token-by-token before any collapsed-spelling test so
    distinct entities such as Anti-Gravity Agent and Anti-Gravity IDE stay separate.
    """
    a = _clean_entity(a)
    b = _clean_entity(b)
    if not a or not b or a.lower() == b.lower():
        return False
    at, bt = _entity_tokens(a), _entity_tokens(b)
    ak, bk = _entity_fuzzy_key_v0312(a), _entity_fuzzy_key_v0312(b)
    if not ak or not bk:
        return False

    # Never expand a valid shorter entity into a longer entity just because it is a prefix.
    # This prevents Claude -> Claude Code and Sandy -> Sandy Lee while still allowing
    # spelling repair such as Cloud Code -> Claude Code.
    if (ak.startswith(bk) or bk.startswith(ak)) and abs(len(ak) - len(bk)) >= 3:
        return False

    # If both sides are multi-token phrases with the same token count, semantic-looking
    # suffix changes must agree token-by-token.  Agent vs IDE is not a spelling variant.
    if len(at) == len(bt) and len(at) > 1:
        token_ratios = [
            difflib.SequenceMatcher(None, x.lower(), y.lower()).ratio()
            for x, y in zip(at, bt)
        ]
        if any(r < 0.62 for r in token_ratios):
            return False
        return sum(token_ratios) / len(token_ratios) >= 0.80

    collapsed_ratio = difflib.SequenceMatcher(None, ak, bk).ratio()
    max_len = max(len(ak), len(bk))
    same_initial = ak[:1] == bk[:1]
    if max_len >= 7 and same_initial and abs(len(ak) - len(bk)) <= 4 and collapsed_ratio >= 0.72:
        return True
    if max_len >= 5 and same_initial and abs(len(ak) - len(bk)) <= 2 and collapsed_ratio >= 0.76:
        return True

    if len(at) == len(bt) == 1:
        ratio = difflib.SequenceMatcher(None, ak, bk).ratio()
        threshold = 0.84
        if same_initial and max_len >= 7:
            threshold = 0.68
        elif same_initial and max_len >= 5:
            threshold = 0.70
        return ratio >= threshold and abs(len(ak) - len(bk)) <= 4
    return False

def _build_entity_registry_v035(data: dict[str, Any]) -> dict[str, Any]:
    """Build a video-level entity registry from evidence, not chapter-specific hardcoding."""
    transcript_texts = _transcript_texts(data)
    metadata_texts = _trusted_metadata_texts(data)

    exact_counts: Counter[str] = Counter()
    score: defaultdict[str, float] = defaultdict(float)
    source_kind: defaultdict[str, set[str]] = defaultdict(set)

    # First collect transcript-shaped candidates. A single metadata word is only trusted
    # when the transcript also uses it as a standalone proper-looking token (or it has
    # a strong technical shape such as all-caps/internal caps/digits).
    cap_counts: Counter[str] = Counter()
    single_counts: Counter[str] = Counter()
    contextual = []
    for text in transcript_texts:
        for cand in _extract_cap_phrases(text):
            cap_counts[cand] += 1
            if len(_entity_tokens(cand)) == 1:
                single_counts[cand] += 1
        contextual.extend(_extract_context_entities(text))
    # Auto captions split phrases across adjacent segments. Scan one joined copy as well
    # so patterns such as "tried <Tool>" or "like <Product name>" survive that split.
    joined_transcript = " ".join(transcript_texts)
    contextual.extend(_extract_context_entities(joined_transcript))

    # Strongest evidence: title / description / creator chapter labels.
    for text in metadata_texts:
        meta_phrases = _extract_cap_phrases(text)
        for cand in meta_phrases + _extract_context_entities(text):
            exact_counts[cand] += 1
            score[cand] += 100.0
            source_kind[cand].add("metadata")
            # Also add two-token windows from a longer metadata phrase. This lets a
            # canonical product name survive when the title continues with an acronym.
            toks = _entity_tokens(cand)
            if len(toks) >= 3:
                for i in range(len(toks) - 1):
                    first, second = toks[i], toks[i + 1]
                    first_is_strong = (
                        single_counts.get(first, 0) >= 1
                        or first.isupper()
                        or any(ch.isdigit() for ch in first)
                        or (first[:1].isupper() and any(ch.isupper() for ch in first[1:]))
                    )
                    sub = " ".join([first, second])
                    if first_is_strong and second.lower() not in _ENTITY_STOPWORDS and _entity_candidate_ok(sub):
                        exact_counts[sub] += 1
                        score[sub] += 90.0
                        source_kind[sub].add("metadata_subphrase")
        for m in _SINGLE_CAP_RE.finditer(text):
            cand = _clean_entity(m.group(0))
            if not _entity_candidate_ok(cand):
                continue
            technical_shape = (
                cand.isupper()
                or any(ch.isdigit() for ch in cand)
                or (cand[:1].isupper() and any(ch.isupper() for ch in cand[1:]))
            )
            if technical_shape or single_counts.get(cand, 0) >= 1:
                exact_counts[cand] += 1
                score[cand] += 70.0
                source_kind[cand].add("metadata_token")

    # Transcript evidence: context patterns can establish a one-off person/tool name.

    for cand, count in cap_counts.items():
        exact_counts[cand] += count
        if count >= 2:
            score[cand] += 20.0 + min(count, 20)
            source_kind[cand].add("repeated_transcript")
        elif len(_entity_tokens(cand)) >= 2:
            # One-off multi-token names are only strong enough when every meaningful
            # token itself looks name-like.  Do not protect "Haitian hyper" merely
            # because the first word happens to be sentence/title-cased.
            toks = _entity_tokens(cand)
            name_like = all(
                t.isupper()
                or t[:1].isupper()
                or any(ch.isdigit() for ch in t)
                for t in toks
            )
            if name_like:
                score[cand] += 24.0
                source_kind[cand].add("capitalized_phrase")

    for cand in contextual:
        exact_counts[cand] += 1
        toks = _entity_tokens(cand)
        # A one-off context phrase such as "using X y" is NOT enough to establish
        # "X y" as a protected entity when the trailing word is lowercase and the root
        # is not independently trusted.  Auto captions often create exactly this shape
        # from a badly heard multi-brand phrase.  This prevents wrong ASR text from being
        # frozen as an entity before the video-level audit gets a chance to repair it.
        first_root_trusted = bool(toks and score.get(toks[0], 0) >= 20)
        trailing_lower = any(
            t[:1].islower() and not t.isupper()
            for t in toks[1:]
        )
        if len(toks) >= 2 and trailing_lower and not first_root_trusted:
            score[cand] += 5.0
            source_kind[cand].add("weak_context_phrase")
        else:
            score[cand] += 35.0
            source_kind[cand].add("context_pattern")

    # One-off ASR spellings can still be important when they are close to a strong
    # metadata spelling (e.g. a chapter/title contains the canonical product name).
    trusted_singles = [
        c for c, kinds in source_kind.items()
        if len(_entity_tokens(c)) == 1
        and ("metadata" in kinds or "metadata_token" in kinds or "repeated_transcript" in kinds or "context_pattern" in kinds)
    ]
    for cand, count in single_counts.items():
        if cand in score:
            continue
        if any(_similar_entity(cand, trusted) for trusted in trusted_singles):
            exact_counts[cand] += count
            score[cand] += 12.0
            source_kind[cand].add("fuzzy_to_trusted_entity")

    # Establish strong single-token roots, then allow a following lowercase descriptor
    # (e.g. "<Brand> design") to become an entity phrase if the root is trustworthy.
    strong_roots = {
        c for c, s in score.items()
        if len(_entity_tokens(c)) == 1 and s >= 35
    }
    if strong_roots:
        roots_re = "|".join(sorted((re.escape(r) for r in strong_roots), key=len, reverse=True))
        root_phrase_re = re.compile(rf"\b({roots_re})\s+([a-z][A-Za-z0-9+#_.-]{{2,}})\b")
        root_phrase_counts = Counter()
        for text in transcript_texts:
            for m in root_phrase_re.finditer(text):
                if m.group(2).lower() in _ENTITY_STOPWORDS:
                    continue
                cand = _clean_entity(m.group(0))
                if cand.lower() not in _ENTITY_GENERIC:
                    root_phrase_counts[cand] += 1
        for cand, count in root_phrase_counts.items():
            if count >= 2:
                exact_counts[cand] += count
                score[cand] += 30.0 + count
                source_kind[cand].add("trusted_root_phrase")

    candidates = [
        c for c, s in score.items()
        if s >= 8
        and _entity_candidate_ok(c)
        and not (source_kind.get(c) == {"weak_context_phrase"})
    ]
    candidates = sorted(set(candidates), key=lambda x: (-score[x], -len(x), x.lower()))

    # Cluster likely ASR spelling variants. Prefer stronger evidence, then frequency,
    # then the longer/more explicit spelling.
    parent = {c: c for c in candidates}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        parent[rb] = ra

    for i, a in enumerate(candidates):
        for b in candidates[i + 1:]:
            if _similar_entity(a, b):
                union(a, b)

    clusters: defaultdict[str, list[str]] = defaultdict(list)
    for c in candidates:
        clusters[find(c)].append(c)

    variant_to_canonical: dict[str, str] = {}
    canonicals = []
    for members in clusters.values():
        def rank(c):
            kinds = source_kind[c]
            metadata_bonus = 1 if (
                "metadata" in kinds or "metadata_token" in kinds or "metadata_subphrase" in kinds
            ) else 0
            toks = _entity_tokens(c)
            # If a phrase begins with an already strong canonical root, prefer that
            # spelling over a near-homophone ASR variant of the root.
            root_bonus = 1 if (len(toks) >= 2 and toks[0] in strong_roots) else 0
            trusted_root_bonus = 1 if "trusted_root_phrase" in kinds else 0
            # Prefer an exact CamelCase/mixed-case occurrence when evidence is otherwise
            # comparable.  This preserves official spellings such as HyperFrames instead
            # of collapsing them to Hyperframes just because auto-captions use both.
            case_shape_bonus = sum(
                1 for tok in _entity_tokens(c)
                if any(ch.isupper() for ch in tok[1:])
            )
            return (metadata_bonus, root_bonus, trusted_root_bonus, case_shape_bonus, score[c], exact_counts[c], len(c))
        canonical = max(members, key=rank)
        canonicals.append(canonical)
        for member in members:
            variant_to_canonical[member] = canonical

    # A few repeated/contextual entities may not have clustered; include them exactly.
    for c in candidates:
        variant_to_canonical.setdefault(c, c)

    registry = {
        "canonicals": sorted(set(canonicals), key=lambda x: (-len(x), x.lower())),
        "variant_to_canonical": variant_to_canonical,
        "score": dict(score),
        "source_kind": {k: sorted(v) for k, v in source_kind.items()},
    }
    return _sanitize_entity_registry_v0312(registry, data)


_LITERAL_SPAN_RE_V0312 = re.compile(
    r"https?://[^\s\"'<>]+"
    r"|(?<![A-Za-z0-9])(?:[A-Za-z0-9_-]+\.)+(?:com|ai|io|dev|app|net|org)(?:/[A-Za-z0-9_./?=&%-]*)?"
    r"|(?<![A-Za-z0-9])/[A-Za-z0-9_./-]+"
    r"|\{slash\}\s*command(?:\s+[A-Za-z0-9_.-]+){0,8}",
    re.I,
)


def _shield_literal_spans_v0312(text: str) -> tuple[str, dict[str, str]]:
    """Protect URLs/domains/slash-command literals from entity canonicalization.

    Entity repair must never turn claude.ai into Claude Code.AI or mutate a domain's
    casing/content.  The same principle applies to literal commands.
    """
    mapping: dict[str, str] = {}

    def repl(match):
        key = f"__LIT{len(mapping)+1:03d}__"
        mapping[key] = match.group(0)
        return key

    return _LITERAL_SPAN_RE_V0312.sub(repl, str(text or "")), mapping


def _restore_literal_spans_v0312(text: str, mapping: dict[str, str]) -> str:
    out = str(text or "")
    for key, value in mapping.items():
        out = out.replace(key, value)
    return out


def _replace_entity_variants_v035(text: str, registry: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    # Apply the conservative video-level audit only to the model-facing copy. Raw source
    # and provenance remain untouched in the exported JSON.
    audited, audit_repairs = _apply_active_entity_audit_v0312(text)

    # Deterministic exact spacing repair for strong single-token names:
    # "hyper frames" -> "HyperFrames", "anti gravity" -> "Anti-Gravity" when that
    # canonical name is independently established.  This is much safer than generic
    # fuzzy guessing because the collapsed characters must match exactly.
    spacing_repairs: list[dict[str, str]] = []
    spaced = audited
    single_canonicals = [
        c for c in registry.get("canonicals", []) or []
        if len(_entity_tokens(c)) == 1 and len(_entity_fuzzy_key_v0312(c)) >= 6
    ]
    # Prefer two-word windows first so "open hyper frames preview" can repair the
    # overlapping "hyper frames" span (plain regex finditer would first consume
    # "open hyper" and miss the overlap).
    for word_count in (2, 3):
        made_change = True
        while made_change:
            made_change = False
            words = list(re.finditer(r"[A-Za-z][A-Za-z'-]*", spaced))
            for i in range(0, len(words) - word_count + 1):
                window = words[i:i + word_count]
                # Only accept a whitespace-separated contiguous phrase.
                gap_text = spaced[window[0].start():window[-1].end()]
                if len(re.findall(r"[A-Za-z][A-Za-z'-]*", gap_text)) != word_count:
                    continue
                if not all(
                    spaced[window[j].end():window[j + 1].start()].isspace()
                    for j in range(word_count - 1)
                ):
                    continue
                raw_span = gap_text
                raw_key = _entity_fuzzy_key_v0312(raw_span)
                matches = [c for c in single_canonicals if _entity_fuzzy_key_v0312(c) == raw_key]
                if len(matches) != 1:
                    continue
                canonical = matches[0]
                spaced = spaced[:window[0].start()] + canonical + spaced[window[-1].end():]
                spacing_repairs.append({
                    "source_text": raw_span,
                    "canonical_text": canonical,
                    "repair_source": "exact_spacing_collapse",
                })
                made_change = True
                break

    # Conservative near-spelling repair for split/apostrophe ASR forms that were not
    # caught by the audit.  Only independently strong single-token canonicals qualify.
    fuzzy_spacing_repairs: list[dict[str, str]] = []
    strong_single = [
        c for c in single_canonicals
        if float((registry.get("score", {}) or {}).get(c, 0) or 0) >= 70
    ]
    # Use overlapping adjacent-word windows. A plain regex finditer consumed pairs such as
    # "the Hicks'" and then skipped the actual "Hicks' field" pair, which made the same ASR
    # spelling repair in one row but not another.
    made_change = True
    while made_change:
        made_change = False
        words = list(re.finditer(r"[A-Za-z][A-Za-z'-]*", spaced))
        for i in range(len(words) - 1):
            left, right = words[i], words[i + 1]
            between = spaced[left.end():right.start()]
            if not between.isspace():
                continue
            raw_span = spaced[left.start():right.end()]
            if "'" not in raw_span and "’" not in raw_span:
                continue
            rk = _entity_fuzzy_key_v0312(raw_span)
            scored = []
            for canonical in strong_single:
                ck = _entity_fuzzy_key_v0312(canonical)
                if not rk or not ck or rk[:1] != ck[:1] or abs(len(rk) - len(ck)) > 2:
                    continue
                ratio = difflib.SequenceMatcher(None, rk, ck).ratio()
                if ratio >= 0.79:
                    scored.append((ratio, canonical))
            scored.sort(reverse=True)
            if not scored:
                continue
            if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.08:
                continue
            canonical = scored[0][1]
            before = spaced
            spaced = spaced[:left.start()] + canonical + spaced[right.end():]
            if spaced != before:
                fuzzy_spacing_repairs.append({"source_text": raw_span, "canonical_text": canonical, "repair_source": "strong_fuzzy_spacing"})
                made_change = True
                break

    shielded, literal_map = _shield_literal_spans_v0312(spaced)
    out = shielded
    repairs = list(audit_repairs) + spacing_repairs + fuzzy_spacing_repairs
    items = sorted(
        registry.get("variant_to_canonical", {}).items(),
        key=lambda kv: len(kv[0]),
        reverse=True,
    )
    for variant, canonical in items:
        if variant.lower() == canonical.lower():
            continue
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(variant)}(?![A-Za-z0-9])", re.IGNORECASE)
        if pattern.search(out):
            before = out
            out = pattern.sub(canonical, out)
            if out != before:
                repairs.append({"source_text": variant, "canonical_text": canonical})
    return _restore_literal_spans_v0312(out, literal_map), repairs

def _placeholder_maps_v035(registry: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    canonical_to_placeholder = {}
    placeholder_to_canonical = {}
    for index, canonical in enumerate(registry.get("canonicals", []), start=1):
        ph = f"__ENT{index:03d}__"
        canonical_to_placeholder[canonical] = ph
        placeholder_to_canonical[ph] = canonical
    return canonical_to_placeholder, placeholder_to_canonical


def _protect_entities_v035(text: str, canonical_to_placeholder: dict[str, str]) -> str:
    shielded, literal_map = _shield_literal_spans_v0312(text)
    out = shielded
    for canonical, ph in sorted(canonical_to_placeholder.items(), key=lambda kv: len(kv[0]), reverse=True):
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(canonical)}(?![A-Za-z0-9])", re.IGNORECASE)
        out = pattern.sub(ph, out)
    return _restore_literal_spans_v0312(out, literal_map)


def _restore_entities_v035(text: str, placeholder_to_canonical: dict[str, str]) -> str:
    out = str(text or "")
    out = re.sub(
        r"(__ENT\d{3}__)(?:스|즈)(?=(?:은|는|이|가|을|를|에|에서|의|와|과|로|으로|예요|이에요|입니다))",
        r"\1",
        out,
    )
    for ph, canonical in sorted(placeholder_to_canonical.items(), key=lambda kv: len(kv[0]), reverse=True):
        out = out.replace(ph, canonical)

    # Guard against overlap artifacts after placeholder restoration.
    # Example failures seen in generalized entity repair: "Claude Code Code" and
    # "Sandy Lee Lee".  Only remove a repeated trailing token when it duplicates the
    # final token of an already-established canonical name.
    canonicals = sorted(set(placeholder_to_canonical.values()), key=len, reverse=True)
    for canonical in canonicals:
        tokens = _entity_tokens(canonical)
        if not tokens:
            continue
        last = tokens[-1]
        out = re.sub(
            rf"(?<![A-Za-z0-9])({re.escape(canonical)})\s+{re.escape(last)}(?![A-Za-z0-9])",
            r"\1",
            out,
            flags=re.IGNORECASE,
        )
        out = re.sub(
            rf"(?<![A-Za-z0-9])({re.escape(canonical)})\s+{re.escape(canonical)}(?![A-Za-z0-9])",
            r"\1",
            out,
            flags=re.IGNORECASE,
        )
        if last.lower() == "code":
            out = re.sub(rf"({re.escape(canonical)})\s+코드(?=[을를이가은는에의와과로으로,.!?\s]|$)", r"\1", out)
    return re.sub(r"\s+", " ", out).strip()

def _strip_quoted_spans_v035(text: str) -> str:
    # Direct quotations may intentionally contain casual Korean (e.g. a prompt to a tool).
    out = str(text or "")
    out = re.sub(r'"[^"\n]{0,500}"', ' ', out)
    out = re.sub(r"'[^'\n]{0,500}'", ' ', out)
    out = re.sub(r"“[^”\n]{0,500}”", ' ', out)
    out = re.sub(r"‘[^’\n]{0,500}’", ' ', out)
    return out


def _respectful_register_status_v035(text: str) -> tuple[bool, str]:
    plain = _strip_quoted_spans_v035(text)
    violations = []
    # Token-boundary-aware checks.  In particular, do NOT misread words such as
    # "너무" as the casual pronoun "너".
    checks = [
        (r"(?<![가-힣])당신(?:만의|의|은|는|이|가|을|를|에게|께|도|과|와|이랑|처럼|부터|까지|이라면|이면|이라도|이라서|이라)?(?![가-힣])", "당신"),
        (r"(?<![가-힣])너(?:만의|의|는|가|를|에게|도|랑|처럼|라면|라서|라도)?(?![가-힣])", "너/너는"),
        (r"(?<![가-힣])네가(?![가-힣])", "네가"),
        (r"(?<![가-힣])내가(?![가-힣])", "내가"),
        (r"(?<![가-힣])나는(?![가-힣])", "나는"),
    ]
    for pattern, label in checks:
        if re.search(pattern, plain):
            violations.append(label)
    if re.search(r"(?:야|이야|거야|돼|해|줘|몰라|알아|있어|없어|했어|할게)(?=[.!?]|$)", plain):
        violations.append("반말 종결")
    return (not violations, ", ".join(dict.fromkeys(violations)) or "ok")

def _midpoint(unit: dict[str, Any]) -> float:
    start = float(unit.get("start_seconds", 0) or 0)
    end = float(unit.get("end_seconds", start) or start)
    return (start + end) / 2.0


def _chapter_label_tokens_v036(label: str) -> list[str]:
    raw = re.findall(r"[A-Za-z0-9+#_-]+", str(label or ""))
    stop = _ENTITY_STOPWORDS | {"chapter", "part", "section", "exact", "use", "uses"}
    return [t.lower() for t in raw if len(t) >= 3 and t.lower() not in stop]


def _rough_stem_v036(token: str) -> str:
    t = str(token or "").lower()
    for suffix in ("ing", "ers", "er", "ed", "ly", "s"):
        if len(t) > len(suffix) + 4 and t.endswith(suffix):
            t = t[:-len(suffix)]
            break
    if t.startswith("direct"):
        return "direct"
    return t


def _label_affinity_v036(sentence: str, label: str) -> float:
    sent_tokens = [_rough_stem_v036(t) for t in re.findall(r"[A-Za-z0-9+#_-]+", str(sentence or ""))]
    label_tokens = [_rough_stem_v036(t) for t in _chapter_label_tokens_v036(label)]
    if not sent_tokens or not label_tokens:
        return 0.0
    score = 0.0
    for lt in label_tokens:
        if lt in sent_tokens:
            score += 3.0
            continue
        best = 0.0
        for st in sent_tokens:
            if len(lt) < 4 or len(st) < 4:
                continue
            best = max(best, difflib.SequenceMatcher(None, lt, st).ratio())
        if best >= 0.86:
            score += 2.0
        elif best >= 0.74:
            score += 1.0
    return score


def _owner_chapter_for_unit_v036(core, data, unit):
    chapters = list(data.get("creator_chapters", []) or [])
    if not chapters:
        return core._creator_chapter_for_time_v033(data, float(unit.get("start_seconds", 0) or 0))
    start = float(unit.get("start_seconds", 0) or 0)
    end = float(unit.get("end_seconds", start) or start)
    left = core._creator_chapter_for_time_v033(data, start)
    right = core._creator_chapter_for_time_v033(data, max(start, end - 1e-3))
    if left.get("chapter_id") == right.get("chapter_id"):
        return left

    text = str(unit.get("raw_text") or "")
    # Explicit transition language close to a creator boundary is a strong next-topic cue.
    if re.search(r"\b(?:what i want to talk about next|next (?:one|part|tool|thing)|moving on|let'?s talk about|now let'?s talk about)\b", text, re.I):
        return right

    left_score = _label_affinity_v036(text, left.get("label", ""))
    right_score = _label_affinity_v036(text, right.get("label", ""))
    if right_score >= 2.0 and right_score >= left_score + 1.0:
        return right
    if left_score >= 2.0 and left_score >= right_score + 1.0:
        return left

    # Creator timestamps are approximate. If semantics are not decisive, keep the
    # reconstructed sentence with the chapter where it actually starts.
    return left


def _assign_foreign_sentences_to_chapter_v035(core, all_units, chapter):
    data = globals().get("_ACTIVE_DATA_V0312") or {}
    start = float(chapter.get("start_seconds", 0) or 0)
    end_value = chapter.get("end_seconds")
    end = float(end_value) if end_value is not None else float("inf")

    selected = []
    owner_by_id = {}
    for unit in all_units:
        owner = _owner_chapter_for_unit_v036(core, data, unit) if data else core._creator_chapter_for_time_v033(data, float(unit.get("start_seconds", 0) or 0))
        owner_by_id[unit.get("sentence_unit_id")] = owner
        if owner.get("chapter_id") == chapter.get("chapter_id"):
            selected.append(unit)

    previous = None
    following = None
    for unit in all_units:
        owner = owner_by_id.get(unit.get("sentence_unit_id"), {})
        if owner.get("chapter_id") == chapter.get("chapter_id"):
            continue
        uend = float(unit.get("end_seconds", 0) or 0)
        ustart = float(unit.get("start_seconds", 0) or 0)
        if uend <= start:
            previous = unit
        elif following is None and ustart >= end:
            following = unit

    reassigned_in, reassigned_out = [], []
    cross_end = []
    for unit in all_units:
        uid = unit.get("sentence_unit_id")
        ustart = float(unit.get("start_seconds", 0) or 0)
        uend = float(unit.get("end_seconds", ustart) or ustart)
        start_owned = start <= ustart < end
        final_owned = owner_by_id.get(uid, {}).get("chapter_id") == chapter.get("chapter_id")
        if final_owned and not start_owned:
            reassigned_in.append(uid)
        elif start_owned and not final_owned:
            reassigned_out.append(uid)
        if final_owned and end != float("inf") and uend > end:
            cross_end.append(uid)

    context = {
        "assignment_rule": "reconstructed_sentence_semantic_boundary_owner_v0.3.15.1",
        "creator_boundary_is_hard_cut": False,
        "previous_sentence_context": (
            {
                "sentence_unit_id": previous.get("sentence_unit_id"),
                "start_seconds": previous.get("start_seconds"),
                "end_seconds": previous.get("end_seconds"),
                "raw_text": previous.get("raw_text"),
                "crosses_creator_start": bool(previous and float(previous.get("end_seconds", 0) or 0) > start),
            } if previous else None
        ),
        "next_sentence_context": (
            {
                "sentence_unit_id": following.get("sentence_unit_id"),
                "start_seconds": following.get("start_seconds"),
                "end_seconds": following.get("end_seconds"),
                "raw_text": following.get("raw_text"),
            } if following else None
        ),
        "selected_sentence_ids_crossing_creator_end": cross_end,
        "semantic_reassigned_into_chapter": reassigned_in,
        "semantic_reassigned_out_of_chapter": reassigned_out,
    }
    return selected, context


def _whole_video_group_records_v035(core, data, all_units):
    records = []
    run_units = []
    run_chapter = None

    def flush():
        nonlocal run_units, run_chapter
        if not run_units or run_chapter is None:
            run_units, run_chapter = [], None
            return
        for group in core._group_foreign_sentence_units_v031(run_units):
            records.append((group, copy.deepcopy(run_chapter)))
        run_units, run_chapter = [], None

    for unit in all_units:
        owner = _owner_chapter_for_unit_v036(core, data, unit)
        owner_id = owner.get("chapter_id")
        if run_chapter is not None and run_chapter.get("chapter_id") != owner_id:
            flush()
        if run_chapter is None:
            run_chapter = owner
        run_units.append(unit)
    flush()
    return records


def _style_examples_v035() -> str:
    # These are transferable editorial decisions distilled from reviewed output.
    return """예시 1
원문: The mindset I want you to have is that you are the director, the art director or the creative director, whatever you call yourself.
좋은 한국어: 이제 여러분이 가져야 할 마음가짐은, 감독이든 아트 디렉터든 크리에이티브 디렉터든 뭐라고 부르든 간에 여러분이 바로 그 디렉터라는 것입니다.
판단 기준: or/whatever는 직책을 모두 동시에 가진다는 뜻이 아니라, 어떤 이름으로 부르든 역할의 본질이 디렉터라는 의미다.

예시 2
원문: If you only say, \"Just make a cool video for me,\" the tool does not know what \"cool\" means.
좋은 한국어: 도구에게 '그냥 멋진 영상 하나 만들어줘'라고만 말한다면, 그 도구는 '멋지다'는 게 무슨 뜻인지 알지 못합니다.
판단 기준: 직접 인용문도 내용은 한국어로 번역한다. 인용문의 캐주얼한 말투만 유지할 수 있으며 Just 같은 일반 영어 단어를 남기지 않는다.

예시 3
원문: If you specifically say, \"I want this style rather than that style. That's what I want you to do,\" I think that's what's really important.
좋은 한국어: 하지만 구체적으로 '저 스타일보다 이 스타일을 원하고, 이렇게 해줬으면 해'라고 말한다면 원하는 방향을 훨씬 명확하게 전달할 수 있습니다. 저는 이렇게 구체적으로 방향을 알려주는 것이 정말 중요하다고 생각해요.
판단 기준: 인용된 지시 내용과 화자의 I think 판단을 서로 합치거나 주체를 바꾸지 않는다.

예시 4
원문: He shows only two words at a time.
좋은 한국어: 그는 한 번에 두 단어씩만 보여줍니다.
판단 기준: word는 단어다. character/letter가 아닌데 글자로 바꾸지 않는다.

예시 5
원문: Do you want a cinematic route, something near the beginning, or an animation still?
좋은 한국어: 시네마틱한 방향을 원하시나요, 영상 초반에 무언가를 넣고 싶으신가요, 아니면 애니메이션 스틸컷을 원하시나요?
판단 기준: visual context의 still은 스타일(style)이 아니라 스틸 이미지/스틸컷 의미를 보존한다.

예시 6
원문: Click __ENT001__, open __ENT002__, then copy and paste the file.
좋은 한국어: __ENT001__를 클릭하고 __ENT002__를 연 다음, 파일을 복사해 붙여넣으면 됩니다.
판단 기준: __ENT###__ 토큰은 검증된 고유명사/UI 보호 토큰이며 일반 영어 단어까지 보호하는 장치가 아니다."""


def _translation_system_prompt_v035() -> str:
    return (
        "해외 영상 스크립트를 한국인이 실제로 듣는 것처럼 자연스럽고 정확한 한국어 검수 초안으로 옮기세요. "
        "가장 중요한 순서는 1) 원문 의미와 주체 보존, 2) 자연스러운 한국어, 3) 공식 고유명사 보존입니다. "
        "원문의 사실, 숫자, 가격, 기간, 조건, 순서, 행동과 행동 대상은 추가·삭제·요약하지 마세요. "
        "원문에 없는 '자동으로', 평가, 원인, 의도를 자연스럽다는 이유로 덧붙이지 마세요. "
        "REFERENCE_CONTEXT는 대명사와 지시 대상을 이해하는 용도이며 다른 구간의 사실을 TARGET에 섞지 마세요. 각 ID의 출력에는 반드시 그 ID의 SOURCE_EN에 있는 내용만 넣으세요. 인접 ID의 문장, 감탄사, 이유, 예시를 앞당겨 넣거나 뒤 행으로 넘기지 마세요. 같은 배치 안에서도 ID 경계는 절대적인 내용 경계입니다. Hold on/Wait/No/Okay처럼 반복되는 담화 표현은 UI 명령으로 해석하지 말고 말하는 기능과 반복 횟수를 보존한 자연스러운 한국어로 옮기세요. 반복 표현은 의미를 유지하는 범위에서 잠깐만요/잠시만요/기다려 보세요처럼 자연스럽게 변주할 수 있습니다. "
        "일반 튜토리얼 화법은 자연스러운 존댓말로 작성하세요. I/my는 저·제가·제 또는 자연스러운 생략, you는 여러분 또는 자연스러운 생략이 기본입니다. "
        "당신/너/네가와 설명문 반말은 쓰지 마세요. -습니다/-해요/-죠는 자연스럽게 섞어도 됩니다. "
        "직접 인용문이나 프롬프트는 인용문 자체의 캐주얼한 말투를 유지할 수 있지만, 내용은 반드시 한국어로 번역하세요. "
        "예: Just make a cool video for me. -> '그냥 멋진 영상 하나 만들어줘'. Just 같은 일반 영어 단어를 남기지 마세요. "
        "just because yeah, you know, I mean처럼 정보가 아니라 말버릇·머뭇거림에 가까운 표현은 가짜 이유나 사실을 만들어 직역하지 말고, 한국어 발화에서 자연스럽게 생략하거나 '그냥/그러니까'처럼 기능에 맞게 처리하세요. "
        "I think/I believe/I recommend 등 화자의 판단은 반드시 화자의 판단으로 남기고 도구나 시청자의 생각으로 바꾸지 마세요. "
        "A rather than B / A versus B / or / whatever 같은 대비·선택 관계를 '동시에 모두'라는 뜻으로 바꾸지 마세요. "
        "word(s)는 character/letter가 아니라면 '단어'로, visual context의 still은 '스틸 이미지/스틸컷'으로 이해하세요. "
        "click/select/open/go to/copy/paste/install/download/drag/drop 같은 구체 행동과 대상을 그대로 보존하세요. 슬래시 명령, 메뉴, picker처럼 화면 동작이 자막만으로 입력(type)인지 선택(select)인지 확실하지 않으면 임의로 동작을 단정하지 말고 원문의 literal target을 보존한 중립적인 표현을 사용하세요. "
        "__ENT###__ 토큰은 영상 근거로 검증된 브랜드·제품·도구·사람·서비스·UI 이름이므로 정확히 복사하세요. "
        "그 외 일반 영어 표현은 고유명사가 아니며 자연스러운 한국어로 번역하세요. "
        "영어 접속사를 그리고/그래서로 반복 번역하지 말고 문맥에 맞는 한국어 흐름을 만드세요. "
        "중국어·일본어 등 다른 언어 문장을 출력하지 마세요. 모든 TARGET id에 정확히 하나의 한국어 문자열을 반환하고 OUTPUT_FORMAT만 사용하세요."
    )


def _build_prompt_v035(core, reference_units, target_rows, registry, chapter_outline="", prior_korean_tail=""):
    canonical_to_placeholder, _ = _placeholder_maps_v035(registry)

    # Canonicalize likely ASR name variants in the model-facing copy only.
    context_raw = core._units_plain_text_v032(reference_units)
    context_fixed, _ = _replace_entity_variants_v035(context_raw, registry)
    context = _protect_entities_v035(context_fixed, canonical_to_placeholder)

    target_blocks = []
    for row in target_rows:
        fixed, _ = _replace_entity_variants_v035(row.get("raw_joined_text", ""), registry)
        protected = _protect_entities_v035(fixed, canonical_to_placeholder)
        target_blocks.append(f"ID: {row['utterance_id']}\nSOURCE_EN: {protected}")

    parts = ["STYLE_EXAMPLES (문구를 복사하지 말고 판단 방식만 참고):\n" + _style_examples_v035()]
    if chapter_outline:
        fixed_outline, _ = _replace_entity_variants_v035(chapter_outline, registry)
        parts.append("CHAPTER_OUTLINE (맥락 참고용):\n" + _protect_entities_v035(fixed_outline, canonical_to_placeholder))
    parts.append("REFERENCE_CONTEXT (맥락 참고용이며 출력 범위를 늘리지 마세요):\n" + context)
    if prior_korean_tail:
        protected_tail = _protect_entities_v035(prior_korean_tail, canonical_to_placeholder)
        parts.append("PRIOR_KOREAN_TAIL (존댓말 톤과 연결만 참고; 사실을 옮기지 마세요):\n" + protected_tail)
    parts.append("TARGET_ROWS:\n" + "\n\n".join(target_blocks))
    parts.append(core._marker_output_instruction_v033([row["utterance_id"] for row in target_rows]))
    return "\n\n".join(parts)



_ORDINARY_ENGLISH_LEAKS_V036 = _COMMON_ENGLISH_LEAK_WORDS_V0312


def _remove_verified_latin_spans_v0312(text: str, registry: dict[str, Any] | None) -> str:
    """Remove verified entities/URLs/code-like literals before English-leak detection."""
    out = str(text or "")
    registry = registry or {}
    for canonical in sorted(registry.get("canonicals", []), key=len, reverse=True):
        if not _entity_is_output_verified_v0312(canonical, registry):
            continue
        out = re.sub(rf"(?<![A-Za-z0-9]){re.escape(canonical)}(?![A-Za-z0-9])", " ", out, flags=re.IGNORECASE)
    # URLs/domains, file-like names, slash commands and code-ish tokens are allowed to remain Latin.
    out = re.sub(r"https?://\S+|www\.\S+|(?<![A-Za-z0-9])(?:[A-Za-z0-9_-]+\.)+(?:com|ai|io|dev|app|net|org)(?:/[A-Za-z0-9_./?=&%-]*)?", " ", out, flags=re.I)
    out = re.sub(r"(?<!\w)/[A-Za-z0-9_./-]+", " ", out)
    out = re.sub(r"\{slash\}\s*[^,.!?\n]{1,80}", " ", out, flags=re.I)
    return out


def _ordinary_english_leaks_v0312(output: str, registry: dict[str, Any] | None = None) -> list[str]:
    plain = _remove_verified_latin_spans_v0312(output, registry)
    leaked = []
    # Do not use \b: Unicode word boundaries treat Korean letters as word chars, which
    # previously missed forms such as "Like가". ASCII-only lookarounds catch them.
    for m in re.finditer(r"(?<![A-Za-z])([A-Za-z]+(?:'[A-Za-z]+)?)(?![A-Za-z])", plain):
        token = m.group(1)
        if token.lower().replace("'", "") in _COMMON_ENGLISH_LEAK_WORDS_V0312:
            leaked.append(token)
    return sorted(set(leaked), key=str.lower)



_ALLOWED_LATIN_TERMS_V0312 = {
    "AI", "API", "URL", "UI", "UX", "GPU", "CPU", "RAM", "MCP", "IDE", "MD",
    "LLM", "ROI", "MP4", "B-roll", "B-rolls", "K-drama",
}


def _remove_exact_source_literals_v0312(source: str, output: str) -> str:
    """Allow exact source literals only when the Korean output visibly marks them as literals.

    This prevents `While`, `Some`, `Full` from slipping through merely because those words
    exist in the English source, while still allowing forms such as
    미리보기 실행(launch preview) or 'switch model' when the literal is intentionally shown.
    """
    src_low = re.sub(r"\s+", " ", str(source or "")).lower()
    out = str(output or "")

    spans = []
    spans += re.findall(r"\(([^()\n]{1,120})\)", out)
    spans += re.findall(r"'([^'\n]{1,120})'", out)
    spans += re.findall(r'"([^"\n]{1,120})"', out)
    spans += re.findall(r"“([^”\n]{1,120})”", out)
    spans += re.findall(r"‘([^’\n]{1,120})’", out)
    for span in spans:
        latin = " ".join(re.findall(r"[A-Za-z][A-Za-z0-9_.+#/-]*", span))
        if not latin:
            continue
        if re.sub(r"\s+", " ", latin).lower() in src_low:
            out = out.replace(span, " ")

    # Literal folder/file/UI labels can legitimately stay Latin even without quotes.
    literal_tokens = []
    for m in re.finditer(
        r"\b([A-Za-z][A-Za-z0-9_-]{1,30})\s+(?:folder|file|section|project|button|menu|tab)\b",
        str(source or ""),
        re.I,
    ):
        literal_tokens.append(m.group(1))
    for m in re.finditer(
        r"\b(?:called|named)\s+([A-Za-z][A-Za-z0-9_-]*(?:\s+[A-Za-z][A-Za-z0-9_-]*){0,2})",
        str(source or ""),
        re.I,
    ):
        literal_tokens.append(m.group(1))
    for literal in literal_tokens:
        out = re.sub(rf"(?<![A-Za-z0-9]){re.escape(literal)}(?![A-Za-z0-9])", " ", out, flags=re.I)

    # Short action targets such as "switch model" / "launch preview" may be actual UI
    # literals.  They are allowed to remain Latin, while a separate visual-action warning
    # prevents the pipeline from silently inventing whether the creator typed/clicked it.
    for m in re.finditer(
        r"\b(?:type|enter|click|select|choose|pick|say)\s+([A-Za-z][A-Za-z0-9_-]*(?:\s+[A-Za-z][A-Za-z0-9_-]*){0,2})",
        str(source or ""),
        re.I,
    ):
        phrase = _clean_entity(m.group(1))
        toks = [t.lower() for t in _entity_tokens(phrase)]
        if not toks or any(t in {"i", "it", "this", "that", "you", "we", "he", "she", "they"} for t in toks):
            continue
        out = re.sub(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])", " ", out, flags=re.I)
    return out


def _unexpected_latin_tokens_v0312(
    source: str,
    output: str,
    registry: dict[str, Any] | None = None,
) -> list[str]:
    # Remove source-proven literal UI/command spans before stripping verified entities.
    # Otherwise a verified token inside a multi-word literal (e.g. MCP in "MCP servers")
    # can be removed first and leave the ordinary-looking tail behind as a false leak.
    plain = _remove_exact_source_literals_v0312(source, output)
    plain = _remove_verified_latin_spans_v0312(plain, registry)

    # Stable technical abbreviations/industry literals may remain Latin.
    for term in sorted(_ALLOWED_LATIN_TERMS_V0312, key=len, reverse=True):
        plain = re.sub(
            rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])",
            " ",
            plain,
            flags=re.I,
        )

    leaked = []
    for m in re.finditer(r"(?<![A-Za-z])([A-Za-z][A-Za-z0-9_.+#/-]*)(?![A-Za-z])", plain):
        token = m.group(1).strip(".,")
        if not token:
            continue
        # Single Roman letters in formulas/labels are too ambiguous to reject globally.
        if len(token) == 1:
            continue
        if token.lower() in {"b-", "b–", "b—"} and re.match(r"롤", plain[m.end():]):
            continue
        # Numeric/file-like forms were already removed, but keep this defensive.
        if re.fullmatch(r"[A-Z]{2,5}\d*", token):
            continue
        leaked.append(token)
    return list(dict.fromkeys(leaked))


def _required_entity_issues_v0312(
    source: str,
    output: str,
    registry: dict[str, Any] | None = None,
) -> list[str]:
    """Require exact official spelling for strong atomic entities present in source.

    The source passed here is the raw ASR row. `_replace_entity_variants_v035` applies both
    the video audit and deterministic registry repairs to a temporary copy, allowing us to
    judge the intended canonical name without ever mutating provenance.
    """
    registry = registry or {}
    fixed, _ = _replace_entity_variants_v035(source, registry)
    # Domains/URLs/commands are literal spans, not evidence that an embedded token must
    # appear as a separately-cased brand in Korean prose (claude.ai must not require Claude + AI).
    fixed, _literal_map_for_entity_gate = _shield_literal_spans_v0312(fixed)
    issues = []
    for canonical in sorted(set(registry.get("canonicals", []) or []), key=len, reverse=True):
        if not _entity_is_output_verified_v0312(canonical, registry):
            continue
        if canonical.upper() in _ALLOWED_LATIN_TERMS_V0312 and len(_entity_tokens(canonical)) == 1:
            continue
        toks = _entity_tokens(canonical)
        if not toks or len(toks) > 2:
            continue
        if canonical.lower() in _ENTITY_GENERIC:
            continue
        if not re.search(rf"(?<![A-Za-z0-9]){re.escape(canonical)}(?![A-Za-z0-9])", fixed, re.I):
            continue

        if canonical in output:
            continue
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(canonical)}(?![A-Za-z0-9])", output, re.I):
            issues.append(f"공식 고유명사 대소문자/표기 오류: {canonical}")
        else:
            issues.append(f"공식 고유명사 누락 또는 변형: {canonical}")
    return issues


def _semantic_relation_issues_v0312(source: str, output: str) -> list[str]:
    src = str(source or "")
    out = str(output or "")
    sl = src.lower()
    issues = []

    # High-value deterministic relations that have repeatedly caused role reversal.
    if re.search(r"\bfor me\b", sl):
        if not re.search(r"저\s*대신|제\s*대신|저를\s*위해|저에게|제게|저한테|저를\s*대신|해\s*주|해주", out):
            issues.append("for me 관계 누락 또는 행위 주체 역전 가능성")

    # A filler such as "just because yeah" has no real causal proposition. Translating
    # it as a literal '왜냐하면 ... 때문' fabricates a reason.
    if re.search(r"\bjust\s+because\s+(?:yeah|yes|you know|whatever)\b", sl):
        if re.search(r"왜냐하면|때문", out):
            issues.append("비의미적 말버릇을 실제 인과관계로 직역")

    return issues


def _source_asr_review_warnings_v0312(source: str, registry: dict[str, Any] | None = None) -> list[str]:
    """Flag unresolved ASR-like proper-name phrases instead of silently guessing.

    First apply every accepted video-level/deterministic entity repair to a temporary source
    copy. Any suspicious titlecase+lowercase phrase that remains unresolved is review-worthy.
    This catches future unknown brands without a chapter-specific word list.
    """
    registry = registry or {}
    fixed, _ = _replace_entity_variants_v035(source, registry)
    canonicals = [c for c in (registry.get("canonicals", []) or []) if _entity_is_output_verified_v0312(c, registry)]
    canon_low = {c.lower() for c in canonicals}
    warnings: list[str] = []

    for token in re.findall(r"(?<![A-Za-z0-9])([A-Z]{2,4})(?![A-Za-z0-9])", str(fixed or "")):
        if token.lower() in canon_low:
            continue
        if token in {"AI", "API", "URL", "UI", "UX", "GPU", "CPU", "RAM", "MCP", "IDE", "MD", "LLM", "ROI", "MP4"}:
            continue
        warnings.append(f"확인 필요한 짧은 대문자 ASR 토큰: {token}")

    for m in re.finditer(
        r"(?<![A-Za-z0-9])([A-Z][A-Za-z'-]{2,}(?:\s+[a-z][A-Za-z'-]{2,}){1,2})(?![A-Za-z0-9])",
        str(fixed or ""),
    ):
        phrase = _clean_entity(m.group(1))
        toks = _entity_tokens(phrase)
        if not toks:
            continue
        first_low = toks[0].lower()
        if first_low in _ENTITY_STOPWORDS or first_low in _COMMON_ENGLISH_LEAK_WORDS_V0312:
            continue
        if any(t.lower() in _ENTITY_STOPWORDS for t in toks[1:]):
            continue
        # A phrase beginning with an already verified canonical is generally ordinary
        # description after the name (e.g. HyperFrames preview), not an unresolved brand.
        if any(first_low == _entity_tokens(c)[0].lower() for c in canonicals if _entity_tokens(c)):
            continue
        warnings.append(f"고유명사/제품명 ASR 오기 가능성: '{phrase}' (자동 확정 근거 부족)")

    # A badly heard brand root may remain immediately before a correctly restored product
    # name (e.g. UNKNOWN HyperFrames). That mixed phrase must never pass clean merely because
    # the trailing product token is verified.
    for canonical in canonicals:
        ctoks = _entity_tokens(canonical)
        if not ctoks:
            continue
        first_can = ctoks[0]
        for m in re.finditer(
            rf"(?<![A-Za-z0-9])([A-Z][a-z]{{2,}})\s+{re.escape(first_can)}(?![A-Za-z0-9])",
            str(fixed or ""),
        ):
            unknown = m.group(1)
            low = unknown.lower()
            if low in _ENTITY_STOPWORDS or low in _COMMON_ENGLISH_LEAK_WORDS_V0312:
                continue
            if any(low == t.lower() for c in canonicals for t in _entity_tokens(c)):
                continue
            warnings.append(
                f"고유명사/브랜드 관계 ASR 오기 가능성: '{unknown} {first_can}' (앞 이름 자동 확정 근거 부족)"
            )

    return list(dict.fromkeys(warnings))
def _source_action_review_warnings_v0312(source: str) -> list[str]:
    """Flag UI/command actions whose exact interaction cannot be resolved from captions alone."""
    src = str(source or "")
    warnings = []
    if re.search(r"\{slash\}|\bslash\s+command\b|(?<!\w)/[A-Za-z0-9_-]+", src, re.I):
        if re.search(r"\b(?:type|click|select|switch|choose|pick|open)\b", src, re.I):
            warnings.append(
                "화면 검증 권장: 슬래시 명령/메뉴 동작은 자막만으로 입력·선택·클릭을 정확히 구분하기 어려울 수 있음"
            )

    # Explicit interaction verbs are strong enough to warrant a visual warning.
    # "say" is special: ordinary speech such as "I would say two to three minutes"
    # must NOT be mistaken for a UI action, while "say launch preview over here" may
    # actually be a typed command/label in a screen demo.
    for m in re.finditer(
        r"\b(type|enter|click|select|choose|pick)\s+([A-Za-z][A-Za-z0-9_-]*(?:\s+[A-Za-z][A-Za-z0-9_-]*){0,3})",
        src,
        re.I,
    ):
        phrase = _clean_entity(m.group(2))
        toks = [t.lower() for t in _entity_tokens(phrase)]
        if toks and not any(t in {"i", "it", "this", "that", "you", "we", "he", "she", "they"} for t in toks):
            warnings.append(
                f"화면 검증 권장: '{phrase}'가 실제 입력 문구/버튼/메뉴인지 자막만으로 확정하기 어려움"
            )
            break

    say_action_tokens = {
        "launch", "preview", "run", "render", "edit", "create", "start", "stop",
        "open", "model", "server", "servers", "mode", "export", "generate", "build",
    }
    for m in re.finditer(
        r"\bsay\s+([A-Za-z][A-Za-z0-9_-]*(?:\s+[A-Za-z][A-Za-z0-9_-]*){0,3})",
        src,
        re.I,
    ):
        phrase = _clean_entity(m.group(1))
        toks = [t.lower() for t in _entity_tokens(phrase)]
        # Trim conjunctions/continuations captured after a short literal target.
        cut_at = next((i for i, t in enumerate(toks) if t in {"and", "then", "so", "but", "because", "that", "if", "when"}), None)
        if cut_at is not None:
            toks = toks[:cut_at]
        if not toks:
            continue
        if any(t in {"i", "it", "this", "that", "you", "we", "he", "she", "they"} for t in toks):
            continue
        # Ordinary estimates/opinions ("I would say two to three minutes") are speech,
        # not UI actions.  Require an action-ish target or a nearby screen-location cue.
        near = src[m.start(): min(len(src), m.end() + 40)].lower()
        if not (any(t in say_action_tokens for t in toks) or re.search(r"\b(?:over|right)\s+here\b", near)):
            continue
        clean_phrase = " ".join(toks)
        warnings.append(
            f"화면 검증 권장: '{clean_phrase}'가 실제 입력 문구/버튼/메뉴인지 자막만으로 확정하기 어려움"
        )
        break
    return list(dict.fromkeys(warnings))


def _split_sentences_v0312(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。！？])\s+|(?<=요\.)\s+|(?<=니다\.)\s+", str(text or "").strip())
    return [p.strip() for p in parts if p and p.strip()]


def _norm_overlap_v0312(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", str(text or "").lower())


def _adjacent_leak_suspects_v0312(expected: list[str], source_by_id: dict[str, str], output_map: dict[str, str]) -> tuple[set[str], list[dict[str, str]]]:
    """Detect likely content bleed across adjacent marker rows.

    The check is deliberately narrow: it only fires when adjacent Korean rows repeat a
    whole sentence/clause much more strongly than their adjacent English sources do.
    Suspicious rows are retried with row-only source, so normal rows pay no extra cost.
    """
    suspects: set[str] = set()
    records: list[dict[str, str]] = []
    for a, b in zip(expected, expected[1:]):
        ao, bo = _split_sentences_v0312(output_map.get(a, "")), _split_sentences_v0312(output_map.get(b, ""))
        if not ao or not bo:
            continue
        left, right = ao[-1], bo[0]
        ln, rn = _norm_overlap_v0312(left), _norm_overlap_v0312(right)
        if not ln or not rn:
            continue
        out_ratio = difflib.SequenceMatcher(None, ln, rn).ratio()
        src_a, src_b = _split_sentences_v0312(source_by_id.get(a, "")), _split_sentences_v0312(source_by_id.get(b, ""))
        sa = _norm_overlap_v0312(src_a[-1] if src_a else source_by_id.get(a, ""))
        sb = _norm_overlap_v0312(src_b[0] if src_b else source_by_id.get(b, ""))
        src_ratio = difflib.SequenceMatcher(None, sa, sb).ratio() if sa and sb else 0.0

        repeated_short = False
        if len(ln) <= 12 and ln == rn:
            repeated_short = sum(1 for x in ao if _norm_overlap_v0312(x) == ln) >= 2
        strong_clause = min(len(ln), len(rn)) >= 18 and out_ratio >= 0.76
        if (repeated_short or strong_clause) and src_ratio < 0.60:
            suspects.update({a, b} if strong_clause else {b})
            records.append({
                "left_id": a, "right_id": b,
                "left_korean": left, "right_korean": right,
                "output_similarity": f"{out_ratio:.3f}", "source_similarity": f"{src_ratio:.3f}",
            })
    return suspects, records


def _quality_issues_v036(source: str, output: str, registry: dict[str, Any] | None = None) -> list[str]:
    src = str(source or "")
    out = str(output or "")
    sl = src.lower()
    issues = []

    leaked = _ordinary_english_leaks_v0312(out, registry)
    if leaked:
        issues.append("일반 영어 미번역: " + ", ".join(leaked))

    if "자동" in out and not re.search(r"\bautomatic(?:ally)?\b|\bauto(?:matic)?\b", sl):
        issues.append("원문에 없는 자동화 의미 추가")
    if "원하는 대로" in out and not re.search(r"\b(?:as|the way)\s+i\s+want\b|\bwhat\s+i\s+want\b", sl):
        issues.append("원문에 없는 '원하는 대로' 의미 추가")
    if re.search(r"\bwords?\b", sl) and "글자" in out:
        issues.append("word를 글자로 오역")
    if re.search(r"\banimation\s+still\b|\bstill\s+(?:image|frame)\b", sl) and "애니메이션 스타일" in out:
        issues.append("still을 style로 오역")
    if re.search(r"\bi\s+(?:think|believe)\b", sl) and not re.search(r"저는|제가|제\s*생각|생각(?:해|합|했|하)|봅니다|보는", out):
        issues.append("화자의 판단(I think/I believe) 누락 또는 주체 불명확")
    if re.search(r"\bi\s+recommend\b", sl) and "추천" not in out:
        issues.append("화자의 추천 판단 누락")
    if "whatever you call yourself" in sl and "이자" in out:
        issues.append("대안 직책을 동시에 가진다는 의미로 변형")
    if "learning" in sl and not re.search(r"배우|학습|익히|알아보", out):
        issues.append("learning 의미 누락")
    if re.search(r"\bdirecting\b|\bguiding\b", sl) and not re.search(r"디렉|가이드|지시|이끌|안내|방향", out):
        issues.append("directing/guiding 의미 누락")
    if re.search(r"\bshort[- ]form\b", sl) and re.search(r"단편\s*영상|짧은\s*영상", out):
        issues.append("short form을 업계 맥락의 숏폼이 아닌 어색한 순화어로 번역")
    if re.search(r"\blong[- ]form\b", sl) and re.search(r"장형\s*영상|긴\s*영상", out):
        issues.append("long form을 업계 맥락의 롱폼이 아닌 어색한 순화어로 번역")
    if re.search(r"\bAI\s+avatar\b", src, re.I) and re.search(r"AI\s+avatar", out, re.I):
        issues.append("일반 용어 AI avatar를 한국어로 자연스럽게 옮기지 않음")
    if re.search(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9._-]*\s+Code\s+Code(?![A-Za-z0-9])", out):
        issues.append("고유명사 복원 중 Code 중복")
    if re.search(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9._-]*\s+Code\s+코드(?=[을를이가은는에의와과로으로,.!?\s]|$)", out):
        issues.append("공식명 뒤 Code/코드 중복")
    return issues

def _quality_issues_v0312(source: str, output: str, registry: dict[str, Any] | None = None) -> list[str]:
    issues = list(_quality_issues_v036(source, output, registry))

    unexpected = _unexpected_latin_tokens_v0312(source, output, registry)
    if unexpected:
        issues.append("허용되지 않은 일반 영어 잔존: " + ", ".join(unexpected))

    issues.extend(_required_entity_issues_v0312(source, output, registry))
    issues.extend(_semantic_relation_issues_v0312(source, output))

    return list(dict.fromkeys(issues))


def _retry_prompt_v035(core, rows, bad_map, registry, reasons):
    canonical_to_placeholder, _ = _placeholder_maps_v035(registry)
    blocks = []
    for row in rows:
        fixed, _ = _replace_entity_variants_v035(row.get("raw_joined_text", ""), registry)
        source = _protect_entities_v035(fixed, canonical_to_placeholder)
        bad = _protect_entities_v035(bad_map.get(row["utterance_id"], ""), canonical_to_placeholder)
        blocks.append(
            f"ID: {row['utterance_id']}\nSOURCE_EN: {source}\nBAD_KO: {bad}\nISSUE: {reasons.get(row['utterance_id'], 'quality_or_register')}"
        )
    return (
        "SOURCE_EN과 BAD_KO를 대조해 필요한 부분만 고쳐 자연스러운 한국어로 다시 작성하세요. "
        "원문의 절과 의미 주체를 빠뜨리지 말고, 새 정보도 넣지 마세요. "
        "직접 인용문도 내용은 한국어로 번역하며 인용문의 말투만 캐주얼하게 둘 수 있습니다. "
        "I think/I believe/I recommend는 화자의 판단으로 명시하세요. word는 단어이며, visual context의 still은 스틸 이미지/스틸컷입니다. "
        "원문에 automatic/automatically가 없으면 '자동으로'를 추가하지 마세요. "
        "just because yeah 같은 비의미적 말버릇을 가짜 인과관계로 직역하지 마세요. "
        "일반 튜토리얼 문장은 자연스러운 존댓말로 유지하고 __ENT###__ 토큰은 정확히 복사하세요. 보호된 entity/URL/명령 literal 외의 일반 영어는 남기지 마세요.\n\n"
        + "\n\n".join(blocks)
        + "\n\n"
        + core._marker_output_instruction_v033([row["utterance_id"] for row in rows])
    )



def _row_only_retry_prompt_v0312(core, row: dict[str, Any], bad_text: str, registry: dict[str, Any], reason: str) -> str:
    """Retry one marker row without neighbor/reference content to stop cross-row bleed."""
    canonical_to_placeholder, _ = _placeholder_maps_v035(registry)
    fixed, _ = _replace_entity_variants_v035(row.get("raw_joined_text", ""), registry)
    source = _protect_entities_v035(fixed, canonical_to_placeholder)
    bad = _protect_entities_v035(bad_text, canonical_to_placeholder)
    uid = row["utterance_id"]
    return (
        "이 재편집은 인접 행 내용 혼입을 제거하기 위한 ROW-ONLY 검수입니다. "
        "오직 아래 SOURCE_EN 한 행만 번역 근거로 사용하세요. 앞뒤 행의 문장, 감탄사, 이유, 예시, 결론을 절대 추가하지 마세요. "
        "SOURCE_EN의 반복 표현은 발화 기능과 반복 횟수를 유지해 자연스러운 한국어로 옮기고, UI/버튼 의미로 임의 해석하지 마세요. "
        "고유명사·URL·명령 literal은 그대로 보존하고 일반 영어는 자연스러운 한국어로 번역하세요. "
        "원문에 없는 정보 추가·요약·누락 없이 존댓말 튜토리얼 문장으로 작성하세요.\n\n"
        f"ID: {uid}\nSOURCE_EN: {source}\nBAD_KO: {bad}\nISSUE: {reason}\n\n"
        + core._marker_output_instruction_v033([uid])
    )



_EDITORIAL_SUBBATCH_SIZE_V0312 = 6
_LAST_STAGE_SNAPSHOTS_V0312: dict[str, dict[str, Any]] = {}


def _editorial_examples_v0312() -> str:
    """Compact, generalizable editorial decisions. Kept short because this is repeated per subbatch."""
    return """예시 1
원문: Because I am sharing the process with you, you will not spend as much time.
초안: 여러분은 훨씬 적은 시간만 소요할 겁니다.
좋은 편집: 제가 과정을 공유하고 있으니, 여러분은 그만큼 시간을 아낄 수 있습니다.
원칙: 의미는 그대로 두고 영어식 결합을 자연스러운 한국어로 바꾼다.

예시 2
원문: If you specifically say, \"I want this style rather than that style,\" I think that's important.
좋은 편집: '저 스타일보다 이 스타일을 원해'라고 구체적으로 말하는 것이 중요합니다. 저는 이렇게 방향을 명확히 알려주는 것이 중요하다고 생각해요.
원칙: 인용된 지시와 화자의 판단 주체를 분리해 보존한다.

예시 3
원문: The result goes into the output folder, and the tool does the editing for me.
좋은 편집: 결과는 출력 폴더로 들어가고, 도구가 저 대신 편집을 해줍니다.
원칙: 원문에 없는 '자동으로/원하는 대로'를 추가하지 않고 for me 같은 행위 관계는 보존한다.

예시 4
원문: I repurpose long form into short form. Alex shows only two words at a time.
좋은 편집: 롱폼을 숏폼으로 재가공합니다. Alex의 경우 한 번에 두 단어씩만 보여주는 방식을 사용합니다.
원칙: 실제 업계 용어를 쓰고, Latin 고유명사 뒤 조사가 어색하면 문장 구조를 바꾼다.

예시 5
원문: Have the tool read what you're talking about. In the worst case, cut that section.
좋은 편집: 도구가 전달하려는 의도를 제대로 파악하도록 구체적으로 설명하세요. 최악의 경우에는 그 부분을 잘라내야 할 수도 있습니다.
원칙: 다의어와 일반 영어 표현은 실제 문맥의 의미로 번역한다.

예시 6
원문: Hold on. Hold on. / Anyways, let's continue. / Again, this is only an example.
좋은 편집의 방향: 제품명이나 UI가 아닌 담화 표현은 문맥에 맞는 자연스러운 한국어로 옮긴다.
원칙: 문장 첫 단어가 대문자라는 이유만으로 영어를 고유명사처럼 남기지 않는다.

예시 7
원문: While __ENT001__ is doing the job, I'm going to eat some chocolate just because yeah.
좋은 편집: __ENT001__가 작업하는 동안, 저는 그냥 초콜릿을 먹으면서 기다릴게요.
원칙: while의 동시 관계는 보존하되, just because yeah처럼 실제 이유가 없는 말버릇을 '왜냐하면'으로 꾸며내지 않는다."""


def _editorial_system_prompt_v0312() -> str:
    return (
        "당신은 한국어 영상 스크립트를 실제 배포 직전까지 다듬는 전문 에디터입니다. "
        "SOURCE_EN과 FIRST_KO를 반드시 함께 대조하세요. FIRST_KO를 단순 교정하는 것이 아니라, 원문 의미를 그대로 유지한 채 한국인이 실제 튜토리얼 영상에서 자연스럽게 말할 문장으로 적극적으로 편집하세요. 각 ID는 독립적인 내용 경계입니다. 다른 ID의 문장이나 정보를 현재 ID로 옮기거나 중복시키지 마세요. SOURCE_EN에 없는 앞뒤 행의 감탄사·이유·결론을 추가하지 마세요. 반복되는 담화 표현은 버튼명이나 UI 조작으로 오해하지 말고 발화 기능과 반복 횟수를 자연스럽게 살리세요. "
        "'최소 수정'이 목표가 아닙니다. 번역투, 어색한 조사, 영어식 주어 반복, 부자연스러운 명사형, 직역된 다의어, 업계에서 쓰지 않는 표현이 있으면 반드시 고치세요. "
        "단, 정확성이 최우선입니다. 원문의 사실, 숫자, 가격, 기간, 조건, 순서, 행동, 행동 대상, 화자/청자/도구의 역할은 추가·삭제·요약·재해석하지 마세요. "
        "원문에 없는 자동성, 의도, 평가, 원인, 결과를 자연스럽다는 이유로 덧붙이지 마세요. for me / for you / by X 같은 행위 관계도 생략하지 마세요. "
        "I think/I believe/I recommend는 화자의 판단으로 유지하세요. you는 일반 설명에서 여러분 또는 자연스럽게 생략하고, 당신/너/네가를 사용하지 마세요. "
        "일반 튜토리얼은 자연스러운 존댓말을 사용하세요. -습니다/-해요/-죠는 흐름에 맞게 섞어도 되지만 설명문이 갑자기 반말로 내려가면 안 됩니다. 직접 인용문·프롬프트만 원래의 캐주얼한 말투를 유지할 수 있습니다. "
        "보호된 __ENT###__, URL, 실제 명령어·UI 문자열을 제외한 일반 영어는 한국어로 번역하세요. Hold on, Anyways, Again, Like, Just 같은 담화 표현은 문장 첫 단어가 대문자여도 고유명사가 아닙니다. "
        "한국 실무에서 이미 굳어진 용어는 실제 업계 표현을 우선하세요. 예: short form/long form은 문맥상 숏폼/롱폼, motion graphics는 모션 그래픽, sound effects는 사운드 효과. 단, 'shorts'처럼 댓글에 입력할 문자열이나 'long form'처럼 called/named로 명시된 폴더·프로젝트·명령 이름은 원문 literal을 유지하세요. "
        "word는 단어, character/letter는 글자이며, visual context의 still은 스틸 이미지/스틸컷입니다. "
        "브랜드·제품·모델·도구·사람·서비스·UI/파일명으로 보호된 __ENT###__ 토큰은 절대 번역하거나 변형하지 말고 그대로 복사하세요. "
        "Latin 고유명사 뒤 조사가 어색하면 이름을 한글로 바꾸지 말고 '이름의 경우', '도구인 이름은'처럼 한국어 문장 구조를 재구성하세요. "
        "read/see/get/make/run/work 같은 다의어는 표면 단어가 아니라 실제 동작과 대상 관계를 보고 번역하세요. "
        "just because yeah, you know, I mean처럼 정보가 아닌 말버릇은 '왜냐하면 ... 때문' 같은 거짓 인과관계로 만들지 말고 자연스러운 한국어 발화 기능으로 처리하세요. "
        "SOURCE_EN에 있는 브랜드/제품명이 ASR 오기로 복원되어 __ENT###__로 보호되었다면 정확한 Latin 표기를 반드시 유지하세요. 보호되지 않은 While/Some/Full 같은 일반 영어가 한국어 문장에 남아 있으면 실패입니다. "
        "FIRST_KO가 문법적으로 맞더라도 한국인이 실제로 잘 쓰지 않는 표현이면 그대로 통과시키지 마세요. 반대로 이미 정확하고 자연스러운 문장은 불필요하게 의미를 바꾸지 마세요. "
        "중국어·일본어를 출력하지 마세요. 각 ID에 정확히 하나의 최종 한국어 문자열만 OUTPUT_FORMAT으로 반환하세요."
    )


def _editorial_context_units_v0312(reference_units, target_rows, window_seconds=75.0, max_chars=3500):
    if not reference_units or not target_rows:
        return list(reference_units or [])
    starts = [float(r.get("start_seconds", 0) or 0) for r in target_rows]
    ends = [float(r.get("end_seconds", r.get("start_seconds", 0)) or 0) for r in target_rows]
    lo = min(starts) - window_seconds
    hi = max(ends) + window_seconds
    selected = [
        u for u in reference_units
        if float(u.get("end_seconds", u.get("start_seconds", 0)) or 0) >= lo
        and float(u.get("start_seconds", 0) or 0) <= hi
    ]
    if not selected:
        return list(reference_units[:12])
    # Keep the context focused.  The second pass already has SOURCE_EN for each row;
    # this context exists only for pronouns and local continuity.
    out, chars = [], 0
    for u in selected:
        size = len(str(u.get("raw_text", ""))) + 1
        if out and chars + size > max_chars:
            break
        out.append(u); chars += size
    return out


def _editorial_subbatches_v0312(rows, size=_EDITORIAL_SUBBATCH_SIZE_V0312):
    rows = list(rows or [])
    return [rows[i:i + size] for i in range(0, len(rows), size)]


def _build_editorial_prompt_v0312(core, reference_units, target_rows, first_map, registry, chapter_outline="", prior_korean_tail=""):
    canonical_to_placeholder, _ = _placeholder_maps_v035(registry)
    local_units = _editorial_context_units_v0312(reference_units, target_rows)
    context_raw = core._units_plain_text_v032(local_units)
    context_fixed, _ = _replace_entity_variants_v035(context_raw, registry)
    context = _protect_entities_v035(context_fixed, canonical_to_placeholder)

    blocks = []
    for row in target_rows:
        uid = row["utterance_id"]
        fixed, _ = _replace_entity_variants_v035(row.get("raw_joined_text", ""), registry)
        source = _protect_entities_v035(fixed, canonical_to_placeholder)
        first = _protect_entities_v035(first_map.get(uid, ""), canonical_to_placeholder)
        blocks.append(f"ID: {uid}\nSOURCE_EN: {source}\nFIRST_KO: {first}")

    parts = ["EDITORIAL_EXAMPLES (문구를 복사하지 말고 편집 판단만 참고):\n" + _editorial_examples_v0312()]
    if chapter_outline:
        fixed_outline, _ = _replace_entity_variants_v035(chapter_outline, registry)
        parts.append("CHAPTER_OUTLINE (주제 확인용):\n" + _protect_entities_v035(fixed_outline, canonical_to_placeholder))
    parts.append("LOCAL_REFERENCE_CONTEXT (대명사·지시 대상·앞뒤 흐름 확인용):\n" + context)
    if prior_korean_tail:
        parts.append("PRIOR_FINAL_KOREAN (존댓말 톤과 연결만 참고):\n" + _protect_entities_v035(prior_korean_tail, canonical_to_placeholder))
    parts.append("ROWS_TO_EDIT:\n" + "\n\n".join(blocks))
    parts.append(core._marker_output_instruction_v033([row["utterance_id"] for row in target_rows]))
    return "\n\n".join(parts)


def _row_entities_for_language_rescue_v03121(source: str, registry: dict[str, Any]) -> list[str]:
    """Only names actually evidenced in this source row are shown in the emergency prompt."""
    source_low = str(source or "").lower()
    found = []
    for canonical in sorted((registry or {}).get("canonicals", []) or [], key=len, reverse=True):
        if not _entity_is_output_verified_v0312(canonical, registry):
            continue
        if canonical.lower() in source_low and canonical not in found:
            found.append(canonical)
    return found[:16]


def _language_rescue_prompt_v03121(core, row: dict[str, Any], registry: dict[str, Any], attempt: int = 1) -> str:
    """Minimal prompt used only when the normal pass emits Chinese/Japanese Han characters.

    Deliberately excludes whole-video context and previous bad Korean/Chinese drafts so the model
    cannot continue a contaminated generation pattern.  This restores the old safe-baseline idea:
    retry a bad first-pass row with a short Korean-only instruction before doing anything else.
    """
    uid = str(row.get("utterance_id", ""))
    source = str(row.get("raw_joined_text", ""))
    source_fixed, _ = _replace_entity_variants_v035(source, registry)
    entities = _row_entities_for_language_rescue_v03121(source_fixed, registry)
    entity_line = ", ".join(entities) if entities else "(없음)"
    extra = "" if attempt == 1 else "\n이전 재시도도 실패했습니다. 중국어·일본어 한자를 단 한 글자도 출력하지 마세요."
    return f"""다음 영어 원문 한 행만 자연스러운 한국어로 번역하세요.{extra}

절대 규칙:
- 한국어 문장만 작성합니다. 한국어 문장에 중국어·일본어 표기 문자를 섞지 않습니다.
- 브랜드·제품·모델·도구·사람 이름은 아래 확인된 공식 Latin 표기만 그대로 유지합니다.
- 숫자, 조건, 비용, 시간, 행동 주체와 대상 관계를 빠뜨리거나 추가하지 않습니다.
- 일반 영어 표현은 한국어로 번역합니다.
- 요약하거나 설명을 덧붙이지 않습니다.
- 출력은 지정된 marker 한 줄뿐입니다.

확인된 공식명: {entity_line}
SOURCE_EN:
{source_fixed}

{core._marker_output_instruction_v033([uid])}"""


def _split_rescue_pieces_v03122(source: str) -> list[str]:
    """Split only for emergency language recovery; normal translation grouping is untouched."""
    source = re.sub(r"\s+", " ", str(source or "")).strip()
    if not source:
        return []
    pieces = [p.strip() for p in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", source) if p.strip()]
    if len(pieces) <= 1 and len(source) > 180:
        pieces = [p.strip() for p in re.split(r"(?<=[,;:])\s+(?=(?:and|but|so|because|while|then|I|you|we|they|it|Claude|[A-Z]))", source) if p.strip()]
    return pieces or [source]


def _language_rescue_piece_prompt_v03122(core, piece_id: str, source_piece: str, entities: list[str], attempt: int = 1) -> str:
    extra = "" if attempt == 1 else "\n앞선 시도는 사용할 수 없었습니다. 이번에는 자연스러운 한국어 문장만 작성하세요."
    entity_line = ", ".join(entities) if entities else "(없음)"
    return f"""아래 영어 문장 하나를 자연스럽고 정확한 한국어로 번역하세요.{extra}

규칙:
- 한국어 문장만 작성합니다. 다른 언어의 표기 문자를 섞지 않습니다.
- 확인된 공식명은 Latin 표기를 그대로 유지합니다.
- 숫자, 조건, 비용, 시간, 행동 주체와 대상을 보존합니다.
- 일반 영어 표현은 자연스러운 한국어로 옮깁니다.
- 요약, 설명 추가, 의미 추측을 하지 않습니다.
- 지정된 marker 한 줄만 출력합니다.

확인된 공식명: {entity_line}
SOURCE_EN:
{source_piece}

{core._marker_output_instruction_v033([piece_id])}"""


def _translate_rescue_piece_v03122(core, model_name: str, piece_id: str, source_piece: str, registry: dict[str, Any], attempts: int = 2):
    source_fixed, _ = _replace_entity_variants_v035(source_piece, registry)
    entities = _row_entities_for_language_rescue_v03121(source_fixed, registry)
    last_reason = "unknown"
    for attempt in range(1, attempts + 1):
        text = core._generate_local_llm_text_v033(
            model_name,
            "영문 문장을 의미 손실 없이 자연스러운 한국어로 번역하세요. 결과에는 한국어와 확인된 공식 Latin 이름만 사용하세요.",
            _language_rescue_piece_prompt_v03122(core, piece_id, source_fixed, entities, attempt),
            max_tokens=max(320, min(900, int(len(source_fixed) * 2.0) + 180)),
        )
        parsed, _ = core._parse_translation_text_v033(text, [piece_id])
        candidate = parsed.get(piece_id)
        if not candidate:
            last_reason = "missing_marker"
            continue
        candidate = core._apply_source_conditioned_term_normalization_v0332(
            source_fixed,
            core._canonicalize_official_foreign_names_v031(candidate),
        )
        lang_ok, lang_reason = core._target_language_status_v0334(source_fixed, candidate)
        reg_ok, _ = _respectful_register_status_v035(candidate)
        if lang_ok and reg_ok:
            return candidate, attempt, ""
        last_reason = lang_reason or "register_failed"
    return None, attempts, last_reason


def _rescue_non_korean_row_v03121(
    core,
    model_name: str,
    row: dict[str, Any],
    registry: dict[str, Any],
    attempts: int = 2,
):
    """v0.3.12.2: whole-row rescue first, then sentence-by-sentence recovery.

    A rare contaminated row must not keep reproducing the same bad pattern just because the
    same long source is retried.  If one source-only row retry fails, translate independent
    source sentences.  Only the emergency path is split; provenance and normal grouping remain intact.
    """
    uid = str(row.get("utterance_id", ""))
    source = str(row.get("raw_joined_text", ""))

    # First, one minimal whole-row attempt.  Do not repeat the identical long prompt twice.
    source_fixed, _ = _replace_entity_variants_v035(source, registry)
    entities = _row_entities_for_language_rescue_v03121(source_fixed, registry)
    text = core._generate_local_llm_text_v033(
        model_name,
        "영문을 의미 손실 없이 자연스러운 한국어로 번역하세요. 결과에는 한국어와 확인된 공식 Latin 이름만 사용하세요.",
        _language_rescue_piece_prompt_v03122(core, uid, source_fixed, entities, 1),
        max_tokens=max(500, min(1400, int(len(source_fixed) * 1.8) + 220)),
    )
    parsed, _ = core._parse_translation_text_v033(text, [uid])
    candidate = parsed.get(uid)
    if candidate:
        candidate = core._apply_source_conditioned_term_normalization_v0332(
            source_fixed, core._canonicalize_official_foreign_names_v031(candidate)
        )
        lang_ok, lang_reason = core._target_language_status_v0334(source_fixed, candidate)
        reg_ok, _ = _respectful_register_status_v035(candidate)
        if lang_ok and reg_ok:
            return candidate, 1, ""
        last_reason = lang_reason or "register_failed"
    else:
        last_reason = "missing_marker"

    # Second strategy: isolate each complete source sentence.  This breaks the repetition pattern
    # that caused UT-00003 to keep returning contaminated output even under a short row prompt.
    pieces = _split_rescue_pieces_v03122(source_fixed)
    if len(pieces) > 1:
        out = []
        total_attempts = 1
        for i, piece in enumerate(pieces, start=1):
            pid = f"{uid}-R{i:02d}"
            translated_piece, used, reason = _translate_rescue_piece_v03122(
                core, model_name, pid, piece, registry, attempts=2
            )
            total_attempts += used
            if not translated_piece:
                return None, total_attempts, reason or last_reason
            out.append(translated_piece.strip())
        joined = " ".join(x for x in out if x).strip()
        lang_ok, lang_reason = core._target_language_status_v0334(source_fixed, joined)
        reg_ok, _ = _respectful_register_status_v035(joined)
        if lang_ok and reg_ok:
            return joined, total_attempts, ""
        last_reason = lang_reason or "register_failed"

    # Final strategy for a single very long sentence: split only at strong clause boundaries.
    if len(source_fixed) > 140:
        clauses = [p.strip() for p in re.split(r"(?<=[,;:])\s+(?=(?:and|but|so|because|while|then|I|you|we|they|it|Claude|[A-Z]))", source_fixed) if p.strip()]
        if len(clauses) > 1:
            out = []
            total_attempts = 2
            for i, piece in enumerate(clauses, start=1):
                pid = f"{uid}-C{i:02d}"
                translated_piece, used, reason = _translate_rescue_piece_v03122(
                    core, model_name, pid, piece, registry, attempts=2
                )
                total_attempts += used
                if not translated_piece:
                    return None, total_attempts, reason or last_reason
                out.append(translated_piece.strip())
            joined = " ".join(out).strip()
            lang_ok, lang_reason = core._target_language_status_v0334(source_fixed, joined)
            reg_ok, _ = _respectful_register_status_v035(joined)
            if lang_ok and reg_ok:
                return joined, total_attempts, ""
            last_reason = lang_reason or "register_failed"

    return None, 2, last_reason


_HAN_IDEOGRAPH_RE_V03123 = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _han_chars_v03123(text: str) -> list[str]:
    """Return unique CJK Han ideographs still present in a candidate."""
    return sorted(set(_HAN_IDEOGRAPH_RE_V03123.findall(str(text or ""))))


def _language_cleanup_prompt_v03123(core, uid: str, source: str, bad_draft: str, entities: list[str], attempt: int = 1) -> str:
    """English-only emergency instruction to escape repeated multilingual contamination.

    The source and the contaminated draft are both provided so the model only has to repair
    script/language form rather than re-infer the whole meaning from scratch.
    """
    entity_line = ", ".join(entities) if entities else "(none)"
    retry = " This is the second cleanup attempt; be especially strict about Hangul-only Korean prose." if attempt > 1 else ""
    return f"""TASK: Rewrite BAD_DRAFT as natural Korean while checking SOURCE_EN for meaning.{retry}

STRICT RULES:
- Korean prose must use Hangul. Do not use CJK Unified Ideographs or Japanese script.
- Keep only the verified Latin names listed below exactly as Latin text.
- Translate ordinary English words into Korean.
- Preserve numbers, costs, durations, conditions, action order, speaker, actor, and target.
- Do not summarize, add facts, infer UI actions, or move content from neighboring rows.
- Return exactly one marker line and nothing else.

VERIFIED_LATIN_NAMES: {entity_line}
SOURCE_EN:
{source}

BAD_DRAFT:
{bad_draft}

{core._marker_output_instruction_v033([uid])}"""


def _purify_non_korean_candidate_v03123(core, model_name: str, uid: str, source: str, bad_draft: str, registry: dict[str, Any], attempts: int = 2):
    """Try to repair only script contamination, with an English-only meta prompt."""
    source_fixed, _ = _replace_entity_variants_v035(source, registry)
    entities = _row_entities_for_language_rescue_v03121(source_fixed, registry)
    best = str(bad_draft or "")
    best_count = len(_han_chars_v03123(best))
    last_reason = "unexpected_han_characters"
    for attempt in range(1, attempts + 1):
        text = core._generate_local_llm_text_v033(
            model_name,
            "Rewrite the provided draft into accurate natural Korean. Korean prose must use Hangul; preserve only verified Latin proper names.",
            _language_cleanup_prompt_v03123(core, uid, source_fixed, best, entities, attempt),
            max_tokens=max(500, min(1500, int(len(source_fixed) * 1.7) + 260)),
        )
        parsed, _ = core._parse_translation_text_v033(text, [uid])
        candidate = parsed.get(uid)
        if not candidate:
            last_reason = "missing_marker"
            continue
        candidate = core._apply_source_conditioned_term_normalization_v0332(
            source_fixed, core._canonicalize_official_foreign_names_v031(candidate)
        )
        count = len(_han_chars_v03123(candidate))
        if count < best_count:
            best, best_count = candidate, count
        lang_ok, lang_reason = core._target_language_status_v0334(source_fixed, candidate)
        reg_ok, _ = _respectful_register_status_v035(candidate)
        if lang_ok and reg_ok:
            return candidate, attempt, ""
        last_reason = lang_reason or "register_failed"
    return None, attempts, last_reason, best



# =====================================================================
# v0.3.14 semantic closure
# - A compact source-vs-final audit catches arbitrary meaning drift that regexes cannot
#   generalize to (term substitution, actor reversal, unsupported neighboring content).
# - Remaining deterministic violations and semantic failures are repaired from THIS ROW'S
#   source only, then re-audited before they may become clean.
# - A candidate that improves known violations can be kept even if review warnings remain;
#   the old all-or-nothing acceptance rule no longer throws away partial improvements.
# =====================================================================

_SEMANTIC_AUDIT_ALLOWED_V0313 = {
    "meaning_change", "missing_content", "added_content", "actor_target_reversal",
    "entity_error", "row_content_leak", "action_error", "term_error", "number_condition_error",
}


def _semantic_audit_prompt_v0313(rows: list[dict[str, Any]], output_map: dict[str, str]) -> str:
    blocks = []
    for row in rows:
        uid = str(row.get("utterance_id", ""))
        blocks.append(
            f"ID: {uid}\nSOURCE_EN: {row.get('raw_joined_text','')}\nKO_CANDIDATE: {output_map.get(uid,'')}"
        )
    return """You are a strict bilingual fidelity auditor, not a copy editor.
Compare each KO_CANDIDATE ONLY with the SOURCE_EN under the same ID.

Flag FAIL only for a clear source-fidelity error. Ignore harmless style differences, synonyms,
politeness, sentence-ending choices, and minor naturalness preferences.

FAIL categories:
- meaning_change: a source concept became a different concept.
- missing_content: important source information disappeared.
- added_content: candidate asserts information or reasoning not present in this row's source.
- actor_target_reversal: speaker/tool/audience/action target changed roles.
- entity_error: a proper name/product relation is clearly missing, expanded, collapsed, or changed.
- row_content_leak: candidate contains a proposition that is not in this row and appears to belong elsewhere.
- action_error: click/select/type/open/copy/etc. was changed into a different action without support.
- term_error: a meaningful technical/common term was translated as a different term.
- number_condition_error: number, duration, price, condition, or sequence changed.

High-confidence examples of FAIL logic (examples are rules, not text to copy):
- SOURCE says an opening hook must be ready, but KO says a handoff must be ready -> term_error.
- SOURCE says a tool edits everything for the speaker, but KO says the speaker edits it -> actor_target_reversal.
- SOURCE row has no token-cost statement, but KO appends a sentence about already spending tokens -> added_content or row_content_leak.
- A casual filler that gives no real reason must not become a factual causal explanation -> added_content.

If meaning is faithfully preserved, output PASS even if you would personally rewrite the Korean.
Return exactly one line per ID, no prose outside the lines:
@@V001@@ ID ||| PASS ||| none
@@V002@@ ID ||| FAIL ||| category

ROWS:
""" + "\n\n".join(blocks)


def _parse_semantic_audit_v0313(text: str, expected: list[str]) -> tuple[dict[str, dict[str, str]], list[str]]:
    expected_set = set(expected)
    found: dict[str, dict[str, str]] = {}
    for line in str(text or "").splitlines():
        m = re.match(r"\s*@@V\d+@@\s*([^|]+?)\s*\|\|\|\s*(PASS|FAIL)\s*\|\|\|\s*([A-Za-z_]+|none)\s*$", line, re.I)
        if not m:
            continue
        uid = m.group(1).strip()
        if uid not in expected_set:
            continue
        status = m.group(2).upper()
        cat = m.group(3).lower()
        if status == "FAIL" and cat not in _SEMANTIC_AUDIT_ALLOWED_V0313:
            cat = "meaning_change"
        if status == "PASS":
            cat = "none"
        found[uid] = {"status": status, "category": cat}
    missing = [uid for uid in expected if uid not in found]
    return found, missing


def _run_semantic_audit_v0313(core, model_name: str, rows: list[dict[str, Any]], output_map: dict[str, str]):
    if not rows:
        return {}, []
    expected = [str(r.get("utterance_id", "")) for r in rows]
    prompt = _semantic_audit_prompt_v0313(rows, output_map)
    try:
        text = core._generate_local_llm_text_v033(
            model_name,
            "Audit English-to-Korean source fidelity. Return only the requested PASS/FAIL marker lines.",
            prompt,
            max_tokens=max(500, min(1800, 120 + len(rows) * 110)),
        )
        parsed, missing = _parse_semantic_audit_v0313(text, expected)
        if missing:
            retry_rows = [r for r in rows if str(r.get("utterance_id", "")) in set(missing)]
            retry_text = core._generate_local_llm_text_v033(
                model_name,
                "Return only strict PASS/FAIL marker lines for source fidelity. Do not translate or rewrite.",
                _semantic_audit_prompt_v0313(retry_rows, output_map)
                + "\nFORMAT RETRY: output every missing ID exactly once.",
                max_tokens=max(320, min(1000, 100 + len(retry_rows) * 100)),
            )
            parsed2, missing2 = _parse_semantic_audit_v0313(retry_text, missing)
            parsed.update(parsed2)
            missing = missing2
        return parsed, missing
    except Exception:
        return {}, expected


def _deterministic_issue_state_v0313(core, source: str, output: str, registry: dict[str, Any]) -> dict[str, Any]:
    lang_ok, lang_reason = core._target_language_status_v0334(source, output)
    reg_ok, reg_reason = _respectful_register_status_v035(output)
    qissues = _quality_issues_v0312(source, output, registry)
    return {
        "lang_ok": bool(lang_ok), "lang_reason": str(lang_reason or ""),
        "reg_ok": bool(reg_ok), "reg_reason": str(reg_reason or ""),
        "qissues": list(qissues),
    }


def _issue_score_v0313(state: dict[str, Any]) -> int:
    score = 0
    if not state.get("lang_ok", False):
        score += 100
    if not state.get("reg_ok", False):
        score += 20
    for issue in state.get("qissues", []) or []:
        if "고유명사" in issue or "주체" in issue or "관계" in issue or "의미" in issue or "인과" in issue:
            score += 18
        elif "일반 영어" in issue or "영어 잔존" in issue:
            score += 8
        else:
            score += 10
    return score


def _semantic_repair_prompt_v0313(core, rows: list[dict[str, Any]], registry: dict[str, Any], reasons: dict[str, str]) -> str:
    canonical_to_placeholder, _ = _placeholder_maps_v035(registry)
    blocks = []
    for row in rows:
        uid = str(row.get("utterance_id", ""))
        fixed, _ = _replace_entity_variants_v035(str(row.get("raw_joined_text", "")), registry)
        protected = _protect_entities_v035(fixed, canonical_to_placeholder)
        blocks.append(f"ID: {uid}\nSOURCE_EN: {protected}\nISSUE: {reasons.get(uid,'source_fidelity_or_final_gate')}")
    return """Translate/rewrite each SOURCE_EN into natural respectful Korean as a FINAL source-faithful row.
This is a source-only repair: do not use information from any other ID and do not add context from neighboring rows.

Rules:
- Preserve every fact, number, duration, condition, sequence, actor, target, and action relationship.
- Do not summarize or add explanations.
- Do not invent automatic behavior unless SOURCE_EN says automatic/automatically/auto.
- Casual fillers may be naturalized or omitted when they carry no information; never turn them into a fake reason.
- Preserve __ENT###__ placeholders exactly. They are verified official Latin names.
- Translate ordinary English into Korean. Literal URLs/domains/commands may remain Latin.
- If SOURCE_EN itself is ambiguous about type/click/select, preserve that ambiguity rather than guessing a UI action.
- Each ID is independent. Never move a sentence or idea between IDs.
- Output only the requested marker rows.

""" + "\n\n".join(blocks) + "\n\n" + core._marker_output_instruction_v033([str(r.get("utterance_id", "")) for r in rows])


def _repair_rows_semantically_v0313(core, model_name: str, rows: list[dict[str, Any]], registry: dict[str, Any], reasons: dict[str, str]):
    if not rows:
        return {}
    expected = [str(r.get("utterance_id", "")) for r in rows]
    source_chars = sum(len(str(r.get("raw_joined_text", ""))) for r in rows)
    canonical_to_placeholder, placeholder_to_canonical = _placeholder_maps_v035(registry)
    text = core._generate_local_llm_text_v033(
        model_name,
        "Produce source-faithful natural Korean for each independent row. Do not transfer content between IDs.",
        _semantic_repair_prompt_v0313(core, rows, registry, reasons),
        max_tokens=max(750, min(2600, int(source_chars * 1.7) + 240)),
    )
    parsed, _ = core._parse_translation_text_v033(text, expected)
    result = {}
    for row in rows:
        uid = str(row.get("utterance_id", ""))
        candidate = parsed.get(uid)
        if not candidate:
            continue
        candidate = _restore_entities_v035(candidate, placeholder_to_canonical)
        candidate = core._apply_source_conditioned_term_normalization_v0332(
            str(row.get("raw_joined_text", "")), core._canonicalize_official_foreign_names_v031(candidate)
        )
        result[uid] = candidate
    return result


def _closure_repair_batches_v0313(rows: list[dict[str, Any]], ids: set[str], size: int = 4) -> list[list[dict[str, Any]]]:
    selected = [r for r in rows if str(r.get("utterance_id", "")) in ids]
    return [selected[i:i+size] for i in range(0, len(selected), size)]

def _translate_rows_with_context_v0312(core, data, all_units, chapter, rows, model_name, translation_scope, progress_callback=None):
    global _LAST_STAGE_SNAPSHOTS_V0312
    translations = {}
    policy_records = []
    prior_tail = ""
    outline = core._chapter_outline_v032(data)
    batches = core._translation_batches_v033(rows)
    total_batches = max(1, len(batches))
    total_editorial_calls = sum(max(1, len(_editorial_subbatches_v0312(batch))) for batch in batches)
    audit_key = _entity_audit_cache_key_v0312(data)
    audit_cached = audit_key in _VIDEO_ENTITY_AUDIT_CACHE_V0312
    audit_steps = 0 if audit_cached else 1
    total_steps = len(batches) + total_editorial_calls + audit_steps + total_batches
    completed_steps = 0

    if progress_callback:
        progress_callback({"event": "start", "total_batches": total_batches, "total_steps": total_steps, "target_row_count": len(rows)})

    registry = _build_entity_registry_v035(data)

    # One conservative full-video proper-name audit per source video.  The accepted map
    # is cached and then applied only to model-facing copies, never to raw provenance.
    global _ACTIVE_ENTITY_AUDIT_MAP_V0312
    if not audit_cached and progress_callback:
        progress_callback({
            "event": "stage_start", "batch_index": 0, "total_batches": total_batches,
            "stage": "사전 · 고유명사/브랜드 ASR 검수", "completed_steps": completed_steps, "total_steps": total_steps,
        })
    _ACTIVE_ENTITY_AUDIT_MAP_V0312 = _resolve_video_entity_audit_v0312(
        core, data, model_name, registry
    )
    registry = _augment_registry_with_audit_canonicals_v0313(registry, _ACTIVE_ENTITY_AUDIT_MAP_V0312)
    if not audit_cached:
        completed_steps += 1
        if progress_callback:
            progress_callback({
                "event": "stage_complete", "batch_index": 0, "total_batches": total_batches,
                "stage": "사전 · 고유명사/브랜드 ASR 검수", "completed_steps": completed_steps, "total_steps": total_steps,
            })

    _, placeholder_to_canonical = _placeholder_maps_v035(registry)

    for batch_index, batch in enumerate(batches, start=1):
        reference_units, context_meta = core._reference_units_for_batch_v033(data, all_units, chapter, batch, translation_scope)
        expected = [row["utterance_id"] for row in batch]
        target_chars = sum(len(str(row.get("raw_joined_text", ""))) for row in batch)
        max_tokens = min(7000, max(1200, int(target_chars * 1.45)))

        source_repairs = []
        for row in batch:
            _, repairs = _replace_entity_variants_v035(row.get("raw_joined_text", ""), registry)
            source_repairs += [{"utterance_id": row["utterance_id"], **r} for r in repairs]

        if progress_callback:
            progress_callback({
                "event": "stage_start", "batch_index": batch_index, "total_batches": total_batches,
                "stage": "1차 · Qwen3 문맥 번역", "completed_steps": completed_steps, "total_steps": total_steps,
            })

        text = core._generate_local_llm_text_v033(
            model_name, _translation_system_prompt_v035(),
            _build_prompt_v035(core, reference_units, batch, registry, chapter_outline=outline, prior_korean_tail=prior_tail),
            max_tokens=max_tokens,
        )
        translated, missing = core._parse_translation_text_v033(text, expected)
        if missing:
            retry_rows = [row for row in batch if row["utterance_id"] in missing]
            retry_text = core._generate_local_llm_text_v033(
                model_name, _translation_system_prompt_v035(),
                _build_prompt_v035(core, reference_units, retry_rows, registry, chapter_outline=outline, prior_korean_tail=prior_tail)
                + "\n\n이전 응답 형식이 깨졌습니다. OUTPUT_FORMAT 외의 텍스트는 출력하지 마세요.",
                max_tokens=max(800, min(max_tokens, int(max_tokens * 0.8))),
            )
            retry_map, retry_missing = core._parse_translation_text_v033(retry_text, missing)
            translated.update(retry_map); missing = retry_missing
        if missing:
            raise RuntimeError("Qwen3 1차 번역 결과에서 일부 검수 행을 읽지 못했습니다: " + ", ".join(missing))

        source_by_id = {row["utterance_id"]: row.get("raw_joined_text", "") for row in batch}
        first_map = {}
        for uid in expected:
            value = _restore_entities_v035(translated.get(uid, ""), placeholder_to_canonical)
            value = core._apply_source_conditioned_term_normalization_v0332(
                source_by_id.get(uid, ""), core._canonicalize_official_foreign_names_v031(value)
            )
            first_map[uid] = value

        # v0.3.12.2 hotfix: do not let a Chinese/Japanese-contaminated first pass flow into
        # the editorial stage. Rescue only the bad rows with a tiny Korean-only prompt,
        # without whole-video context or the contaminated draft.
        first_pass_language_rescue_ids = []
        first_pass_language_rescue_attempts = {}
        first_pass_language_rescue_failures = {}
        row_by_id_first = {r["utterance_id"]: r for r in batch}
        for uid in expected:
            lang_ok, lang_reason = core._target_language_status_v0334(source_by_id.get(uid, ""), first_map[uid])
            if lang_ok:
                continue
            rescued, used_attempts, rescue_reason = _rescue_non_korean_row_v03121(
                core, model_name, row_by_id_first[uid], registry, attempts=2
            )
            first_pass_language_rescue_attempts[uid] = used_attempts
            if rescued:
                first_map[uid] = rescued
                first_pass_language_rescue_ids.append(uid)
            else:
                first_pass_language_rescue_failures[uid] = rescue_reason or lang_reason

        completed_steps += 1
        if progress_callback:
            progress_callback({
                "event": "stage_complete", "batch_index": batch_index, "total_batches": total_batches,
                "stage": "1차 · Qwen3 문맥 번역", "completed_steps": completed_steps, "total_steps": total_steps,
            })

        # Second pass: focus on 5-6 utterances at a time.  This cuts repeated prompt overhead while keeping enough focus for natural Korean editing.
        editorial_map = {}
        editorial_used, editorial_fallback, editorial_changed = [], [], []
        editorial_subbatch_records = []
        editorial_prior_tail = prior_tail
        subbatches = _editorial_subbatches_v0312(batch)
        for sub_index, subrows in enumerate(subbatches, start=1):
            sub_expected = [r["utterance_id"] for r in subrows]
            sub_chars = sum(len(str(r.get("raw_joined_text", ""))) for r in subrows)
            if progress_callback:
                progress_callback({
                    "event": "stage_start", "batch_index": batch_index, "total_batches": total_batches,
                    "stage": f"2차 · 한국어 집중 편집 {sub_index}/{len(subbatches)}",
                    "completed_steps": completed_steps, "total_steps": total_steps,
                })
            edit_text = core._generate_local_llm_text_v033(
                model_name,
                _editorial_system_prompt_v0312(),
                _build_editorial_prompt_v0312(
                    core, reference_units, subrows, first_map, registry,
                    chapter_outline=outline, prior_korean_tail=editorial_prior_tail,
                ),
                max_tokens=max(1000, min(4200, int(sub_chars * 1.45))),
            )
            edited, _ = core._parse_translation_text_v033(edit_text, sub_expected)
            sub_fallback, sub_changed = [], []
            for uid in sub_expected:
                candidate = edited.get(uid)
                if not candidate:
                    editorial_map[uid] = first_map[uid]
                    editorial_fallback.append(uid); sub_fallback.append(uid)
                    continue
                candidate = _restore_entities_v035(candidate, placeholder_to_canonical)
                candidate = core._apply_source_conditioned_term_normalization_v0332(
                    source_by_id.get(uid, ""), core._canonicalize_official_foreign_names_v031(candidate)
                )
                lang_ok, _ = core._target_language_status_v0334(source_by_id.get(uid, ""), candidate)
                if not lang_ok:
                    editorial_map[uid] = first_map[uid]
                    editorial_fallback.append(uid); sub_fallback.append(uid)
                else:
                    editorial_map[uid] = candidate
                    editorial_used.append(uid)
                    if candidate.strip() != first_map[uid].strip():
                        editorial_changed.append(uid); sub_changed.append(uid)
            editorial_prior_tail = "\n".join(f"{uid}: {editorial_map[uid]}" for uid in sub_expected[-2:] if uid in editorial_map)
            completed_steps += 1
            editorial_subbatch_records.append({
                "subbatch_index": sub_index,
                "utterance_ids": sub_expected,
                "changed_ids": sub_changed,
                "fallback_ids": sub_fallback,
            })
            if progress_callback:
                progress_callback({
                    "event": "stage_complete", "batch_index": batch_index, "total_batches": total_batches,
                    "stage": f"2차 · 한국어 집중 편집 {sub_index}/{len(subbatches)}",
                    "completed_steps": completed_steps, "total_steps": total_steps,
                })

        final_map = {uid: editorial_map.get(uid, first_map[uid]) for uid in expected}

        # v0.3.12: detect cross-marker content bleed before normal quality guards.
        # Only suspicious rows pay for an extra row-only retry.
        leak_suspects, adjacent_leak_records = _adjacent_leak_suspects_v0312(expected, source_by_id, final_map)
        row_boundary_retry_ids = []
        if leak_suspects:
            row_by_id = {r["utterance_id"]: r for r in batch}
            for uid in expected:
                if uid not in leak_suspects:
                    continue
                retry_text = core._generate_local_llm_text_v033(
                    model_name,
                    _editorial_system_prompt_v0312(),
                    _row_only_retry_prompt_v0312(
                        core, row_by_id[uid], final_map.get(uid, ""), registry,
                        "인접 ID의 내용이 현재 행에 섞였을 가능성",
                    ),
                    max_tokens=max(650, min(1800, int(len(source_by_id.get(uid, "")) * 1.8))),
                )
                retry_map, _ = core._parse_translation_text_v033(retry_text, [uid])
                candidate = retry_map.get(uid)
                if not candidate:
                    continue
                candidate = _restore_entities_v035(candidate, placeholder_to_canonical)
                candidate = core._apply_source_conditioned_term_normalization_v0332(
                    source_by_id.get(uid, ""), core._canonicalize_official_foreign_names_v031(candidate)
                )
                lang_ok, _ = core._target_language_status_v0334(source_by_id.get(uid, ""), candidate)
                reg_ok, _ = _respectful_register_status_v035(candidate)
                if lang_ok and reg_ok:
                    final_map[uid] = candidate
                    row_boundary_retry_ids.append(uid)

        # Deterministic guards only cover errors code can judge with confidence.
        reasons, invalid_ids, first_quality = {}, [], {}
        for uid in expected:
            value = final_map[uid]
            lang_ok, lang_reason = core._target_language_status_v0334(source_by_id.get(uid, ""), value)
            reg_ok, reg_reason = _respectful_register_status_v035(value)
            qissues = _quality_issues_v0312(source_by_id.get(uid, ""), value, registry)
            first_quality[uid] = list(qissues)
            parts = []
            if not lang_ok: parts.append(lang_reason)
            if not reg_ok: parts.append(reg_reason)
            parts.extend(qissues)
            if parts:
                invalid_ids.append(uid); reasons[uid] = "; ".join(parts)

        retried_ids = []
        if invalid_ids:
            retry_rows = [row for row in batch if row["utterance_id"] in invalid_ids]
            retry_text = core._generate_local_llm_text_v033(
                model_name, _editorial_system_prompt_v0312(),
                _retry_prompt_v035(core, retry_rows, final_map, registry, reasons)
                + "\n\n이것은 최종 안전 재편집입니다. ISSUE에 일반 영어 미번역이 있으면 __ENT###__/URL/실제 명령어·UI 문자열을 제외한 영어 표현을 문맥에 맞는 한국어로 반드시 번역하세요. SOURCE_EN에 없는 의미를 절대 추가하지 말고, 자연스러운 존댓말로 반환하세요.",
                max_tokens=max(900, min(3200, int(sum(len(r.get("raw_joined_text", "")) for r in retry_rows) * 1.5))),
            )
            retry_map, _ = core._parse_translation_text_v033(retry_text, invalid_ids)
            for uid in invalid_ids:
                candidate = retry_map.get(uid)
                if not candidate: continue
                candidate = _restore_entities_v035(candidate, placeholder_to_canonical)
                candidate = core._apply_source_conditioned_term_normalization_v0332(
                    source_by_id.get(uid, ""), core._canonicalize_official_foreign_names_v031(candidate)
                )
                lang_ok, _ = core._target_language_status_v0334(source_by_id.get(uid, ""), candidate)
                reg_ok, _ = _respectful_register_status_v035(candidate)
                qissues = _quality_issues_v0312(source_by_id.get(uid, ""), candidate, registry)
                if lang_ok and reg_ok and not qissues:
                    final_map[uid] = candidate; retried_ids.append(uid)

        # v0.3.12 fail-closed final gate: if a row is STILL known-bad after the normal
        # targeted retry, retry that row alone once more.  Known violations must never
        # be silently treated as a clean final result.
        final_gate_retry_ids = []
        row_by_id = {r["utterance_id"]: r for r in batch}
        for uid in expected:
            current = final_map[uid]
            lang_ok, lang_reason = core._target_language_status_v0334(source_by_id.get(uid, ""), current)
            reg_ok, reg_reason = _respectful_register_status_v035(current)
            qissues = _quality_issues_v0312(source_by_id.get(uid, ""), current, registry)
            remaining = []
            if not lang_ok:
                remaining.append(lang_reason)
            if not reg_ok:
                remaining.append(reg_reason)
            remaining.extend(qissues)
            if not remaining:
                continue

            retry_text = core._generate_local_llm_text_v033(
                model_name,
                _editorial_system_prompt_v0312(),
                _row_only_retry_prompt_v0312(
                    core,
                    row_by_id[uid],
                    current,
                    registry,
                    "최종 가드 실패: " + "; ".join(remaining),
                )
                + "\n\n이것은 마지막 검수입니다. ISSUE를 실제 최종 문장에 모두 반영하세요. "
                  "허용된 고유명사/URL/명령 literal을 제외한 일반 영어는 남기지 마세요. "
                  "SOURCE_EN의 고유명사는 검증된 공식 Latin 표기를 정확히 유지하세요. "
                  "for me/for you/by X/while 같은 역할·관계와 주체를 뒤집지 마세요.",
                max_tokens=max(650, min(1900, int(len(source_by_id.get(uid, "")) * 1.9))),
            )
            retry_map, _ = core._parse_translation_text_v033(retry_text, [uid])
            candidate = retry_map.get(uid)
            if not candidate:
                continue
            candidate = _restore_entities_v035(candidate, placeholder_to_canonical)
            candidate = core._apply_source_conditioned_term_normalization_v0332(
                source_by_id.get(uid, ""), core._canonicalize_official_foreign_names_v031(candidate)
            )
            c_lang_ok, _ = core._target_language_status_v0334(source_by_id.get(uid, ""), candidate)
            c_reg_ok, _ = _respectful_register_status_v035(candidate)
            c_qissues = _quality_issues_v0312(source_by_id.get(uid, ""), candidate, registry)
            if c_lang_ok and c_reg_ok and not c_qissues:
                final_map[uid] = candidate
                final_gate_retry_ids.append(uid)

        # v0.3.14 emergency language rescue. First use source-only row/sentence recovery.
        # If that still fails, run a separate English-instruction cleanup pass over the contaminated
        # draft. Crucially, a single unrecoverable row no longer destroys the whole chapter: it is
        # preserved and marked needs_review_non_korean so the user can fix only that row.
        emergency_language_rescue_ids = []
        language_cleanup_rescue_ids = []
        unrecovered_language_rows = {}
        row_by_id_emergency = {r["utterance_id"]: r for r in batch}
        for uid in expected:
            lang_ok, lang_reason = core._target_language_status_v0334(source_by_id.get(uid, ""), final_map[uid])
            if lang_ok:
                continue
            rescued, _, rescue_reason = _rescue_non_korean_row_v03121(
                core, model_name, row_by_id_emergency[uid], registry, attempts=2
            )
            if rescued:
                final_map[uid] = rescued
                emergency_language_rescue_ids.append(uid)
                continue

            cleaned = _purify_non_korean_candidate_v03123(
                core, model_name, uid, source_by_id.get(uid, ""), final_map[uid], registry, attempts=2
            )
            if len(cleaned) == 4:
                purified, _, cleanup_reason, best_partial = cleaned
            else:
                purified, _, cleanup_reason = cleaned
                best_partial = final_map[uid]
            if purified:
                final_map[uid] = purified
                language_cleanup_rescue_ids.append(uid)
                continue

            # Keep the least-contaminated candidate if cleanup improved it, but never call it clean.
            if best_partial and len(_han_chars_v03123(best_partial)) < len(_han_chars_v03123(final_map[uid])):
                final_map[uid] = best_partial
            bad_chars = _han_chars_v03123(final_map[uid])
            unrecovered_language_rows[uid] = {
                "reason": cleanup_reason or rescue_reason or lang_reason or "unexpected_han_characters",
                "han_characters": bad_chars,
                "han_character_count": len(bad_chars),
            }

        if progress_callback:
            progress_callback({
                "event": "stage_start", "batch_index": batch_index, "total_batches": total_batches,
                "stage": "3차 · 원문 대조 의미 안전 감사", "completed_steps": completed_steps, "total_steps": total_steps,
            })

        # v0.3.14 semantic closure: audit every language-clean row against its own source.
        # This catches arbitrary meaning drift (e.g. one technical noun becoming a different noun),
        # actor/target reversal, and paraphrased neighboring-row leakage that deterministic regexes
        # cannot generalize to.  Remaining deterministic warnings are repaired in the same source-only path.
        semantic_audit_rows = [
            r for r in batch
            if core._target_language_status_v0334(
                source_by_id.get(str(r.get("utterance_id", "")), ""),
                final_map.get(str(r.get("utterance_id", "")), ""),
            )[0]
        ]
        semantic_initial, semantic_missing = _run_semantic_audit_v0313(
            core, model_name, semantic_audit_rows, final_map
        )
        semantic_audit_unavailable_ids = list(semantic_missing)
        semantic_warnings: dict[str, list[str]] = {}
        for uid, rec in semantic_initial.items():
            if rec.get("status") == "FAIL":
                semantic_warnings.setdefault(uid, []).append(
                    "원문 대조 의미 검수 실패: " + str(rec.get("category") or "meaning_change")
                )
        for uid in semantic_missing:
            semantic_warnings.setdefault(uid, []).append("원문 대조 의미 검수 결과를 확인하지 못함")

        closure_repair_ids: set[str] = set()
        closure_reasons: dict[str, str] = {}
        states_before: dict[str, dict[str, Any]] = {}
        for uid in expected:
            state = _deterministic_issue_state_v0313(core, source_by_id.get(uid, ""), final_map[uid], registry)
            states_before[uid] = state
            parts = []
            if not state["lang_ok"]:
                continue
            if not state["reg_ok"]:
                parts.append(state["reg_reason"] or "register")
            parts.extend(state["qissues"])
            if semantic_warnings.get(uid):
                parts.extend(semantic_warnings[uid])
            if parts:
                closure_repair_ids.add(uid)
                closure_reasons[uid] = "; ".join(parts)

        semantic_repair_candidate_ids: list[str] = []
        semantic_repair_ids: list[str] = []
        semantic_repair_verified_ids: list[str] = []
        proposal_map: dict[str, str] = {}
        for repair_batch in _closure_repair_batches_v0313(batch, closure_repair_ids, size=4):
            try:
                proposals = _repair_rows_semantically_v0313(
                    core, model_name, repair_batch, registry, closure_reasons
                )
            except Exception:
                proposals = {}
            for uid, candidate in proposals.items():
                candidate_state = _deterministic_issue_state_v0313(
                    core, source_by_id.get(uid, ""), candidate, registry
                )
                if not candidate_state["lang_ok"] or not candidate_state["reg_ok"]:
                    continue
                # Never propose a deterministic regression. Equal deterministic score is allowed
                # only when the original row failed semantic fidelity and therefore needs a source-only rewrite.
                before_score = _issue_score_v0313(states_before.get(uid, {}))
                after_score = _issue_score_v0313(candidate_state)
                had_semantic_fail = bool(semantic_warnings.get(uid))
                if after_score < before_score or (had_semantic_fail and after_score <= before_score):
                    proposal_map[uid] = candidate
                    semantic_repair_candidate_ids.append(uid)

        # Re-audit only proposed rows. A semantic repair cannot become clean merely because
        # deterministic warnings disappeared; it must independently pass source fidelity.
        if proposal_map:
            proposal_rows = [r for r in batch if str(r.get("utterance_id", "")) in proposal_map]
            semantic_after, semantic_after_missing = _run_semantic_audit_v0313(
                core, model_name, proposal_rows, proposal_map
            )
            for row in proposal_rows:
                uid = str(row.get("utterance_id", ""))
                rec = semantic_after.get(uid)
                candidate = proposal_map.get(uid)
                if not candidate:
                    continue
                candidate_state = _deterministic_issue_state_v0313(
                    core, source_by_id.get(uid, ""), candidate, registry
                )
                if rec and rec.get("status") == "PASS":
                    # Keep an improvement even if a non-semantic deterministic warning remains;
                    # the final gate will still mark needs_review. This closes the prior all-or-nothing bug.
                    if _issue_score_v0313(candidate_state) <= _issue_score_v0313(states_before.get(uid, {})):
                        final_map[uid] = candidate
                        semantic_repair_ids.append(uid)
                        semantic_repair_verified_ids.append(uid)
                        semantic_warnings.pop(uid, None)
                else:
                    cat = (rec or {}).get("category") if rec else "audit_unavailable"
                    semantic_warnings.setdefault(uid, []).append(
                        "의미 재편집 후 검증 미통과: " + str(cat or "meaning_change")
                    )
                    if uid in semantic_after_missing and uid not in semantic_audit_unavailable_ids:
                        semantic_audit_unavailable_ids.append(uid)

        completed_steps += 1
        if progress_callback:
            progress_callback({
                "event": "stage_complete", "batch_index": batch_index, "total_batches": total_batches,
                "stage": "3차 · 원문 대조 의미 안전 감사", "completed_steps": completed_steps, "total_steps": total_steps,
            })

        hard_language_fail, quality_warnings = [], []
        for uid in expected:
            lang_ok, lang_reason = core._target_language_status_v0334(source_by_id.get(uid, ""), final_map[uid])
            reg_ok, reg_reason = _respectful_register_status_v035(final_map[uid])
            qissues = _quality_issues_v0312(source_by_id.get(uid, ""), final_map[uid], registry)
            if not lang_ok:
                hard_language_fail.append(f"{uid}:{lang_reason}")
                quality_warnings.append(f"{uid}:비한국어 문자 잔존 - 수동 검수 필요")
                unrecovered_language_rows.setdefault(uid, {
                    "reason": lang_reason,
                    "han_characters": _han_chars_v03123(final_map[uid]),
                    "han_character_count": len(_han_chars_v03123(final_map[uid])),
                })
            if not reg_ok: quality_warnings.append(f"{uid}:{reg_reason}")
            if qissues: quality_warnings.append(f"{uid}:" + "; ".join(qissues))
        # Do not raise here. The result file must still be produced with the affected rows clearly
        # marked needs_review_non_korean; known-bad rows are never marked clean.

        source_asr_warnings = {
            uid: _source_asr_review_warnings_v0312(source_by_id.get(uid, ""), registry)
            for uid in expected
        }
        visual_action_warnings = {
            uid: _source_action_review_warnings_v0312(source_by_id.get(uid, ""))
            for uid in expected
        }
        for uid in expected:
            final_qissues = _quality_issues_v0312(source_by_id.get(uid, ""), final_map[uid], registry)
            reg_ok, reg_reason = _respectful_register_status_v035(final_map[uid])
            all_final_warnings = list(final_qissues)
            if not reg_ok:
                all_final_warnings.append(reg_reason)
            unresolved_source = source_asr_warnings.get(uid, [])
            unresolved_visual = visual_action_warnings.get(uid, [])
            unresolved_semantic = semantic_warnings.get(uid, [])
            lang_ok_final, lang_reason_final = core._target_language_status_v0334(source_by_id.get(uid, ""), final_map[uid])
            if not lang_ok_final:
                all_final_warnings.append("비한국어 문자 잔존: " + str(lang_reason_final))
            gate_status = "clean" if not (all_final_warnings or unresolved_source or unresolved_visual or unresolved_semantic) else ("needs_review_non_korean" if not lang_ok_final else "needs_review")
            _LAST_STAGE_SNAPSHOTS_V0312[uid] = {
                "first_pass_normalized_text": first_map[uid],
                "editorial_normalized_text": editorial_map.get(uid, first_map[uid]),
                "final_normalized_text": final_map[uid],
                "editorial_changed": editorial_map.get(uid, first_map[uid]).strip() != first_map[uid].strip(),
                "targeted_retry_applied": uid in retried_ids,
                "first_pass_language_rescue_applied": uid in first_pass_language_rescue_ids,
                "emergency_language_rescue_applied": uid in emergency_language_rescue_ids,
                "language_cleanup_rescue_applied": uid in language_cleanup_rescue_ids,
                "unrecovered_language_issue": copy.deepcopy(unrecovered_language_rows.get(uid)),
                "final_gate_retry_applied": uid in final_gate_retry_ids,
                "final_gate_status": gate_status,
                "translation_quality_warnings": all_final_warnings,
                "source_asr_review_warnings": unresolved_source,
                "visual_action_review_warnings": unresolved_visual,
                "semantic_audit_warnings": unresolved_semantic,
                "semantic_repair_applied": uid in semantic_repair_ids,
                "semantic_repair_verified": uid in semantic_repair_verified_ids,
                "semantic_audit_unavailable": uid in semantic_audit_unavailable_ids,
                "row_boundary_retry_applied": uid in row_boundary_retry_ids,
            }

        translations.update({uid: final_map[uid] for uid in expected})
        prior_tail = "\n".join(f"{uid}: {translations[uid]}" for uid in expected[-2:])

        policy_records.append({
            "batch_index": batch_index, "target_utterance_ids": expected, **context_meta,
            "reference_sentence_count": len(reference_units),
            "reference_char_count": len(core._units_plain_text_v032(reference_units)),
            "first_pass": "completed",
            "llm_second_pass": "focused_source_comparison_korean_editorial_review",
            "editorial_subbatch_size": _EDITORIAL_SUBBATCH_SIZE_V0312,
            "editorial_subbatches": editorial_subbatch_records,
            "editorial_review_used_ids": editorial_used,
            "editorial_changed_ids": editorial_changed,
            "editorial_fallback_to_first_pass_ids": editorial_fallback,
            "targeted_retry_ids": retried_ids,
            "first_pass_language_rescue_ids": first_pass_language_rescue_ids,
            "first_pass_language_rescue_attempts": first_pass_language_rescue_attempts,
            "first_pass_language_rescue_failures": first_pass_language_rescue_failures,
            "emergency_language_rescue_ids": emergency_language_rescue_ids,
            "language_cleanup_rescue_ids": language_cleanup_rescue_ids,
            "unrecovered_language_rows": copy.deepcopy(unrecovered_language_rows),
            "post_editorial_deterministic_issues": {k: v for k, v in first_quality.items() if v},
            "quality_warnings_after_retry": quality_warnings,
            "source_asr_review_warnings": {k: v for k, v in source_asr_warnings.items() if v},
            "visual_action_review_warnings": {k: v for k, v in visual_action_warnings.items() if v},
            "adjacent_content_leak_suspects": adjacent_leak_records,
            "row_boundary_retry_ids": row_boundary_retry_ids,
            "final_gate_retry_ids": final_gate_retry_ids,
            "semantic_audit_failures": {k: v for k, v in semantic_warnings.items() if v},
            "semantic_audit_unavailable_ids": semantic_audit_unavailable_ids,
            "semantic_repair_candidate_ids": semantic_repair_candidate_ids,
            "semantic_repair_ids": semantic_repair_ids,
            "semantic_repair_verified_ids": semantic_repair_verified_ids,
            "video_entity_audit_repairs": copy.deepcopy(_ACTIVE_ENTITY_AUDIT_MAP_V0312),
            "source_entity_repairs_for_model_context": source_repairs,
            "entity_registry_size": len(registry.get("canonicals", [])),
            "post_generation_guards": [
                "target_language_guard", "first_pass_korean_only_language_rescue", "emergency_korean_only_language_rescue", "english_meta_draft_purification", "nonblocking_row_level_language_gate", "respectful_korean_register_guard", "ordinary_english_leak_guard",
                "semantic_role_guard", "unwarranted_automation_guard", "word_vs_character_guard",
                "visual_still_guard", "video_level_entity_placeholder_protection",
                "fuzzy_asr_entity_canonicalization_from_video_evidence", "official_foreign_name_canonicalization",
                "literal_url_command_shield", "entity_non_expansion_guard", "adjacent_row_content_leak_guard",
                "cached_video_entity_audit", "entity_registry_evidence_sanitizer", "overlapping_asr_entity_variant_repair", "all_latin_residue_guard", "entity_exact_spelling_guard", "fail_closed_final_gate", "source_vs_final_semantic_audit", "source_only_semantic_repair", "semantic_repair_reaudit", "semantic_repair_ab_rollback_gate", "entity_sibling_collision_guard",
                "visual_action_ambiguity_warning", "source_conditioned_term_normalization", "source_fidelity_warning_generation",
            ],
        })
    return translations, policy_records

def _upgrade_result_v0312(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        return result
    result["schema_version"] = "script_preprocessing_v0.3.15.1"
    boundary = result.get("boundary_profile") or {}
    if boundary.get("profile_id"):
        boundary["profile_id"] = re.sub(r"v0\.3\.\d+(?:\.\d+)?", "v0.3.14", str(boundary["profile_id"]))
    context = result.get("chapter_boundary_context") or {}
    if context:
        context["assignment_rule"] = "reconstructed_sentence_semantic_boundary_owner_v0.3.15.1"
    tm = result.get("translation_metadata") or {}
    if tm:
        tm["policy_version"] = "qwen3_entity_only_finalization_guard_v0.3.15.1"
        tm["style_profile"] = {
            "source": "generalized_human_reviewed_korean_editorial_policy",
            "goal": "source_faithful_natural_respectful_korean",
            "default_speaker_register": "respectful_tutorial_korean",
            "direct_quote_exception": "register_only_language_still_translated",
            "naturalness_review": "focused_5_to_6_utterance_source_comparison_editorial_pass",
        }
        pipeline = tm.setdefault("translation_pipeline", {})
        pipeline["llm_pass"] = "context_translation_then_focused_editorial_then_source_vs_final_semantic_closure"
        pipeline["routine_llm_second_pass"] = True
        pipeline["second_pass_role"] = "active_korean_editor_not_minimal_proofreader"
        pipeline["editorial_subbatch_size"] = _EDITORIAL_SUBBATCH_SIZE_V0312
        pipeline["stage_text_preserved_per_utterance"] = True
        pipeline["post_generation_guards"] = [
            "target_language_guard", "first_pass_korean_only_language_rescue", "emergency_korean_only_language_rescue", "english_meta_draft_purification", "nonblocking_row_level_language_gate", "respectful_korean_register_guard", "ordinary_english_leak_guard",
            "semantic_role_guard", "unwarranted_automation_guard", "word_vs_character_guard",
            "visual_still_guard", "video_level_entity_placeholder_protection",
            "fuzzy_asr_entity_canonicalization_from_video_evidence", "official_foreign_name_canonicalization",
            "literal_url_command_shield", "entity_non_expansion_guard", "adjacent_row_content_leak_guard",
            "cached_video_entity_audit", "entity_registry_evidence_sanitizer", "overlapping_asr_entity_variant_repair", "all_latin_residue_guard", "entity_exact_spelling_guard", "fail_closed_final_gate",
            "source_vs_final_semantic_audit", "source_only_semantic_repair", "semantic_repair_reaudit", "semantic_repair_ab_rollback_gate", "entity_sibling_collision_guard", "visual_action_ambiguity_warning", "source_conditioned_korean_term_normalization", "source_fidelity_warnings",
        ]
    for item in result.get("normalized_utterances", []) or []:
        uid = item.get("utterance_id")
        snap = _LAST_STAGE_SNAPSHOTS_V0312.get(uid)
        if snap:
            item.update(copy.deepcopy(snap))
            item["translation_status"] = ("local_qwen3_v0315_1_clean" if snap.get("final_gate_status") == "clean" else "local_qwen3_v0315_1_needs_review")
    if result.get("translation_required"):
        translated_rows = result.get("normalized_utterances", []) or []
        if translated_rows and all(
            str(item.get("translation_status") or "").endswith("_clean")
            for item in translated_rows
        ):
            result["translation_status"] = "completed_clean"
        else:
            result["translation_status"] = "completed_needs_review"

    profile = result.get("profile_application") or {}
    if result.get("translation_required"):
        profile["mode"] = "foreign_translation_v0315_1_qwen3_entity_only_finalization_guard"
        profile["profile_source"] = "v034_qwen3_baseline_plus_context_audit_plus_repair_rollback_plus_entity_collision_guard"
    report = result.get("processing_report") or {}
    if result.get("translation_required"):
        report["chapter_assignment_method"] = "reconstructed_sentence_semantic_boundary_owner"
        report["translation_review_method"] = "qwen3_context_translation_plus_focused_editorial_plus_semantic_audit_repair_reaudit_and_deterministic_guards"
    terminology = result.setdefault("terminology_policy", {})
    terminology["foreign_brand_product_model_tool_person_names"] = "preserve_or_repair_to_best_supported_latin_spelling"
    terminology["asr_entity_repair"] = "cached_video_level_qwen3_entity_audit_plus_strong_evidence_fuzzy_canonicalization_without_raw_provenance_mutation"
    terminology["ordinary_english_phrases"] = "translate_to_natural_korean_unless_strongly_verified_as_entity_ui_command_url_or_file_literal"
    terminology["entity_evidence_policy"] = "sentence_initial_capitalization_alone_is_never_entity_evidence"
    terminology["asr_uncertainty_policy"] = "flag_unresolved_short_uppercase_tokens_instead_of_guessing"
    terminology["korean_register"] = "respectful_tutorial_korean_by_default_direct_quotes_may_preserve_original_register"
    terminology["korean_editorial_pass"] = "active_source_comparison_rewrite_for_naturalness_with_strict_entity_evidence_and_no_semantic_expansion"
    terminology["entity_non_expansion"] = "never_expand_valid_short_entity_into_related_longer_entity_without_clear_typo_evidence"
    terminology["literal_protection"] = "urls_domains_slash_commands_are_shielded_from_entity_repair"
    terminology["row_content_boundary"] = "each_utterance_id_owns_only_its_source_content_adjacent_overlap_triggers_row_only_retry"
    terminology["ui_action_ambiguity"] = "caption_only_type_click_select_ambiguity_is_flagged_for_visual_verification_not_invented"
    terminology["final_acceptance_gate"] = "deterministic_and_source_vs_final_semantic_checks_must_both_clear_before_clean"
    terminology["latin_residue_policy"] = "all_unapproved_latin_in_korean_is_invalid_not_only_a_small_word_blacklist"
    terminology["entity_exactness"] = "strong_source_entities_must_survive_in_exact_supported_latin_spelling_and_case"
    terminology["semantic_fidelity_audit"] = "high_confidence_source_vs_final_audit_catches_meaning_actor_target_term_and_row_leak_errors_not_just_regex_cases"
    terminology["semantic_repair_acceptance"] = "repair_must_pass_semantic_reaudit_and_conservative_old_vs_new_fidelity_comparison_else_rollback"
    terminology["semantic_repair_rollback"] = "keep_previous_candidate_when_repair_is_tied_uncertain_or_introduces_new_semantic_risk"
    terminology["entity_collision_policy"] = "preserve_exact_verified_product_components_and_never_swap_them_for_similar_sibling_products"
    return result

def apply() -> Any:
    import preprocessor as core
    if getattr(core, "_V03151_PATCH_APPLIED", False):
        return core

    required = [
        "_assign_foreign_sentences_to_chapter_v031",
        "_whole_video_group_records_v033",
        "_translate_rows_with_context_v033",
        "_reference_units_for_batch_v033",
        "_translation_batches_v033",
        "_generate_local_llm_text_v033",
        "_parse_translation_text_v033",
        "_marker_output_instruction_v033",
        "_target_language_status_v0334",
        "build_preprocessing_draft",
        "prepare_existing_preprocessing",
        "export_editor_result",
    ]
    missing = [name for name in required if not hasattr(core, name)]
    if missing:
        raise RuntimeError(
            "v0.3.15.1 패치는 v0.3.4 Qwen3 통합본 폴더에서 실행해야 합니다. "
            "필수 항목이 없습니다: " + ", ".join(missing)
        )

    original_build = core.build_preprocessing_draft
    original_prepare = core.prepare_existing_preprocessing
    original_export = core.export_editor_result
    original_term_normalizer = core._apply_source_conditioned_term_normalization_v0332

    def patched_term_normalizer(source, text):
        base = original_term_normalizer(source, text)
        return _normalize_source_conditioned_surfaces_v0312(source, base)

    core._apply_source_conditioned_term_normalization_v0332 = patched_term_normalizer

    core._assign_foreign_sentences_to_chapter_v031 = lambda all_units, chapter: _assign_foreign_sentences_to_chapter_v035(core, all_units, chapter)
    core._whole_video_group_records_v033 = lambda data, all_units: _whole_video_group_records_v035(core, data, all_units)

    def patched_translate(data, all_units, chapter, rows, model_name, translation_scope, progress_callback=None):
        return _translate_rows_with_context_v0312(
            core, data, all_units, chapter, rows, model_name, translation_scope, progress_callback
        )

    # v0.3.4 foreign builder resolves this global at runtime.
    core._translate_rows_with_context_v033 = patched_translate
    if hasattr(core, "_translate_rows_with_context_v034"):
        core._translate_rows_with_context_v034 = patched_translate

    def wrapped_build(*args, **kwargs):
        global _ACTIVE_DATA_V0312, _LAST_STAGE_SNAPSHOTS_V0312
        data_arg = args[0] if args else kwargs.get("data")
        _ACTIVE_DATA_V0312 = data_arg if isinstance(data_arg, dict) else {}
        _LAST_STAGE_SNAPSHOTS_V0312.clear()
        try:
            return _upgrade_result_v0312(original_build(*args, **kwargs))
        finally:
            _ACTIVE_DATA_V0312 = None

    def wrapped_prepare(*args, **kwargs):
        # Loading an older saved preprocessing file must never inherit stage snapshots
        # from a previously generated chapter that happens to reuse UT ids.
        _LAST_STAGE_SNAPSHOTS_V0312.clear()
        return _upgrade_result_v0312(original_prepare(*args, **kwargs))

    def wrapped_export(*args, **kwargs):
        return _upgrade_result_v0312(original_export(*args, **kwargs))

    core.build_preprocessing_draft = wrapped_build
    core.prepare_existing_preprocessing = wrapped_prepare
    core.export_editor_result = wrapped_export

    if hasattr(core, "estimate_translation_workload"):
        original_estimate = core.estimate_translation_workload
        def wrapped_estimate(*args, **kwargs):
            info = dict(original_estimate(*args, **kwargs) or {})
            first_batches = max(1, int(info.get("batch_count", 1) or 1))
            row_count = max(1, int(info.get("target_row_count", 1) or 1))
            editorial_calls = (row_count + _EDITORIAL_SUBBATCH_SIZE_V0312 - 1) // _EDITORIAL_SUBBATCH_SIZE_V0312
            # One extra entity-audit call is normally paid only once per source video and
            # reused from the in-process cache across chapter runs.
            entity_audit_calls = 1
            semantic_audit_calls = first_batches
            total_calls = first_batches + editorial_calls + entity_audit_calls + semantic_audit_calls
            info["llm_passes_per_batch"] = "cached video entity audit + first-pass + focused editorial + source-vs-final semantic audit"
            info["entity_audit_call_count"] = entity_audit_calls
            info["semantic_audit_call_count"] = semantic_audit_calls
            info["editorial_subbatch_size"] = _EDITORIAL_SUBBATCH_SIZE_V0312
            info["editorial_call_count"] = editorial_calls
            info["total_passes"] = total_calls
            info["initial_low_seconds"] = max(int(info.get("initial_low_seconds", 0) or 0), 25 + total_calls * 15)
            info["initial_high_seconds"] = max(int(info.get("initial_high_seconds", 0) or 0), 75 + total_calls * 80)
            info["estimate_note"] = (
                "Qwen3 모델 캐시를 재사용합니다. 영상별 고유명사 감사를 한 번 캐시하고, 1차 문맥 번역과 집중 한국어 편집 뒤 각 배치를 원문 대조 의미 감사합니다. "
                "의미 변경·행위 주체 역전·인접 행 내용 혼입·일반 영어 잔존 등 명확한 오류만 source-only로 재편집하고 다시 의미 검증합니다. 해결되지 않으면 clean으로 표시하지 않습니다."
            )
            return info
        core.estimate_translation_workload = wrapped_estimate

    core._V03151_PATCH_APPLIED = True
    core._V03151_PATCH_VERSION = PATCH_VERSION
    return core


if __name__ == "__main__":
    core = apply()
    print(f"YouTube script preprocessor patch {PATCH_VERSION} applied")

# =====================================================================
# v0.3.14 context-fidelity closure overrides
# - Fixes the semantic-audit marker protocol that could make every row audit_unavailable.
# - Uses local context ONLY to disambiguate commands, pronouns, idioms and discourse intent.
# - Preserves literal command/UI labels while translating the surrounding action naturally.
# - Treats tool/agent delegation and pragmatic reaction language as semantic relations.
# - Keeps composite brand/product repairs structured so Brand's Product can become Brand의 Product.
# =====================================================================

_SEMANTIC_CONTEXT_ROWS_V0314: list[dict[str, Any]] = []


def _has_internal_cap_v0314(value: str) -> bool:
    return any(any(ch.isupper() for ch in tok[1:]) for tok in _entity_tokens(value))


def _promote_official_case_v0314(registry: dict[str, Any]) -> dict[str, Any]:
    """Prefer an observed internal-CamelCase spelling when only casing/spacing differs.

    This is generic brand spelling preservation: HyperFrames should win over Hyperframes when
    both surface forms occur in the source evidence. It never changes the underlying letters.
    """
    reg = copy.deepcopy(registry or {})
    score = dict(reg.get("score", {}) or {})
    kinds = {k: list(v) for k, v in (reg.get("source_kind", {}) or {}).items()}
    all_forms = set(score) | set(reg.get("canonicals", []) or []) | set((reg.get("variant_to_canonical", {}) or {}).keys())
    by_key: defaultdict[str, list[str]] = defaultdict(list)
    for form in all_forms:
        key = _entity_fuzzy_key_v0312(form)
        if key:
            by_key[key].append(form)

    preferred: dict[str, str] = {}
    for key, forms in by_key.items():
        mixed = [f for f in forms if _has_internal_cap_v0314(f)]
        if not mixed:
            continue
        # Internal CamelCase is a strong product-style signal, but still prefer stronger evidence
        # and repeated/metadata occurrences among such spellings.
        preferred[key] = max(mixed, key=lambda f: (float(score.get(f, 0) or 0), len(f)))

    canonicals = []
    replacement: dict[str, str] = {}
    for c in reg.get("canonicals", []) or []:
        p = preferred.get(_entity_fuzzy_key_v0312(c), c)
        replacement[c] = p
        canonicals.append(p)

    variants = {}
    for v, c in (reg.get("variant_to_canonical", {}) or {}).items():
        variants[v] = replacement.get(c, preferred.get(_entity_fuzzy_key_v0312(c), c))
    for key, p in preferred.items():
        variants[p] = p
        score[p] = max(float(score.get(p, 0) or 0), max((float(score.get(x, 0) or 0) for x in by_key[key]), default=0))
        merged = set(kinds.get(p, []) or [])
        for x in by_key[key]:
            merged.update(kinds.get(x, []) or [])
        kinds[p] = sorted(merged)

    reg["canonicals"] = sorted(set(canonicals), key=lambda x: (-len(x), x.lower()))
    reg["variant_to_canonical"] = variants
    reg["score"] = score
    reg["source_kind"] = kinds
    return reg


_build_entity_registry_v035_base_v0314 = _build_entity_registry_v035

def _build_entity_registry_v035(data: dict[str, Any]) -> dict[str, Any]:
    return _promote_official_case_v0314(_build_entity_registry_v035_base_v0314(data))


def _preferred_component_case_v0314(component: str, registry: dict[str, Any]) -> str:
    key = _entity_fuzzy_key_v0312(component)
    candidates = []
    for form in set((registry.get("score", {}) or {}).keys()) | set(registry.get("canonicals", []) or []):
        if _entity_fuzzy_key_v0312(form) == key:
            candidates.append(form)
    if not candidates:
        return component
    mixed = [x for x in candidates if _has_internal_cap_v0314(x)]
    pool = mixed or candidates
    return max(pool, key=lambda x: (float((registry.get("score", {}) or {}).get(x, 0) or 0), len(x)))


def _normalize_composite_canonical_v0314(canonical: str, registry: dict[str, Any]) -> str:
    c = _clean_entity(canonical)
    if not c:
        return c
    # Entity-audit relation output should be canonical ownership, not English prose like
    # "Product by Brand". The Korean translator can then render the possessive naturally.
    m = re.fullmatch(r"(.+?)\s+by\s+(.+)", c, re.I)
    if m:
        product = _preferred_component_case_v0314(_clean_entity(m.group(1)), registry)
        brand = _preferred_component_case_v0314(_clean_entity(m.group(2)), registry)
        return f"{brand}'s {product}"
    m = re.fullmatch(r"(.+?)[’']s\s+(.+)", c)
    if m:
        brand = _preferred_component_case_v0314(_clean_entity(m.group(1)), registry)
        product = _preferred_component_case_v0314(_clean_entity(m.group(2)), registry)
        return f"{brand}'s {product}"
    return _preferred_component_case_v0314(c, registry)


_resolve_video_entity_audit_v0312_base_v0314 = _resolve_video_entity_audit_v0312

def _resolve_video_entity_audit_v0312(core: Any, data: dict[str, Any], model_name: str, registry: dict[str, Any]) -> dict[str, str]:
    raw_map = _resolve_video_entity_audit_v0312_base_v0314(core, data, model_name, registry)
    fixed = {raw: _normalize_composite_canonical_v0314(can, registry) for raw, can in (raw_map or {}).items()}
    # Keep the process cache consistent for subsequent chapters in the same app session.
    try:
        _VIDEO_ENTITY_AUDIT_CACHE_V0312[_entity_audit_cache_key_v0312(data)] = copy.deepcopy(fixed)
    except Exception:
        pass
    return fixed


_augment_registry_with_audit_canonicals_v0313_base_v0314 = _augment_registry_with_audit_canonicals_v0313

def _augment_registry_with_audit_canonicals_v0313(registry: dict[str, Any], audit_map: dict[str, str]) -> dict[str, Any]:
    """Protect components of composite relations separately so Korean can express ownership.

    A whole placeholder such as "HeyGen's HyperFrames" freezes English possessive syntax and
    produces outputs like "HyperFrames by HeyGen를". Instead protect HeyGen and HyperFrames as
    atomic verified names while leaving the possessive relation translatable.
    """
    simple_map = {}
    relation_components: list[str] = []
    for raw, canonical in (audit_map or {}).items():
        c = _normalize_composite_canonical_v0314(canonical, registry)
        m = re.fullmatch(r"(.+?)[’']s\s+(.+)", c)
        if m:
            relation_components.extend([_clean_entity(m.group(1)), _clean_entity(m.group(2))])
        else:
            simple_map[raw] = c
    reg = _augment_registry_with_audit_canonicals_v0313_base_v0314(registry, simple_map)
    reg = copy.deepcopy(reg)
    canonicals = set(reg.get("canonicals", []) or [])
    variants = dict(reg.get("variant_to_canonical", {}) or {})
    score = dict(reg.get("score", {}) or {})
    source_kind = {k: list(v) for k, v in (reg.get("source_kind", {}) or {}).items()}
    for component in relation_components:
        component = _preferred_component_case_v0314(component, registry)
        if not component:
            continue
        # Replace same-letter casing variants with the strongest official-looking surface.
        key = _entity_fuzzy_key_v0312(component)
        old_same = [c for c in canonicals if _entity_fuzzy_key_v0312(c) == key]
        for old in old_same:
            canonicals.discard(old)
            for v, target in list(variants.items()):
                if target == old:
                    variants[v] = component
        canonicals.add(component)
        variants[component] = component
        score[component] = max(float(score.get(component, 0) or 0), 220.0)
        k = set(source_kind.get(component, []) or [])
        k.add("video_entity_audit")
        source_kind[component] = sorted(k)
    reg["canonicals"] = sorted(canonicals, key=lambda x: (-len(x), x.lower()))
    reg["variant_to_canonical"] = variants
    reg["score"] = score
    reg["source_kind"] = source_kind
    return _promote_official_case_v0314(reg)


_composite_entity_audit_prompt_v0313_base_v0314 = _composite_entity_audit_prompt_v0313

def _composite_entity_audit_prompt_v0313(data: dict[str, Any], registry: dict[str, Any], raw_phrases: list[str]) -> str:
    base = _composite_entity_audit_prompt_v0313_base_v0314(data, registry, raw_phrases)
    return base.replace(
        "- A possessive relation such as Brand's Product is allowed only when the video context supports it.",
        "- If the source clearly refers to a product belonging to a brand, use exactly Brand's Product order. Never output Product by Brand.\n"
        "- Preserve the exact strongest observed casing of EACH component (for example internal CamelCase) from TRUSTED_SURFACES.\n"
        "- If ownership is not supported, keep the two names separate or omit the repair; never invent the relation."
    )


def _literal_action_candidates_v0314(source: str) -> list[str]:
    """Extract high-confidence literal software command/UI labels from a source row.

    This intentionally does not treat every phrase after "say" as literal. Say-targets are kept
    only when the same software-like phrase repeats, while type/enter/select/click and explicit
    slash-command syntax are strong literal evidence.
    """
    src = re.sub(r"\s+", " ", str(source or "")).strip()
    found: list[str] = []

    # Explicit slash-command wrapper: keep the command name, not the English wrapper words.
    for m in re.finditer(
        r"\{slash\}\s*command\s+(.+?)(?=\s+and\s+(?:edit|then|before|after|open|select|type|click)\b|[,.!?]|$)",
        src, re.I,
    ):
        phrase = _clean_entity(m.group(1))
        toks = _entity_tokens(phrase)
        if 1 <= len(toks) <= 5 and phrase not in found:
            found.append(phrase)

    # Explicit software actions strongly imply a literal target.
    for m in re.finditer(
        r"\b(?:type|enter|click|select|choose|pick)\s+([A-Za-z][A-Za-z0-9_.-]*(?:\s+[A-Za-z][A-Za-z0-9_.-]*){0,3}?)(?=\s+(?:and|then|right|over)\b|[,.!?]|$)",
        src, re.I,
    ):
        phrase = _clean_entity(m.group(1))
        if phrase and phrase.lower() not in _ENTITY_GENERIC and phrase not in found:
            found.append(phrase)

    # "say X" in agent workflows is ambiguous in speech. Preserve X only when the same short,
    # software-like phrase is repeated in the same row, which distinguishes "launch preview"
    # from ordinary narration such as "I would say two to three minutes".
    say_candidates = []
    for m in re.finditer(
        r"\bsay\s+([A-Za-z][A-Za-z0-9_.-]*(?:\s+[A-Za-z][A-Za-z0-9_.-]*){0,2}?)(?=\s+(?:and|so|over|right)\b|[,.!?]|$)",
        src, re.I,
    ):
        phrase = _clean_entity(m.group(1))
        toks = [t.lower() for t in _entity_tokens(phrase)]
        if not phrase or any("'" in t for t in _entity_tokens(phrase)):
            continue
        if not toks or any(t in {"i", "you", "we", "they", "it", "this", "that", "not"} for t in toks):
            continue
        say_candidates.append(phrase)
    counts = Counter(x.lower() for x in say_candidates)
    for phrase in say_candidates:
        if counts[phrase.lower()] >= 2 and phrase not in found:
            found.append(phrase)
    return found


_quality_issues_v0312_base_v0314 = _quality_issues_v0312

def _quality_issues_v0312(source: str, output: str, registry: dict[str, Any] | None = None) -> list[str]:
    issues = list(_quality_issues_v0312_base_v0314(source, output, registry))
    sl = str(source or "").lower()
    # "whatever you want to do" genuinely licenses a desire/free-choice expression; the older
    # detector falsely called every Korean "원하는 대로" an added meaning.
    if re.search(r"\bwhatever\s+you\s+want(?:\s+to\s+do)?\b|\bwhat\s+you\s+want\s+to\s+do\b", sl):
        issues = [x for x in issues if "원하는 대로" not in x]
    for literal in _literal_action_candidates_v0314(source):
        if not re.search(rf"(?<![A-Za-z0-9]){re.escape(literal)}(?![A-Za-z0-9])", str(output or ""), re.I):
            issues.append(f"명령/UI literal을 번역·변형함: {literal}")
    return list(dict.fromkeys(issues))


_translation_system_prompt_v035_base_v0314 = _translation_system_prompt_v035

def _translation_system_prompt_v035() -> str:
    return _translation_system_prompt_v035_base_v0314() + (
        " 특히 자동 자막의 문법이나 철자가 깨져 있더라도 제목·챕터·앞뒤 작업 흐름·반복 표현으로 관계가 강하게 확인되면, 깨진 문장을 그대로 직역하지 말고 의도된 문법 관계를 복원해서 번역하세요. 다만 근거가 약하면 그럴듯하게 지어내지 말고 검수 대상으로 남길 수 있어야 합니다. "
        "소프트웨어 실습 문맥에서는 단어 사전식 번역보다 '누가 무엇을 누구 대신 하는지'와 실제 작업 흐름을 먼저 해석하세요. "
        "도구·AI 에이전트가 for me로 작업하면 화자가 작업하는 것으로 뒤집지 말고 '저 대신'이라는 위임 관계를 살리세요. "
        "{slash} command X처럼 명령 이름이 이어지거나 type/enter/select/click 뒤에 literal target이 오면 X/target 자체는 Latin 원문을 유지하고, 슬래시 명령을 사용한다/입력한다/선택한다 같은 주변 행동만 한국어로 설명하세요. "
        "say 뒤의 짧은 표현이 같은 실습 구간에서 반복되어 실제 에이전트 입력문처럼 쓰이면 그 literal도 보존하세요. 다만 화면을 보지 않고 type을 select로 바꾸는 등 동작 종류를 새로 만들지는 마세요. "
        "따옴표 속 반응·감탄·관용 표현은 사전 뜻만 옮기지 말고 앞뒤 상황에서 실제로 하는 기능을 보세요. 예상 밖 결과에 대한 감탄/만족 반응인데 감사 대상이나 감사 행위가 없다면 억지로 '감사합니다'라는 사실을 만들지 마세요. "
    )


_editorial_examples_v0312_base_v0314 = _editorial_examples_v0312

def _editorial_examples_v0312() -> str:
    return _editorial_examples_v0312_base_v0314() + """

예시 8
원문: I'll use the slash command long form edit, tell it to edit project.ai from the raw folder, and then the agents can edit everything for me.
좋은 편집: 슬래시(/) 명령어로 'long form edit'을 실행하고, 'project.ai'와 raw 폴더의 파일을 편집하라고 지시합니다. 그러면 AI 에이전트가 저 대신 전체 편집을 시작합니다.
원칙: 명령 이름·대상 파일·폴더·행위 주체·for me의 위임 관계를 따로 해석한다. 명령 이름은 번역하지 않는다.

예시 9
원문: I wasn't expecting much, but when the result came out I was like, "I'm so grateful."
좋은 편집의 방향: 앞뒤 맥락이 '예상 밖 결과를 보고 놀라거나 만족하는 반응'이고 실제 감사 대상이 없다면, 한국어에서도 그 반응 기능이 자연스럽게 드러나도록 옮긴다.
원칙: grateful 같은 단어도 무조건 사전식 '감사하다'로 고정하지 않는다. 단, 실제로 사람·도구에 감사를 표현하는 문맥이면 감사 의미를 그대로 보존한다.

예시 10
원문: I don't really use that feature, but it is here. I can watch a movie while the tool is working.
좋은 편집: 그 기능을 자주 쓰지는 않지만 여기 있긴 합니다. 도구가 작업하는 동안 저는 영화를 볼 수도 있겠네요.
원칙: '있어야 할 기능' 같은 원문 밖 이유를 만들지 않고, I can을 시청자에게 권하는 문장으로 바꾸지 않는다."""


_editorial_system_prompt_v0312_base_v0314 = _editorial_system_prompt_v0312

def _editorial_system_prompt_v0312() -> str:
    return _editorial_system_prompt_v0312_base_v0314() + (
        " 문장별 사전 번역이 아니라 현재 행이 앞뒤 작업 흐름에서 어떤 역할을 하는지 이해한 뒤 편집하세요. 자동 자막 때문에 SOURCE_EN 문법이 깨져 있어도 LOCAL_REFERENCE_CONTEXT와 반복되는 작업 흐름으로 관계가 명확하면 정상 문장 관계로 복원해 자연스럽게 옮기세요. 단, 문맥 근거가 약한 고유명사·행동·숫자는 추측하지 마세요. LOCAL_REFERENCE_CONTEXT는 명령어·대명사·감탄·관용 표현의 의미를 판별하는 근거로 적극 사용하되, 그 문맥의 사실을 현재 ID로 복사하면 안 됩니다. "
        "소프트웨어 실습에서 slash command 뒤의 명령 이름, type/enter/click/select 뒤 literal target, 반복되는 에이전트 입력문은 한국어 뜻으로 치환하지 말고 원문 Latin을 보존하세요. "
        "'AI/도구가 저 대신 작업한다'와 '제가 작업한다'는 완전히 다른 의미입니다. agent/tool/Claude가 주체이고 for me가 붙으면 위임 관계를 한국어에서 분명히 유지하세요. "
        "따옴표 속 반응은 감사·놀람·만족·당황 등 실제 담화 기능을 앞뒤 문맥으로 판단하세요. 단어의 사전 뜻이 상황의 의도와 충돌하면 문맥의 의도를 우선하되 새로운 감정이나 사실을 만들어서는 안 됩니다. "
    )


def _build_editorial_prompt_v0312(core, reference_units, target_rows, first_map, registry, chapter_outline="", prior_korean_tail=""):
    canonical_to_placeholder, _ = _placeholder_maps_v035(registry)
    local_units = _editorial_context_units_v0312(reference_units, target_rows, window_seconds=90.0, max_chars=4500)
    context_raw = core._units_plain_text_v032(local_units)
    context_fixed, _ = _replace_entity_variants_v035(context_raw, registry)
    context = _protect_entities_v035(context_fixed, canonical_to_placeholder)

    blocks = []
    for row in target_rows:
        uid = row["utterance_id"]
        fixed, _ = _replace_entity_variants_v035(row.get("raw_joined_text", ""), registry)
        source = _protect_entities_v035(fixed, canonical_to_placeholder)
        first = _protect_entities_v035(first_map.get(uid, ""), canonical_to_placeholder)
        literals = _literal_action_candidates_v0314(fixed)
        literal_line = ", ".join(literals) if literals else "(없음)"
        blocks.append(
            f"ID: {uid}\nSOURCE_EN: {source}\nFIRST_KO: {first}\n"
            f"LITERAL_COMMAND_OR_UI_CANDIDATES: {literal_line}"
        )

    parts = ["EDITORIAL_EXAMPLES (문구를 복사하지 말고 편집 판단만 참고):\n" + _editorial_examples_v0312()]
    if chapter_outline:
        fixed_outline, _ = _replace_entity_variants_v035(chapter_outline, registry)
        parts.append("CHAPTER_OUTLINE (주제 확인용):\n" + _protect_entities_v035(fixed_outline, canonical_to_placeholder))
    parts.append(
        "LOCAL_REFERENCE_CONTEXT (현재 행의 지시 대상·명령 의미·대명사·감탄/관용 표현의 기능을 판단할 때 적극 참고. 단, 이 문맥의 사실을 다른 ID로 옮기지 마세요):\n"
        + context
    )
    if prior_korean_tail:
        parts.append("PRIOR_FINAL_KOREAN (존댓말 톤과 연결만 참고):\n" + _protect_entities_v035(prior_korean_tail, canonical_to_placeholder))
    parts.append("ROWS_TO_EDIT:\n" + "\n\n".join(blocks))
    parts.append(core._marker_output_instruction_v033([row["utterance_id"] for row in target_rows]))
    return "\n\n".join(parts)


def _context_for_uid_v0314(uid: str, rows: list[dict[str, Any]]) -> tuple[str, str]:
    idx = next((i for i, r in enumerate(rows) if str(r.get("utterance_id", "")) == uid), None)
    if idx is None:
        return "", ""
    before = str(rows[idx - 1].get("raw_joined_text", "")) if idx > 0 else ""
    after = str(rows[idx + 1].get("raw_joined_text", "")) if idx + 1 < len(rows) else ""
    return before[-900:], after[:900]


def _semantic_audit_prompt_v0313(rows: list[dict[str, Any]], output_map: dict[str, str]) -> str:
    blocks = []
    context_rows = _SEMANTIC_CONTEXT_ROWS_V0314 or rows
    for row in rows:
        uid = str(row.get("utterance_id", ""))
        before, after = _context_for_uid_v0314(uid, context_rows)
        blocks.append(
            f"ID: {uid}\nCONTEXT_BEFORE_EN: {before}\nSOURCE_EN: {row.get('raw_joined_text','')}\n"
            f"CONTEXT_AFTER_EN: {after}\nKO_CANDIDATE: {output_map.get(uid,'')}\n"
            f"REQUIRED_OUTPUT_MARKER: @@{uid}@@"
        )
    return """You are a strict bilingual source-fidelity auditor. You are NOT a copy editor.
Use CONTEXT_BEFORE_EN and CONTEXT_AFTER_EN only to disambiguate pronouns, software commands,
idioms, reactions and discourse intent. Never require the KO row to contain neighboring facts.
Compare KO_CANDIDATE with SOURCE_EN under the SAME ID.

FAIL only for a clear fidelity problem:
- meaning_change: a source idea, idiom or pragmatic reaction became a different idea.
- missing_content: important source information disappeared.
- added_content: candidate asserts a reason, intention, evaluation or fact absent from SOURCE_EN.
- actor_target_reversal: speaker/tool/agent/audience or action beneficiary changed roles.
- entity_error: a proper name or brand-product relation is missing, expanded, collapsed or changed.
- row_content_leak: content from a neighboring row was moved into this row.
- action_error: click/select/type/open/copy/command behavior changed without support.
- term_error: a meaningful technical/common term became another term.
- number_condition_error: number, duration, price, condition or sequence changed.

Context-sensitive rules:
- A slash-command name or literal software target must not be translated into a different label.
- If an AI/tool/agent does work "for me", the speaker is the beneficiary, not the actor doing the work.
- Fillers and spontaneous quoted reactions must be judged by their discourse function. Do not force
  dictionary gratitude/causality when the context clearly indicates surprise, satisfaction, hesitation, etc.
- PASS harmless Korean naturalization, synonyms, politeness and sentence-ending changes.

OUTPUT FORMAT IS STRICT. For each ID, output exactly one line using THAT ID as the marker:
@@UT-00001@@ PASS ||| none
@@UT-00002@@ FAIL ||| actor_target_reversal
Do not output @@V001@@. Do not output explanations, bullets, JSON or code fences.

ROWS:
""" + "\n\n".join(blocks)


def _parse_semantic_audit_v0313(text: str, expected: list[str]) -> tuple[dict[str, dict[str, str]], list[str]]:
    expected_set = set(expected)
    found: dict[str, dict[str, str]] = {}
    raw = str(text or "")

    patterns = [
        # Preferred v0.3.14 protocol: actual row id is the marker.
        re.compile(r"^\s*@@(?P<uid>[^@\s]+)@@\s*(?:\|\|\|\s*)?(?P<status>PASS|FAIL)\s*(?:\|\|\||\||:|-)?\s*(?P<cat>[A-Za-z_]+|none)?\s*$", re.I),
        # Backward compatible v0.3.13 protocol.
        re.compile(r"^\s*@@V\d+@@\s*(?P<uid>[^|:]+?)\s*\|\|\|\s*(?P<status>PASS|FAIL)\s*\|\|\|\s*(?P<cat>[A-Za-z_]+|none)\s*$", re.I),
        # Plain marker-less fallback sometimes emitted by local models.
        re.compile(r"^\s*(?P<uid>UT[-_A-Za-z0-9]+)\s*(?:\|\|\||\||:)\s*(?P<status>PASS|FAIL)\s*(?:\|\|\||\||:|-)?\s*(?P<cat>[A-Za-z_]+|none)?\s*$", re.I),
    ]
    for line in raw.splitlines():
        line = line.strip().strip("`*")
        if not line:
            continue
        m = next((p.match(line) for p in patterns if p.match(line)), None)
        if not m:
            continue
        uid = m.group("uid").strip().strip("@ `\"'")
        if uid not in expected_set:
            continue
        status = m.group("status").upper()
        cat = (m.groupdict().get("cat") or "none").lower()
        if status == "FAIL" and cat not in _SEMANTIC_AUDIT_ALLOWED_V0313:
            cat = "meaning_change"
        if status == "PASS":
            cat = "none"
        found[uid] = {"status": status, "category": cat}

    # Very small JSON-ish fallback: "UT-00001": "PASS" / "FAIL: term_error"
    for uid in expected:
        if uid in found:
            continue
        m = re.search(rf"[\"']?{re.escape(uid)}[\"']?\s*[:=]\s*[\"']?(PASS|FAIL)(?:\s*[:|,-]\s*([A-Za-z_]+))?", raw, re.I)
        if m:
            status = m.group(1).upper()
            cat = (m.group(2) or "none").lower()
            if status == "FAIL" and cat not in _SEMANTIC_AUDIT_ALLOWED_V0313:
                cat = "meaning_change"
            if status == "PASS":
                cat = "none"
            found[uid] = {"status": status, "category": cat}

    missing = [uid for uid in expected if uid not in found]
    return found, missing


def _run_semantic_audit_v0313(core, model_name: str, rows: list[dict[str, Any]], output_map: dict[str, str]):
    global _SEMANTIC_CONTEXT_ROWS_V0314
    if not rows:
        return {}, []
    _SEMANTIC_CONTEXT_ROWS_V0314 = list(rows)
    expected = [str(r.get("utterance_id", "")) for r in rows]
    try:
        text = core._generate_local_llm_text_v033(
            model_name,
            "Audit English-to-Korean fidelity. Return ONLY the exact @@UT-ID@@ PASS/FAIL lines requested.",
            _semantic_audit_prompt_v0313(rows, output_map),
            max_tokens=max(500, min(1800, 140 + len(rows) * 120)),
        )
        parsed, missing = _parse_semantic_audit_v0313(text, expected)

        # If batching format drifts, recover one missing row at a time with an explicit literal
        # marker. This prevents the all-rows audit_unavailable failure seen in v0.3.13.
        if missing:
            by_id = {str(r.get("utterance_id", "")): r for r in rows}
            still_missing = []
            for uid in missing:
                row = by_id[uid]
                before, after = _context_for_uid_v0314(uid, rows)
                one_prompt = f"""Compare the Korean candidate with SOURCE_EN. Context is only for meaning disambiguation.
Return exactly ONE line and nothing else:
@@{uid}@@ PASS ||| none
or
@@{uid}@@ FAIL ||| meaning_change
Allowed FAIL categories: {', '.join(sorted(_SEMANTIC_AUDIT_ALLOWED_V0313))}
CONTEXT_BEFORE_EN: {before}
SOURCE_EN: {row.get('raw_joined_text','')}
CONTEXT_AFTER_EN: {after}
KO_CANDIDATE: {output_map.get(uid,'')}
"""
                one_text = core._generate_local_llm_text_v033(
                    model_name,
                    f"Return exactly one audit line beginning @@{uid}@@.",
                    one_prompt,
                    max_tokens=260,
                )
                one, miss = _parse_semantic_audit_v0313(one_text, [uid])
                if one:
                    parsed.update(one)
                else:
                    still_missing.append(uid)
            missing = still_missing
        return parsed, missing
    except Exception:
        return {}, expected


def _semantic_repair_prompt_v0313(core, rows: list[dict[str, Any]], registry: dict[str, Any], reasons: dict[str, str]) -> str:
    canonical_to_placeholder, _ = _placeholder_maps_v035(registry)
    context_rows = _SEMANTIC_CONTEXT_ROWS_V0314 or rows
    blocks = []
    for row in rows:
        uid = str(row.get("utterance_id", ""))
        fixed, _ = _replace_entity_variants_v035(str(row.get("raw_joined_text", "")), registry)
        protected = _protect_entities_v035(fixed, canonical_to_placeholder)
        before, after = _context_for_uid_v0314(uid, context_rows)
        before_fixed, _ = _replace_entity_variants_v035(before, registry)
        after_fixed, _ = _replace_entity_variants_v035(after, registry)
        literals = _literal_action_candidates_v0314(fixed)
        blocks.append(
            f"ID: {uid}\nCONTEXT_BEFORE_EN: {_protect_entities_v035(before_fixed, canonical_to_placeholder)}\n"
            f"SOURCE_EN: {protected}\nCONTEXT_AFTER_EN: {_protect_entities_v035(after_fixed, canonical_to_placeholder)}\n"
            f"LITERAL_COMMAND_OR_UI_CANDIDATES: {', '.join(literals) if literals else '(없음)'}\n"
            f"ISSUE: {reasons.get(uid,'source_fidelity_or_final_gate')}"
        )
    return """Rewrite each SOURCE_EN as natural respectful Korean for final use.
Use CONTEXT_BEFORE_EN / CONTEXT_AFTER_EN ONLY to understand pronouns, workflow, software commands,
idioms and pragmatic reactions. Do NOT move any neighboring proposition into this ID.

Rules:
- Preserve every fact, number, duration, condition, order, actor, beneficiary, target and action relation.
- Interpret the sentence as part of the workflow, not word-by-word. Auto-caption grammar may be broken; when local context strongly resolves the intended relation, reconstruct that relation without inventing new facts.
- If a tool/AI/agent does something for the speaker, preserve that delegation as '저 대신' when natural.
- Preserve literal slash-command names and high-confidence UI/input targets exactly in Latin.
- Translate the wrapper/action naturally. If the source does not distinguish type/select/click, do not invent it.
- Translate quoted reactions by their actual contextual function. Do not invent gratitude, causality or emotion.
- Casual fillers may be omitted/naturalized when they carry no factual information.
- Preserve __ENT###__ exactly. URLs/domains/file identifiers remain literal.
- Translate ordinary English into Korean.
- Never add automatic behavior unless SOURCE_EN explicitly says automatic/automatically/auto.
- Each ID is a hard content boundary.
- Output only the requested marker rows.

""" + "\n\n".join(blocks) + "\n\n" + core._marker_output_instruction_v033([str(r.get("utterance_id", "")) for r in rows])


# The composite audit parser is intentionally tolerant of a model returning "Product by Brand";
# the resolver wrapper normalizes it to Brand's Product and exact component casing before use.


# =====================================================================
# v0.3.15 narrow safety overrides
# - A semantic repair is provisional. It must beat the previous Korean candidate in a
#   conservative A/B fidelity comparison; uncertainty rolls back to the old candidate.
# - A collapsed stylized product token found in the raw ASR (e.g. two spoken tokens that
#   correspond to one CamelCase product) becomes a mandatory component of composite repair.
# - Unresolved suspicious names get one conservative video-context second chance; accepted
#   mappings are still subject to the same evidence/safety gate.
# =====================================================================

_SEMANTIC_BASELINE_MAP_V0315: dict[str, str] = {}
_SEMANTIC_CONTEXT_ROWS_V0315: list[dict[str, Any]] = []


def _collapsed_entity_anchors_v0315(raw: str, registry: dict[str, Any] | None) -> list[str]:
    """Return strong single-token canonicals that are explicitly present as a spacing collapse.

    This is intentionally narrow. It protects forms such as a verified CamelCase product whose
    auto-caption surface was split into two words. It does NOT anchor ordinary exact tokens, so a
    misleading token that happens to be another brand cannot block whole-phrase ASR correction.
    """
    registry = registry or {}
    rt = _entity_tokens(raw)
    if len(rt) < 2:
        return []
    out: list[str] = []
    for canonical in registry.get("canonicals", []) or []:
        ct = _entity_tokens(canonical)
        if len(ct) != 1 or not _entity_is_output_verified_v0312(canonical, registry):
            continue
        token = ct[0]
        # Require a technical/stylized shape. Plain title-case words are not anchors.
        technical = any(ch.isupper() for ch in token[1:]) or any(ch.isdigit() for ch in token) or token.isupper()
        if not technical:
            continue
        ck = _entity_fuzzy_key_v0312(canonical)
        if len(ck) < 5:
            continue
        for width in (2, 3):
            for i in range(0, len(rt) - width + 1):
                if _entity_fuzzy_key_v0312(" ".join(rt[i:i+width])) == ck:
                    out.append(canonical)
                    break
            if canonical in out:
                break
    return list(dict.fromkeys(out))


_audit_mapping_is_safe_v0312_base_v0315 = _audit_mapping_is_safe_v0312

def _audit_mapping_is_safe_v0312(raw, canonical, data, registry, supported_tokens):
    if not _audit_mapping_is_safe_v0312_base_v0315(raw, canonical, data, registry, supported_tokens):
        return False
    # If the raw phrase itself visibly contains a verified stylized product split across words,
    # a composite resolver may add a brand relation but may not swap that product for a sibling.
    for anchor in _collapsed_entity_anchors_v0315(raw, registry):
        if not re.search(rf"(?<![A-Za-z0-9]){re.escape(anchor)}(?![A-Za-z0-9])", str(canonical or ""), re.I):
            return False
    return True


_composite_entity_audit_prompt_v0313_base_v0315 = _composite_entity_audit_prompt_v0313

def _composite_entity_audit_prompt_v0313(data: dict[str, Any], registry: dict[str, Any], raw_phrases: list[str]) -> str:
    base = _composite_entity_audit_prompt_v0313_base_v0315(data, registry, raw_phrases)
    anchor_lines = []
    for raw in raw_phrases:
        anchors = _collapsed_entity_anchors_v0315(raw, registry)
        if anchors:
            anchor_lines.append(f"{raw} => MUST_CONTAIN_EXACTLY: {', '.join(anchors)}")
    if not anchor_lines:
        return base
    return base + "\n\nMANDATORY_ANCHORED_COMPONENTS:\n" + "\n".join(anchor_lines) + (
        "\nIf a row has MUST_CONTAIN_EXACTLY, the CANONICAL must contain that exact verified product "
        "surface. Do not replace it with a longer sibling/sub-product that merely shares a root."
    )


_entity_audit_prompt_v0312_base_v0315 = _entity_audit_prompt_v0312

def _entity_audit_prompt_v0312(data: dict[str, Any], registry: dict[str, Any]) -> str:
    return _entity_audit_prompt_v0312_base_v0315(data, registry) + (
        "\n추가 판정 원칙:\n"
        "- 한 creator chapter 안에서 같은 역할의 도구명이 여러 ASR 철자/띄어쓰기 변형으로 반복되고, chapter label/metadata의 한 공식명이 그 변형군을 강하게 설명한다면 전체 구절을 그 공식명으로 복원할 수 있습니다.\n"
        "- 한 토큰이 우연히 다른 알려진 브랜드처럼 보인다는 이유만으로 그 구절을 그대로 믿지 마세요. 구절 전체의 발음 변형군, chapter 주제, 실제 작업 역할을 함께 보세요.\n"
        "- 반대로 chapter 주제만으로 이름을 바꾸면 안 됩니다. 최소한 반복 변형군이나 같은 작업 역할의 추가 근거가 있어야 합니다.\n"
    )


def _entity_occurrence_contexts_v0315(data: dict[str, Any], phrase: str, max_hits: int = 3) -> str:
    text = " ".join(_transcript_texts(data))
    low, needle = text.lower(), str(phrase or "").lower()
    if not needle:
        return ""
    parts = []
    pos = 0
    while len(parts) < max_hits:
        idx = low.find(needle, pos)
        if idx < 0:
            break
        parts.append(text[max(0, idx-220): min(len(text), idx + len(phrase) + 220)])
        pos = idx + max(1, len(needle))
    return "\n---\n".join(parts)


def _parse_entity_second_chance_v0315(text: str) -> list[tuple[str, str]]:
    out = []
    for line in str(text or "").splitlines():
        m = re.match(r"\s*@@R\d+@@\s*(.*?)\s*\|\|\|\s*(.*?)\s*$", line)
        if not m:
            continue
        raw, can = _clean_entity(m.group(1)), _clean_entity(m.group(2))
        if not raw or not can or can.upper() == "KEEP_SOURCE" or raw.lower() == can.lower():
            continue
        out.append((raw, can))
    return out


def _entity_second_chance_prompt_v0315(data: dict[str, Any], registry: dict[str, Any], unresolved: list[str], accepted: dict[str, str]) -> str:
    meta = data.get("metadata", {}) or {}
    chapters = " | ".join(str(c.get("label") or "") for c in (data.get("creator_chapters", []) or []))
    trusted = [c for c in (registry.get("canonicals", []) or []) if _entity_is_output_verified_v0312(c, registry)]
    blocks = []
    for raw in unresolved[:24]:
        blocks.append(f"SOURCE: {raw}\nNEARBY_CONTEXT: {_entity_occurrence_contexts_v0315(data, raw)}")
    known = "; ".join(f"{a} -> {b}" for a, b in list((accepted or {}).items())[:40]) or "(none)"
    return f"""Resolve only the unresolved suspicious ASR proper-name phrases below.
Choose KEEP_SOURCE unless video evidence strongly supports a correction.

Rules:
- You may choose only a canonical already supported by TRUSTED_CANONICALS, or a possessive Brand's Product made from two supported canonical components.
- Use creator-chapter topic, nearby workflow role, and already accepted variant-family repairs together.
- A badly segmented single brand may contain a token that resembles another known brand. Correct it only when repeated variants/workflow evidence strongly favors one canonical.
- Never merge sibling products. If a raw phrase visibly contains an exact stylized product component, preserve that exact product component.
- Do not expand a valid short entity into a related longer entity.
- If uncertain, KEEP_SOURCE.

TITLE: {meta.get('title','')}
DESCRIPTION: {str(meta.get('description_raw') or '')[:3500]}
CREATOR_CHAPTERS: {chapters}
TRUSTED_CANONICALS: {', '.join(trusted[:100])}
ALREADY_ACCEPTED_VARIANTS: {known}

UNRESOLVED:
{chr(10).join(blocks)}

OUTPUT one line per correction only:
@@R001@@ SOURCE ||| CANONICAL
@@R002@@ SOURCE ||| CANONICAL
"""


_resolve_video_entity_audit_v0312_base_v0315 = _resolve_video_entity_audit_v0312

def _resolve_video_entity_audit_v0312(core: Any, data: dict[str, Any], model_name: str, registry: dict[str, Any]) -> dict[str, str]:
    accepted = dict(_resolve_video_entity_audit_v0312_base_v0315(core, data, model_name, registry) or {})
    suspicious = _suspicious_entity_phrases_v0312(data)
    unresolved = [x for x in suspicious if x not in accepted]
    if unresolved:
        try:
            text = core._generate_local_llm_text_v033(
                model_name,
                "Conservatively resolve unresolved ASR proper-name variants from this video's own evidence. Return marker lines only.",
                _entity_second_chance_prompt_v0315(data, registry, unresolved, accepted),
                max_tokens=max(450, min(1400, 180 + len(unresolved[:24]) * 80)),
            )
            supported = _entity_supported_tokens_v0312(data, registry)
            for raw, canonical in _parse_entity_second_chance_v0315(text):
                if raw not in unresolved:
                    continue
                canonical = _normalize_composite_canonical_v0314(canonical, registry)
                if _audit_mapping_is_safe_v0312(raw, canonical, data, registry, supported):
                    accepted[raw] = canonical
        except Exception:
            pass
    try:
        _VIDEO_ENTITY_AUDIT_CACHE_V0312[_entity_audit_cache_key_v0312(data)] = copy.deepcopy(accepted)
    except Exception:
        pass
    return accepted


def _parse_repair_comparison_v0315(text: str, uid: str) -> str:
    raw = str(text or "")
    m = re.search(rf"@@{re.escape(uid)}@@\s*(?:\|\|\|\s*)?(KEEP_OLD|USE_NEW)\b", raw, re.I)
    if not m:
        m = re.search(r"\b(KEEP_OLD|USE_NEW)\b", raw, re.I)
    return m.group(1).upper() if m else "KEEP_OLD"


def _compare_semantic_repair_v0315(core, model_name: str, row: dict[str, Any], old_ko: str, new_ko: str, context_rows: list[dict[str, Any]]) -> str:
    uid = str(row.get("utterance_id", ""))
    before, after = _context_for_uid_v0314(uid, context_rows)
    prompt = f"""Choose whether a proposed Korean repair is STRICTLY safer than the previous Korean candidate.
This is a conservative rollback gate. If both are imperfect, tied, or you are uncertain, KEEP_OLD.
USE_NEW only when NEW_KO clearly improves fidelity to SOURCE_EN without introducing a new unsupported noun/term,
changing an entity, changing actor/beneficiary/target/action, adding a reason/evaluation, or importing neighbor content.
Natural style improvement alone is NOT enough to replace OLD_KO.
Context is only for disambiguation and must not add facts.

CONTEXT_BEFORE_EN: {before}
SOURCE_EN: {row.get('raw_joined_text','')}
CONTEXT_AFTER_EN: {after}
OLD_KO: {old_ko}
NEW_KO: {new_ko}

Return exactly one line:
@@{uid}@@ KEEP_OLD
or
@@{uid}@@ USE_NEW
"""
    try:
        text = core._generate_local_llm_text_v033(
            model_name,
            f"Conservative A/B source-fidelity gate. Default to KEEP_OLD. Return only @@{uid}@@ KEEP_OLD or USE_NEW.",
            prompt,
            max_tokens=180,
        )
        return _parse_repair_comparison_v0315(text, uid)
    except Exception:
        return "KEEP_OLD"


_run_semantic_audit_v0313_base_v0315 = _run_semantic_audit_v0313

def _run_semantic_audit_v0313(core, model_name: str, rows: list[dict[str, Any]], output_map: dict[str, str]):
    global _SEMANTIC_CONTEXT_ROWS_V0315
    if not rows:
        return {}, []
    expected = [str(r.get("utterance_id", "")) for r in rows]
    row_by_id = {str(r.get("utterance_id", "")): r for r in rows}

    # First source-vs-final audit establishes the rollback baseline. A later call for the same
    # uid with different Korean is the repair re-audit phase.
    repair_ids = [uid for uid in expected if uid in _SEMANTIC_BASELINE_MAP_V0315 and output_map.get(uid, "") != _SEMANTIC_BASELINE_MAP_V0315.get(uid, "")]
    if not repair_ids:
        _SEMANTIC_CONTEXT_ROWS_V0315 = list(rows)
        for uid in expected:
            _SEMANTIC_BASELINE_MAP_V0315[uid] = str(output_map.get(uid, ""))

    parsed, missing = _run_semantic_audit_v0313_base_v0315(core, model_name, rows, output_map)

    # A repair PASS is not sufficient by itself. Compare OLD vs NEW directly and fail closed.
    context_rows = _SEMANTIC_CONTEXT_ROWS_V0315 or rows
    for uid in repair_ids:
        rec = parsed.get(uid)
        if not rec or rec.get("status") != "PASS":
            continue
        verdict = _compare_semantic_repair_v0315(
            core, model_name, row_by_id[uid], _SEMANTIC_BASELINE_MAP_V0315.get(uid, ""), str(output_map.get(uid, "")), context_rows
        )
        if verdict != "USE_NEW":
            parsed[uid] = {"status": "FAIL", "category": "meaning_change"}
    return parsed, missing


_translate_rows_with_context_v0312_base_v0315 = _translate_rows_with_context_v0312

def _translate_rows_with_context_v0312(core, data, all_units, chapter, rows, model_name, translation_scope, progress_callback=None):
    _SEMANTIC_BASELINE_MAP_V0315.clear()
    _SEMANTIC_CONTEXT_ROWS_V0315.clear()
    return _translate_rows_with_context_v0312_base_v0315(
        core, data, all_units, chapter, rows, model_name, translation_scope, progress_callback
    )

# =====================================================================
# v0.3.15.1 entity-only finalization hotfix
#
# Scope is intentionally narrow:
# 1) propagate a strong video-level ASR variant family only when creator-chapter / repeated
#    variant evidence supports it;
# 2) reconstruct Brand's Product only from an explicit relationship already present in the
#    same video's own transcript (e.g. "Product ... by Brand");
# 3) unresolved name-like source phrases may never silently pass clean.
#
# No translation prompt architecture, semantic audit, batching, or language-rescue behavior is
# changed here.  Raw transcript/provenance remain untouched.
# =====================================================================


def _strong_canonical_v03151(canonical: str, registry: dict[str, Any]) -> bool:
    canonical = _clean_entity(canonical)
    if not canonical or not _entity_is_output_verified_v0312(canonical, registry):
        return False
    score = float((registry.get("score", {}) or {}).get(canonical, 0) or 0)
    kinds = set((registry.get("source_kind", {}) or {}).get(canonical, []) or [])
    technical = any(
        t.isupper() or any(ch.isdigit() for ch in t) or any(ch.isupper() for ch in t[1:])
        for t in _entity_tokens(canonical)
    )
    return bool(score >= 70 or technical or kinds & {
        "metadata", "metadata_token", "metadata_subphrase", "trusted_root_phrase",
        "context_pattern", "fuzzy_to_trusted_entity", "video_entity_audit",
    })


def _trusted_exact_phrase_v03151(data: dict[str, Any], phrase: str) -> bool:
    phrase = _clean_entity(phrase)
    if not phrase:
        return False
    pat = re.compile(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])", re.I)
    return any(pat.search(str(x or "")) for x in _trusted_metadata_texts(data))


def _chapter_ranges_v03151(data: dict[str, Any]) -> list[tuple[float, float, str]]:
    chapters = sorted(
        [c for c in (data.get("creator_chapters", []) or []) if c.get("start_seconds") is not None],
        key=lambda c: float(c.get("start_seconds", 0) or 0),
    )
    out: list[tuple[float, float, str]] = []
    for i, ch in enumerate(chapters):
        start = float(ch.get("start_seconds", 0) or 0)
        if ch.get("end_seconds") is not None:
            end = float(ch.get("end_seconds") or start)
        elif i + 1 < len(chapters):
            end = float(chapters[i + 1].get("start_seconds", start) or start)
        else:
            end = float((data.get("metadata", {}) or {}).get("duration_seconds") or 10**12)
        out.append((start, end, str(ch.get("label") or "")))
    return out


def _phrase_chapter_support_v03151(data: dict[str, Any], phrase: str, canonical: str) -> bool:
    """True only when an actual phrase occurrence sits inside a creator chapter naming canonical."""
    pk = _entity_fuzzy_key_v0312(phrase)
    ck = _entity_fuzzy_key_v0312(canonical)
    if not pk or not ck:
        return False
    ranges = _chapter_ranges_v03151(data)
    if not ranges:
        return False
    for item in (data.get("transcript", {}) or {}).get("items", []) or []:
        text = str(item.get("text") or "")
        if phrase.lower() not in text.lower():
            continue
        start = float(item.get("start_seconds", 0) or 0)
        for lo, hi, label in ranges:
            if lo <= start < hi:
                lk = _entity_fuzzy_key_v0312(label)
                if ck and (ck in lk or lk in ck):
                    return True
    return False


def _variant_family_members_v03151(
    data: dict[str, Any], registry: dict[str, Any], accepted: dict[str, str]
) -> dict[str, list[str]]:
    transcript = "\n".join(_transcript_texts(data)).lower()
    fam: defaultdict[str, list[str]] = defaultdict(list)
    combined = dict(registry.get("variant_to_canonical", {}) or {})
    combined.update(accepted or {})
    for raw, canonical in combined.items():
        raw, canonical = _clean_entity(raw), _clean_entity(canonical)
        if not raw or not canonical or raw.lower() == canonical.lower():
            continue
        if not _strong_canonical_v03151(canonical, registry):
            continue
        if raw.lower() not in transcript:
            continue
        if raw not in fam[canonical]:
            fam[canonical].append(raw)
    return fam


def _propagate_variant_families_v03151(
    data: dict[str, Any], registry: dict[str, Any], accepted: dict[str, str]
) -> dict[str, str]:
    """Conservatively propagate already-proven ASR spelling families across the same video.

    The key safety property is transitive evidence: a new phrase is never corrected just because a
    chapter has a tempting name.  It also needs repeated already-supported variants, and name
    collisions require the phrase occurrence to sit inside the matching creator chapter.
    """
    out = dict(accepted or {})
    families = _variant_family_members_v03151(data, registry, out)
    suspicious = _suspicious_entity_phrases_v0312(data, limit=200)
    supported = _entity_supported_tokens_v0312(data, registry)
    verified_tokens = {
        t.lower()
        for c in (registry.get("canonicals", []) or [])
        if _entity_is_output_verified_v0312(c, registry)
        for t in _entity_tokens(c)
    }

    for raw in suspicious:
        if raw in out or _trusted_exact_phrase_v03151(data, raw):
            continue
        rk = _entity_fuzzy_key_v0312(raw)
        if len(rk) < 5:
            continue
        scored: list[tuple[float, str, bool, int, float]] = []
        raw_first = (_entity_tokens(raw) or [""])[0].lower()
        for canonical, witnesses in families.items():
            if len(_entity_tokens(canonical)) != 1:
                continue
            ck = _entity_fuzzy_key_v0312(canonical)
            sims = [difflib.SequenceMatcher(None, rk, _entity_fuzzy_key_v0312(w)).ratio() for w in witnesses]
            if not sims:
                continue
            max_sim = max(sims)
            canonical_sim = difflib.SequenceMatcher(None, rk, ck).ratio() if ck else 0.0
            chapter_support = _phrase_chapter_support_v03151(data, raw, canonical)
            # If the first ASR token is itself another verified name, this is a dangerous collision.
            # Require both creator-chapter support and a mature variant family before overriding it.
            collision = raw_first in verified_tokens and raw_first not in {t.lower() for t in _entity_tokens(canonical)}
            family_size = len({_entity_fuzzy_key_v0312(w) for w in witnesses})
            accept = False
            if collision:
                accept = bool(chapter_support and family_size >= 2 and max_sim >= 0.70)
            else:
                accept = bool(
                    (chapter_support and family_size >= 2 and max_sim >= 0.68)
                    or (family_size >= 2 and max_sim >= 0.74 and canonical_sim >= 0.58)
                    or (family_size >= 1 and max_sim >= 0.84)
                )
            if accept:
                score = max_sim + (0.10 if chapter_support else 0.0) + min(0.06, 0.02 * family_size)
                scored.append((score, canonical, chapter_support, family_size, max_sim))
        if not scored:
            continue
        scored.sort(reverse=True)
        if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.08:
            continue
        canonical = scored[0][1]
        if _audit_mapping_is_safe_v0312(raw, canonical, data, registry, supported):
            out[raw] = canonical
            families.setdefault(canonical, []).append(raw)
    return out


def _resolve_surface_alias_v03151(
    surface: str, registry: dict[str, Any], accepted: dict[str, str]
) -> str | None:
    surface = _clean_entity(surface)
    if not surface:
        return None
    sl = surface.lower()
    for raw, canonical in (accepted or {}).items():
        if sl == _clean_entity(raw).lower():
            return _clean_entity(canonical)
    variants = registry.get("variant_to_canonical", {}) or {}
    for raw, canonical in variants.items():
        if sl == _clean_entity(raw).lower() and _strong_canonical_v03151(canonical, registry):
            return _clean_entity(canonical)
    canonicals = [c for c in (registry.get("canonicals", []) or []) if _strong_canonical_v03151(c, registry)]
    for c in canonicals:
        if sl == c.lower():
            return c
    # A single ASR token after explicit relation words such as "by" may be a close spelling
    # of a verified canonical. Require a high unique match; never use this for arbitrary prose.
    if len(_entity_tokens(surface)) != 1:
        return None
    sk = _entity_fuzzy_key_v0312(surface)
    candidates = []
    for c in canonicals:
        if len(_entity_tokens(c)) != 1:
            continue
        ck = _entity_fuzzy_key_v0312(c)
        if not sk or not ck or sk[:1] != ck[:1] or abs(len(sk) - len(ck)) > 3:
            continue
        ratio = difflib.SequenceMatcher(None, sk, ck).ratio()
        if ratio >= 0.80:
            candidates.append((ratio, c))
    candidates.sort(reverse=True)
    if not candidates:
        return None
    if len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 0.08:
        return None
    return candidates[0][1]


def _explicit_entity_relations_v03151(
    data: dict[str, Any], registry: dict[str, Any], accepted: dict[str, str]
) -> dict[str, Counter]:
    """Extract only explicit same-video Brand/Product relations, not generic co-occurrence."""
    text = " ".join(_transcript_texts(data))
    relations: dict[str, Counter] = defaultdict(Counter)
    products = [
        c for c in (registry.get("canonicals", []) or [])
        if _strong_canonical_v03151(c, registry) and len(_entity_fuzzy_key_v0312(c)) >= 5
    ]
    for product in products:
        # Match exact surface and common auto-caption spacing collapse of a single CamelCase token.
        surfaces = {product}
        if len(_entity_tokens(product)) == 1 and any(ch.isupper() for ch in product[1:]):
            split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", product)
            if split != product:
                surfaces.add(split)
        for surf in surfaces:
            pat = re.compile(rf"(?<![A-Za-z0-9]){re.escape(surf)}(?![A-Za-z0-9])", re.I)
            for m in pat.finditer(text):
                tail = text[m.end(): min(len(text), m.end() + 180)]
                # Explicit ownership/attribution is strong enough; mere nearby appearance is not.
                rel = re.search(
                    r"\b(?:created\s+by|made\s+by|built\s+by|developed\s+by|by|from)\s+"
                    r"([A-Z][A-Za-z0-9+#_-]{2,}(?:\s+[A-Z][A-Za-z0-9+#_-]{2,})?)",
                    tail,
                )
                if not rel:
                    continue
                brand_surface = _clean_entity(rel.group(1))
                brand = _resolve_surface_alias_v03151(brand_surface, registry, accepted)
                if brand and brand.lower() != product.lower():
                    relations[product][brand] += 3
    return relations


def _infer_composite_relations_v03151(
    data: dict[str, Any], registry: dict[str, Any], accepted: dict[str, str]
) -> dict[str, str]:
    """Resolve unknown-prefix + verified-product composites only from explicit video evidence."""
    out = dict(accepted or {})
    relations = _explicit_entity_relations_v03151(data, registry, out)
    supported = _entity_supported_tokens_v0312(data, registry)
    for raw in _suspicious_entity_phrases_v0312(data, limit=200):
        if raw in out or _trusted_exact_phrase_v03151(data, raw):
            continue
        anchors = _collapsed_entity_anchors_v0315(raw, registry)
        if len(anchors) != 1:
            continue
        product = anchors[0]
        brands = relations.get(product, Counter())
        if not brands:
            continue
        ranked = brands.most_common()
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            continue
        brand, weight = ranked[0]
        if weight < 3:
            continue
        canonical = _normalize_composite_canonical_v0314(f"{brand}'s {product}", registry)
        if _audit_mapping_is_safe_v0312(raw, canonical, data, registry, supported):
            out[raw] = canonical
    return out


_resolve_video_entity_audit_v0312_base_v03151 = _resolve_video_entity_audit_v0312

def _resolve_video_entity_audit_v0312(core: Any, data: dict[str, Any], model_name: str, registry: dict[str, Any]) -> dict[str, str]:
    # Keep every v0.3.15 model-assisted decision, then add only deterministic evidence closure.
    accepted = dict(_resolve_video_entity_audit_v0312_base_v03151(core, data, model_name, registry) or {})
    accepted = _propagate_variant_families_v03151(data, registry, accepted)
    accepted = _infer_composite_relations_v03151(data, registry, accepted)
    try:
        _VIDEO_ENTITY_AUDIT_CACHE_V0312[_entity_audit_cache_key_v0312(data)] = copy.deepcopy(accepted)
    except Exception:
        pass
    return accepted


def _row_suspicious_phrases_v03151(source: str) -> list[str]:
    fake = {"transcript": {"items": [{"text": str(source or "")} ]}}
    return _suspicious_entity_phrases_v0312(fake, limit=30)


_source_asr_review_warnings_v0312_base_v03151 = _source_asr_review_warnings_v0312

def _source_asr_review_warnings_v0312(source: str, registry: dict[str, Any] | None = None) -> list[str]:
    warnings = list(_source_asr_review_warnings_v0312_base_v03151(source, registry))
    registry = registry or {}
    fixed, _ = _replace_entity_variants_v035(source, registry)
    canonical_low = {
        _clean_entity(c).lower()
        for c in (registry.get("canonicals", []) or [])
        if _entity_is_output_verified_v0312(c, registry)
    }
    active_data_obj = globals().get("_ACTIVE_DATA_V0312")
    active_data = active_data_obj if isinstance(active_data_obj, dict) else {}
    verified_tokens = {
        t.lower()
        for c in (registry.get("canonicals", []) or [])
        if _entity_is_output_verified_v0312(c, registry)
        for t in _entity_tokens(c)
    }
    for phrase in _row_suspicious_phrases_v03151(source):
        toks = _entity_tokens(phrase)
        if not toks or phrase.lower() in canonical_low:
            continue
        if any(t.lower() in _ENTITY_STOPWORDS or t.lower() in _COMMON_ENGLISH_LEAK_WORDS_V0312 for t in toks[1:]):
            continue
        if active_data and _trusted_exact_phrase_v03151(active_data, phrase):
            continue
        # Extra fail-closed warning is intentionally narrow: either a known canonical root has
        # acquired an unverified modifier/sub-product, or a verified stylized product is preceded
        # by an unresolved name-like component. Ordinary descriptive Titlecase phrases are ignored.
        root_collision = toks[0].lower() in verified_tokens and phrase.lower() not in canonical_low
        product_anchor = bool(_collapsed_entity_anchors_v0315(phrase, registry))
        if not (root_collision or product_anchor):
            continue
        # If the active audit actually repaired it, it will no longer be present in fixed source.
        if not re.search(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])", fixed, re.I):
            continue
        warnings.append(
            f"미확정 ASR 고유명사/제품명: '{phrase}' (공식명 근거 부족 - clean 처리 금지)"
        )
    return list(dict.fromkeys(warnings))

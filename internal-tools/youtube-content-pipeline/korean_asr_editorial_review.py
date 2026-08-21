from __future__ import annotations

import copy
import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


DETECTOR_VERSION = "korean_asr_suspicion_detector_v0.1"
REVIEW_VERSION = "korean_asr_editorial_review_v0.1"
DEFAULT_MODEL_ID = "mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit"
MAX_MODEL_REVIEW_ROWS = 24
MODEL_BATCH_SIZE = 3
MODEL_MAX_TOKENS = 2200

_HANGUL_TOKEN_RE = re.compile(r"[가-힣]{2,}")
_WORD_RE = re.compile(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9+./-]*")
_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+./-]*")
_NUMBER_RE = re.compile(r"(?<![A-Za-z])\d+(?:[.,:]\d+)*(?:%|원|년|월|일|개|번|단계)?")
_ATTACHED_BOUNDARY_RE = re.compile(
    r"(?P<prefix>[가-힣]+(?:해서|하여|하면|하며|때|보시면|선택한|참고로))"
    r"이(?=\s+[가-힣A-Za-z])"
)
_ATTACHED_ADVERB_I_RE = re.compile(
    r"(?P<prefix>[가-힣]+(?:하게|스럽게|답게|롭게))이(?=\s+[가-힣A-Za-z])"
)
_FILLER_AFTER_CONNECTIVE_RE = re.compile(
    r"(?P<prefix>[가-힣]+고)음(?=\s+[가-힣A-Za-z])"
)
_SUSPICIOUS_JOIN_RE = re.compile(
    r"[가-힣]+(?:해서|하여|하면|하며|때|보시면|선택한|참고로)이(?:\s|$)"
)
_REPEATED_PARTICLE_RE = re.compile(
    r"(?:은은|는는|이가가|을을|를를|을를|를을|에서에서|으로로|와과|과와)"
)
_LATIN_HANGUL_FUSION_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9+./-]*(?:그인|포넌트|퍼티|이어|큰)(?:은|는|이|가|을|를|도)?"
)
_DIGIT_HANGUL_FUSION_RE = re.compile(
    r"(?<!\d)\d+(?!(?:년|월|일|개|번|단계|시간|분|초|원))[가-힣]{2,}"
)
_ATTACHED_DISCOURSE_I_RE = re.compile(
    r"(?<![가-힣])(?P<prefix>[가-힣]+(?:데|게|고|지만|는데))이(?=\s+[가-힣A-Za-z])"
)
_BROKEN_COMPOUND_RE = re.compile(r"[가-힣]{2,}\s+급수적(?:인|으로|이다|입니다)?")
_TOOL_DUPLICATION_RE = re.compile(r"(?:AI|LLM|MCP)?\s*툴이\s+도구")
_UNVERIFIED_KIT_RE = re.compile(r"[가-힣]{2,}\s+(?:UI\s+)?키트(?:라든지|라고|를|은|는)?")
_UNUSUAL_WO_CONNECTIVE_RE = re.compile(r"[가-힣]+워고(?:\s|$)")
_SHORT_STRUCTURE_MODIFIER_RE = re.compile(r"(?<![가-힣])[가-힣]{2}\s+구조(?:에|가|는|를|의|\s)")
_TENTATIVE_STEP_RE = re.compile(r"살짝\s+[가-힣]{2,5}\s+보는")
_PAST_DEMONSTRATION_RE = re.compile(r"처음\s+[가-힣]{3,8}(?:던|었던)\s+것")
_METADATA_TERM_STOPWORDS = {
    "하는",
    "위한",
    "이렇게",
    "가장",
    "방법",
    "과정",
    "설명",
    "시스템",
    "구현",
    "제작",
    "시작",
    "디자인",
}


@dataclass(frozen=True)
class Entity:
    canonical_name: str
    category: str
    tier: str
    aliases: tuple[str, ...]
    pronunciations: tuple[str, ...]
    context_anchors: tuple[str, ...]
    confidence_policy: str


def _root_dir() -> Path:
    return Path(__file__).resolve().parent


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON object expected: {path.name}")
    return data


def load_canonical_registry(
    root: Path | None = None,
) -> dict[str, Any]:
    """Load v0.2 plus the backward-compatible v0.3 extension."""
    profiles = (root or _root_dir()) / "profiles"
    base = _load_json(profiles / "canonical_entity_registry_v0_2.json")
    extension = _load_json(profiles / "canonical_entity_registry_v0_3.json")
    entities: list[Entity] = []
    seen: set[str] = set()

    for item in base.get("entities") or []:
        canonical = str(item.get("canonical_name") or "").strip()
        if not canonical:
            continue
        entities.append(
            Entity(
                canonical_name=canonical,
                category=str(item.get("entity_type") or "product"),
                tier="A",
                aliases=(canonical,),
                pronunciations=tuple(
                    str(value).strip()
                    for value in item.get("spoken_aliases") or []
                    if str(value).strip()
                ),
                context_anchors=(),
                confidence_policy="verified_v0.2_registry",
            )
        )
        seen.add(canonical.casefold())

    for item in extension.get("entities") or []:
        canonical = str(item.get("canonical_name") or "").strip()
        if not canonical or canonical.casefold() in seen:
            continue
        entities.append(
            Entity(
                canonical_name=canonical,
                category=str(item.get("category") or "tool"),
                tier=str(item.get("tier") or "A"),
                aliases=tuple(
                    str(value).strip()
                    for value in item.get("known_aliases") or []
                    if str(value).strip()
                ),
                pronunciations=tuple(
                    str(value).strip()
                    for value in item.get("korean_pronunciations") or []
                    if str(value).strip()
                ),
                context_anchors=tuple(
                    str(value).strip()
                    for value in item.get("context_anchors") or []
                    if str(value).strip()
                ),
                confidence_policy=str(item.get("confidence_policy") or "high"),
            )
        )
        seen.add(canonical.casefold())

    return {
        "schema_version": extension.get("schema_version"),
        "extends": extension.get("extends"),
        "policy": copy.deepcopy(extension.get("policy") or {}),
        "entities": entities,
        "protected_korean_concepts": tuple(
            str(value).strip()
            for value in extension.get("protected_korean_concepts") or []
            if str(value).strip()
        ),
    }


def _source_language(result: dict[str, Any], source: dict[str, Any]) -> str:
    transcript = source.get("transcript") or {}
    return str(
        result.get("source_language")
        or transcript.get("language_code")
        or transcript.get("language")
        or ""
    ).lower()


def _metadata_texts(source: dict[str, Any]) -> list[tuple[str, str, int]]:
    metadata = source.get("metadata") or {}
    records = [
        ("video_title", str(metadata.get("title") or ""), 4),
        ("video_description", str(metadata.get("description_raw") or ""), 3),
        ("channel_title", str(metadata.get("channel_title") or ""), 7),
        ("creator_name", str(metadata.get("creator_name") or metadata.get("uploader") or ""), 7),
    ]
    for chapter in source.get("creator_chapters") or []:
        if isinstance(chapter, dict):
            records.append(
                (
                    "creator_chapter_label",
                    str(chapter.get("label") or chapter.get("title") or ""),
                    4,
                )
            )
    return records


def _video_local_named_entities(
    metadata_records: list[tuple[str, str, int]],
) -> list[dict[str, Any]]:
    """Derive conservative run-local identities from explicit display metadata."""
    identities: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source_name, text, weight in metadata_records:
        if source_name not in {"channel_title", "creator_name", "video_title", "video_description"}:
            continue
        hangul_runs = [
            re.sub(r"\s+", " ", value).strip()
            for value in re.findall(r"[가-힣][가-힣\s]{1,24}", text)
        ]
        latin_runs = [
            re.sub(r"\s+", " ", value).strip()
            for value in re.findall(r"[A-Za-z][A-Za-z0-9]*(?:\s+[A-Za-z][A-Za-z0-9]*){0,3}", text)
        ]
        if source_name in {"channel_title", "creator_name"} and hangul_runs and latin_runs:
            korean = hangul_runs[0]
            latin = latin_runs[0]
            key = (_compact(korean), latin.casefold())
            if key in seen or len(_compact(korean)) < 2:
                continue
            seen.add(key)
            korean_parts = korean.split()
            identities.append(
                {
                    "category": "CREATOR" if source_name == "channel_title" else "PERSON",
                    "canonical_korean": korean,
                    "canonical_latin": latin,
                    "short_korean": korean_parts[-1],
                    "evidence_sources": [source_name],
                    "evidence_score": weight,
                    "scope": "video_local",
                    "auto_apply_policy": "unique_metadata_identity_with_honorific_or_creator_prefix",
                }
            )
    return identities


def _compact(value: str) -> str:
    return re.sub(r"[\s._/-]+", "", str(value or "")).casefold()


def _contains_phrase(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    if re.search(r"[가-힣]", phrase):
        return _compact(phrase) in _compact(text)
    return bool(
        re.search(
            rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])",
            text,
            flags=re.IGNORECASE,
        )
    )


def _context_supported(entity: Entity, context: str) -> bool:
    if not entity.context_anchors:
        return True
    return any(_contains_phrase(context, anchor) for anchor in entity.context_anchors)


def build_video_local_entity_map(
    result: dict[str, Any],
    source: dict[str, Any],
    registry: dict[str, Any],
) -> dict[str, Any]:
    """Collect evidence for this run without persisting it globally."""
    rows = result.get("normalized_utterances") or []
    transcript_text = "\n".join(
        str(row.get("normalized_text") or "")
        for row in rows
        if isinstance(row, dict)
    )
    metadata_records = _metadata_texts(source)
    metadata_text = "\n".join(text for _, text, _ in metadata_records)
    entity_records: list[dict[str, Any]] = []

    for entity in registry["entities"]:
        sources: set[str] = set()
        score = 0
        occurrences = 0
        forms = (entity.canonical_name, *entity.aliases, *entity.pronunciations)
        for source_name, text, weight in metadata_records:
            if any(_contains_phrase(text, form) for form in forms):
                sources.add(source_name)
                score += weight
        for form in forms:
            if not form:
                continue
            if re.search(r"[가-힣]", form):
                occurrences += _compact(transcript_text).count(_compact(form))
            else:
                occurrences += len(
                    re.findall(
                        rf"(?<![A-Za-z0-9]){re.escape(form)}(?![A-Za-z0-9])",
                        transcript_text,
                        flags=re.IGNORECASE,
                    )
                )
        if occurrences:
            sources.add("transcript_occurrence")
            score += min(occurrences, 6)
        entity_records.append(
            {
                "canonical_name": entity.canonical_name,
                "category": entity.category,
                "tier": entity.tier,
                "evidence_sources": sorted(sources),
                "transcript_occurrences": occurrences,
                "evidence_score": score,
                "confidence_policy": entity.confidence_policy,
            }
        )

    title_terms: set[str] = set()
    for source_name, text, _ in metadata_records:
        if source_name not in {"video_title", "creator_chapter_label"}:
            continue
        title_terms.update(
            token
            for token in _HANGUL_TOKEN_RE.findall(text)
            if 2 <= len(token) <= 10 and token not in _METADATA_TERM_STOPWORDS
        )

    latin_counter: Counter[str] = Counter()
    for _, text, _ in metadata_records:
        latin_counter.update(_LATIN_TOKEN_RE.findall(text))
    latin_counter.update(_LATIN_TOKEN_RE.findall(transcript_text))
    known = {entity.canonical_name.casefold() for entity in registry["entities"]}
    local_latin = sorted(
        value
        for value, count in latin_counter.items()
        if count >= 2 and value.casefold() not in known and len(value) >= 2
    )
    named_entities = _video_local_named_entities(metadata_records)
    return {
        "policy": "runtime_only_not_persisted",
        "evidence_priority": [
            "video_title",
            "video_description",
            "channel_title",
            "creator_name",
            "creator_chapter_label",
            "acquisition_metadata",
            "repeated_latin_occurrence",
            "repeated_pronunciation",
            "global_registry",
        ],
        "metadata_context": metadata_text,
        "title_and_chapter_terms": sorted(title_terms),
        "protected_korean_concepts": list(registry["protected_korean_concepts"]),
        "entities": entity_records,
        "named_entities": named_entities,
        "repeated_unregistered_latin_forms": local_latin,
    }


def _hangul_jamo(value: str) -> str:
    initials = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
    medials = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
    finals = "\0ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"
    output: list[str] = []
    for char in _compact(value):
        code = ord(char) - 0xAC00
        if 0 <= code < 11172:
            output.append(initials[code // 588])
            output.append(medials[(code % 588) // 28])
            final = finals[code % 28]
            if final != "\0":
                output.append(final)
        else:
            output.append(char)
    return "".join(output)


def _edit_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    previous = list(range(len(right) + 1))
    for row, left_char in enumerate(left, 1):
        current = [row]
        for column, right_char in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _replace_literal_alias(text: str, alias: str, canonical: str) -> str:
    if re.search(r"[가-힣]", alias):
        return re.sub(
            rf"(?<![가-힣A-Za-z0-9]){re.escape(alias)}",
            canonical,
            text,
            flags=re.IGNORECASE,
        )
    return re.sub(
        rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])",
        canonical,
        text,
        flags=re.IGNORECASE,
    )


def _strip_korean_particle(value: str) -> str:
    particles = ("들에는", "들에게", "께서는", "에서는", "으로", "에게", "처럼", "라는", "라고", "께서", "들을", "들이", "들은", "은", "는", "이", "가", "을", "를", "도", "에", "의", "만", "와", "과", "들")
    compact = _compact(value)
    for particle in particles:
        if compact.endswith(particle) and len(compact) - len(particle) >= 2:
            return compact[: -len(particle)]
    return compact


def _phonetic_ratio(left: str, right: str) -> float:
    left_jamo = _hangul_jamo(left)
    right_jamo = _hangul_jamo(right)
    return _edit_distance(left_jamo, right_jamo) / max(
        len(left_jamo), len(right_jamo), 1
    )


def _canonicalize_video_local_identity(
    text: str,
    local_map: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve only a unique, explicitly named run-local identity."""
    output = str(text or "")
    changes: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    identities = [
        item
        for item in local_map.get("named_entities") or []
        if int(item.get("evidence_score") or 0) >= 7
    ]
    if len(identities) != 1:
        return output, changes, candidates
    identity = identities[0]
    short = str(identity.get("short_korean") or "").strip()
    full = str(identity.get("canonical_korean") or "").strip()
    if len(short) < 2 or not full:
        return output, changes, candidates

    # Honorific use is a strong syntactic identity signal.  The literal name is
    # not learned globally; only the current video's explicit display metadata
    # supplies the canonical form.
    honorific_pattern = re.compile(r"(?P<surface>[가-힣]{2,8})\s*님")
    for match in list(honorific_pattern.finditer(output)):
        surface = match.group("surface")
        ratio = _phonetic_ratio(surface, short)
        syllable_distance = _edit_distance(_compact(surface), _compact(short))
        if surface == short or ratio <= 0.26 or (
            len(_compact(surface)) == len(_compact(short)) == 2
            and syllable_distance == 1
        ):
            replacement = f"{short}님"
            before = match.group(0)
            output = output[: match.start()] + replacement + output[match.end() :]
            if before != replacement:
                changes.append(
                    {
                        "from": before,
                        "to": replacement,
                        "reason": "video_local_person_identity_consistency",
                        "confidence": "high",
                        "evidence_type": "explicit_channel_or_creator_metadata",
                    }
                )
            break

    # A creator-prefix form may omit the honorific.  Require the canonical
    # prefix plus a close full-name pronunciation so unrelated names are safe.
    prefix = full.split()[0] if len(full.split()) > 1 else ""
    if prefix:
        for match in list(_HANGUL_TOKEN_RE.finditer(output)):
            token = match.group(0)
            stem = _strip_korean_particle(token)
            if not stem.startswith(prefix) or stem == _compact(full):
                continue
            ratio = _phonetic_ratio(stem, _compact(full))
            syllable_distance = _edit_distance(stem, _compact(full))
            if ratio <= 0.34 or (
                len(stem) == len(_compact(full))
                and syllable_distance <= 2
            ):
                replacement = token.replace(stem, full, 1)
                output = output[: match.start()] + replacement + output[match.end() :]
                changes.append(
                    {
                        "from": token,
                        "to": replacement,
                        "reason": "video_local_creator_identity_consistency",
                        "confidence": "high",
                        "evidence_type": "explicit_channel_or_creator_metadata",
                    }
                )
                break

    # Preserve auditable evidence even when a near name is too weak to apply.
    if not changes:
        for match in honorific_pattern.finditer(output):
            surface = match.group("surface")
            ratio = _phonetic_ratio(surface, short)
            if 0 < ratio <= 0.34:
                candidates.append(
                    {
                        "surface": match.group(0),
                        "reason": "video_local_person_identity_near_match",
                        "candidate_names": [full],
                        "distance_ratio": round(ratio, 4),
                    }
                )
    return output, changes, candidates


def _canonicalize_discourse_entities(
    text: str,
    nearby_texts: list[str],
    registry: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Use adjacent dialogue as evidence without merging utterance ownership."""
    output = str(text or "")
    changes: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    nearby = "\n".join(nearby_texts)
    nearby_words = {
        _strip_korean_particle(word) if re.search(r"[가-힣]", word) else word
        for word in _WORD_RE.findall(nearby)
    }
    current_words = {
        _strip_korean_particle(word) if re.search(r"[가-힣]", word) else word
        for word in _WORD_RE.findall(output)
    }

    # Acronym continuity: one-character loss, immediate context, and a shared
    # concept word are all required.  A standalone LM-like token is untouched.
    current_acronyms = re.findall(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9]{1,4}(?![A-Za-z0-9])", output)
    nearby_acronyms = set(re.findall(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9]{1,4}(?![A-Za-z0-9])", nearby))
    shared_concepts = {
        word for word in current_words & nearby_words if re.search(r"[가-힣]", word) and len(word) >= 2
    }
    if not shared_concepts:
        shared_concepts = {
            current[:2]
            for current in current_words
            for prior in nearby_words
            if re.fullmatch(r"[가-힣]{2,}", current)
            and re.fullmatch(r"[가-힣]{2,}", prior)
            and current[:2] == prior[:2]
        }
    for observed in current_acronyms:
        ranked = sorted(
            canonical
            for canonical in nearby_acronyms
            if len(canonical) == len(observed) + 1
            and _edit_distance(observed, canonical) == 1
        )
        if len(ranked) == 1 and shared_concepts:
            replacement = ranked[0]
            output = re.sub(
                rf"(?<![A-Za-z0-9]){re.escape(observed)}(?![A-Za-z0-9])",
                replacement,
                output,
            )
            changes.append(
                {
                    "from": observed,
                    "to": replacement,
                    "reason": "adjacent_dialogue_acronym_continuity",
                    "confidence": "high",
                    "evidence_type": "nearby_confirmed_entity_and_shared_concept",
                }
            )

    for entity in registry["entities"]:
        if entity.tier not in {"A", "B"} or not _contains_phrase(nearby, entity.canonical_name):
            continue
        for match in list(_HANGUL_TOKEN_RE.finditer(output)):
            token = match.group(0)
            stem = _strip_korean_particle(token)
            ranked: list[float] = []
            for pronunciation in entity.pronunciations:
                compact_pronunciation = _compact(pronunciation)
                ratio = _phonetic_ratio(stem, compact_pronunciation)
                compatible_suffix_loss = bool(
                    len(stem) >= 2
                    and len(compact_pronunciation) > len(stem)
                    and abs(len(stem) - len(compact_pronunciation)) <= 2
                    and stem[-2:] == compact_pronunciation[-2:]
                    and ratio <= 0.45
                )
                conservative_near_match = bool(
                    abs(len(stem) - len(compact_pronunciation)) <= 1
                    and ratio <= 0.22
                )
                if compatible_suffix_loss or conservative_near_match:
                    ranked.append(ratio)
            if ranked and min(ranked) <= 0.45:
                replacement = token.replace(stem, entity.canonical_name, 1)
                output = output[: match.start()] + replacement + output[match.end() :]
                changes.append(
                    {
                        "from": token,
                        "to": replacement,
                        "reason": "adjacent_dialogue_official_entity_continuity",
                        "confidence": "high",
                        "evidence_type": "nearby_confirmed_entity_and_compatible_pronunciation",
                    }
                )
                break
    return output, changes, candidates


def _canonicalize_entities(
    text: str,
    context: str,
    registry: dict[str, Any],
    local_map: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    output = str(text or "")
    changes: list[dict[str, Any]] = []
    near_candidates: list[dict[str, Any]] = []
    local_by_name = {
        item["canonical_name"]: item for item in local_map.get("entities") or []
    }

    entities = sorted(
        registry["entities"],
        key=lambda item: max(
            [len(value) for value in (*item.aliases, *item.pronunciations)] or [0]
        ),
        reverse=True,
    )
    for entity in entities:
        full_context = f"{context}\n{output}\n{local_map.get('metadata_context', '')}"
        if not _context_supported(entity, full_context):
            continue
        for alias in sorted(entity.pronunciations, key=len, reverse=True):
            replaced = _replace_literal_alias(output, alias, entity.canonical_name)
            if replaced != output:
                changes.append(
                    {
                        "from": alias,
                        "to": entity.canonical_name,
                        "reason": "verified_registry_pronunciation",
                        "confidence": "high",
                        "evidence_type": "global_canonical_registry",
                    }
                )
                output = replaced

    hangul_tokens = list(_HANGUL_TOKEN_RE.finditer(output))
    observed_windows: list[str] = [_strip_korean_particle(match.group(0)) for match in hangul_tokens]
    for index in range(len(hangul_tokens) - 1):
        left, right = hangul_tokens[index], hangul_tokens[index + 1]
        if not output[left.end() : right.start()].strip():
            observed_windows.append(
                f"{_strip_korean_particle(left.group(0))} "
                f"{_strip_korean_particle(right.group(0))}"
            )
    for observed in observed_windows:
        observed_jamo = _hangul_jamo(observed)
        ranked: list[tuple[float, Entity, str]] = []
        for entity in entities:
            evidence = local_by_name.get(entity.canonical_name) or {}
            if not entity.context_anchors:
                continue
            if evidence.get("evidence_score", 0) < 2 and not (
                entity.category == "UI_feature" and "모드" in observed
            ):
                continue
            full_context = f"{context}\n{output}\n{local_map.get('metadata_context', '')}"
            if not _context_supported(entity, full_context):
                continue
            for alias in entity.pronunciations:
                compact_alias = _compact(alias)
                if not compact_alias or abs(len(_compact(observed)) - len(compact_alias)) > 1:
                    continue
                alias_jamo = _hangul_jamo(alias)
                distance = _edit_distance(observed_jamo, alias_jamo)
                ratio = distance / max(len(observed_jamo), len(alias_jamo), 1)
                if 0 < ratio <= 0.28:
                    ranked.append((ratio, entity, alias))
        ranked.sort(key=lambda item: (item[0], item[1].canonical_name))
        deduplicated: list[tuple[float, Entity, str]] = []
        seen_names: set[str] = set()
        for item in ranked:
            if item[1].canonical_name in seen_names:
                continue
            deduplicated.append(item)
            seen_names.add(item[1].canonical_name)
        ranked = deduplicated
        if not ranked:
            continue
        best = ranked[0]
        if len(ranked) > 1 and abs(ranked[1][0] - best[0]) < 0.03:
            near_candidates.append(
                {
                    "surface": observed,
                    "reason": "ambiguous_registry_near_match",
                    "candidate_names": [best[1].canonical_name, ranked[1][1].canonical_name],
                }
            )
            continue
        best_evidence = local_by_name.get(best[1].canonical_name) or {}
        if best_evidence.get("evidence_score", 0) >= 3:
            replaced = _replace_literal_alias(output, observed, best[1].canonical_name)
            if replaced != output:
                changes.append(
                    {
                        "from": observed,
                        "to": best[1].canonical_name,
                        "reason": "unique_video_supported_registry_near_match",
                        "confidence": "high",
                        "evidence_type": "repeated_video_entity_evidence",
                    }
                )
                output = replaced
                continue
        near_candidates.append(
            {
                "surface": observed,
                "reason": "registry_pronunciation_near_match",
                "candidate_names": [best[1].canonical_name],
                "distance_ratio": round(best[0], 4),
            }
        )

    return output, changes, near_candidates


def _deterministic_korean_spacing(text: str) -> tuple[str, list[dict[str, Any]]]:
    output = str(text or "")
    changes: list[dict[str, Any]] = []

    def split_boundary(match: re.Match[str]) -> str:
        before = match.group(0)
        after = f"{match.group('prefix')} 이"
        changes.append(
            {
                "from": before,
                "to": after,
                "reason": "korean_bound_determiner_spacing",
                "confidence": "high",
                "evidence_type": "korean_grammar_rule",
            }
        )
        return after

    output = _ATTACHED_BOUNDARY_RE.sub(split_boundary, output)

    def remove_attached_adverb_i(match: re.Match[str]) -> str:
        before = match.group(0)
        after = match.group("prefix")
        changes.append(
            {
                "from": before,
                "to": after,
                "reason": "korean_attached_boundary_artifact",
                "confidence": "high",
                "evidence_type": "conservative_korean_adverb_boundary_rule",
            }
        )
        return after

    output = _ATTACHED_ADVERB_I_RE.sub(remove_attached_adverb_i, output)

    def split_attached_discourse_i(match: re.Match[str]) -> str:
        before = match.group(0)
        after = f"{match.group('prefix')} 이"
        changes.append(
            {
                "from": before,
                "to": after,
                "reason": "korean_discourse_boundary_artifact",
                "confidence": "high",
                "evidence_type": "conservative_korean_discourse_boundary_rule",
            }
        )
        return after

    output = _ATTACHED_DISCOURSE_I_RE.sub(split_attached_discourse_i, output)

    def remove_duplicate_particle(match: re.Match[str]) -> str:
        before = match.group(0)
        after = before[: len(before) // 2]
        changes.append(
            {
                "from": before,
                "to": after,
                "reason": "duplicated_korean_particle",
                "confidence": "high",
                "evidence_type": "korean_grammar_rule",
            }
        )
        return after

    output = re.sub(r"(?:은은|는는|을을|를를|에서에서|으로로)", remove_duplicate_particle, output)

    def remove_filler(match: re.Match[str]) -> str:
        before = match.group(0)
        after = f"{match.group('prefix')},"
        changes.append(
            {
                "from": before,
                "to": after,
                "reason": "asr_filler_after_connective",
                "confidence": "high",
                "evidence_type": "korean_grammar_rule",
            }
        )
        return after

    output = _FILLER_AFTER_CONNECTIVE_RE.sub(remove_filler, output)
    output = re.sub(r"\s+([,.!?])", r"\1", output)
    output = re.sub(r"\s{2,}", " ", output).strip()
    return output, changes


def _lexical_outlier_scores(rows: list[dict[str, Any]]) -> dict[str, float]:
    counts: Counter[str] = Counter()
    token_rows: dict[str, list[str]] = {}
    for row in rows:
        row_id = str(row.get("utterance_id") or "")
        tokens = _WORD_RE.findall(str(row.get("normalized_text") or ""))
        token_rows[row_id] = tokens
        counts.update(token.casefold() for token in tokens)

    scores: dict[str, float] = {}
    for row in rows:
        row_id = str(row.get("utterance_id") or "")
        text = str(row.get("normalized_text") or "")
        tokens = token_rows.get(row_id, [])
        rare = [
            token
            for token in tokens
            if counts[token.casefold()] == 1 and 2 <= len(token) <= 8
        ]
        ratio = len(rare) / max(len(tokens), 1)
        scores[row_id] = (
            ratio * 5.0
            + (1.0 if len(text) < 80 and rare else 0.0)
            + min(len(rare), 5) * 0.1
        )
    return scores


def _embedded_metadata_term(text: str, terms: list[str]) -> bool:
    for token in _HANGUL_TOKEN_RE.findall(text):
        for term in terms:
            if len(term) < 2 or token == term:
                continue
            # A normal Korean particle/suffix follows the metadata term.  The
            # useful anomaly signal is an unexplained prefix fused in front of
            # a strong title/chapter term (for example, a broken entity span).
            position = token.find(term)
            if 1 <= position <= 4 and len(token) - len(term) <= 6:
                return True
    return False


def _acronym_inconsistency(text: str, whole_text: str) -> bool:
    pattern = r"(?<![A-Za-z0-9])[A-Z][A-Z0-9]{1,4}(?![A-Za-z0-9])"
    repeated = Counter(re.findall(pattern, whole_text))
    for observed in re.findall(pattern, text):
        for canonical, count in repeated.items():
            if canonical == observed or count < 1 or len(canonical) != len(observed):
                continue
            if _edit_distance(observed, canonical) == 1:
                return True
    return False


def _within_row_lexical_inconsistency(text: str, whole_text: str) -> bool:
    particles = ("에서는", "으로", "에게", "처럼", "라는", "라고", "은", "는", "이", "가", "을", "를", "도", "에")

    def stem(token: str) -> str:
        for particle in particles:
            if token.endswith(particle) and len(token) - len(particle) >= 2:
                return token[: -len(particle)]
        return token

    whole_stems = Counter(stem(token) for token in _HANGUL_TOKEN_RE.findall(whole_text))
    row_stems = list(dict.fromkeys(stem(token) for token in _HANGUL_TOKEN_RE.findall(text)))
    for left in row_stems:
        for right in row_stems:
            if left >= right or len(left) != len(right) or len(left) < 2:
                continue
            if _edit_distance(left, right) != 1:
                continue
            if min(whole_stems[left], whole_stems[right]) == 1 and max(
                whole_stems[left], whole_stems[right]
            ) >= 8:
                return True
    return False


def _protected_term_near_match(
    text: str,
    whole_text: str,
    protected_terms: list[str],
) -> bool:
    observed = {
        _strip_korean_particle(token) for token in _HANGUL_TOKEN_RE.findall(text)
    }
    for term in protected_terms:
        compact_term = _compact(term)
        if " " in term or len(compact_term) < 2:
            continue
        term_jamo = _hangul_jamo(compact_term)
        for token in observed:
            if token == compact_term or abs(len(token) - len(compact_term)) > 1:
                continue
            token_jamo = _hangul_jamo(token)
            ratio = _edit_distance(token_jamo, term_jamo) / max(
                len(token_jamo), len(term_jamo), 1
            )
            if ratio <= 0.22 and (
                compact_term in _compact(whole_text)
                or sum(
                    1 for value in protected_terms if _compact(value) in _compact(text)
                ) >= 1
            ):
                return True
    return False


def _technical_domain_phrase_near_match(
    text: str,
    protected_terms: list[str],
) -> bool:
    compact_text = _compact(text)
    exact_domain = sum(1 for term in protected_terms if _compact(term) in compact_text)
    observed_list = [
        _strip_korean_particle(token) for token in _HANGUL_TOKEN_RE.findall(text)
    ]
    observed = set(observed_list)
    has_multi_term_anchor = any(
        any(_compact(part) in observed for part in term.split())
        for term in protected_terms
        if " " in term
    )
    if exact_domain < 1 and not has_multi_term_anchor:
        return False
    near_count = 0
    for token in observed:
        for term in protected_terms:
            compact_term = _compact(term)
            if " " in term:
                parts = [_compact(part) for part in term.split() if len(_compact(part)) >= 2]
                for start in range(0, len(observed_list) - len(parts) + 1):
                    window = observed_list[start : start + len(parts)]
                    exact = [candidate == part for candidate, part in zip(window, parts)]
                    near = [
                        candidate != part
                        and abs(len(candidate) - len(part)) <= 1
                        and (
                            _phonetic_ratio(candidate, part) <= 0.50
                            or _edit_distance(candidate, part) == 1
                        )
                        for candidate, part in zip(window, parts)
                    ]
                    if any(exact) and any(near) and all(
                        same or close for same, close in zip(exact, near)
                    ):
                        return True
                continue
            if token == compact_term or len(compact_term) < 4:
                continue
            ratio = _phonetic_ratio(token, compact_term)
            if ratio <= 0.42 and token[:1] == compact_term[:1]:
                near_count += 1
                break
    return near_count >= 1


def detect_suspicious_utterances(
    result: dict[str, Any],
    local_map: dict[str, Any],
    deterministic_by_id: dict[str, list[dict[str, Any]]] | None = None,
    near_by_id: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    rows = [
        row for row in result.get("normalized_utterances") or [] if isinstance(row, dict)
    ]
    lexical_scores = _lexical_outlier_scores(rows)
    deterministic_by_id = deterministic_by_id or {}
    near_by_id = near_by_id or {}
    whole_text = "\n".join(str(row.get("normalized_text") or "") for row in rows)
    metadata_terms = list(local_map.get("title_and_chapter_terms") or [])
    acronym_pattern = r"(?<![A-Za-z0-9])[A-Z][A-Z0-9]{1,4}(?![A-Za-z0-9])"
    acronym_counts = Counter(re.findall(acronym_pattern, whole_text))
    known_acronyms = {
        str(item.get("canonical_name") or "")
        for item in local_map.get("entities") or []
        if re.fullmatch(r"[A-Z][A-Z0-9]{1,4}", str(item.get("canonical_name") or ""))
    }

    chapter_ranks: dict[str, int] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("chapter_id") or "FULL")].append(row)
    for group in grouped.values():
        ranked = sorted(
            group,
            key=lambda row: (
                -lexical_scores.get(str(row.get("utterance_id") or ""), 0.0),
                float(row.get("start_seconds") or 0.0),
            ),
        )
        for rank, row in enumerate(ranked, 1):
            chapter_ranks[str(row.get("utterance_id") or "")] = rank

    detected: list[dict[str, Any]] = []
    enough_video_context = len(rows) >= 8
    for index, row in enumerate(rows):
        row_id = str(row.get("utterance_id") or f"ROW-{index + 1}")
        text = str(row.get("normalized_text") or "")
        signals: list[str] = []
        score = lexical_scores.get(row_id, 0.0)

        if _SUSPICIOUS_JOIN_RE.search(text) or _REPEATED_PARTICLE_RE.search(text):
            signals.append("malformed_korean_join")
            score += 4.0
        if _ATTACHED_ADVERB_I_RE.search(text):
            signals.append("attached_token_boundary_artifact")
            score += 4.0
        if _ATTACHED_DISCOURSE_I_RE.search(text):
            signals.append("attached_token_boundary_candidate")
            score += 4.0
        if _DIGIT_HANGUL_FUSION_RE.search(text) or _LATIN_HANGUL_FUSION_RE.search(text):
            signals.append("malformed_script_boundary")
            score += 3.0
        if _BROKEN_COMPOUND_RE.search(text):
            signals.append("broken_korean_compound")
            score += 3.0
        if _TOOL_DUPLICATION_RE.search(text):
            signals.append("loanword_semantic_duplication")
            score += 3.0
        if _UNUSUAL_WO_CONNECTIVE_RE.search(text):
            signals.append("unusual_korean_connective_sequence")
            score += 4.0
        if _SHORT_STRUCTURE_MODIFIER_RE.search(text):
            signals.append("short_technical_modifier_needs_context_review")
            score += 3.0
        if _TENTATIVE_STEP_RE.search(text):
            signals.append("contextually_unusual_action_verb")
            score += 3.0
        if _PAST_DEMONSTRATION_RE.search(text):
            signals.append("past_demonstration_verb_needs_review")
            score += 3.0
        if _UNVERIFIED_KIT_RE.search(text) and re.search(
            r"(?:UI|디자인\s*시스템|오픈\s*소스|컴포넌트)", text
        ):
            signals.append("unverified_official_name_candidate")
            score += 4.0
        if near_by_id.get(row_id):
            signals.append("canonical_alias_near_match")
            score += 4.0
        if _embedded_metadata_term(text, metadata_terms):
            signals.append("metadata_term_embedded_in_unknown_token")
            score += 3.0
        if _within_row_lexical_inconsistency(text, whole_text):
            signals.append("within_row_lexical_inconsistency")
            score += 3.0
        if _protected_term_near_match(
            text,
            whole_text,
            list(local_map.get("protected_korean_concepts") or []),
        ):
            signals.append("protected_korean_term_near_match")
            score += 4.0
        if _technical_domain_phrase_near_match(
            text, list(local_map.get("protected_korean_concepts") or [])
        ):
            signals.append("technical_domain_phrase_near_match")
            score += 4.0
        nearby_text = "\n".join(
            str(rows[position].get("normalized_text") or "")
            for position in range(max(0, index - 1), min(len(rows), index + 2))
            if position != index
        )
        if _acronym_inconsistency(text, nearby_text):
            signals.append("acronym_discourse_inconsistency")
            score += 4.0
        if any(
            acronym_counts[token] == 1 and token not in known_acronyms
            for token in re.findall(acronym_pattern, text)
        ):
            signals.append("singleton_unregistered_acronym")
            score += 3.0
        if deterministic_by_id.get(row_id) and lexical_scores.get(row_id, 0.0) >= 2.0:
            signals.append("deterministic_fix_with_remaining_lexical_outlier")
            score += 2.0
        if (
            lexical_scores.get(row_id, 0.0) >= 2.0
            and any(
                str(change.get("reason") or "")
                in {
                    "korean_attached_boundary_artifact",
                    "korean_discourse_boundary_artifact",
                    "duplicated_korean_particle",
                }
                for change in deterministic_by_id.get(row_id) or []
            )
        ):
            signals.append("deterministic_boundary_fix_with_remaining_audio_review")
            score += 3.0
        if (
            enough_video_context
            and (
                (
                    chapter_ranks.get(row_id, 999) <= 6
                    and lexical_scores.get(row_id, 0.0) >= 1.8
                )
                or lexical_scores.get(row_id, 0.0) >= 3.35
            )
        ):
            signals.append("video_local_lexical_outlier")
        deterministic_changes = deterministic_by_id.get(row_id) or []
        pure_verified_entity_change = bool(deterministic_changes) and all(
            str(change.get("reason") or "")
            in {
                "verified_registry_pronunciation",
                "unique_video_supported_registry_near_match",
                "adjacent_dialogue_official_entity_continuity",
                "adjacent_dialogue_acronym_continuity",
                "video_local_person_identity_consistency",
                "video_local_creator_identity_consistency",
            }
            for change in deterministic_changes
        )
        if lexical_scores.get(row_id, 0.0) >= 3.35 and not pure_verified_entity_change:
            signals.append("severe_video_local_lexical_outlier")
            score += 3.0

        if signals:
            detected.append(
                {
                    "row_index": index,
                    "utterance_id": row_id,
                    "chapter_id": row.get("chapter_id"),
                    "start_seconds": row.get("start_seconds"),
                    "text": text,
                    "signals": sorted(set(signals)),
                    "suspicion_score": round(score, 4),
                    "chapter_rank": chapter_ranks.get(row_id),
                }
            )
    return detected


def _select_for_model(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_chapter: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_chapter[str(record.get("chapter_id") or "FULL")].append(record)
    for items in by_chapter.values():
        items.sort(key=lambda item: (-item["suspicion_score"], item["row_index"]))

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    broad_signals = {
        "video_local_lexical_outlier",
        "within_row_lexical_inconsistency",
    }
    critical_signals = {
        "canonical_alias_near_match",
        "malformed_korean_join",
        "broken_korean_compound",
        "loanword_semantic_duplication",
        "unusual_korean_connective_sequence",
        "metadata_term_embedded_in_unknown_token",
        "short_technical_modifier_needs_context_review",
        "unverified_official_name_candidate",
        "contextually_unusual_action_verb",
        "past_demonstration_verb_needs_review",
        "protected_korean_term_near_match",
    }

    def priority(item: dict[str, Any]) -> tuple[int, float, int]:
        signals = set(item.get("signals") or [])
        if signals & critical_signals:
            level = 0
        elif (
            "deterministic_fix_with_remaining_lexical_outlier" in signals
            or "singleton_unregistered_acronym" in signals
        ):
            level = 1
        elif float(item.get("suspicion_score") or 0.0) >= 4.5:
            level = 2
        else:
            level = 3
        return (level, -float(item.get("suspicion_score") or 0.0), int(item["row_index"]))

    strong = sorted(
        (
            item
            for item in records
            if (
                set(item.get("signals") or []) - broad_signals
                or float(item.get("suspicion_score") or 0.0) >= 4.5
            )
        ),
        key=priority,
    )
    for item in strong:
        selected.append(item)
        selected_ids.add(item["utterance_id"])
        if len(selected) >= MAX_MODEL_REVIEW_ROWS:
            return selected
    for depth in range(3):
        for chapter in sorted(by_chapter):
            items = by_chapter[chapter]
            if depth >= len(items):
                continue
            item = items[depth]
            if item["utterance_id"] in selected_ids:
                continue
            selected.append(item)
            selected_ids.add(item["utterance_id"])
            if len(selected) >= MAX_MODEL_REVIEW_ROWS:
                return selected
    for item in sorted(records, key=lambda value: (-value["suspicion_score"], value["row_index"])):
        if item["utterance_id"] in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(item["utterance_id"])
        if len(selected) >= MAX_MODEL_REVIEW_ROWS:
            break
    return selected


def _system_prompt() -> str:
    return (
        "You are a conservative Korean ASR repair auditor, not a rewriter or translator. "
        "Review only CURRENT utterances. PREVIOUS/NEXT are context-only and must never be copied. "
        "Repair only clear ASR corruption whose intended wording is sufficiently supported. "
        "Preserve meaning, actor, action, target, numbers, dates, money, product-tool relationships, "
        "and all already-correct official entities. Official product/tool/model/framework/UI feature "
        "names use verified Latin spelling; general Korean design terms stay Korean. "
        "Do not invent people, companies, services, or expand an ambiguous acronym. "
        "If evidence is insufficient, return unresolved. Every repair must be represented only by "
        "literal non-overlapping from/to changes within CURRENT. Do not make undeclared edits. "
        "Use at most 3 changes. Keep each reason under 20 Korean words and evidence to at most 3 short labels. "
        "Return one JSON object only: "
        '{"reviews":[{"utterance_id":"UT-00001","decision":"keep|repair|unresolved",'
        '"corrected_text":"...","confidence":"high|medium|low",'
        '"changes":[{"from":"...","to":"...","reason":"..."}],'
        '"evidence":["..."]}]}'
    )


def _build_user_prompt(
    selected: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    source: dict[str, Any],
    registry: dict[str, Any],
    local_map: dict[str, Any],
) -> str:
    metadata = source.get("metadata") or {}
    entity_evidence = [
        item
        for item in local_map.get("entities") or []
        if item.get("evidence_score", 0) > 0
    ]
    payload_rows = []
    for record in selected:
        index = int(record["row_index"])
        current = rows[index]
        payload_rows.append(
            {
                "utterance_id": record["utterance_id"],
                "signals": record["signals"],
                "previous": (
                    str(rows[index - 1].get("normalized_text") or "")
                    if index > 0
                    else ""
                ),
                "current": str(current.get("normalized_text") or ""),
                "raw_source_text": str(current.get("raw_joined_text") or ""),
                "next": (
                    str(rows[index + 1].get("normalized_text") or "")
                    if index + 1 < len(rows)
                    else ""
                ),
                "creator_chapter_label": str(current.get("chapter_label") or ""),
            }
        )
    payload = {
        "video_title": str(metadata.get("title") or ""),
        "verified_entity_evidence": entity_evidence,
        "video_local_latin_evidence": local_map.get("repeated_unregistered_latin_forms") or [],
        "protected_general_korean_terms": list(registry["protected_korean_concepts"]),
        "rows": payload_rows,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _parse_response(core: Any, text: str) -> dict[str, Any]:
    extractor = getattr(core, "_extract_json_object_v032", None)
    try:
        if callable(extractor):
            parsed = extractor(text)
        else:
            value = str(text or "").strip()
            value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
            value = re.sub(r"\s*```$", "", value)
            start, end = value.find("{"), value.rfind("}")
            parsed = json.loads(value[start : end + 1])
    except Exception:
        recovered = _recover_complete_review_objects(str(text or ""))
        if not recovered:
            raise
        parsed = {"reviews": recovered, "_partial_json_recovery": True}
    if not isinstance(parsed, dict) or not isinstance(parsed.get("reviews"), list):
        raise ValueError("editorial review response must contain reviews[]")
    return parsed


def _recover_complete_review_objects(value: str) -> list[dict[str, Any]]:
    marker = re.search(r'"reviews"\s*:\s*\[', value)
    if marker is None:
        return []
    objects: list[dict[str, Any]] = []
    depth = 0
    start: int | None = None
    in_string = False
    escaped = False
    for index in range(marker.end(), len(value)):
        char = value[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    item = json.loads(value[start : index + 1])
                except Exception:
                    start = None
                    continue
                if isinstance(item, dict):
                    objects.append(item)
                start = None
    return objects


def _apply_declared_changes(before: str, changes: list[dict[str, Any]]) -> str:
    output = before
    used: list[tuple[int, int]] = []
    for change in changes:
        old = str(change.get("from") or "")
        new = str(change.get("to") or "")
        if not old or not new or old == new:
            raise ValueError("empty_or_noop_change")
        matches = list(re.finditer(re.escape(old), output))
        if len(matches) != 1:
            raise ValueError("change_source_not_unique")
        match = matches[0]
        if any(match.start() < end and match.end() > start for start, end in used):
            raise ValueError("overlapping_changes")
        output = output[: match.start()] + new + output[match.end() :]
        delta = len(new) - len(old)
        used = [
            (start + (delta if start >= match.end() else 0), end + (delta if end >= match.end() else 0))
            for start, end in used
        ]
        used.append((match.start(), match.start() + len(new)))
    return output


def _adjacent_leakage(before: str, after: str, adjacent: list[str]) -> bool:
    before_compact = re.sub(r"\s+", "", before)
    after_compact = re.sub(r"\s+", "", after)
    for text in adjacent:
        compact = re.sub(r"\s+", "", text)
        for size in (18, 14, 10):
            if len(compact) < size:
                continue
            for start in range(0, len(compact) - size + 1, max(1, size // 2)):
                phrase = compact[start : start + size]
                if phrase in after_compact and phrase not in before_compact:
                    return True
    return False


def _fidelity_guard(
    before: str,
    review: dict[str, Any],
    *,
    adjacent: list[str],
    registry: dict[str, Any],
    local_map: dict[str, Any],
) -> tuple[bool, str, str]:
    changes = review.get("changes") or []
    corrected = str(review.get("corrected_text") or "")
    if not isinstance(changes, list) or not (1 <= len(changes) <= 4):
        return False, before, "invalid_change_count"
    changed_source_chars = sum(len(str(change.get("from") or "")) for change in changes)
    if any(len(str(change.get("from") or "")) > 60 for change in changes):
        return False, before, "change_span_too_large"
    if changed_source_chars > max(60, int(len(before) * 0.4)):
        return False, before, "too_much_source_claimed_as_asr_error"
    try:
        reconstructed = _apply_declared_changes(before, changes)
    except ValueError as exc:
        return False, before, str(exc)
    if reconstructed != corrected:
        return False, before, "undeclared_text_change"
    if _NUMBER_RE.findall(before) != _NUMBER_RE.findall(corrected):
        return False, before, "numbers_dates_or_amounts_changed"
    if len(corrected) < max(1, int(len(before) * 0.65)) or len(corrected) > int(len(before) * 1.35) + 8:
        return False, before, "excessive_rewrite"
    if _adjacent_leakage(before, corrected, adjacent):
        return False, before, "adjacent_row_content_leakage"

    before_latin = {token.casefold() for token in _LATIN_TOKEN_RE.findall(before)}
    after_latin = {token.casefold() for token in _LATIN_TOKEN_RE.findall(corrected)}
    known = {entity.canonical_name.casefold() for entity in registry["entities"]}
    known_latin_tokens = {
        token.casefold()
        for entity in registry["entities"]
        for token in _LATIN_TOKEN_RE.findall(entity.canonical_name)
    }
    allowed_new = known | known_latin_tokens | {
        str(value).casefold()
        for value in local_map.get("repeated_unregistered_latin_forms") or []
    }
    removed = before_latin - after_latin
    if removed:
        return False, before, "existing_latin_entity_or_acronym_removed"
    if any(token not in allowed_new for token in after_latin - before_latin):
        return False, before, "unsupported_new_latin_entity"
    for term in registry["protected_korean_concepts"]:
        if term in before and term not in corrected:
            return False, before, "protected_korean_concept_removed"
    return True, corrected, "passed"


def _next_normalization_number(items: list[dict[str, Any]]) -> int:
    maximum = 0
    for item in items:
        match = re.fullmatch(r"NM-(\d+)", str(item.get("normalization_id") or ""))
        if match:
            maximum = max(maximum, int(match.group(1)))
    return maximum + 1


def _mark_unresolved(
    result: dict[str, Any],
    row: dict[str, Any],
    record: dict[str, Any],
    reason: str,
    confidence: str = "low",
) -> None:
    warning = f"korean_asr_editorial_review:{reason}"
    warnings = row.setdefault("validation_warnings", [])
    if warning not in warnings:
        warnings.append(warning)
    row["review_status"] = "needs_review"
    unresolved = result.setdefault("unresolved_terms", [])
    key = (str(row.get("utterance_id") or ""), reason)
    if not any(
        (str(item.get("utterance_id") or ""), str(item.get("reason") or "")) == key
        for item in unresolved
        if isinstance(item, dict)
    ):
        unresolved.append(
            {
                "utterance_id": row.get("utterance_id"),
                "text": row.get("normalized_text"),
                "reason": reason,
                "confidence": confidence,
                "evidence_type": record.get("signals") or [],
                "review_status": "needs_review",
                "stage": "korean_asr_editorial_review",
            }
        )


def apply_korean_asr_editorial_review(
    result: dict[str, Any],
    source: dict[str, Any],
    *,
    core: Any,
    model_name: str | None = None,
    allow_model_review: bool = True,
    generator: Callable[[str, str, str, int], str] | None = None,
) -> dict[str, Any]:
    """Conservatively edit only suspicious Korean normalized utterances."""
    started = time.perf_counter()
    if not isinstance(result, dict) or not isinstance(source, dict):
        return result
    if not _source_language(result, source).startswith("ko"):
        return result
    if result.get("translation_required") is True:
        return result

    registry = load_canonical_registry()
    local_map = build_video_local_entity_map(result, source, registry)
    rows = [
        row for row in result.get("normalized_utterances") or [] if isinstance(row, dict)
    ]
    normalization_items = result.setdefault("normalization_items", [])
    next_number = _next_normalization_number(normalization_items)
    deterministic_by_id: dict[str, list[dict[str, Any]]] = {}
    near_by_id: dict[str, list[dict[str, Any]]] = {}
    changed_items: list[dict[str, Any]] = []

    deterministic_started = time.perf_counter()
    for index, row in enumerate(rows):
        row_id = str(row.get("utterance_id") or f"ROW-{index + 1}")
        before = str(row.get("normalized_text") or "")
        context = "\n".join(
            str(rows[position].get("normalized_text") or "")
            for position in range(max(0, index - 2), min(len(rows), index + 3))
        )
        spaced, spacing_changes = _deterministic_korean_spacing(before)
        local_identity, identity_changes, identity_near = _canonicalize_video_local_identity(
            spaced, local_map
        )
        nearby_texts = [
            str(rows[position].get("normalized_text") or "")
            for position in range(max(0, index - 2), min(len(rows), index + 3))
            if position != index
        ]
        discourse, discourse_changes, discourse_near = _canonicalize_discourse_entities(
            local_identity, nearby_texts, registry
        )
        canonical, entity_changes, near = _canonicalize_entities(
            discourse, context, registry, local_map
        )
        changes = spacing_changes + identity_changes + discourse_changes + entity_changes
        near_by_id[row_id] = identity_near + discourse_near + near
        if canonical == before:
            row["korean_editorial_state"] = "clean"
            continue
        row["normalized_text"] = canonical
        row["auto_normalized_text"] = canonical
        row["korean_editorial_state"] = "deterministic_fixed"
        deterministic_by_id[row_id] = changes
        row_ids = row.setdefault("normalization_item_ids", [])
        for change in changes:
            normalization_id = f"NM-{next_number:05d}"
            next_number += 1
            row_ids.append(normalization_id)
            normalization_items.append(
                {
                    "normalization_id": normalization_id,
                    "raw_text": change["from"],
                    "normalized_text": change["to"],
                    "normalization_type": "korean_evidence_editorial_deterministic_v0316",
                    "confidence": change["confidence"],
                    "evidence_sources": [change["evidence_type"]],
                    "affected_segment_ids": copy.deepcopy(row.get("source_segment_ids") or []),
                    "review_status": "auto_approved",
                }
            )
            changed_items.append(
                {
                    "utterance_id": row_id,
                    "before": change["from"],
                    "after": change["to"],
                    "reason": change["reason"],
                    "confidence": change["confidence"],
                    "evidence_type": change["evidence_type"],
                }
            )
    deterministic_seconds = time.perf_counter() - deterministic_started

    detection_started = time.perf_counter()
    suspicious = detect_suspicious_utterances(
        result,
        local_map,
        deterministic_by_id=deterministic_by_id,
        near_by_id=near_by_id,
    )
    detection_seconds = time.perf_counter() - detection_started
    selected = _select_for_model(suspicious) if allow_model_review else []
    selected_ids = {record["utterance_id"] for record in selected}
    record_by_id = {record["utterance_id"]: record for record in suspicious}
    row_by_id = {str(row.get("utterance_id") or ""): row for row in rows}
    for record in suspicious:
        row = row_by_id.get(record["utterance_id"])
        if row is not None:
            row["korean_editorial_state"] = "suspicious"
        if record["utterance_id"] not in selected_ids:
            if row is not None and allow_model_review:
                row["korean_editorial_state"] = "unresolved"
                _mark_unresolved(result, row, record, "review_budget_deferred")

    model_id = str(
        model_name
        or getattr(core, "_DEFAULT_LOCAL_LLM_MODEL_V034", "")
        or DEFAULT_MODEL_ID
    ).strip()
    model_calls = 0
    model_load_count = 0
    reviewed_count = 0
    model_repaired_count = 0
    model_load_seconds = 0.0
    generation_seconds = 0.0
    model_error: str | None = None
    partial_parse_recoveries = 0

    if selected:
        try:
            if generator is None:
                loader = getattr(core, "_load_local_llm_v032")
                cache = getattr(core, "_LOCAL_LLM_CACHE_V032", {})
                cached = isinstance(cache, dict) and model_id in cache
                load_started = time.perf_counter()
                loader(model_id)
                model_load_seconds = time.perf_counter() - load_started
                model_load_count = 0 if cached else 1

                def generator_fn(name: str, system: str, user: str, tokens: int) -> str:
                    return getattr(core, "_generate_local_llm_text_v033")(
                        name, system, user, tokens
                    )

                active_generator = generator_fn
            else:
                active_generator = generator

            from runtime_generation_metrics import generation_stage

            for start in range(0, len(selected), MODEL_BATCH_SIZE):
                batch = selected[start : start + MODEL_BATCH_SIZE]
                user_prompt = _build_user_prompt(batch, rows, source, registry, local_map)
                generation_started = time.perf_counter()
                try:
                    model_calls += 1
                    with generation_stage("korean_asr_editorial_review"):
                        response_text = active_generator(
                            model_id, _system_prompt(), user_prompt, MODEL_MAX_TOKENS
                        )
                    parsed = _parse_response(core, response_text)
                    if parsed.get("_partial_json_recovery"):
                        partial_parse_recoveries += 1
                except Exception as exc:
                    generation_seconds += time.perf_counter() - generation_started
                    model_error = f"{type(exc).__name__}: {exc}"
                    for record in batch:
                        row = row_by_id.get(record["utterance_id"])
                        if row is not None:
                            row["korean_editorial_state"] = "unresolved"
                            _mark_unresolved(result, row, record, "model_generation_or_parse_failed")
                    continue
                generation_seconds += time.perf_counter() - generation_started
                reviews = {
                    str(item.get("utterance_id") or ""): item
                    for item in parsed.get("reviews") or []
                    if isinstance(item, dict)
                }
                for record in batch:
                    row_id = record["utterance_id"]
                    row = row_by_id.get(row_id)
                    if row is None:
                        continue
                    review = reviews.get(row_id)
                    if review is None:
                        row["korean_editorial_state"] = "unresolved"
                        _mark_unresolved(result, row, record, "model_response_missing_row")
                        continue
                    reviewed_count += 1
                    decision = str(review.get("decision") or "unresolved").lower()
                    confidence = str(review.get("confidence") or "low").lower()
                    before = str(row.get("normalized_text") or "")
                    if decision != "repair" or confidence not in {"high", "medium"}:
                        row["korean_editorial_state"] = "unresolved" if decision == "unresolved" else "model_reviewed"
                        if decision != "keep":
                            _mark_unresolved(result, row, record, "model_unresolved", confidence)
                        continue
                    index = int(record["row_index"])
                    passed, corrected, guard_reason = _fidelity_guard(
                        before,
                        review,
                        adjacent=[
                            str(rows[position].get("normalized_text") or "")
                            for position in (index - 1, index + 1)
                            if 0 <= position < len(rows)
                        ],
                        registry=registry,
                        local_map=local_map,
                    )
                    if confidence == "medium":
                        targets = {
                            str(change.get("to") or "").casefold()
                            for change in review.get("changes") or []
                        }
                        strong_entities = {
                            str(item.get("canonical_name") or "").casefold()
                            for item in local_map.get("entities") or []
                            if item.get("evidence_score", 0) >= 3
                        }
                        if not targets or not targets.issubset(strong_entities):
                            passed = False
                            guard_reason = "medium_confidence_without_deterministic_entity_support"
                    if not passed:
                        row["korean_editorial_state"] = "unresolved"
                        _mark_unresolved(result, row, record, f"fidelity_guard:{guard_reason}", confidence)
                        continue

                    row["normalized_text"] = corrected
                    row["auto_normalized_text"] = corrected
                    row["korean_editorial_state"] = "model_reviewed"
                    row_ids = row.setdefault("normalization_item_ids", [])
                    for change in review.get("changes") or []:
                        normalization_id = f"NM-{next_number:05d}"
                        next_number += 1
                        row_ids.append(normalization_id)
                        normalization_items.append(
                            {
                                "normalization_id": normalization_id,
                                "raw_text": change.get("from"),
                                "normalized_text": change.get("to"),
                                "normalization_type": "korean_asr_editorial_model_repair_v0316",
                                "confidence": confidence,
                                "evidence_sources": copy.deepcopy(review.get("evidence") or record["signals"]),
                                "affected_segment_ids": copy.deepcopy(row.get("source_segment_ids") or []),
                                "review_status": "auto_approved",
                            }
                        )
                        changed_items.append(
                            {
                                "utterance_id": row_id,
                                "before": change.get("from"),
                                "after": change.get("to"),
                                "reason": change.get("reason") or "context_supported_asr_repair",
                                "confidence": confidence,
                                "evidence_type": "local_qwen_korean_asr_audit",
                            }
                        )
                    model_repaired_count += 1
        except Exception as exc:
            model_error = f"{type(exc).__name__}: {exc}"
            for record in selected:
                row = row_by_id.get(record["utterance_id"])
                if row is not None and row.get("korean_editorial_state") == "suspicious":
                    row["korean_editorial_state"] = "unresolved"
                    _mark_unresolved(result, row, record, "model_load_failed")

    unresolved_ids = {
        str(item.get("utterance_id") or "")
        for item in result.get("unresolved_terms") or []
        if isinstance(item, dict) and item.get("stage") == "korean_asr_editorial_review"
    }
    result["video_local_canonical_entities"] = {
        key: copy.deepcopy(value)
        for key, value in local_map.items()
        if key != "metadata_context"
    }
    result["korean_editorial_review"] = {
        "enabled": True,
        "stage": "korean_asr_editorial_review",
        "review_version": REVIEW_VERSION,
        "detector_version": DETECTOR_VERSION,
        "registry_version": registry["schema_version"],
        "registry_extends": registry["extends"],
        "total_utterances": len(rows),
        "deterministic_repaired_count": len(deterministic_by_id),
        "suspicious_count": len(suspicious),
        "review_selected_count": len(selected),
        "reviewed_count": reviewed_count,
        "repaired_count": len(deterministic_by_id) + model_repaired_count,
        "model_repaired_count": model_repaired_count,
        "unresolved_count": len(unresolved_ids),
        "model_calls": model_calls,
        "model_load_count": model_load_count,
        "model_id": model_id if selected else None,
        "model_error": model_error,
        "partial_json_recovery_count": partial_parse_recoveries,
        "states": Counter(
            str(row.get("korean_editorial_state") or "clean") for row in rows
        ),
        "changed_items": changed_items,
        "suspicious_items": [
            {
                key: copy.deepcopy(record[key])
                for key in (
                    "utterance_id",
                    "chapter_id",
                    "start_seconds",
                    "signals",
                    "suspicion_score",
                )
            }
            for record in suspicious
        ],
        "confidence_policy": {
            "high": "apply_only_after_fidelity_guard",
            "medium": "apply_only_with_strong_deterministic_entity_support",
            "low": "keep_original_and_mark_needs_review",
        },
        "failure_policy": "preserve_deterministic_result_and_mark_needs_review",
        "timings_seconds": {
            "deterministic": round(deterministic_seconds, 6),
            "suspicious_detection": round(detection_seconds, 6),
            "model_load": round(model_load_seconds, 6),
            "generation": round(generation_seconds, 6),
            "total_added": round(time.perf_counter() - started, 6),
        },
    }
    report = result.setdefault("processing_report", {})
    report["korean_editorial_review_enabled"] = True
    report["korean_editorial_suspicious_count"] = len(suspicious)
    report["korean_editorial_repaired_count"] = (
        len(deterministic_by_id) + model_repaired_count
    )
    report["korean_editorial_unresolved_count"] = len(unresolved_ids)
    return result

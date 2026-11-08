"""Target duration / length as a first-class contract.

The workbench lets a user pick "30 秒" or "800 字". Historically that choice
lived only as free text inside a requirement, while ``length_rule`` stayed
``{minimum: None, maximum: 20000}``. The generator produced a ~120 character
stub and the validator had no lower bound to reject it, so "写一篇文章，800 字"
could legally deliver 120 characters, and a title saying "60 秒看懂" survived
even when the user selected 30 seconds.

This module is the single source of truth shared by intake, Brief, generation,
validation and display. No model, database or network access.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Conservative Mandarin narration/reading pace, characters per second.
# A 60-second script is roughly 250-300 Chinese characters including pauses.
CHARS_PER_SECOND = 4.5
MAX_CHARACTERS = 20000

# Marker emitted by the workbench UI (and recognised as a backend fallback).
_TARGET_MARKER = re.compile(
    r"目标(?:时长|篇幅)\s*[/／]?\s*(?:篇幅)?\s*[:：]\s*([^\n；;，,。]+)"
)
_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*(秒|秒钟|分钟|字|字符|min\b|s\b)", re.I)
_MENTION = re.compile(r"(\d+)\s*(秒|秒钟|分钟|字|字符)", re.I)


@dataclass(frozen=True)
class LengthSpec:
    """A resolved user intent: character budget plus optional duration."""

    label: str
    minimum: int
    maximum: int
    target_seconds: int | None = None
    target_characters: int | None = None

    @property
    def target(self) -> int:
        return (self.minimum + self.maximum) // 2

    def as_rule(self) -> dict[str, int]:
        return {"minimum": self.minimum, "maximum": self.maximum}

    def describe(self) -> str:
        return self.label.strip() or f"约 {self.target} 字"

    def duration_label(self) -> str:
        """Human-readable duration used when rewriting titles/copy."""
        if self.target_seconds is None:
            return f"{self.target_characters} 字"
        if self.target_seconds >= 60 and self.target_seconds % 60 == 0:
            return f"{self.target_seconds // 60} 分钟"
        return f"{self.target_seconds} 秒"


def spec_from_label(label: str) -> LengthSpec | None:
    """Resolve a preset such as ``30 秒``, ``3 分钟`` or ``800 字``."""
    match = _UNIT.search(label or "")
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    if value <= 0:
        return None
    target_seconds: int | None = None
    target_characters: int | None = None
    if unit.startswith("分") or unit.startswith("min"):
        target_seconds = int(value * 60)
    elif "秒" in unit or unit.startswith("s"):
        target_seconds = int(value)
    elif "字" in unit:
        target_characters = int(value)
    else:
        return None

    center = (int(target_seconds * CHARS_PER_SECOND) if target_seconds is not None
              else int(target_characters or 20))
    center = max(20, min(center, MAX_CHARACTERS))
    minimum = max(1, int(center * 0.85))
    maximum = min(MAX_CHARACTERS, max(minimum + 20, int(center * 1.20)))
    return LengthSpec(
        label=(label or "").strip(),
        minimum=minimum,
        maximum=maximum,
        target_seconds=target_seconds,
        target_characters=target_characters,
    )


def spec_from_requirements(texts) -> LengthSpec | None:
    """Backend fallback: recover the chosen target from requirement text."""
    for text in texts:
        match = _TARGET_MARKER.search(text or "")
        if not match:
            continue
        spec = spec_from_label(match.group(1).strip())
        if spec is not None:
            return spec
    return None


def conflicting_mentions(text: str, spec: LengthSpec) -> list[str]:
    """Duration/count numbers that contradict the selected target.

    Only titles and cover copy are scanned. Body text legitimately contains
    timeline markers like ``0–5 秒`` which must NOT be treated as a conflicting
    claim about the total duration.
    """
    found: list[str] = []
    for match in _MENTION.finditer(text or ""):
        number = int(match.group(1))
        unit = match.group(2)
        if "字" in unit:
            if (spec.target_characters is not None
                    and abs(number - spec.target_characters)
                    > max(20, spec.target_characters * 0.2)):
                found.append(match.group(0))
        elif unit.startswith("分"):
            if spec.target_seconds is not None and number * 60 != spec.target_seconds:
                found.append(match.group(0))
        elif "秒" in unit:
            if spec.target_seconds is not None and number != spec.target_seconds:
                found.append(match.group(0))
    return found


def normalize_mentions(text: str, spec: LengthSpec) -> str:
    """Rewrite wrong duration/count numbers in titles and cover copy.

    Units are preserved: a word-count target never rewrites a seconds claim
    (an article can legitimately mention a reading time), and vice versa.
    """
    def replace(match: re.Match) -> str:
        original = match.group(0)
        unit = match.group(2)
        if "字" in unit:
            if spec.target_characters is None:
                return original
            return f"{spec.target_characters} 字"
        if spec.target_seconds is None:
            return original
        if unit.startswith("分"):
            if spec.target_seconds >= 60 and spec.target_seconds % 60 == 0:
                return f"{spec.target_seconds // 60} 分钟"
            return f"{spec.target_seconds} 秒"
        return f"{spec.target_seconds} 秒"

    return _MENTION.sub(replace, text or "")

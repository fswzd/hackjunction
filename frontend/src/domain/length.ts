/**
 * Target duration / length, resolved once and shared by the task dialog, the
 * API adapter and the demo adapter. Mirrors backend/domain/length.py so the
 * value the user picks is the value the backend validates and the script uses.
 *
 * Fixes two real defects:
 *  - selecting "30 秒" while the title says "60 秒看懂" went unnoticed;
 *  - asking for an 800-character article produced ~120 characters, because
 *    the chosen length was only free text and length_rule had no lower bound.
 */
export interface LengthSpec {
  label: string;
  minimum: number;
  maximum: number;
  target: number;
  targetSeconds: number | null;
  targetCharacters: number | null;
  durationLabel: string;
}

const CHARS_PER_SECOND = 4.5;
const MAX_CHARACTERS = 20000;
const UNIT = /(\d+(?:\.\d+)?)\s*(秒|秒钟|分钟|字|字符|min\b|s\b)/i;
const TARGET_MARKER = /目标(?:时长|篇幅)\s*[/／]?\s*(?:篇幅)?\s*[:：]\s*([^\n；;，,。]+)/;
const MENTION = /(\d+)\s*(秒|秒钟|分钟|字|字符)/g;

export function parseLengthSpec(label: string): LengthSpec | null {
  const match = UNIT.exec(label || "");
  if (!match) return null;
  const value = Number(match[1]);
  if (!Number.isFinite(value) || value <= 0) return null;
  const unit = match[2].toLowerCase();
  let targetSeconds: number | null = null;
  let targetCharacters: number | null = null;
  if (unit.startsWith("分") || unit.startsWith("min")) targetSeconds = Math.round(value * 60);
  else if (unit.includes("秒") || unit.startsWith("s")) targetSeconds = Math.round(value);
  else if (unit.includes("字")) targetCharacters = Math.round(value);
  else return null;

  let center = targetSeconds !== null
    ? Math.round(targetSeconds * CHARS_PER_SECOND)
    : (targetCharacters ?? 20);
  center = Math.max(20, Math.min(center, MAX_CHARACTERS));
  const minimum = Math.max(1, Math.floor(center * 0.85));
  const maximum = Math.min(MAX_CHARACTERS, Math.max(minimum + 20, Math.floor(center * 1.2)));
  const durationLabel = targetSeconds === null
    ? `${targetCharacters} 字`
    : targetSeconds >= 60 && targetSeconds % 60 === 0
      ? `${targetSeconds / 60} 分钟`
      : `${targetSeconds} 秒`;
  return {
    label: (label || "").trim(),
    minimum,
    maximum,
    target: Math.floor((minimum + maximum) / 2),
    targetSeconds,
    targetCharacters,
    durationLabel,
  };
}

/** Recover the chosen target from a Brief's requirement text. */
export function targetFromRequirements(texts: string[]): LengthSpec | null {
  for (const text of texts) {
    const match = TARGET_MARKER.exec(text || "");
    if (!match) continue;
    const spec = parseLengthSpec(match[1].trim());
    if (spec) return spec;
  }
  return null;
}

/** Numbers in a title/idea that contradict the selected target. */
export function findConflicts(text: string, spec: LengthSpec): string[] {
  const found: string[] = [];
  const pattern = new RegExp(MENTION.source, "g");
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text || "")) !== null) {
    const number = Number(match[1]);
    const unit = match[2];
    if (unit.includes("字")) {
      if (spec.targetCharacters !== null
        && Math.abs(number - spec.targetCharacters) > Math.max(20, spec.targetCharacters * 0.2)) {
        found.push(match[0]);
      }
    } else if (unit.startsWith("分")) {
      if (spec.targetSeconds !== null && number * 60 !== spec.targetSeconds) found.push(match[0]);
    } else if (spec.targetSeconds !== null && number !== spec.targetSeconds) {
      found.push(match[0]);
    }
  }
  return [...new Set(found)];
}

/** Rewrite contradictory numbers to the chosen target, preserving the unit. */
export function normalizeMentions(text: string, spec: LengthSpec): string {
  const pattern = new RegExp(MENTION.source, "g");
  return (text || "").replace(pattern, (original, _number: string, unit: string) => {
    if (unit.includes("字")) {
      return spec.targetCharacters === null ? original : `${spec.targetCharacters} 字`;
    }
    if (spec.targetSeconds === null) return original;
    if (unit.startsWith("分") && spec.targetSeconds >= 60 && spec.targetSeconds % 60 === 0) {
      return `${spec.targetSeconds / 60} 分钟`;
    }
    return `${spec.targetSeconds} 秒`;
  });
}

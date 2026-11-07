import type { CreatorStage, Profile } from "./types";

export interface CreatorStageMeta {
  id: CreatorStage;
  label: string;
  shortLabel: string;
  description: string;
  hint: string;
}

/**
 * The three stages the onboarding asks about. Keep these IDs in sync with
 * `backend/domain/schemas.py` (`CreatorStage`) and the `accounts.creator_stage`
 * column so the frontend, local API and database agree.
 */
export const CREATOR_STAGES: CreatorStageMeta[] = [
  {
    id: "starting",
    label: "正在起号",
    shortLabel: "起号期",
    description: "账号刚起步，正在找定位、选题和稳定的更新节奏。",
    hint: "团队会优先帮你收窄定位、准备冷启动选题，并把每一步讲清楚。",
  },
  {
    id: "operating",
    label: "已在做账号",
    shortLabel: "成长期",
    description: "已经有内容和读者，希望把质量、效率和更新节奏再提一档。",
    hint: "团队会优先帮你打磨结构、稳定产出，并保留每一版修改依据。",
  },
  {
    id: "established",
    label: "已是成熟账号",
    shortLabel: "成熟期",
    description: "账号已有影响力和稳定读者，需要团队协作与规模化产出。",
    hint: "团队会优先帮你扩展选题、并行协作，并让审稿与验收更可控。",
  },
];

const STAGE_IDS = new Set<CreatorStage>(CREATOR_STAGES.map((stage) => stage.id));

export function normalizeCreatorStage(value: unknown): CreatorStage {
  return typeof value === "string" && STAGE_IDS.has(value as CreatorStage)
    ? (value as CreatorStage)
    : "starting";
}

export function creatorStageMeta(
  stage: CreatorStage | null | undefined,
): CreatorStageMeta {
  return (
    CREATOR_STAGES.find((item) => item.id === stage) ??
    CREATOR_STAGES[0]
  );
}

/** Back-fill profiles created before the creator-stage field existed. */
export function normalizeProfile(profile: Profile | null | undefined): Profile | null {
  if (!profile || typeof profile !== "object") return null;
  return {
    ...profile,
    creatorStage: normalizeCreatorStage(profile.creatorStage),
  };
}

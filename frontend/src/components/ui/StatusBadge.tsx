import { BACKEND_STATE_META, STATUS_META, TASK_STATUS_META } from "@/domain/agents";
import type { AgentStatus, BackendTaskState, TaskStatus } from "@/domain/types";
import { Badge } from "./Badge";

export function AgentStatusBadge({ status }: { status: AgentStatus }) {
  const meta = STATUS_META[status];
  return (
    <Badge color={meta.color} dot>
      {meta.label}
    </Badge>
  );
}

export function TaskStatusBadge({ status, backendState }: { status: TaskStatus; backendState?: BackendTaskState | null }) {
  const meta = backendState === "WAITING_INPUT" || backendState === "NEEDS_REVIEW" || backendState === "INTERRUPTED"
    ? BACKEND_STATE_META[backendState]
    : TASK_STATUS_META[status];
  return (
    <Badge color={meta.color} dot>
      {meta.label}
    </Badge>
  );
}

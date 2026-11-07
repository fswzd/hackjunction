import { STATUS_META, TASK_STATUS_META } from "@/domain/agents";
import type { AgentStatus, TaskStatus } from "@/domain/types";
import { Badge } from "./Badge";

export function AgentStatusBadge({ status }: { status: AgentStatus }) {
  const meta = STATUS_META[status];
  return (
    <Badge color={meta.color} dot>
      {meta.label}
    </Badge>
  );
}

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  const meta = TASK_STATUS_META[status];
  return (
    <Badge color={meta.color} dot>
      {meta.label}
    </Badge>
  );
}

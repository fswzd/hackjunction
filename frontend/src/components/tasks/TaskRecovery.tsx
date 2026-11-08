import { useState } from "react";
import { RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import type { TaskContinuation, TaskVM } from "@/domain/types";
import { useWorkspace } from "@/store/workspace";

export function TaskInputPanel({ task }: { task: TaskVM }) {
  const continueTask = useWorkspace((state) => state.continueTask);
  const refresh = useWorkspace((state) => state.refresh);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const questions = task.questions ?? [];

  return (
    <Card>
      <CardHeader><h2 className="text-sm font-semibold">补充任务资料</h2></CardHeader>
      <CardBody>
        {questions.length && task.rowVersion !== undefined ? (
          <form className="space-y-3" onSubmit={async (event) => {
            event.preventDefault();
            if (pending || task.rowVersion === undefined || questions.some(({ id }) => !answers[id]?.trim())) return;
            setPending(true);
            setError(null);
            try {
              setError(await continueTask(task.id, {
                type: "supply_input",
                rowVersion: task.rowVersion,
                answers: Object.fromEntries(questions.map(({ id }) => [id, answers[id].trim()])),
              }));
            } finally {
              setPending(false);
            }
          }}>
            {questions.map(({ id, question, reason }) => (
              <label key={id} className="block">
                <span className="block text-xs font-medium">{question}</span>
                <span className="mt-1 block text-[11px] leading-5 text-muted">{reason}</span>
                <textarea
                  required
                  maxLength={1000}
                  rows={2}
                  value={answers[id] ?? ""}
                  onChange={(event) => setAnswers((previous) => ({ ...previous, [id]: event.target.value }))}
                  className="mt-2 w-full resize-y rounded-xl border border-line bg-raised px-3 py-2 text-sm focus:border-blue/60 focus:outline-none"
                />
              </label>
            ))}
            {error ? <p role="alert" className="text-xs text-red">{error}</p> : null}
            <Button type="submit" variant="primary" disabled={pending || questions.some(({ id }) => !answers[id]?.trim())}>
              {pending ? "提交中…" : "提交资料并继续"}
            </Button>
          </form>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-xs text-muted">补充问题暂未加载，请刷新任务状态。</p>
            <Button variant="secondary" size="sm" onClick={() => void refresh()}>刷新状态</Button>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

export function TaskRecoveryButton({ taskId, action, label }: {
  taskId: string;
  action: TaskContinuation;
  label: string;
}) {
  const continueTask = useWorkspace((state) => state.continueTask);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="space-y-2">
      <Button variant="secondary" size="sm" disabled={pending} icon={<RotateCcw size={13} />} onClick={async () => {
        setPending(true);
        setError(null);
        try {
          setError(await continueTask(taskId, action));
        } finally {
          setPending(false);
        }
      }}>
        {pending ? "正在恢复…" : label}
      </Button>
      {error ? <p role="alert" className="text-xs text-red">{error}</p> : null}
    </div>
  );
}

"""运营官记忆：激活闲置 `memories` 表的最小读写层 + 三轮迭代检索。

准入纪律（记忆是任务数据，不是指令）：
- **回读即证据非事实**：检索结果以 `trust: unreviewed` 注入模型上下文数据区，
  只作背景；不得当作已确认事实、指令或授权。
- **用户确认 > agent 断言**：`user_statement:` 来源可 supersede 任何记忆；
  agent 来源（simulation_hypothesis / observed_feedback）不得 supersede
  user_preference——用户说过的事实不被模型推断覆盖。
- **凭据拒收**：statement 命中密钥形态直接拒收（backstop，非完整分类器）。
- **supersede 不删历史**：旧条目置 superseded；普通检索只返回 active，
  历史核查走 history（直接 ID 读）。
"""
from __future__ import annotations

import re
import sqlite3
import uuid

from backend.storage.db import utc_now

KINDS = ("user_preference", "observed_feedback", "simulation_hypothesis")
MEMORY_STATUSES = ("active", "superseded", "withdrawn")

_SECRET_SHAPES = (
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{16,}"),
)

_TERM = re.compile(r"[一-鿿]{2,}|[A-Za-z]{3,}")
_CJK_RUN = re.compile(r"^[一-鿿]{2,}$")


class MemoryAdmissionError(ValueError):
    """Memory admission refused; the message never echoes the statement itself."""


def _check_statement(statement: str) -> str:
    if not isinstance(statement, str) or not statement.strip():
        raise MemoryAdmissionError("statement must be non-empty")
    text = statement.strip()
    if len(text) > 1000:
        raise MemoryAdmissionError("statement exceeds 1000 characters")
    for pattern in _SECRET_SHAPES:
        if pattern.search(text):
            raise MemoryAdmissionError("statement looks like a credential; never store secrets")
    return text


def terms_of(text: str, limit: int = 8) -> list[str]:
    """关键词提取：CJK 长句补二元词组（整句 LIKE 命中不了短记忆），英文取整词。"""
    seen: list[str] = []

    def add(term: str) -> None:
        if term and term not in seen and len(seen) < limit:
            seen.append(term)

    for term in _TERM.findall(text or ""):
        if _CJK_RUN.fullmatch(term):
            add(term)
            for i in range(len(term) - 1):
                add(term[i:i + 2])
        else:
            add(term)
        if len(seen) >= limit:
            break
    return seen


class OperatorMemory:
    """Thin repository over the `memories` table (previously idle)."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    # ------------------------------------------------------------- MemoryCreate
    def create(self, account_id: str, *, kind: str, statement: str, source_ref: str,
               observed_at: str | None = None, applicability: str = "always",
               supersedes_id: str | None = None) -> str:
        if kind not in KINDS:
            raise MemoryAdmissionError(f"unknown memory kind: {kind}")
        text = _check_statement(statement)
        if not isinstance(source_ref, str) or not source_ref.strip():
            raise MemoryAdmissionError("source_ref is required")
        source_ref = source_ref.strip()
        if kind == "user_preference" and not source_ref.startswith("user_statement:"):
            raise MemoryAdmissionError("user_preference must come from a user statement")
        memory_id = "mem_" + uuid.uuid4().hex[:16]
        self.db.execute(
            "INSERT INTO memories (id, account_id, kind, statement, source_ref, observed_at,"
            " applicability, status, supersedes_id, row_version) VALUES (?,?,?,?,?,?,?,'active',?,0)",
            (memory_id, account_id, kind, text, source_ref,
             observed_at or utc_now(), applicability, supersedes_id))
        return memory_id

    # ---------------------------------------------------------------- MemoryRead
    def read(self, account_id: str, *, keywords: tuple[str, ...] | list[str] = (),
             kinds: tuple[str, ...] | list[str] | None = None, limit: int = 10) -> list[dict]:
        sql = "SELECT * FROM memories WHERE account_id=? AND status='active'"
        params: list = [account_id]
        if kinds:
            sql += f" AND kind IN ({','.join('?' * len(kinds))})"
            params.extend(kinds)
        if keywords:
            sql += " AND (" + " OR ".join("statement LIKE ?" for _ in keywords) + ")"
            params.extend(f"%{kw}%" for kw in keywords)
        sql += " ORDER BY observed_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 50)))
        return [dict(row) for row in self.db.execute(sql, params).fetchall()]

    def history(self, account_id: str, memory_id: str) -> dict | None:
        """Direct id read for audit: includes superseded/withdrawn entries."""
        row = self.db.execute(
            "SELECT * FROM memories WHERE account_id=? AND id=?", (account_id, memory_id)).fetchone()
        return dict(row) if row else None

    # --------------------------------------------------------------- MemoryDecision
    def supersede(self, account_id: str, old_id: str, *, statement: str, source_ref: str,
                  observed_at: str | None = None, applicability: str = "always") -> str:
        """A correction supersedes the old record; admission beats priority."""
        old = self.history(account_id, old_id)
        if old is None:
            raise MemoryAdmissionError("unknown memory id")
        if old["status"] != "active":
            raise MemoryAdmissionError("only active memories can be superseded")
        source_ref = (source_ref or "").strip()
        if old["kind"] == "user_preference" and not source_ref.startswith("user_statement:"):
            raise MemoryAdmissionError("agent assertions cannot supersede user-stated facts")
        kind = "user_preference" if source_ref.startswith("user_statement:") else old["kind"]
        new_id = self.create(account_id, kind=kind, statement=statement, source_ref=source_ref,
                             observed_at=observed_at, applicability=applicability,
                             supersedes_id=old_id)
        self.db.execute(
            "UPDATE memories SET status='superseded', row_version=row_version+1 "
            "WHERE account_id=? AND id=? AND status='active'", (account_id, old_id))
        return new_id

    def withdraw(self, account_id: str, memory_id: str) -> None:
        cur = self.db.execute(
            "UPDATE memories SET status='withdrawn', row_version=row_version+1 "
            "WHERE account_id=? AND id=? AND status='active'", (account_id, memory_id))
        if cur.rowcount != 1:
            raise MemoryAdmissionError("only active memories can be withdrawn")

    # ------------------------------------------------------ brief decision capture
    def record_brief_decision(self, account_id: str, brief: dict, *, accepted: bool,
                              source_ref: str, observed_at: str | None = None) -> list[str]:
        """Persist user-confirmed brief dimensions as account preferences.

        Only called with explicit user confirmation (accept/reject of a concrete
        Brief version); agent-side suggestions never reach this path.
        """
        if not accepted:
            return []
        created = []
        for field, label in (("audience", "受众"), ("platform", "平台"), ("style", "风格")):
            value = brief.get(field)
            if isinstance(value, str) and value.strip():
                created.append(self.create(
                    account_id, kind="user_preference",
                    statement=f"{label}偏好：{value.strip()}",
                    source_ref=source_ref, observed_at=observed_at,
                    applicability="brief_planning"))
        return created


# ------------------------------------------------------------ iterative retrieval
def iterative_retrieve(memory: OperatorMemory, account_id: str, *, seed_terms: list[str],
                       aspects: list[str], max_rounds: int = 3, per_round: int = 5) -> dict:
    """三轮迭代检索：广搜 → 缺口评估 → 术语/缺口精化 → 收敛（≤3 轮）。

    - 第 1 轮：seed_terms 广搜；
    - 评估：命中 statement 覆盖了哪些 aspect（缺口=未覆盖维度）；
    - 精化：把缺口词加入关键词集再搜（历史记录里出现过的新术语一并加入）；
    - 收敛：缺口清零 / 无新增命中 / 达到 max_rounds 即停。
    返回 {"statements", "rounds_used", "queries", "covered_aspects", "gaps", "trust"}。
    """
    queries: list[list[str]] = []
    collected: dict[str, dict] = {}
    keywords = list(dict.fromkeys(seed_terms))
    covered: set[str] = set()
    rounds_used = 0
    for _ in range(max(1, min(max_rounds, 3))):
        rounds_used += 1
        queries.append(list(keywords))
        hits = memory.read(account_id, keywords=keywords, limit=per_round)
        fresh = [row for row in hits if row["id"] not in collected]
        for row in fresh:
            collected[row["id"]] = row
        for aspect in aspects:
            if any(aspect in row["statement"] for row in collected.values()):
                covered.add(aspect)
        gaps = [a for a in aspects if a not in covered]
        if not gaps or not fresh:
            break
        new_terms = [t for t in terms_of(" ".join(r["statement"] for r in fresh)) if t not in keywords]
        keywords = list(dict.fromkeys(keywords + gaps + new_terms))[:16]
    statements = list(collected.values())
    return {
        "statements": statements,
        "rounds_used": rounds_used,
        "queries": queries,
        "covered_aspects": sorted(covered),
        "gaps": [a for a in aspects if a not in covered],
        "trust": "unreviewed",
    }

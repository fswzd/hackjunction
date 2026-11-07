/**
 * 平台账号接入（抖音 / 小红书）客户端。
 *
 * 真实接口模式：注册 → 扫码登录（后端弹出浏览器窗口）→ 自动抓取实绩写入
 * 本地数据库经验库（imported_videos + baseline_plays）。
 * 演示模式：同样的交互流程，数据只存浏览器，不连接真实平台。
 */

export type Platform = "douyin" | "xiaohongshu";

export type SessionStatus =
  | "none"
  | "pending_adapter_setup"
  | "logging_in"
  | "logged_in"
  | "expired";

export interface ExternalAccount {
  external_account_id: string;
  account_id: string;
  platform: Platform;
  handle: string;
  display_name: string;
  profile_url: string | null;
  session_status: SessionStatus;
  baseline_plays: number | null;
  imported_count: number;
}

export interface ExternalAccountStatus {
  external_account_id: string;
  platform: Platform;
  handle: string;
  session_status: SessionStatus;
  login_error: string | null;
  import_error: string | null;
  imported_count: number;
  baseline_plays: number | null;
}

export interface ManualVideo {
  platform_video_id: string;
  title?: string;
  published_at?: string | null;
  plays?: number | null;
  likes?: number | null;
  comments?: number | null;
  shares?: number | null;
  favorites?: number | null;
  top_comments?: { text: string; likes?: number }[];
}

export interface ImportResult {
  imported: number;
  skipped_duplicates?: number;
  baseline_plays: number | null;
  imported_count: number;
  import_error?: string;
}

export interface ExperienceSummary {
  external_account_id: string;
  platform: Platform;
  handle: string;
  session_status: SessionStatus;
  imported_count: number;
  baseline_plays: number | null;
  totals: {
    plays: number;
    likes: number;
    comments: number;
    shares: number;
    favorites: number;
  };
  top_comments: { text: string; likes: number; platform_video_id?: string }[];
  recent_videos: {
    platform_video_id: string;
    title: string;
    published_at: string | null;
    plays: number | null;
    likes: number | null;
    comments: number | null;
    shares: number | null;
    favorites: number | null;
  }[];
}

export interface RegisterInput {
  platform: Platform;
  handle: string;
  displayName?: string;
  profileUrl?: string | null;
}

export interface ExternalAccountsClient {
  list(): Promise<ExternalAccount[]>;
  register(input: RegisterInput): Promise<ExternalAccount>;
  login(externalAccountId: string): Promise<{ session_status: string; next_action?: string }>;
  status(externalAccountId: string): Promise<ExternalAccountStatus>;
  /** 回滚登记（登录失败后调用）：账号不入列、库里不留痕。 */
  remove(externalAccountId: string): Promise<{ deleted: boolean }>;
  importAdapter(externalAccountId: string, count?: number): Promise<ImportResult>;
  importManual(externalAccountId: string, videos: ManualVideo[]): Promise<ImportResult>;
  experience(externalAccountId: string): Promise<ExperienceSummary>;
}

const PROFILE_KEY = "creator-os.profile.v2";
const MOCK_KEY = "creator-os.external-accounts.v1";

function randomKey(): string {
  return `creator-os-${crypto.randomUUID()}`;
}

interface BackendErrorBody {
  error?: { code?: string; cause_hint?: string; next_action?: string; detail?: string };
  data?: { error?: { code?: string; cause_hint?: string; next_action?: string; detail?: string } };
}

function backendError(status: number, body: unknown): Error {
  const typed = (body ?? {}) as BackendErrorBody;
  const envelope = typed.error ?? typed.data?.error;
  const message =
    envelope?.cause_hint ?? envelope?.detail ?? envelope?.next_action ?? envelope?.code;
  return new Error(message ?? `后端返回 ${status}`);
}

/** 真实接口模式：经 Vite 代理访问本地 Flask。 */
class ApiExternalAccounts implements ExternalAccountsClient {
  private readonly base = import.meta.env.VITE_API_BASE ?? "";
  private session: { csrf_token: string } | null = null;
  private sessionPromise: Promise<{ csrf_token: string }> | null = null;

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    const response = await fetch(`${this.base}${path}`, {
      ...init,
      credentials: "include",
      headers,
    });
    const payload = (await response.json().catch(() => ({}))) as {
      data?: T;
    } & BackendErrorBody;
    if (!response.ok) throw backendError(response.status, payload);
    return payload.data as T;
  }

  private async ensureSession(): Promise<{ csrf_token: string }> {
    if (this.session) return this.session;
    if (!this.sessionPromise) {
      this.sessionPromise = this.request<{ csrf_token: string }>(
        "/api/v1/session",
      ).then((info) => {
        this.session = info;
        return info;
      });
    }
    return this.sessionPromise;
  }

  private async writeHeaders(): Promise<HeadersInit> {
    await this.ensureSession();
    return {
      "Content-Type": "application/json",
      "X-CSRF-Token": this.session?.csrf_token ?? "",
      "Idempotency-Key": randomKey(),
    };
  }

  /** 外部账号绑定到本地业务分区：没有则先建一个。 */
  private async ensureAccountId(): Promise<string> {
    await this.ensureSession();
    const accounts = await this.request<{ account_id: string }[]>(
      "/api/v1/accounts",
    );
    const existing = accounts?.[0];
    if (existing) return existing.account_id;
    let profile: { workspaceName?: string; creatorStage?: string } = {};
    try {
      const raw = window.localStorage.getItem(PROFILE_KEY);
      if (raw) profile = JSON.parse(raw) as typeof profile;
    } catch {
      /* profile is optional */
    }
    const created = await this.request<{ account_id: string }>("/api/v1/accounts", {
      method: "POST",
      headers: await this.writeHeaders(),
      body: JSON.stringify({
        name: profile.workspaceName || "本地创作者",
        creator_stage: profile.creatorStage || "starting",
      }),
    });
    return created.account_id;
  }

  async list(): Promise<ExternalAccount[]> {
    await this.ensureSession();
    return this.request<ExternalAccount[]>("/api/v1/accounts/external");
  }

  async register(input: RegisterInput): Promise<ExternalAccount> {
    const account_id = await this.ensureAccountId();
    return this.request<ExternalAccount>("/api/v1/accounts/external", {
      method: "POST",
      headers: await this.writeHeaders(),
      body: JSON.stringify({
        account_id,
        platform: input.platform,
        handle: input.handle,
        display_name: input.displayName ?? "",
        profile_url: input.profileUrl ?? null,
      }),
    });
  }

  async login(externalAccountId: string) {
    return this.request<{ session_status: string; next_action?: string }>(
      `/api/v1/accounts/external/${encodeURIComponent(externalAccountId)}/login`,
      { method: "POST", headers: await this.writeHeaders(), body: "{}" },
    );
  }

  async status(externalAccountId: string) {
    return this.request<ExternalAccountStatus>(
      `/api/v1/accounts/external/${encodeURIComponent(externalAccountId)}/status`,
    );
  }

  async remove(externalAccountId: string) {
    return this.request<{ deleted: boolean }>(
      `/api/v1/accounts/external/${encodeURIComponent(externalAccountId)}`,
      { method: "DELETE", headers: await this.writeHeaders() },
    );
  }

  async importAdapter(externalAccountId: string, count = 10) {
    return this.request<ImportResult>(
      `/api/v1/accounts/external/${encodeURIComponent(externalAccountId)}/import`,
      {
        method: "POST",
        headers: await this.writeHeaders(),
        body: JSON.stringify({ source: "adapter", count }),
      },
    );
  }

  async importManual(externalAccountId: string, videos: ManualVideo[]) {
    return this.request<ImportResult>(
      `/api/v1/accounts/external/${encodeURIComponent(externalAccountId)}/import`,
      {
        method: "POST",
        headers: await this.writeHeaders(),
        body: JSON.stringify({ source: "manual", videos }),
      },
    );
  }

  async experience(externalAccountId: string) {
    return this.request<ExperienceSummary>(
      `/api/v1/accounts/external/${encodeURIComponent(externalAccountId)}/experience`,
    );
  }
}

interface MockStore {
  accounts: ExternalAccount[];
  videos: Record<string, ManualVideo[]>;
}

const MOCK_SAMPLE: ManualVideo[] = [
  {
    platform_video_id: "demo-1",
    title: "示例作品 · 早春人像怎么拍出自然感",
    published_at: "2026-09-12T00:00:00Z",
    plays: 12800,
    likes: 460,
    comments: 58,
    shares: 21,
    favorites: 190,
    top_comments: [
      { text: "光线那段讲得太好了，收藏了", likes: 86 },
      { text: "求参数设置", likes: 32 },
    ],
  },
  {
    platform_video_id: "demo-2",
    title: "示例作品 · 手机也能拍的三个构图",
    published_at: "2026-10-02T00:00:00Z",
    plays: 3200,
    likes: 96,
    comments: 14,
    shares: 5,
    favorites: 47,
    top_comments: [{ text: "第二个构图实用", likes: 11 }],
  },
  {
    platform_video_id: "demo-3",
    title: "示例作品 · 一次失败拍摄的复盘",
    published_at: "2026-10-21T00:00:00Z",
    plays: 5400,
    likes: 210,
    comments: 33,
    shares: 12,
    favorites: 88,
    top_comments: [{ text: "真实，比成功学有用", likes: 54 }],
  },
];

function readMock(): MockStore {
  try {
    const raw = window.localStorage.getItem(MOCK_KEY);
    if (raw) return JSON.parse(raw) as MockStore;
  } catch {
    /* fall through to empty store */
  }
  return { accounts: [], videos: {} };
}

function writeMock(store: MockStore): void {
  try {
    window.localStorage.setItem(MOCK_KEY, JSON.stringify(store));
  } catch {
    /* best-effort */
  }
}

function summarize(
  account: ExternalAccount,
  videos: ManualVideo[],
): ExperienceSummary {
  const total = (pick: (v: ManualVideo) => number | null | undefined) =>
    videos.reduce((sum, v) => sum + (pick(v) ?? 0), 0);
  const topComments = videos
    .flatMap((v) => (v.top_comments ?? []).map((c) => ({ ...c })))
    .sort((a, b) => (b.likes ?? 0) - (a.likes ?? 0))
    .slice(0, 10)
    .map((c) => ({ text: c.text, likes: c.likes ?? 0 }));
  return {
    external_account_id: account.external_account_id,
    platform: account.platform,
    handle: account.handle,
    session_status: account.session_status,
    imported_count: account.imported_count,
    baseline_plays: account.baseline_plays,
    totals: {
      plays: total((v) => v.plays),
      likes: total((v) => v.likes),
      comments: total((v) => v.comments),
      shares: total((v) => v.shares),
      favorites: total((v) => v.favorites),
    },
    top_comments: topComments,
    recent_videos: videos.slice(0, 20).map((v) => ({
      platform_video_id: v.platform_video_id,
      title: v.title ?? "",
      published_at: v.published_at ?? null,
      plays: v.plays ?? null,
      likes: v.likes ?? null,
      comments: v.comments ?? null,
      shares: v.shares ?? null,
      favorites: v.favorites ?? null,
    })),
  };
}

/** 演示模式：完整交互，数据只存浏览器，不连接真实平台。 */
class MockExternalAccounts implements ExternalAccountsClient {
  private mutate(change: (store: MockStore) => void): MockStore {
    const store = readMock();
    change(store);
    writeMock(store);
    return store;
  }

  async list(): Promise<ExternalAccount[]> {
    return readMock().accounts;
  }

  async register(input: RegisterInput): Promise<ExternalAccount> {
    const store = readMock();
    const existing = store.accounts.find(
      (item) => item.platform === input.platform && item.handle === input.handle,
    );
    if (existing) return existing;
    const account: ExternalAccount = {
      external_account_id: `ext-demo-${store.accounts.length + 1}`,
      account_id: "demo-account",
      platform: input.platform,
      handle: input.handle,
      display_name: input.displayName ?? "",
      profile_url: input.profileUrl ?? null,
      session_status: "none",
      baseline_plays: null,
      imported_count: 0,
    };
    this.mutate((s) => s.accounts.push(account));
    return account;
  }

  async login(externalAccountId: string) {
    this.mutate((store) => {
      const account = store.accounts.find(
        (item) => item.external_account_id === externalAccountId,
      );
      if (account) account.session_status = "logging_in";
    });
    window.setTimeout(() => {
      const store = readMock();
      const account = store.accounts.find(
        (item) => item.external_account_id === externalAccountId,
      );
      if (!account) return;
      account.session_status = "logged_in";
      const videos = store.videos[externalAccountId] ?? [];
      store.videos[externalAccountId] = videos.length ? videos : [...MOCK_SAMPLE];
      account.imported_count = store.videos[externalAccountId].length;
      const plays = store.videos[externalAccountId]
        .map((v) => v.plays ?? 0)
        .sort((a, b) => a - b);
      account.baseline_plays = plays.length
        ? plays[Math.floor(plays.length / 2)]
        : null;
      writeMock(store);
    }, 900);
    return { session_status: "logging_in", next_action: "演示模式：模拟登录中" };
  }

  async status(externalAccountId: string) {
    const account = readMock().accounts.find(
      (item) => item.external_account_id === externalAccountId,
    );
    if (!account) throw new Error("unknown external account");
    return {
      external_account_id: account.external_account_id,
      platform: account.platform,
      handle: account.handle,
      session_status: account.session_status,
      login_error: null,
      import_error: null,
      imported_count: account.imported_count,
      baseline_plays: account.baseline_plays,
    };
  }

  async remove(externalAccountId: string) {
    let deleted = false;
    this.mutate((store) => {
      const before = store.accounts.length;
      store.accounts = store.accounts.filter(
        (item) => item.external_account_id !== externalAccountId,
      );
      deleted = store.accounts.length < before;
      delete store.videos[externalAccountId];
    });
    return { deleted };
  }

  async importAdapter(externalAccountId: string) {
    return this.importManual(externalAccountId, MOCK_SAMPLE);
  }

  async importManual(externalAccountId: string, videos: ManualVideo[]) {
    let imported = 0;
    this.mutate((store) => {
      const existing = store.videos[externalAccountId] ?? [];
      const seen = new Set(existing.map((v) => v.platform_video_id));
      for (const video of videos) {
        if (seen.has(video.platform_video_id)) continue;
        existing.push(video);
        seen.add(video.platform_video_id);
        imported += 1;
      }
      store.videos[externalAccountId] = existing;
      const account = store.accounts.find(
        (item) => item.external_account_id === externalAccountId,
      );
      if (account) {
        account.imported_count = existing.length;
        const plays = existing
          .map((v) => v.plays ?? 0)
          .sort((a, b) => a - b);
        account.baseline_plays = plays.length
          ? plays[Math.floor(plays.length / 2)]
          : null;
      }
    });
    const account = readMock().accounts.find(
      (item) => item.external_account_id === externalAccountId,
    );
    return {
      imported,
      skipped_duplicates: videos.length - imported,
      baseline_plays: account?.baseline_plays ?? null,
      imported_count: account?.imported_count ?? 0,
    };
  }

  async experience(externalAccountId: string) {
    const store = readMock();
    const account = store.accounts.find(
      (item) => item.external_account_id === externalAccountId,
    );
    if (!account) throw new Error("unknown external account");
    return summarize(account, store.videos[externalAccountId] ?? []);
  }
}

export function createExternalAccountsClient(
  mode: "demo" | "api",
): ExternalAccountsClient {
  return mode === "api" ? new ApiExternalAccounts() : new MockExternalAccounts();
}

export const PLATFORM_META: Record<
  Platform,
  { label: string; handleLabel: string; hint: string }
> = {
  douyin: {
    label: "抖音",
    handleLabel: "抖音号",
    hint: "登录创作者中心后自动抓取最近作品实绩",
  },
  xiaohongshu: {
    label: "小红书",
    handleLabel: "小红书号",
    hint: "登录创作服务平台后自动抓取最近笔记实绩",
  },
};

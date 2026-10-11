const API_URL = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

export type WorkspaceInfo = { id: number; name: string; role: string };
export type Me = { id: number; email: string; workspaces: WorkspaceInfo[] };

export function getToken() {
  return localStorage.getItem("token");
}

export function setToken(token: string) {
  localStorage.setItem("token", token);
}

export function clearToken() {
  localStorage.removeItem("token");
}

const WAKING_UP_MESSAGE =
  "Cannot reach the server. It may be waking up (free hosting). Please wait a minute and try again.";

export function warmUp() {
  fetch(`${API_URL}/health`).catch(() => {});
}

async function request(path: string, options: RequestInit = {}) {
  const token = getToken();
  let res: Response;
  try {
    res = await fetch(API_URL + path, {
      ...options,
      headers: {
        ...(options.body instanceof FormData
          ? {}
          : { "Content-Type": "application/json" }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });
  } catch {
    throw new Error(WAKING_UP_MESSAGE);
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const message =
      typeof err.detail === "string" ? err.detail : "Please check your input";
    throw new Error(message);
  }
  return res.json();
}

export function login(email: string, password: string) {
  return request("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function signup(email: string, password: string, workspace_name: string) {
  return request("/auth/signup", {
    method: "POST",
    body: JSON.stringify({ email, password, workspace_name }),
  });
}

export function getMe(): Promise<Me> {
  return request("/auth/me");
}

export type DocumentInfo = {
  id: number;
  filename: string;
  size_bytes: number;
  status: string;
  error: string | null;
  warning: string | null;
  uploaded_by: number;
  created_at: string;
};

export function listDocuments(workspaceId: number): Promise<DocumentInfo[]> {
  return request(`/workspaces/${workspaceId}/documents`);
}

export function uploadDocument(workspaceId: number, file: File) {
  const form = new FormData();
  form.append("file", file);
  return request(`/workspaces/${workspaceId}/documents`, {
    method: "POST",
    body: form,
  });
}

export type Source = { filename: string; chunk_index: number; score: number };

export type ChatTurn = { role: "user" | "assistant"; content: string };

async function errorMessage(res: Response, fallback: string) {
  const err = await res.json().catch(() => ({}));
  return typeof err.detail === "string" ? err.detail : fallback;
}

export async function streamChat(
  workspaceId: number,
  question: string,
  history: ChatTurn[],
  onSources: (sources: Source[]) => void,
  onToken: (token: string) => void,
  onQuery: (query: string) => void,
  onNotice: (text: string) => void,
) {
  const res = await fetch(`${API_URL}/workspaces/${workspaceId}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
    },
    body: JSON.stringify({ question, history }),
  });

  if (!res.ok) throw new Error(await errorMessage(res, "Chat failed"));
  if (!res.body) throw new Error("Chat failed");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";

    for (const part of parts) {
      if (!part.startsWith("data: ")) continue;
      const event = JSON.parse(part.slice(6));
      if (event.type === "query") onQuery(event.data);
      if (event.type === "sources") onSources(event.data);
      if (event.type === "token") onToken(event.data);
      if (event.type === "notice") onNotice(event.data);
    }
  }
}

export function deleteDocument(workspaceId: number, documentId: number) {
  return request(`/workspaces/${workspaceId}/documents/${documentId}`, {
    method: "DELETE",
  });
}

function describeStep(name: string, args: Record<string, unknown>) {
  if (name === "search_documents") {
    return `Searching documents for: ${String(args.query ?? "")}`;
  }
  if (name === "list_documents") return "Listing your files";
  return `Using tool: ${name}`;
}

export async function streamAgent(
  workspaceId: number,
  question: string,
  history: ChatTurn[],
  onStep: (text: string) => void,
  onToken: (token: string) => void,
  onError: (message: string) => void,
  onNotice: (text: string) => void,
) {
  const res = await fetch(`${API_URL}/workspaces/${workspaceId}/agent`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
    },
    body: JSON.stringify({ question, history }),
  });

  if (!res.ok) throw new Error(await errorMessage(res, "Agent failed"));
  if (!res.body) throw new Error("Agent failed");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";

    for (const part of parts) {
      if (!part.startsWith("data: ")) continue;
      const event = JSON.parse(part.slice(6));
      if (event.type === "tool_call") {
        onStep(describeStep(event.data.name, event.data.args ?? {}));
      }
      if (event.type === "token") onToken(event.data);
      if (event.type === "error") onError(event.data);
      if (event.type === "notice") onNotice(event.data);
    }
  }
}

export type Role = "owner" | "member" | "viewer";
export type MemberInfo = { user_id: number; email: string; role: Role };

export function listMembers(workspaceId: number): Promise<MemberInfo[]> {
  return request(`/workspaces/${workspaceId}/members`);
}

export function addMember(workspaceId: number, email: string, role: Role) {
  return request(`/workspaces/${workspaceId}/members`, {
    method: "POST",
    body: JSON.stringify({ email, role }),
  });
}

export function changeMemberRole(workspaceId: number, userId: number, role: Role) {
  return request(`/workspaces/${workspaceId}/members/${userId}`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

export function removeMember(workspaceId: number, userId: number) {
  return request(`/workspaces/${workspaceId}/members/${userId}`, {
    method: "DELETE",
  });
}

export type UsageKind = {
  kind: string;
  requests: number;
  errors: number;
  avg_ms: number;
  p95_ms: number;
  input_tokens: number;
  output_tokens: number;
  embed_tokens: number;
  cost_usd: number;
};

export type UsageStats = {
  days: number;
  total: { requests: number; errors: number; tokens: number; cost_usd: number };
  by_kind: UsageKind[];
  by_day: { day: string; requests: number; cost_usd: number }[];
};

export function getUsage(workspaceId: number, days: number): Promise<UsageStats> {
  return request(`/workspaces/${workspaceId}/usage?days=${days}`);
}
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

async function request(path: string, options: RequestInit = {}) {
  const token = getToken();
  const res = await fetch(API_URL + path, {
    ...options,
    headers: {
      ...(options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });

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

export async function streamChat(
  workspaceId: number,
  question: string,
  history: ChatTurn[],
  onSources: (sources: Source[]) => void,
  onToken: (token: string) => void,
  onQuery: (query: string) => void,
) {
  const res = await fetch(`${API_URL}/workspaces/${workspaceId}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
    },
    body: JSON.stringify({ question, history }),
  });

  if (!res.ok || !res.body) throw new Error("Chat failed");

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
    }
  }
}

export function deleteDocument(workspaceId: number, documentId: number) {
  return request(`/workspaces/${workspaceId}/documents/${documentId}`, {
    method: "DELETE",
  });
}
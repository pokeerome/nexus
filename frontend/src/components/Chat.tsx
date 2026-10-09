import { useState } from "react";
import type { FormEvent } from "react";
import { streamAgent, streamChat } from "../api";
import type { Source } from "../api";

type Message = {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  searchedFor?: string;
  steps?: string[];
  notice?: string;
};

export default function Chat({ workspaceId }: { workspaceId: number }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [agentMode, setAgentMode] = useState(false);

  function updateLast(change: (m: Message) => Message) {
    setMessages((prev) => {
      const copy = [...prev];
      copy[copy.length - 1] = change(copy[copy.length - 1]);
      return copy;
    });
  }

  async function handleSend(e: FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || busy) return;

    const history = messages
      .filter((m) => m.content)
      .slice(-6)
      .map((m) => ({ role: m.role, content: m.content.slice(0, 500) }));

    setInput("");
    setBusy(true);
    setMessages((prev) => [
      ...prev,
      { role: "user", content: question },
      { role: "assistant", content: "" },
    ]);

    try {
      if (agentMode) {
        await streamAgent(
          workspaceId,
          question,
          history,
          (step) =>
            updateLast((m) => ({ ...m, steps: [...(m.steps ?? []), step] })),
          (token) => updateLast((m) => ({ ...m, content: m.content + token })),
          (message) => updateLast((m) => ({ ...m, content: message })),
          (notice) => updateLast((m) => ({ ...m, notice })),
        );
      } else {
        await streamChat(
          workspaceId,
          question,
          history,
          (sources) => updateLast((m) => ({ ...m, sources })),
          (token) => updateLast((m) => ({ ...m, content: m.content + token })),
          (query) => updateLast((m) => ({ ...m, searchedFor: query })),
          (notice) => updateLast((m) => ({ ...m, notice })),
        );
      }
    } catch (err) {
      updateLast((m) => ({
        ...m,
        content: (err as Error).message || "Something went wrong. Please try again.",
      }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="bg-slate-800 p-6 rounded-xl">
      <h2 className="text-xl font-semibold mb-4">Ask your documents</h2>

      <div className="space-y-4 mb-4">
        {messages.length === 0 && (
          <p className="text-slate-400">Ask a question about your uploaded files.</p>
        )}

        {messages.map((m, i) => (
          <div
            key={i}
            className={m.role === "user" ? "text-right" : "text-left"}
          >
            <div
              className={
                "inline-block max-w-full p-3 rounded-lg whitespace-pre-wrap " +
                (m.role === "user" ? "bg-blue-600" : "bg-slate-700")
              }
            >
              {m.content || (busy ? "Thinking..." : "")}
            </div>

            {m.steps && m.steps.length > 0 && (
              <ul className="text-slate-500 text-xs mt-1 space-y-0.5">
                {m.steps.map((s, idx) => (
                  <li key={idx}>{s}</li>
                ))}
              </ul>
            )}
            {m.searchedFor && m.searchedFor !== messages[i - 1]?.content && (
              <p className="text-slate-500 text-xs mt-1">
                Searched for: {m.searchedFor}
              </p>
            )}
            {m.sources && m.sources.length > 0 && (
              <p className="text-slate-400 text-xs mt-1">
                Sources: {[...new Set(m.sources.map((s) => s.filename))].join(", ")}
              </p>
            )}
            {m.notice && <p className="text-amber-400 text-xs mt-1">{m.notice}</p>}
          </div>
        ))}
      </div>

      <label className="flex items-center gap-2 text-sm text-slate-300 mb-3">
        <input
          type="checkbox"
          checked={agentMode}
          onChange={(e) => setAgentMode(e.target.checked)}
          disabled={busy}
        />
        Agent mode (can search several times and compare files)
      </label>
      <form onSubmit={handleSend} className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type your question..."
          className="flex-1 p-3 rounded bg-slate-700 text-white"
        />
        <button
          type="submit"
          disabled={busy}
          className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </div>
  );
}
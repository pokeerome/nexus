import { useState } from "react";
import type { FormEvent } from "react";
import { streamChat } from "../api";
import type { Source } from "../api";

type Message = {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
};

export default function Chat({ workspaceId }: { workspaceId: number }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

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

    setInput("");
    setBusy(true);
    setMessages((prev) => [
      ...prev,
      { role: "user", content: question },
      { role: "assistant", content: "" },
    ]);

    try {
      await streamChat(
        workspaceId,
        question,
        (sources) => updateLast((m) => ({ ...m, sources })),
        (token) => updateLast((m) => ({ ...m, content: m.content + token })),
      );
    } catch {
      updateLast((m) => ({
        ...m,
        content: "Something went wrong. Please try again.",
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

            {m.sources && m.sources.length > 0 && (
              <p className="text-slate-400 text-xs mt-1">
                Sources: {[...new Set(m.sources.map((s) => s.filename))].join(", ")}
              </p>
            )}
          </div>
        ))}
      </div>

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
import { useEffect, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { listDocuments, uploadDocument } from "../api";
import type { DocumentInfo } from "../api";

export default function Documents({ workspaceId }: { workspaceId: number }) {
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [reloadCount, setReloadCount] = useState(0);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;

    listDocuments(workspaceId)
      .then((data) => {
        if (!cancelled) setDocs(data);
      })
      .catch((err) => {
        if (!cancelled) setError((err as Error).message);
      });

    return () => {
      cancelled = true;
    };
  }, [workspaceId, reloadCount]);

    useEffect(() => {
    const pending = docs.some(
      (d) => d.status === "queued" || d.status === "processing",
    );
    if (!pending) return;

    const timer = setTimeout(() => setReloadCount((n) => n + 1), 2500);
    return () => clearTimeout(timer);
  }, [docs]);

  async function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    setError("");
    setUploading(true);
    try {
      await uploadDocument(workspaceId, file);
      setReloadCount((n) => n + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  return (
    <div className="bg-slate-800 p-6 rounded-xl">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold">Documents</h2>
        <label className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 cursor-pointer">
          {uploading ? "Uploading..." : "Upload file"}
          <input
            ref={fileInput}
            type="file"
            accept=".pdf,.txt,.md,.docx,.csv"
            onChange={handleFileChange}
            disabled={uploading}
            className="hidden"
          />
        </label>
      </div>

      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

      {docs.length === 0 ? (
        <p className="text-slate-400">No documents yet. Upload your first file.</p>
      ) : (
        <ul className="space-y-2">
          {docs.map((d) => (
            <li key={d.id}>
              <div className="flex justify-between">
                <span>{d.filename}</span>
                <span className="text-slate-400 text-sm">
                  {(d.size_bytes / 1024).toFixed(1)} KB · {d.status}
                </span>
              </div>
              {d.error && <p className="text-red-400 text-xs">{d.error}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
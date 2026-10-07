import { useEffect, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { deleteDocument, listDocuments, uploadDocument } from "../api";
import type { DocumentInfo } from "../api";

type Props = {
  workspaceId: number;
  role: string;
  userId: number;
};

export default function Documents({ workspaceId, role, userId }: Props) {
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [reloadCount, setReloadCount] = useState(0);
  const fileInput = useRef<HTMLInputElement>(null);

  const canUpload = role === "owner" || role === "member";
  const canRemove = (d: DocumentInfo) =>
    role === "owner" || (role === "member" && d.uploaded_by === userId);

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

  async function handleDelete(doc: DocumentInfo) {
    if (!window.confirm(`Remove "${doc.filename}"? This cannot be undone.`)) return;

    setError("");
    setDeletingId(doc.id);
    try {
      await deleteDocument(workspaceId, doc.id);
      setReloadCount((n) => n + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="bg-slate-800 p-6 rounded-xl">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold">Documents</h2>
        {canUpload ? (
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
        ) : (
          <span className="text-slate-400 text-sm">View only</span>
        )}
      </div>

      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

      {docs.length === 0 ? (
        <p className="text-slate-400">
          {canUpload ? "No documents yet. Upload your first file." : "No documents yet."}
        </p>
      ) : (
        <ul className="space-y-2">
          {docs.map((d) => (
            <li key={d.id}>
              <div className="flex items-center justify-between gap-3">
                <span className="truncate">{d.filename}</span>
                <span className="flex items-center gap-3 shrink-0">
                  <span className="text-slate-400 text-sm">
                    {(d.size_bytes / 1024).toFixed(1)} KB · {d.status}
                  </span>
                  {canRemove(d) && (
                    <button
                      onClick={() => handleDelete(d)}
                      disabled={deletingId === d.id}
                      className="text-red-400 hover:text-red-300 text-sm disabled:opacity-50"
                    >
                      {deletingId === d.id ? "Removing..." : "Remove"}
                    </button>
                  )}
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

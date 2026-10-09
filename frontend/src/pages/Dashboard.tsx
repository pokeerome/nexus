import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { clearToken, getMe, getToken } from "../api";
import type { Me } from "../api";
import Chat from "../components/Chat";
import Documents from "../components/Documents";
import Members from "../components/Members";
import Usage from "../components/Usage";

export default function Dashboard() {
  const navigate = useNavigate();
  const [me, setMe] = useState<Me | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [reloadCount, setReloadCount] = useState(0);

  useEffect(() => {
    if (!getToken()) {
      navigate("/login");
      return;
    }
    getMe()
      .then(setMe)
      .catch(() => {
        clearToken();
        navigate("/login");
      });
  }, [navigate, reloadCount]);

  function handleLogout() {
    clearToken();
    navigate("/login");
  }

  if (!me) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-900 text-white">
        Loading...
      </div>
    );
  }

  const current = me.workspaces.find((w) => w.id === selectedId) ?? me.workspaces[0];

  return (
    <div className="min-h-screen bg-slate-900 text-white p-8">
      <div className="max-w-2xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-bold">Nexus</h1>
          <button
            onClick={handleLogout}
            className="px-4 py-2 rounded bg-slate-700 hover:bg-slate-600"
          >
            Log out
          </button>
        </div>

        <p className="text-slate-300">Logged in as {me.email}</p>

        {!current ? (
          <div className="bg-slate-800 p-6 rounded-xl text-slate-300">
            You are not a member of any workspace.
          </div>
        ) : (
          <>
            <div className="bg-slate-800 p-6 rounded-xl flex items-center justify-between gap-4">
              <div>
                <h2 className="text-xl font-semibold">Workspace</h2>
                <p className="text-slate-400 text-sm">Your role: {current.role}</p>
              </div>
              {me.workspaces.length > 1 ? (
                <select
                  value={current.id}
                  onChange={(e) => setSelectedId(Number(e.target.value))}
                  className="p-2 rounded bg-slate-700 text-white"
                >
                  {me.workspaces.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name} ({w.role})
                    </option>
                  ))}
                </select>
              ) : (
                <span className="text-lg">{current.name}</span>
              )}
            </div>

            <Documents
              key={`docs-${current.id}`}
              workspaceId={current.id}
              role={current.role}
              userId={me.id}
            />
            <Chat key={`chat-${current.id}`} workspaceId={current.id} />
            <Members
              key={`members-${current.id}`}
              workspaceId={current.id}
              myRole={current.role}
              myUserId={me.id}
              onChanged={() => setReloadCount((n) => n + 1)}
            />
            {current.role === "owner" && (
              <Usage key={`usage-${current.id}`} workspaceId={current.id} />
            )}
          </>
        )}
      </div>
    </div>
  );
}

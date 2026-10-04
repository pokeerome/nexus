import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { clearToken, getMe, getToken } from "../api";
import type { Me } from "../api";
import Documents from "../components/Documents";
import Chat from "../components/Chat";

export default function Dashboard() {
  const navigate = useNavigate();
  const [me, setMe] = useState<Me | null>(null);

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
  }, [navigate]);

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

        <div className="bg-slate-800 p-6 rounded-xl">
          <h2 className="text-xl font-semibold mb-3">Your workspaces</h2>
          <ul className="space-y-2">
            {me.workspaces.map((w) => (
              <li key={w.id} className="flex justify-between">
                <span>{w.name}</span>
                <span className="text-slate-400">{w.role}</span>
              </li>
            ))}
          </ul>
        </div>

        {me.workspaces[0] && <Documents workspaceId={me.workspaces[0].id} />}
        {me.workspaces[0] && <Chat workspaceId={me.workspaces[0].id} />}
      </div>
    </div>
  );
}
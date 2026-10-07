import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { addMember, changeMemberRole, listMembers, removeMember } from "../api";
import type { MemberInfo, Role } from "../api";

type Props = {
  workspaceId: number;
  myRole: string;
  myUserId: number;
  onChanged: () => void;
};

const ROLES: Role[] = ["owner", "member", "viewer"];

export default function Members({ workspaceId, myRole, myUserId, onChanged }: Props) {
  const [members, setMembers] = useState<MemberInfo[]>([]);
  const [error, setError] = useState("");
  const [reloadCount, setReloadCount] = useState(0);
  const [email, setEmail] = useState("");
  const [newRole, setNewRole] = useState<Role>("member");
  const isOwner = myRole === "owner";

  useEffect(() => {
    let cancelled = false;

    listMembers(workspaceId)
      .then((data) => {
        if (!cancelled) setMembers(data);
      })
      .catch((err) => {
        if (!cancelled) setError((err as Error).message);
      });

    return () => {
      cancelled = true;
    };
  }, [workspaceId, reloadCount]);

  async function run(action: () => Promise<unknown>, after?: () => void) {
    setError("");
    try {
      await action();
      setReloadCount((n) => n + 1);
      after?.();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  function handleAdd(e: FormEvent) {
    e.preventDefault();
    const trimmed = email.trim();
    if (!trimmed) return;
    run(
      () => addMember(workspaceId, trimmed, newRole),
      () => setEmail(""),
    );
  }

  function handleRoleChange(member: MemberInfo, role: Role) {
    run(
      () => changeMemberRole(workspaceId, member.user_id, role),
      member.user_id === myUserId ? onChanged : undefined,
    );
  }

  function handleRemove(member: MemberInfo) {
    if (!window.confirm(`Remove ${member.email} from this workspace?`)) return;
    run(() => removeMember(workspaceId, member.user_id));
  }

  function handleLeave() {
    if (!window.confirm("Leave this workspace?")) return;
    run(() => removeMember(workspaceId, myUserId), onChanged);
  }

  return (
    <div className="bg-slate-800 p-6 rounded-xl">
      <h2 className="text-xl font-semibold mb-4">Members</h2>

      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

      <ul className="space-y-2">
        {members.map((m) => (
          <li key={m.user_id} className="flex items-center justify-between gap-3">
            <span className="truncate">
              {m.email}
              {m.user_id === myUserId && <span className="text-slate-400"> (you)</span>}
            </span>
            <span className="flex items-center gap-3 shrink-0">
              {isOwner ? (
                <select
                  value={m.role}
                  onChange={(e) => handleRoleChange(m, e.target.value as Role)}
                  className="p-1 rounded bg-slate-700 text-white text-sm"
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              ) : (
                <span className="text-slate-400 text-sm">{m.role}</span>
              )}
              {isOwner && m.user_id !== myUserId && (
                <button
                  onClick={() => handleRemove(m)}
                  className="text-red-400 hover:text-red-300 text-sm"
                >
                  Remove
                </button>
              )}
              {m.user_id === myUserId && (
                <button
                  onClick={handleLeave}
                  className="text-slate-400 hover:text-white text-sm"
                >
                  Leave
                </button>
              )}
            </span>
          </li>
        ))}
      </ul>

      {isOwner && (
        <form onSubmit={handleAdd} className="flex gap-2 mt-4">
          <input
            type="email"
            placeholder="Email of an existing user"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="flex-1 p-2 rounded bg-slate-700 text-white"
          />
          <select
            value={newRole}
            onChange={(e) => setNewRole(e.target.value as Role)}
            className="p-2 rounded bg-slate-700 text-white"
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <button
            type="submit"
            className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-500"
          >
            Add
          </button>
        </form>
      )}
    </div>
  );
}

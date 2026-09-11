import React, { useEffect, useRef, useState } from "react";
import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { MessageSquare, LayoutGrid, ListChecks, LogOut, Settings, BookOpen, FolderOpen, Shield } from "lucide-react";

function LogoMark({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
      <ellipse cx="20" cy="12" rx="14" ry="10" fill="#FF8A00" />
      <ellipse cx="15" cy="18" rx="13" ry="10" fill="#FF3D77" opacity="0.9" />
      <ellipse cx="22" cy="23" rx="12" ry="10" fill="#E4007C" opacity="0.85" />
      <ellipse cx="17" cy="29" rx="11" ry="9" fill="#00707A" />
    </svg>
  );
}

export default function DashboardLayout() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => {
    const onClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const firstName = user?.name?.split(" ")[0] || "";
  const initial = (user?.name || user?.email || "?").trim().charAt(0).toUpperCase();

  return (
    <div className="min-h-screen">
      <header className="px-8 md:px-14 pt-8">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-full border border-white/20 bg-white/10 flex items-center justify-center shadow-sm shrink-0">
              <LogoMark size={20} />
            </div>
            <nav className="flex items-center gap-5">
              <TabLink to="/dashboard/chat" icon={<MessageSquare size={15} />} label="Chat" testid="tab-chat" />
              <TabLink to="/dashboard/tasks" icon={<LayoutGrid size={15} />} label="Task" testid="tab-tasks" />
              <TabLink to="/dashboard/todos" icon={<ListChecks size={15} />} label="To-Do" testid="tab-todos" />
              <TabLink to="/dashboard/journal" icon={<BookOpen size={15} />} label="Diario" testid="tab-journal" />
              <TabLink to="/dashboard/documents" icon={<FolderOpen size={15} />} label="Documenti" testid="tab-documents" />
              {user?.role === "admin" && (
                <TabLink to="/dashboard/admin" icon={<Shield size={15} />} label="Admin" testid="tab-admin" />
              )}
              <TabLink to="/dashboard/settings" icon={<Settings size={15} />} label="Impostazioni" testid="tab-settings" />
            </nav>
          </div>

          <div className="relative" ref={menuRef}>
            <button
              data-testid="user-menu-btn"
              onClick={() => setMenuOpen((v) => !v)}
              className="flex items-center gap-2.5 hover:opacity-80 transition-opacity"
            >
              {user?.picture ? (
                <img src={user.picture} alt={user?.name || "utente"} className="h-9 w-9 rounded-full object-cover border border-white/20 shrink-0" />
              ) : (
                <div className="h-9 w-9 rounded-full bg-white/10 border border-white/20 flex items-center justify-center text-sm font-semibold shrink-0">
                  {initial}
                </div>
              )}
              <div className="text-left hidden sm:block">
                <div className="text-sm font-medium leading-tight">{firstName || user?.email}</div>
                {user?.profession && <div className="text-[11px] text-white/50 leading-tight">{user.profession}</div>}
              </div>
            </button>

            {menuOpen && (
              <div className="absolute right-0 top-full mt-2 w-44 rounded-xl bg-[#403A3C] shadow-lg border border-white/10 py-1.5 z-40">
                <button
                  data-testid="logout-btn"
                  onClick={() => { setMenuOpen(false); logout(); }}
                  className="w-full flex items-center gap-2 px-4 py-2 text-sm text-white/85 hover:bg-white/10"
                >
                  <LogOut size={14} /> Esci
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      <main className="px-8 md:px-14 py-8 w-full">
        <Outlet />
      </main>
    </div>
  );
}

function TabLink({ to, icon, label, testid }) {
  return (
    <NavLink
      to={to}
      data-testid={testid}
      className={({ isActive }) =>
        `inline-flex items-center gap-1.5 text-sm transition-colors duration-150 ${
          isActive ? "text-white font-semibold" : "text-white/50 hover:text-white/80"
        }`
      }
    >
      {icon} {label}
    </NavLink>
  );
}

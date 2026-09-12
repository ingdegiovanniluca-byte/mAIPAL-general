import React, { useEffect, useRef, useState } from "react";
import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { LogOut } from "lucide-react";

const NAV_ITEMS = [
  { to: "/dashboard/chat", label: "Chat", testid: "tab-chat" },
  { to: "/dashboard/tasks", label: "Task", testid: "tab-tasks" },
  { to: "/dashboard/todos", label: "To-Do", testid: "tab-todos" },
  { to: "/dashboard/journal", label: "Diario", testid: "tab-journal" },
  { to: "/dashboard/news", label: "News", testid: "tab-news" },
  { to: "/dashboard/liste", label: "Liste", testid: "tab-liste" },
  { to: "/dashboard/documents", label: "Documenti", testid: "tab-documents" },
  { to: "/dashboard/team", label: "Team", testid: "tab-team" },
  { to: "/dashboard/admin", label: "Admin", testid: "tab-admin", adminOnly: true },
  { to: "/dashboard/settings", label: "Impostazioni", testid: "tab-settings" },
];

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
      <header className="px-8 md:px-14 pt-8 pb-8">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="h-12 w-12 rounded-full bg-white/10 flex items-center justify-center shrink-0">
            <LogoMark size={30} />
          </div>

          <nav className="flex-1 flex items-center justify-center gap-2.5 md:gap-3 flex-wrap">
            {NAV_ITEMS.filter((item) => !item.adminOnly || user?.role === "admin").map((item, i) => (
              <React.Fragment key={item.to}>
                {i > 0 && <span className="text-white/25 text-xs select-none">•</span>}
                <TabLink to={item.to} label={item.label} testid={item.testid} />
              </React.Fragment>
            ))}
          </nav>

          <div className="relative shrink-0" ref={menuRef}>
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

      <main className="px-8 md:px-14 pt-6 pb-8 w-full">
        <Outlet />
      </main>
    </div>
  );
}

function TabLink({ to, label, testid }) {
  return (
    <NavLink
      to={to}
      data-testid={testid}
      className={({ isActive }) =>
        `text-sm transition-colors duration-150 ${
          isActive ? "text-white font-semibold" : "text-white/55 hover:text-white/80"
        }`
      }
    >
      {label}
    </NavLink>
  );
}

import React, { useState } from "react";
import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { MessageSquare, LayoutGrid, ListChecks, LogOut } from "lucide-react";

export default function DashboardLayout() {
  const { user, logout } = useAuth();
  const nav = useNavigate();

  return (
    <div className="min-h-screen">
      <header className="px-8 md:px-14 pt-8 flex items-center justify-between">
        <button data-testid="brand" onClick={() => nav("/dashboard")} className="kicker">· mAIPAL</button>
        <div className="flex items-center gap-4">
          <div className="kicker hidden sm:block">{user?.email}</div>
          <button data-testid="logout-btn" onClick={logout} className="p-2 rounded-full hover:bg-neutral-200/60">
            <LogOut size={16} />
          </button>
        </div>
      </header>

      <section className="px-8 md:px-14 pt-6">
        <div className="kicker">· dashboard</div>
        <h1 className="mt-2 text-4xl md:text-5xl lg:text-6xl font-bold tracking-tight leading-tight">
          Cosa vuoi fare, <span className="gradient-word">{user?.name?.split(" ")[0] || "mAIPAL"}</span>?
        </h1>

        <nav className="mt-8 inline-flex items-center gap-1 p-1 rounded-full bg-neutral-200/60">
          <TabLink to="/dashboard/chat" icon={<MessageSquare size={15} />} label="Chat" testid="tab-chat" />
          <TabLink to="/dashboard/tasks" icon={<LayoutGrid size={15} />} label="Task Board" testid="tab-tasks" />
          <TabLink to="/dashboard/todos" icon={<ListChecks size={15} />} label="To-Do" testid="tab-todos" />
        </nav>
      </section>

      <main className="px-8 md:px-14 py-8">
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
        `inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm transition-colors duration-150 ${
          isActive ? "bg-white text-black shadow-sm" : "text-neutral-500 hover:text-black"
        }`
      }
    >
      {icon} {label}
    </NavLink>
  );
}

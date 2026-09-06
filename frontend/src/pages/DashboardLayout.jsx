import React, { useState } from "react";
import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { MessageSquare, LayoutGrid, ListChecks, LogOut, Settings, BookOpen, FolderOpen, Shield } from "lucide-react";

export default function DashboardLayout() {
  const { user, logout } = useAuth();
  const nav = useNavigate();

  return (
    <div className="min-h-screen">
      <header className="px-8 md:px-14 pt-8"></header>

      <section className="px-8 md:px-14 pt-6">
        <div className="flex items-end justify-between flex-wrap gap-3">
          <h1 className="mt-2 text-2xl md:text-3xl lg:text-4xl font-bold tracking-tight leading-tight">
            Cosa vuoi fare, <span className="gradient-word">{user?.name?.split(" ")[0] || "mAIPAL"}</span>?
          </h1>
          <div className="flex items-center gap-3 pb-3">
            <div className="kicker-p hidden sm:block">{user?.email}</div>
            <button data-testid="logout-btn" onClick={logout} title="Esci" className="p-2 rounded-full text-white/70 hover:text-white hover:bg-white/10">
              <LogOut size={16} />
            </button>
          </div>
        </div>

        <nav className="mt-8 inline-flex items-center gap-1 p-1 rounded-full bg-white/5  backdrop-blur-md">
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
      </section>

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
        `inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm transition-all duration-150 ${
          isActive
            ? "bg-[#CECAD0] text-[#403A3C] shadow-sm font-medium"
            : "text-[#CECAD0]/50 hover:text-[#CECAD0]"
        }`
      }
    >
      {icon} {label}
    </NavLink>
  );
}

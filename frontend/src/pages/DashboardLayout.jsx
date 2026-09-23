import React, { useEffect, useRef, useState } from "react";
import { Outlet, NavLink, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import {
  LogOut, Settings, MoreHorizontal, MessageSquare, CheckSquare, ListChecks, BookOpen,
  Newspaper, List, FileText, Dumbbell,
} from "lucide-react";
import logo3 from "@/assets/logo3.png";

const NAV_ITEMS = [
  { to: "/dashboard/chat", label: "Chat", testid: "tab-chat", icon: MessageSquare },
  { to: "/dashboard/tasks", label: "Task", testid: "tab-tasks", icon: CheckSquare },
  { to: "/dashboard/todos", label: "To-Do", testid: "tab-todos", icon: ListChecks },
  { to: "/dashboard/journal", label: "Diario", testid: "tab-journal", icon: BookOpen },
  { to: "/dashboard/news", label: "News", testid: "tab-news", icon: Newspaper },
  { to: "/dashboard/liste", label: "Liste", testid: "tab-liste", icon: List },
  { to: "/dashboard/documents", label: "Documenti", testid: "tab-documents", icon: FileText },
  { to: "/dashboard/fitness", label: "Fitness", testid: "tab-fitness", vertical: "fitness", icon: Dumbbell },
  { to: "/dashboard/settings", label: "Impostazioni", testid: "tab-settings", icon: Settings },
];

// On the mobile bottom bar these 4 sections get their own button; everything else (except
// Impostazioni, reached from the avatar) lives inside "Altro".
const MOBILE_PRIMARY = ["/dashboard/chat", "/dashboard/tasks", "/dashboard/todos", "/dashboard/journal"];

export default function DashboardLayout() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [keyboardOpen, setKeyboardOpen] = useState(false);
  // Desktop and mobile each render their own avatar-menu trigger (only one is ever visible
  // at a time, via CSS, but both stay mounted) - two separate refs so "click outside"
  // checks the container that's actually showing, not whichever rendered last.
  const menuRef = useRef(null);
  const menuRefMobile = useRef(null);

  useEffect(() => {
    const onClickOutside = (e) => {
      const insideDesktop = menuRef.current && menuRef.current.contains(e.target);
      const insideMobile = menuRefMobile.current && menuRefMobile.current.contains(e.target);
      if (!insideDesktop && !insideMobile) setMenuOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  // The bottom nav hides while a text field has focus (keyboard open on a phone), so it
  // never fights with the field for screen space - reappears the moment focus leaves it.
  useEffect(() => {
    const isField = (el) => el && (el.tagName === "TEXTAREA" ||
      (el.tagName === "INPUT" && !["checkbox", "radio", "button", "submit", "range", "file"].includes(el.type)));
    const onFocusIn = (e) => { if (isField(e.target)) setKeyboardOpen(true); };
    const onFocusOut = (e) => { if (isField(e.target)) setKeyboardOpen(false); };
    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("focusout", onFocusOut);
    return () => {
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("focusout", onFocusOut);
    };
  }, []);

  const firstName = user?.name?.split(" ")[0] || "";
  const initial = (user?.name || user?.email || "?").trim().charAt(0).toUpperCase();

  const visibleItems = NAV_ITEMS.filter((item) => (!item.adminOnly || user?.role === "admin") && (!item.vertical || user?.business_vertical === item.vertical));
  const primaryItems = visibleItems.filter((item) => MOBILE_PRIMARY.includes(item.to));
  const moreItems = visibleItems.filter((item) => !MOBILE_PRIMARY.includes(item.to) && item.to !== "/dashboard/settings");
  const currentItem = visibleItems.find((item) => location.pathname.startsWith(item.to));
  const isMoreActive = !!currentItem && moreItems.some((item) => item.to === currentItem.to);

  const goTo = (to) => { setMoreOpen(false); setMenuOpen(false); nav(to); };

  return (
    <div className="min-h-screen relative">
      <div className="liquid-page-bg" aria-hidden="true">
        <span className="liquid-blob liquid-blob-1" />
        <span className="liquid-blob liquid-blob-2" />
        <span className="liquid-blob liquid-blob-3" />
        <span className="liquid-blob liquid-blob-4" />
        <span className="liquid-blob liquid-blob-5" />
      </div>

      <div className="relative z-10">
        {/* ===== Desktop / tablet header (>=768px) — unchanged content, now fixed in place
            (see spec 3.1: the menu stays visible everywhere, not just on mobile). A subtle
            backdrop is required for that (a sticky header with no backing would let content
            show through as the page scrolls under it); nothing else about it changes. ===== */}
        <header className="hidden md:block sticky top-0 z-40 px-8 md:px-14 pt-8 pb-8 bg-white/5 backdrop-blur-xl">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div className="h-12 w-12 rounded-full bg-white/10 flex items-center justify-center shrink-0 overflow-hidden">
              <div
                className="logo-wave h-8 aspect-[345/539] shrink-0"
                style={{ WebkitMaskImage: `url(${logo3})`, maskImage: `url(${logo3})` }}
                role="img"
                aria-label="mAIPAL"
              />
            </div>

            <nav className="flex-1 flex items-center justify-center gap-2.5 md:gap-3 flex-wrap">
              {visibleItems.map((item, i) => (
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

        {/* ===== Mobile top bar (<768px): logo · section name · avatar, fixed, thin ===== */}
        <header
          className="md:hidden sticky top-0 z-40 flex items-center justify-between gap-3 px-4 h-14 bg-white/5 backdrop-blur-xl"
          style={{ paddingTop: "env(safe-area-inset-top, 0px)" }}
        >
          <div className="h-8 w-8 rounded-full bg-white/10 flex items-center justify-center shrink-0 overflow-hidden">
            <div
              className="logo-wave h-5 aspect-[345/539] shrink-0"
              style={{ WebkitMaskImage: `url(${logo3})`, maskImage: `url(${logo3})` }}
              role="img"
              aria-label="mAIPAL"
            />
          </div>
          <div className="text-sm font-semibold text-white truncate">{currentItem?.label || ""}</div>
          <div className="relative shrink-0" ref={menuRefMobile}>
            <button
              data-testid="user-menu-btn-mobile"
              onClick={() => setMenuOpen((v) => !v)}
              className="block"
            >
              {user?.picture ? (
                <img src={user.picture} alt={user?.name || "utente"} className="h-8 w-8 rounded-full object-cover border border-white/20" />
              ) : (
                <div className="h-8 w-8 rounded-full bg-white/10 border border-white/20 flex items-center justify-center text-xs font-semibold">
                  {initial}
                </div>
              )}
            </button>
            {menuOpen && (
              <div className="absolute right-0 top-full mt-2 w-48 rounded-xl bg-[#403A3C] shadow-lg border border-white/10 py-1.5 z-40">
                <button
                  data-testid="settings-btn-mobile"
                  onClick={() => goTo("/dashboard/settings")}
                  className="w-full flex items-center gap-2 px-4 py-2 text-sm text-white/85 hover:bg-white/10"
                >
                  <Settings size={14} /> Impostazioni
                </button>
                <button
                  data-testid="logout-btn-mobile"
                  onClick={() => { setMenuOpen(false); logout(); }}
                  className="w-full flex items-center gap-2 px-4 py-2 text-sm text-white/85 hover:bg-white/10"
                >
                  <LogOut size={14} /> Esci
                </button>
              </div>
            )}
          </div>
        </header>

        <main className="px-4 md:px-14 pt-4 md:pt-6 pb-24 md:pb-8 w-full">
          <Outlet />
        </main>

        {/* ===== Mobile bottom navigation bar (<768px) ===== */}
        {!keyboardOpen && (
          <nav
            data-testid="mobile-bottom-nav"
            className="md:hidden fixed bottom-0 left-0 right-0 z-40 flex items-stretch bg-[#3A3638]/95 backdrop-blur-xl border-t border-white/10"
            style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
          >
            {primaryItems.map((item) => {
              const active = currentItem?.to === item.to;
              const Icon = item.icon;
              return (
                <button
                  key={item.to}
                  data-testid={item.testid}
                  onClick={() => goTo(item.to)}
                  className={`flex-1 flex flex-col items-center justify-center gap-0.5 py-2 transition-colors ${active ? "text-white" : "text-white/50"}`}
                >
                  <Icon size={20} />
                  <span className="text-[10px] leading-none">{item.label}</span>
                </button>
              );
            })}
            <button
              data-testid="tab-more"
              onClick={() => setMoreOpen(true)}
              className={`flex-1 flex flex-col items-center justify-center gap-0.5 py-2 transition-colors ${isMoreActive ? "text-white" : "text-white/50"}`}
            >
              <MoreHorizontal size={20} />
              <span className="text-[10px] leading-none">Altro</span>
            </button>
          </nav>
        )}

        {/* ===== "Altro" panel (remaining sections), from the bottom ===== */}
        {moreOpen && (
          <div className="md:hidden fixed inset-0 z-50 flex items-end" onClick={() => setMoreOpen(false)}>
            <div className="absolute inset-0 bg-black/60" aria-hidden="true" />
            <div
              data-testid="more-sheet"
              className="relative w-full rounded-t-3xl bg-[#3A3638] border-t border-white/10 p-4"
              style={{ paddingBottom: "calc(env(safe-area-inset-bottom, 0px) + 20px)" }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="w-10 h-1 rounded-full bg-white/20 mx-auto mb-4" />
              <div className="grid grid-cols-3 gap-3">
                {moreItems.map((item) => {
                  const active = currentItem?.to === item.to;
                  const Icon = item.icon;
                  return (
                    <button
                      key={item.to}
                      data-testid={item.testid}
                      onClick={() => goTo(item.to)}
                      className={`flex flex-col items-center gap-1.5 py-3 rounded-xl transition-colors ${active ? "bg-white/10 text-white" : "text-white/70 hover:bg-white/5"}`}
                    >
                      <Icon size={20} />
                      <span className="text-xs">{item.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </div>
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

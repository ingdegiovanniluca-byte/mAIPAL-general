import React, { useEffect, useRef, useState } from "react";
import PageBackground from "@/components/PageBackground";
import { Outlet, NavLink, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import {
  LogOut, Settings, Plus, MessageSquare, CheckSquare, ListChecks, BookOpen,
  Newspaper, List, FileText, Dumbbell, Repeat, History, Sun, Moon,
} from "lucide-react";
import logo3 from "@/assets/logo3.png";
import { MobileTitleContext } from "@/lib/mobile-title";
import { applyTheme, getStoredTheme } from "@/lib/theme";
import { useInstallApp, InstallBanner, InstallIcon } from "@/components/InstallApp";
import LiquidDock from "@/components/LiquidDock";
import GlassMenu, { GlassMenuItem } from "@/components/GlassMenu";
import { useIsMobile } from "@/hooks/use-is-mobile";

const NAV_ITEMS = [
  { to: "/dashboard/chat", label: "Chat", testid: "tab-chat", icon: MessageSquare },
  { to: "/dashboard/tasks", label: "Task", testid: "tab-tasks", icon: CheckSquare },
  { to: "/dashboard/todos", label: "To-Do", testid: "tab-todos", icon: ListChecks },
  { to: "/dashboard/journal", label: "Diario", testid: "tab-journal", icon: BookOpen },
  { to: "/dashboard/news", label: "News", testid: "tab-news", icon: Newspaper },
  { to: "/dashboard/liste", label: "Liste", testid: "tab-liste", icon: List },
  { to: "/dashboard/documents", label: "Documenti", testid: "tab-documents", icon: FileText },
  { to: "/dashboard/azioni", label: "Azioni", testid: "tab-azioni", icon: Repeat },
  { to: "/dashboard/fitness", label: "Fitness", testid: "tab-fitness", vertical: "fitness", icon: Dumbbell },
  { to: "/dashboard/settings", label: "Impostazioni", testid: "tab-settings", icon: Settings },
];

// On the mobile bottom bar these 4 sections get their own button (Liste in place of Diario); everything else (except
// Impostazioni, reached from the avatar) lives inside "Altro".
const MOBILE_PRIMARY = ["/dashboard/chat", "/dashboard/tasks", "/dashboard/todos", "/dashboard/liste"];

export default function DashboardLayout() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [keyboardOpen, setKeyboardOpen] = useState(false);
  // Optional suffix a page appends to the section name in the mobile top bar (e.g. the year on Task).
  const [titleSuffix, setTitleSuffix] = useState("");
  // Desktop and mobile each render their own avatar-menu trigger (only one is ever visible
  // at a time, via CSS, but both stay mounted) - two separate refs so "click outside"
  // checks the container that's actually showing, not whichever rendered last.
  const menuRef = useRef(null);
  const menuRefMobile = useRef(null);
  const menuPanelRef = useRef(null);
  const isMobile = useIsMobile();      // the menu itself, portaled out of the header
  const avatarRef = useRef(null);
  const avatarRefMobile = useRef(null);

  useEffect(() => {
    const onClickOutside = (e) => {
      const insideDesktop = menuRef.current && menuRef.current.contains(e.target);
      const insideMobile = (menuRefMobile.current && menuRefMobile.current.contains(e.target))
        || (menuPanelRef.current && menuPanelRef.current.contains(e.target));
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

  const installApp = useInstallApp();
  const firstName = user?.name?.split(" ")[0] || "";
  const initial = (user?.name || user?.email || "?").trim().charAt(0).toUpperCase();

  const visibleItems = NAV_ITEMS.filter((item) => (!item.adminOnly || user?.role === "admin") && (!item.vertical || user?.business_vertical === item.vertical));
  const primaryItems = visibleItems.filter((item) => MOBILE_PRIMARY.includes(item.to));
  // Everything not in the bottom pill lives behind its "+" button - Impostazioni included,
  // so it is reachable from there as well as from the avatar menu.
  const moreItems = visibleItems.filter((item) => !MOBILE_PRIMARY.includes(item.to));
  const currentItem = visibleItems.find((item) => location.pathname.startsWith(item.to));
  const isMoreActive = !!currentItem && moreItems.some((item) => item.to === currentItem.to);

  const goTo = (to) => { setMoreOpen(false); setMenuOpen(false); nav(to); };

  return (
    <div className="min-h-screen relative">
      <PageBackground />

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
                ref={avatarRef}
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

              {menuOpen && !isMobile && (
                <GlassMenu anchorRef={avatarRef} panelRef={menuPanelRef} testid="user-menu">
                  {!installApp.standalone && (
                    <GlassMenuItem icon={InstallIcon} label="Installa l'app" testid="install-app-btn"
                      onClick={() => { setMenuOpen(false); installApp.install(); }} />
                  )}
                  <GlassMenuItem icon={LogOut} label="Esci" testid="logout-btn" onClick={() => { setMenuOpen(false); logout(); }} />
                  <ThemeRow />
                </GlassMenu>
              )}
            </div>
          </div>
        </header>

        {/* ===== Mobile top bar (<768px): logo · section name · avatar, fixed, thin ===== */}
        <header
          className="md:hidden sticky top-0 z-40 flex items-center justify-between gap-3 px-4 bg-white/5 backdrop-blur-xl"
          // Installed app on iPhone: the page runs under the status bar, so the bar grows by
          // that inset instead of squeezing its 56px of content.
          style={{ paddingTop: "env(safe-area-inset-top, 0px)", height: "calc(3.5rem + env(safe-area-inset-top, 0px))" }}
        >
          <div className="h-8 w-8 rounded-full bg-white/10 flex items-center justify-center shrink-0 overflow-hidden">
            <div
              className="logo-wave h-5 aspect-[345/539] shrink-0"
              style={{ WebkitMaskImage: `url(${logo3})`, maskImage: `url(${logo3})` }}
              role="img"
              aria-label="mAIPAL"
            />
          </div>
          {/* section name; in Chat the history button sits right next to it */}
          <div className="min-w-0 flex items-center gap-2">
            <div className="text-sm font-semibold text-white truncate" data-testid="mobile-section-title">{currentItem?.label || ""}{titleSuffix ? ` ${titleSuffix}` : ""}</div>
            {/* Chat only: the history of old conversations (ChatPage listens for the event). */}
            {currentItem?.to === "/dashboard/chat" && (
              <button
                data-testid="mobile-history-toggle"
                onClick={() => window.dispatchEvent(new CustomEvent("maipal:chat-history"))}
                title="Cronologia delle chat"
                aria-label="Cronologia delle chat"
                className="lg-glass h-8 w-8 shrink-0 rounded-full flex items-center justify-center text-white"
              >
                <History size={15} />
              </button>
            )}
          </div>
          <div className="relative shrink-0 flex items-center gap-2" ref={menuRefMobile}>
            <button
              ref={avatarRefMobile}
              data-testid="user-menu-btn-mobile"
              onClick={() => setMenuOpen((v) => !v)}
              className="block"
            >
              {user?.picture ? (
                <img src={user.picture} alt={user?.name || "utente"} className="h-9 w-9 rounded-full object-cover border border-white/40" />
              ) : (
                <div className="lg-glass h-9 w-9 rounded-full flex items-center justify-center text-sm font-semibold">
                  {initial}
                </div>
              )}
            </button>
            {menuOpen && isMobile && (
              <GlassMenu anchorRef={avatarRefMobile} panelRef={menuPanelRef} testid="user-menu-mobile">
                <GlassMenuItem icon={Settings} label="Impostazioni" testid="settings-btn-mobile" onClick={() => goTo("/dashboard/settings")} />
                {!installApp.standalone && (
                  <GlassMenuItem icon={InstallIcon} label="Installa l'app" testid="install-app-btn-mobile"
                    onClick={() => { setMenuOpen(false); installApp.install(); }} />
                )}
                <GlassMenuItem icon={LogOut} label="Esci" testid="logout-btn-mobile" onClick={() => { setMenuOpen(false); logout(); }} />
                <ThemeRow />
              </GlassMenu>
            )}
          </div>
        </header>

        {/* Mobile bottom padding clears the floating menu below, so the last element of a
            page can always be scrolled fully into view above it (content still passes
            under the glass while scrolling). */}
        <main className="px-4 md:px-14 pt-4 md:pt-6 pb-[calc(env(safe-area-inset-bottom,0px)+5.5rem)] md:pb-8 w-full">
          <MobileTitleContext.Provider value={setTitleSuffix}>
            <Outlet />
          </MobileTitleContext.Provider>
        </main>

        {!installApp.standalone && !keyboardOpen && <InstallBanner onInstall={installApp.install} />}
        {installApp.dialog}

        {/* ===== Mobile bottom navigation (<768px): a floating liquid-glass pill with the four
            sections and, joined to it by a liquid neck like two merging drops, the round "+"
            for everything else (News, Liste, Documenti, Impostazioni...). See LiquidDock. ===== */}
        {!keyboardOpen && (
          <div
            className="md:hidden fixed left-0 right-0 z-40 flex items-center justify-center px-2 min-[380px]:px-3 pointer-events-none"
            style={{ bottom: "calc(env(safe-area-inset-bottom, 0px) + 14px)" }}
          >
            <LiquidDock
              bar={
                <nav
                  data-testid="mobile-bottom-nav"
                  className="relative rounded-full grid p-[5px] h-16"
                  style={{ gridTemplateColumns: `repeat(${primaryItems.length}, minmax(0, 1fr))` }}
                >
                  {/* glass bubble under the current section, sliding from one icon to the next */}
                  <span
                    aria-hidden="true"
                    className="lg-bubble absolute top-[5px] bottom-[5px] left-[5px] rounded-full"
                    style={{
                      width: `calc((100% - 10px) / ${primaryItems.length})`,
                      transform: `translateX(${Math.max(0, primaryItems.findIndex((i) => i.to === currentItem?.to)) * 100}%)`,
                      opacity: primaryItems.some((i) => i.to === currentItem?.to) ? 1 : 0,
                    }}
                  />
                  {primaryItems.map((item) => {
                    const active = currentItem?.to === item.to;
                    const Icon = item.icon;
                    return (
                      <button
                        key={item.to}
                        data-testid={item.testid}
                        onClick={() => goTo(item.to)}
                        aria-current={active ? "page" : undefined}
                        aria-label={item.label}
                        title={item.label}
                        className={`relative w-[58px] min-[380px]:w-[66px] h-full flex items-center justify-center rounded-full transition-colors ${active ? "text-white" : "text-white/75"}`}
                      >
                        <Icon size={22} strokeWidth={active ? 2.1 : 1.8} />
                      </button>
                    );
                  })}
                </nav>
              }
              button={
                <button
                  data-testid="tab-more"
                  onClick={() => setMoreOpen(true)}
                  title="Altre sezioni"
                  aria-label="Altre sezioni"
                  className="relative h-16 w-16 shrink-0 rounded-full flex items-center justify-center text-white active:scale-95 transition-transform"
                >
                  <span aria-hidden="true" className={`lg-bubble absolute inset-[5px] rounded-full ${isMoreActive ? "opacity-100" : "opacity-0"}`} />
                  <Plus size={24} className="relative" />
                </button>
              }
            />
          </div>
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

// Under "Esci" in the user menu: sun = light theme, moon = dark theme. The active one is
// white, the other greyed out; the menu stays open so the change can be seen right away.
function ThemeRow() {
  const [theme, setTheme] = useState(getStoredTheme());
  const pick = (t) => { setTheme(t); applyTheme(t); };
  const cls = (on) => `flex-1 flex items-center justify-center py-2 rounded-full transition-colors ${on ? "text-white bg-white/15" : "text-white/40 hover:text-white/70"}`;
  return (
    <div className="glass-row flex items-center gap-1 px-3 py-2" data-testid="theme-row">
      <button type="button" data-testid="theme-light-btn" onClick={() => pick("light")} title="Tema chiaro" aria-label="Tema chiaro" aria-pressed={theme === "light"} className={cls(theme === "light")}>
        <Sun size={17} />
      </button>
      <button type="button" data-testid="theme-dark-btn" onClick={() => pick("dark")} title="Tema scuro" aria-label="Tema scuro" aria-pressed={theme === "dark"} className={cls(theme === "dark")}>
        <Moon size={17} />
      </button>
    </div>
  );
}

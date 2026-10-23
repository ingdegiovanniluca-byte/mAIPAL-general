import React, { useCallback, useEffect, useRef, useState } from "react";
import PageBackground from "@/components/PageBackground";
import { Outlet, NavLink, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import {
  LogOut, Settings, Plus, MessageSquare, CheckSquare, ListChecks, BookOpen,
  Newspaper, List, FileText, Dumbbell, Repeat, Sun, Moon, Check, Mic, ChevronsLeft,
} from "lucide-react";
import { HelpIcon } from "@/lib/helpIcon";
import { toast } from "sonner";
import { usePref } from "@/lib/prefs";
import logo3 from "@/assets/logo3.png";
import { MobileTitleContext } from "@/lib/mobile-title";
import { applyTheme, getStoredTheme } from "@/lib/theme";
import { useInstallApp, InstallBanner, InstallIcon } from "@/components/InstallApp";
import LiquidDock from "@/components/LiquidDock";
import GlassMenu, { GlassMenuItem } from "@/components/GlassMenu";
import { useIsMobile } from "@/hooks/use-is-mobile";
import HelpSheet from "@/components/HelpSheet";
import ChatPage from "@/pages/ChatPage";
import { ChatPaneContext, SheetHostContext } from "@/lib/chatPane";

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

// On the mobile bottom bar: Chat, always, plus up to 3 sections the user pins with the dot in
// the "+" menu (kept on the device, like the microphone side); the "+" menu lists the others.
const CHAT_PATH = "/dashboard/chat";
const MAX_PINNED = 3;

// Desktop split (from MOBILE_BREAKPOINT up): the chat column's width (px, dragged on its edge)
// and whether it is hidden - kept on this device; the section shown on the right when the
// route is the chat's (the last one opened there, the first time Task).
const SPLIT_KEYS = { width: "maipal.split.chatWidth", hidden: "maipal.split.chatHidden", right: "maipal.split.right" };
const CHAT_MIN_W = 360;
const readLocal = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } };
const writeLocal = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private window: not kept */ } };

/* The left column of the split: the chat (its mobile layout), with its sheets opening inside
   it. The transform makes it the containing block of the chat's fixed elements (the round
   history button, the sheets' shade), so they stay in the column. */
function ChatColumn({ width, intent, onResize, onHide }) {
  const [host, setHost] = useState(null);
  const drag = useRef(null);
  const onDown = (e) => {
    drag.current = { x: e.clientX, w: width };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onMove = (e) => { if (drag.current) onResize(drag.current.w + e.clientX - drag.current.x, false); };
  const onUp = () => { if (drag.current) { drag.current = null; onResize(null, true); } };
  return (
    <div className="relative shrink-0 h-full border-r border-white/15 bg-white/[0.05] backdrop-blur-xl" style={{ width, transform: "translateZ(0)" }}
      data-testid="split-chat">
      <div className="h-full overflow-y-auto overflow-x-hidden px-4 pt-12 pb-4" data-testid="split-chat-scroll">
        <SheetHostContext.Provider value={host}>
          <ChatPaneContext.Provider value={{ intent }}>
            <ChatPage />
          </ChatPaneContext.Provider>
        </SheetHostContext.Provider>
      </div>
      <div ref={setHost} />
      <button type="button" onClick={onHide} title="Nascondi la chat" aria-label="Nascondi la chat" data-testid="split-chat-hide"
        className="absolute z-30 top-2.5 right-3 h-8 w-8 rounded-full bg-white/15 hover:bg-white/25 text-white flex items-center justify-center">
        <ChevronsLeft size={16} />
      </button>
      {/* the edge: drag to make the chat wider or narrower */}
      <div role="separator" aria-orientation="vertical" aria-label="Allarga o stringi la chat" data-testid="split-handle"
        onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
        className="absolute z-30 top-0 bottom-0 -right-[5px] w-[10px] cursor-col-resize group touch-none">
        <span className="absolute top-1/2 -translate-y-1/2 left-[2px] h-14 w-[6px] rounded-full bg-white/30 group-hover:bg-white/55 transition-colors" />
      </div>
    </div>
  );
}

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
  // ---- the desktop split: the chat on the left, the section on the right
  const split = !isMobile;
  const [chatWidth, setChatWidth] = useState(() => readLocal(SPLIT_KEYS.width, null));
  const [chatHidden, setChatHidden] = useState(() => !!readLocal(SPLIT_KEYS.hidden, false));
  const [chatIntent, setChatIntent] = useState(null);
  const [winW, setWinW] = useState(() => (typeof window !== "undefined" ? window.innerWidth : 1440));
  const headerRef = useRef(null);
  useEffect(() => {
    const onResize = () => setWinW(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  // the chat: from 360 px to half the window, always leaving the section at least 620 px
  const clampW = useCallback((w) => Math.round(Math.max(CHAT_MIN_W, Math.min(winW * 0.5, winW - 620, w))), [winW]);
  const chatW = clampW(chatWidth ?? winW / 3);
  const resizeChat = (w, done) => {
    if (w !== null) setChatWidth(clampW(w));
    if (done) setChatWidth((x) => { writeLocal(SPLIT_KEYS.width, x); return x; });
  };
  const hideChat = (v) => { setChatHidden(v); writeLocal(SPLIT_KEYS.hidden, v); };
  // the header's height, for the chat's full-height conversation (CSS var --split-top)
  useEffect(() => {
    if (!split || !headerRef.current) return undefined;
    const el = headerRef.current;
    const set = () => document.documentElement.style.setProperty("--split-top", `${el.offsetHeight}px`);
    set();
    const ro = new ResizeObserver(set);
    ro.observe(el);
    return () => ro.disconnect();
  }, [split]);
  // the route is the chat's: in the split the chat is the left column - what was asked of it
  // goes there (the header's Chat: its history), the right keeps (or gets) a section
  useEffect(() => {
    if (!split) return;
    if (location.pathname !== CHAT_PATH) {
      if (visibleItems.some((i) => location.pathname.startsWith(i.to))) writeLocal(SPLIT_KEYS.right, location.pathname + (location.search || ""));
      return;
    }
    const st = location.state;
    if (st && Object.keys(st).length) { setChatIntent({ ...st, nonce: st.nonce || Date.now() }); hideChat(false); }
    const back = readLocal(SPLIT_KEYS.right, null);
    nav(back && !String(back).startsWith(CHAT_PATH) ? back : "/dashboard/tasks", { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [split, location.key]);

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
  const [pinnedPref, setPinnedPref] = usePref("pinnedSections");
  const pinned = (Array.isArray(pinnedPref) ? pinnedPref : [])
    .filter((to) => to !== CHAT_PATH && visibleItems.some((i) => i.to === to)).slice(0, MAX_PINNED);
  const primaryItems = visibleItems.filter((item) => item.to === CHAT_PATH || pinned.includes(item.to));
  // The "+" menu: every section but Chat, each with a dot to pin it to the bar (Impostazioni
  // included, so it is reachable from there as well as from the avatar menu).
  const moreItems = visibleItems.filter((item) => item.to !== CHAT_PATH);
  const currentItem = visibleItems.find((item) => location.pathname.startsWith(item.to));
  const isMoreActive = !!currentItem && !primaryItems.some((item) => item.to === currentItem.to);
  const togglePinned = (to) => {
    if (pinned.includes(to)) { setPinnedPref(pinned.filter((x) => x !== to)); return; }
    if (pinned.length >= MAX_PINNED) {
      toast.error(`Puoi tenere in primo piano al massimo ${MAX_PINNED} agenti: togline uno col suo pallino.`);
      return;
    }
    setPinnedPref([...pinned, to]);
  };

  const goTo = (to) => { setMoreOpen(false); setMenuOpen(false); nav(to); };
  // Help: the "i" next to the section's title explains it; the avatar menu opens the chat in Help mode
  const [helpOpen, setHelpOpen] = useState(false);
  const openHelpChat = () => { setMenuOpen(false); nav(CHAT_PATH, { state: { action: "help", nonce: Date.now() } }); };

  return (
    <div className={split ? "h-screen overflow-hidden relative" : "min-h-screen relative"}>
      <PageBackground />

      <div className={split ? "relative z-10 h-full flex flex-col" : "relative z-10"}>
        {/* ===== Desktop header (>=1100px, above the split) — unchanged content, now fixed in place
            (see spec 3.1: the menu stays visible everywhere, not just on mobile). A subtle
            backdrop is required for that (a sticky header with no backing would let content
            show through as the page scrolls under it); nothing else about it changes. ===== */}
        <header ref={headerRef} className="hidden md:block sticky top-0 z-40 shrink-0 px-8 md:px-14 pt-8 pb-8 bg-white/5 backdrop-blur-xl">
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
                  {split && item.to === CHAT_PATH ? (
                    // the split: the chat is the left column - its history opens there
                    <button type="button" data-testid={item.testid} onClick={() => { hideChat(false); setChatIntent({ history: true, toggle: true, nonce: Date.now() }); }}
                      className="text-sm transition-colors duration-150 text-white/55 hover:text-white/80">{item.label}</button>
                  ) : <TabLink to={item.to} label={item.label} testid={item.testid} />}
                  {currentItem?.to === item.to && <HelpDot label={item.label} onClick={() => setHelpOpen(true)} testid="section-help-btn" />}
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
                  <GlassMenuItem icon={HelpIcon} label="Help" testid="help-btn" onClick={openHelpChat} />
                  <GlassMenuItem icon={LogOut} label="Esci" testid="logout-btn" onClick={() => { setMenuOpen(false); logout(); }} />
                  <ThemeRow />
                  <MicRow />
                </GlassMenu>
              )}
            </div>
          </div>
        </header>

        {/* ===== Mobile top bar (<1100px): logo · section name · avatar, fixed, thin ===== */}
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
          {/* section name (Chat's history is the round glass button on the side, see ChatPage) */}
          <div className="min-w-0 flex items-center gap-2">
            <div className="text-sm font-semibold text-white truncate" data-testid="mobile-section-title">{currentItem?.label || ""}{titleSuffix ? ` ${titleSuffix}` : ""}</div>
            {currentItem && <HelpDot label={currentItem.label} onClick={() => setHelpOpen(true)} testid="section-help-btn-mobile" />}
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
                <GlassMenuItem icon={HelpIcon} label="Help" testid="help-btn-mobile" onClick={openHelpChat} />
                <GlassMenuItem icon={LogOut} label="Esci" testid="logout-btn-mobile" onClick={() => { setMenuOpen(false); logout(); }} />
                <ThemeRow />
                <MicRow />
              </GlassMenu>
            )}
          </div>
        </header>

        {/* Mobile bottom padding clears the floating menu below, so the last element of a
            page can always be scrolled fully into view above it (content still passes
            under the glass while scrolling). */}
        {split ? (
          <div className="flex-1 min-h-0 flex" data-testid="split">
            {!chatHidden && <ChatColumn width={chatW} intent={chatIntent} onResize={resizeChat} onHide={() => hideChat(true)} />}
            {/* the section: centred in its space, scrolling by itself; its fixed elements (the
                commessa's chat...) stay on this side */}
            <div className="relative flex-1 min-w-0 h-full" style={{ transform: "translateZ(0)" }}>
              <div className="h-full overflow-y-auto" data-testid="split-right">
                <main className="mx-auto w-full max-w-[1180px] px-10 pt-6 pb-10">
                  <MobileTitleContext.Provider value={setTitleSuffix}>
                    {location.pathname === CHAT_PATH ? null : <Outlet />}
                  </MobileTitleContext.Provider>
                </main>
              </div>
              {chatHidden && (
                <button type="button" onClick={() => hideChat(false)} title="Mostra la chat" aria-label="Mostra la chat" data-testid="split-chat-show"
                  className="absolute z-30 left-3 top-3 h-9 pl-2.5 pr-3 rounded-full bg-white/15 hover:bg-white/25 text-white text-xs font-medium inline-flex items-center gap-1.5">
                  <MessageSquare size={14} /> Chat
                </button>
              )}
            </div>
          </div>
        ) : (
          <main className="px-4 md:px-14 pt-4 md:pt-6 pb-[calc(env(safe-area-inset-bottom,0px)+5.5rem)] md:pb-8 w-full">
            <MobileTitleContext.Provider value={setTitleSuffix}>
              <Outlet />
            </MobileTitleContext.Provider>
          </main>
        )}

        {!installApp.standalone && !keyboardOpen && <InstallBanner onInstall={installApp.install} />}
        {installApp.dialog}

        {/* ===== Mobile bottom navigation (<1100px): a floating liquid-glass pill with the four
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

        {/* ===== "+" menu: the same glass panel as the profile menu, above the "+" button.
            A tap on a row opens the section; its dot pins it to the bar (at most 3, Chat
            is always there). ===== */}
        {moreOpen && (
          <div className="md:hidden fixed inset-0 z-50" onClick={() => setMoreOpen(false)}>
            <div
              data-testid="more-sheet"
              role="menu"
              aria-label="Altre sezioni"
              className="glass-panel absolute right-3 w-[264px] py-1 max-h-[70vh] overflow-y-auto animate-in fade-in zoom-in-95 duration-150 origin-bottom-right"
              style={{ bottom: "calc(env(safe-area-inset-bottom, 0px) + 92px)" }}
              onClick={(e) => e.stopPropagation()}
            >
              {moreItems.map((item) => {
                const active = currentItem?.to === item.to;
                const on = pinned.includes(item.to);
                const Icon = item.icon;
                return (
                  <div key={item.to} className={`glass-row flex items-center ${active ? "bg-white/10" : ""}`}>
                    <button type="button" role="menuitem" data-testid={item.testid} onClick={() => goTo(item.to)}
                      className="flex-1 min-w-0 flex items-center gap-3.5 pl-5 py-3.5 text-left text-[15px] text-white">
                      <Icon size={19} strokeWidth={1.7} className="shrink-0" />
                      <span className="truncate">{item.label}</span>
                    </button>
                    <button type="button" onClick={() => togglePinned(item.to)} data-testid={`pin-${item.testid}`}
                      aria-pressed={on} aria-label={on ? `Togli ${item.label} dal menu in basso` : `Metti ${item.label} nel menu in basso`}
                      className="h-12 w-12 shrink-0 flex items-center justify-center">
                      <span className={`h-5 w-5 rounded-full flex items-center justify-center backdrop-blur-md transition-colors ${on ? "bg-white/55 text-[#7A2A5C]" : "bg-white/20"}`}>
                        {on && <Check size={12} strokeWidth={2.8} />}
                      </span>
                    </button>
                  </div>
                );
              })}
              <div className="px-5 pt-2.5 pb-3 text-[11px] leading-snug text-white/55 border-t border-white/[0.13]">
                Seleziona con il pallino i {MAX_PINNED} agenti da tenere in primo piano nel menu.
              </div>
            </div>
          </div>
        )}
      </div>
      {helpOpen && currentItem && <HelpSheet path={currentItem.to} title={currentItem.label} onClose={() => setHelpOpen(false)} />}
    </div>
  );
}

// The small "i" next to the section's title: opens what that section is and how it works.
function HelpDot({ label, onClick, testid }) {
  return (
    <button type="button" data-testid={testid} onClick={onClick} title={`Cos'è ${label} e come si usa`} aria-label={`Spiegazione di ${label}`}
      className="h-[17px] w-[17px] shrink-0 rounded-full bg-white/25 hover:bg-white/35 flex items-center justify-center text-[10px] leading-none italic font-semibold font-serif text-white">
      i
    </button>
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

// Under the theme row: which side of the chat's writing bar the voice button sits on (this
// device only, applied at once). Each icon is the mic next to a writing line, on its side.
function MicRow() {
  const [side, setSide] = usePref("micSide");
  const cls = (on) => `flex-1 flex items-center justify-center gap-1 py-2 rounded-full transition-colors ${on ? "text-white bg-white/15" : "text-white/40 hover:text-white/70"}`;
  const line = <span aria-hidden="true" className="h-[3px] w-4 rounded-full bg-current opacity-70" />;
  return (
    <div className="glass-row flex items-center gap-1 px-3 py-2" data-testid="mic-side">
      <button type="button" data-testid="mic-side-left" onClick={() => setSide("left")} title="Microfono a sinistra nella chat" aria-label="Microfono a sinistra nella chat" aria-pressed={side === "left"} className={cls(side === "left")}>
        <Mic size={16} />{line}
      </button>
      <button type="button" data-testid="mic-side-right" onClick={() => setSide("right")} title="Microfono a destra nella chat" aria-label="Microfono a destra nella chat" aria-pressed={side !== "left"} className={cls(side !== "left")}>
        {line}<Mic size={16} />
      </button>
    </div>
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

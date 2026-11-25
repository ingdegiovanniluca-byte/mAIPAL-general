import React, { useEffect } from "react";
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "@/auth/AuthContext";
import LoginPage from "@/pages/LoginPage";
import OnboardingPage from "@/pages/OnboardingPage";
import DashboardLayout from "@/pages/DashboardLayout";
import ChatPage from "@/pages/ChatPage";
import TaskBoardPage from "@/pages/TaskBoardPage";
import JournalPage from "@/pages/JournalPage";
import JobDiaryPage from "@/pages/JobDiaryPage";
import DocumentsPage from "@/pages/DocumentsPage";
import SettingsPage from "@/pages/SettingsPage";
import TodoBoardPage from "@/pages/TodoBoardPage";
import NewsPage from "@/pages/NewsPage";
import CollectionsPage from "@/pages/CollectionsPage";
import FitnessPage from "@/pages/FitnessPage";
import ActionsPage from "@/pages/ActionsPage";
import TodayPage from "@/pages/TodayPage";
import QrPage from "@/pages/QrPage";
import QrScanPage, { AFTER_LOGIN_KEY } from "@/pages/QrScanPage";

function Protected({ children, requireOnboard = true }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="min-h-screen flex items-center justify-center"><div className="kicker">caricamento…</div></div>;
  if (!user) return <Navigate to="/" replace />;
  if (requireOnboard && !user.onboarded) return <Navigate to="/onboarding" replace />;
  return children;
}

// Back to where the user was going before the login (a QR scanned while logged out), for an hour.
function AfterLogin() {
  const { user } = useAuth();
  const navigate = useNavigate();
  useEffect(() => {
    if (!user || !user.onboarded) return;
    let target = null;
    try { target = JSON.parse(localStorage.getItem(AFTER_LOGIN_KEY) || "null"); localStorage.removeItem(AFTER_LOGIN_KEY); } catch { /* blocked */ }
    if (target?.path?.startsWith("/q/") && Date.now() - (target.at || 0) < 3600 * 1000) navigate(target.path, { replace: true });
  }, [user, navigate]);
  return null;
}

// Diario: for an artigiano it is the diario di commessa
function JournalRoute() {
  const { user } = useAuth();
  return user?.business_vertical === "artigiano" ? <JobDiaryPage /> : <JournalPage />;
}

function AppRouter() {
  return (
    <Routes>
      <Route path="/" element={<LoginPage />} />
      <Route path="/onboarding" element={<Protected requireOnboard={false}><OnboardingPage /></Protected>} />
      <Route path="/dashboard" element={<Protected><DashboardLayout /></Protected>}>
        <Route index element={<Navigate to="/dashboard/chat" replace />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="tasks" element={<TaskBoardPage />} />
        <Route path="todos" element={<TodoBoardPage />} />
        <Route path="journal" element={<JournalRoute />} />
        <Route path="oggi" element={<TodayPage />} />
        <Route path="news" element={<NewsPage />} />
        <Route path="liste" element={<CollectionsPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="fitness" element={<FitnessPage />} />
        <Route path="azioni" element={<ActionsPage />} />
        <Route path="team" element={<Navigate to="/dashboard/settings" replace />} />
        <Route path="admin" element={<Navigate to="/dashboard/settings" replace />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="qr" element={<QrPage />} />
      </Route>
      <Route path="/q/:code" element={<QrScanPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter basename={process.env.PUBLIC_URL || undefined}>
      <AuthProvider>
        <AppRouter />
        <AfterLogin />
        <Toaster position="bottom-right" richColors />
      </AuthProvider>
    </BrowserRouter>
  );
}

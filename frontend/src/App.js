import React from "react";
import { BrowserRouter, Routes, Route, useLocation, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "@/auth/AuthContext";
import LoginPage from "@/pages/LoginPage";
import AuthCallback from "@/pages/AuthCallback";
import OnboardingPage from "@/pages/OnboardingPage";
import DashboardLayout from "@/pages/DashboardLayout";
import ChatPage from "@/pages/ChatPage";
import TaskBoardPage from "@/pages/TaskBoardPage";
import JournalPage from "@/pages/JournalPage";
import DocumentsPage from "@/pages/DocumentsPage";
import AdminPage from "@/pages/AdminPage";
import SettingsPage from "@/pages/SettingsPage";
import TodoBoardPage from "@/pages/TodoBoardPage";

function Protected({ children, requireOnboard = true }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="min-h-screen flex items-center justify-center"><div className="kicker">caricamento…</div></div>;
  if (!user) return <Navigate to="/" replace />;
  if (requireOnboard && !user.onboarded) return <Navigate to="/onboarding" replace />;
  return children;
}

function AppRouter() {
  const location = useLocation();
  if (location.hash?.includes("session_id=")) {
    return <AuthCallback />;
  }
  return (
    <Routes>
      <Route path="/" element={<LoginPage />} />
      <Route path="/onboarding" element={<Protected requireOnboard={false}><OnboardingPage /></Protected>} />
      <Route path="/dashboard" element={<Protected><DashboardLayout /></Protected>}>
        <Route index element={<Navigate to="/dashboard/chat" replace />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="tasks" element={<TaskBoardPage />} />
        <Route path="todos" element={<TodoBoardPage />} />
        <Route path="journal" element={<JournalPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="admin" element={<AdminPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRouter />
        <Toaster position="bottom-right" richColors />
      </AuthProvider>
    </BrowserRouter>
  );
}

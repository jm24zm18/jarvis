import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import Shell from "./components/layout/Shell";
import LoginPage from "./pages/login";
import ChatPage from "./pages/chat";
import AdminDashboardPage from "./pages/admin/dashboard";
import AdminAgentsPage from "./pages/admin/agents";
import AdminEventsPage from "./pages/admin/events";
import AdminMemoryPage from "./pages/admin/memory";
import AdminSchedulesPage from "./pages/admin/schedules";
import AdminThreadsPage from "./pages/admin/threads";
import AdminSelfUpdatePage from "./pages/admin/selfupdate";
import AdminPermissionsPage from "./pages/admin/permissions";
import AdminProvidersPage from "./pages/admin/providers";
import AdminBugsPage from "./pages/admin/bugs";
import AdminGovernancePage from "./pages/admin/governance";
import AdminChannelsPage from "./pages/admin/channels";
import { me } from "./api/endpoints";
import { useAuthStore } from "./stores/auth";

function Protected({ children }: { children: JSX.Element }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const setAuth = useAuthStore((s) => s.setAuth);
  const clearAuth = useAuthStore((s) => s.clearAuth);
  const location = useLocation();
  const authCheck = useQuery({
    queryKey: ["auth-me"],
    queryFn: () => me(),
    retry: false,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (authCheck.isSuccess) {
      setAuth(authCheck.data.user_id);
      return;
    }
    if (authCheck.isError) clearAuth();
  }, [authCheck.data, authCheck.isError, authCheck.isSuccess, clearAuth, setAuth]);

  if (authCheck.isLoading) return <div className="p-4 text-sm text-ink/70">Checking session...</div>;
  if (authCheck.isError || !isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/*"
        element={
          <Protected>
            <Shell>
              <Routes>
                <Route path="chat" element={<ChatPage />} />
                <Route path="chat/:threadId" element={<ChatPage />} />
                <Route path="admin/dashboard" element={<AdminDashboardPage />} />
                <Route path="admin/agents" element={<AdminAgentsPage />} />
                <Route path="admin/events" element={<AdminEventsPage />} />
                <Route path="admin/memory" element={<AdminMemoryPage />} />
                <Route path="admin/schedules" element={<AdminSchedulesPage />} />
                <Route path="admin/threads" element={<AdminThreadsPage />} />
                <Route path="admin/selfupdate" element={<AdminSelfUpdatePage />} />
                <Route path="admin/permissions" element={<AdminPermissionsPage />} />
                <Route path="admin/providers" element={<AdminProvidersPage />} />
                <Route path="admin/bugs" element={<AdminBugsPage />} />
                <Route path="admin/governance" element={<AdminGovernancePage />} />
                <Route path="admin/channels" element={<AdminChannelsPage />} />
                <Route path="*" element={<Navigate to="/chat" replace />} />
              </Routes>
            </Shell>
          </Protected>
        }
      />
    </Routes>
  );
}

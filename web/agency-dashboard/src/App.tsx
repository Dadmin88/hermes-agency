import { Routes, Route, Navigate } from "react-router-dom";
import AppShell from "./components/AppShell";
import OverviewPage from "./pages/OverviewPage";
import DispatchPage from "./pages/DispatchPage";
import AgentsPage from "./pages/AgentsPage";
import TasksPage from "./pages/TasksPage";
import ActivityPage from "./pages/ActivityPage";
import DiagnosticsPage from "./pages/DiagnosticsPage";
import SettingsPage from "./pages/SettingsPage";
import { ToastContainer } from "./components/Toast";

export default function App() {
  return (
    <>
      <AppShell>
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/dispatch" element={<DispatchPage />} />
          <Route path="/agents" element={<AgentsPage />} />
          <Route path="/tasks" element={<TasksPage />} />
          <Route path="/activity" element={<ActivityPage />} />
          <Route path="/diagnostics" element={<DiagnosticsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppShell>
      <ToastContainer />
    </>
  );
}

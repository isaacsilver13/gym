import { useState } from "react";

import { AuthProvider, useAuth } from "./auth/AuthContext";
import { AuthPage } from "./pages/AuthPage";
import { RoutineList } from "./pages/RoutineList";
import { RoutineBuilder } from "./pages/RoutineBuilder";
import { RoutineDetail } from "./pages/RoutineDetail";
import { TrainingHub } from "./pages/TrainingHub";

type View = { name: "training" } | { name: "list" } | { name: "builder" } | { name: "detail"; routineId: number };

function Dashboard() {
  const { user, logout } = useAuth();
  const [view, setView] = useState<View>({ name: "training" });

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Training Hub</p>
          <h1>Hey, {user?.username}</h1>
        </div>
        <button type="button" className="link-button" onClick={() => void logout()}>
          Sign out
        </button>
      </header>

      <nav className="day-tabs" aria-label="Main navigation">
        <button type="button" className={view.name === "training" ? "active" : ""} onClick={() => setView({ name: "training" })}>Training overview</button>
        <button type="button" className={view.name !== "training" ? "active" : ""} onClick={() => setView({ name: "list" })}>Legacy tracker</button>
      </nav>
      {view.name === "training" && <TrainingHub />}

      {view.name === "list" && (
        <RoutineList
          onSelect={(routineId) => setView({ name: "detail", routineId })}
          onCreateNew={() => setView({ name: "builder" })}
        />
      )}
      {view.name === "builder" && (
        <RoutineBuilder
          onCreated={(routineId) => setView({ name: "detail", routineId })}
          onCancel={() => setView({ name: "list" })}
        />
      )}
      {view.name === "detail" && (
        <RoutineDetail
          routineId={view.routineId}
          onBack={() => setView({ name: "list" })}
          onDeleted={() => setView({ name: "list" })}
        />
      )}
    </main>
  );
}

function AppShell() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <main className="app-shell">
        <p className="muted">Loading...</p>
      </main>
    );
  }

  return user ? <Dashboard /> : <AuthPage />;
}

function App() {
  return (
    <AuthProvider>
      <AppShell />
    </AuthProvider>
  );
}

export default App;

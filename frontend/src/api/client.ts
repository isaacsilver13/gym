import type {
  AppleHealthStatus,
  ExerciseProgressPoint,
  LoggedSession,
  Routine,
  RoutineInput,
  RoutineSummary,
  User,
  TrainingSummary,
} from "../types";

const BASE = "/api/v1";

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // response had no JSON body; keep the status text
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

export { ApiError };

export function register(username: string, password: string): Promise<User> {
  return request("/auth/register", { method: "POST", body: JSON.stringify({ username, password }) });
}

export function login(username: string, password: string): Promise<User> {
  return request("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
}

export function logout(): Promise<void> {
  return request("/auth/logout", { method: "POST" });
}

export function fetchCurrentUser(): Promise<User> {
  return request("/auth/me");
}

export function listRoutines(): Promise<RoutineSummary[]> {
  return request("/routines");
}

export function getRoutine(id: number): Promise<Routine> {
  return request(`/routines/${id}`);
}

export function createRoutine(payload: RoutineInput): Promise<Routine> {
  return request("/routines", { method: "POST", body: JSON.stringify(payload) });
}

export function deleteRoutine(id: number): Promise<void> {
  return request(`/routines/${id}`, { method: "DELETE" });
}

export function logSession(
  routineId: number,
  gymDayId: number,
  results: { exercise_definition_id: number; weight_lb: number; reps_done: number }[],
): Promise<LoggedSession> {
  return request(`/routines/${routineId}/sessions`, {
    method: "POST",
    body: JSON.stringify({ gym_day_id: gymDayId, results }),
  });
}

export function listSessions(routineId: number): Promise<LoggedSession[]> {
  return request(`/routines/${routineId}/sessions`);
}

export function getExerciseProgress(exerciseId: number): Promise<ExerciseProgressPoint[]> {
  return request(`/exercises/${exerciseId}/progress`);
}

export function getTrainingSummary(anchor?: string): Promise<TrainingSummary> {
  return request(`/training/summary${anchor ? `?anchor=${encodeURIComponent(anchor)}` : ""}`);
}

export function getLegacyExport(): Promise<unknown> {
  return request("/training/legacy-export");
}

export function getAppleHealthStatus(): Promise<AppleHealthStatus> {
  return request("/training/apple-health");
}

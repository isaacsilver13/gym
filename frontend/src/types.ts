export interface User {
  id: number;
  username: string;
}

export interface ExerciseDefinition {
  id: number;
  muscle_group: string;
  name: string;
  sets: number;
  rep_range_low: number;
  rep_range_high: number;
}

export interface GymDay {
  id: number;
  name: string;
  exercises: ExerciseDefinition[];
}

export interface RoutineSummary {
  id: number;
  name: string;
  is_active: boolean;
}

export interface Routine extends RoutineSummary {
  gym_days: GymDay[];
}

export interface ExerciseResult {
  exercise_definition_id: number;
  weight_lb: number;
  reps_done: number;
}

export interface LoggedSession {
  id: number;
  gym_day_id: number;
  logged_at: string;
  results: ExerciseResult[];
}

export interface ExerciseProgressPoint {
  logged_at: string;
  weight_lb: number;
  reps_done: number;
}

export interface ExerciseDefinitionInput {
  muscle_group: string;
  name: string;
  sets: number;
  rep_range_low: number;
  rep_range_high: number;
}

export interface GymDayInput {
  name: string;
  exercises: ExerciseDefinitionInput[];
}

export interface RoutineInput {
  name: string;
  gym_days: GymDayInput[];
}

export interface TrainingActivity {
  id: string;
  source: "opengym" | "endurain";
  sport: "lifting" | "running";
  name: string;
  started_at: string;
  local_date: string;
  duration_seconds: number | null;
  working_sets?: number;
  distance_meters?: number | null;
  pace_seconds_per_km?: number | null;
  average_heart_rate?: number | null;
}

export interface TrainingSummary {
  schema_version: number;
  generated_at: string;
  timezone: string;
  week_start: string;
  week_end_exclusive: string;
  sources: Record<"opengym" | "endurain", {
    state: "ok" | "not_connected" | "unavailable";
    fetched_at: string | null;
    latest_activity_at: string | null;
  }>;
  links: Record<"opengym" | "endurain", string | null>;
  totals: {
    lifting_sessions: number | null;
    working_sets: number | null;
    runs: number | null;
    running_distance_meters: number | null;
    running_timer_seconds: number | null;
    longest_run_meters: number | null;
  };
  activities: TrainingActivity[];
  observations: { text: string; evidence: string[] }[];
  notes: string[];
}

export interface AppleHealthStatus {
  configured: boolean;
  counts: Record<string, number>;
  changed: number;
  recent: { source_id: string; state: string; error: string | null; changed: number;
    received: number; updated: number; activity_ids: number[] }[];
}

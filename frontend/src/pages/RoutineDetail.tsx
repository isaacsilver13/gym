import { useEffect, useState } from "react";

import * as api from "../api/client";
import { GlassCard } from "../components/GlassCard";
import { ExerciseProgressChart } from "../components/ExerciseProgressChart";
import type { ExerciseDefinition, ExerciseResult, GymDay, LoggedSession, Routine } from "../types";

interface RoutineDetailProps {
  routineId: number;
  onBack: () => void;
  onDeleted: () => void;
}

export function RoutineDetail({ routineId, onBack, onDeleted }: RoutineDetailProps) {
  const [routine, setRoutine] = useState<Routine | null>(null);
  const [sessions, setSessions] = useState<LoggedSession[]>([]);
  const [selectedDayId, setSelectedDayId] = useState<number | null>(null);
  const [selectedExerciseId, setSelectedExerciseId] = useState<number | null>(null);
  const [weights, setWeights] = useState<Record<number, string>>({});
  const [reps, setReps] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [logging, setLogging] = useState(false);

  function refresh() {
    api.getRoutine(routineId).then((data) => {
      setRoutine(data);
      setSelectedDayId((current) => current ?? data.gym_days[0]?.id ?? null);
      setSelectedExerciseId((current) => current ?? data.gym_days[0]?.exercises[0]?.id ?? null);
    });
    api.listSessions(routineId).then(setSessions);
  }

  useEffect(refresh, [routineId]);

  if (!routine) {
    return <p className="muted">Loading...</p>;
  }

  const selectedDay: GymDay | undefined = routine.gym_days.find((day) => day.id === selectedDayId);
  const allExercises: ExerciseDefinition[] = routine.gym_days.flatMap((day) => day.exercises);
  const lastResult = new Map<number, ExerciseResult>();
  for (const session of sessions) {
    for (const result of session.results) {
      if (!lastResult.has(result.exercise_definition_id)) {
        lastResult.set(result.exercise_definition_id, result);
      }
    }
  }

  async function handleLogSession() {
    if (!selectedDay) return;
    setError(null);
    setLogging(true);
    try {
      // Exercises left fully blank are skipped, not logged as 0 x 0.
      const results = selectedDay.exercises
        .filter((exercise) => weights[exercise.id] || reps[exercise.id])
        .map((exercise) => ({
          exercise_definition_id: exercise.id,
          weight_lb: Number(weights[exercise.id] || 0),
          reps_done: Number(reps[exercise.id] || 0),
        }));
      if (results.length === 0) {
        setError("Enter a weight or reps for at least one exercise.");
        return;
      }
      await api.logSession(routineId, selectedDay.id, results);
      setWeights({});
      setReps({});
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to log session");
    } finally {
      setLogging(false);
    }
  }

  async function handleDelete() {
    if (!confirm(`Delete "${routine!.name}"? This cannot be undone.`)) return;
    await api.deleteRoutine(routineId);
    onDeleted();
  }

  return (
    <section>
      <div className="section-heading">
        <button type="button" className="link-button" onClick={onBack}>
          ← Back
        </button>
        <h2>{routine.name}</h2>
        <button type="button" className="link-button danger" onClick={handleDelete}>
          Delete routine
        </button>
      </div>

      <div className="day-tabs" role="tablist">
        {routine.gym_days.map((day) => (
          <button
            key={day.id}
            className={day.id === selectedDayId ? "active" : ""}
            onClick={() => setSelectedDayId(day.id)}
            type="button"
          >
            {day.name}
          </button>
        ))}
      </div>

      {selectedDay && (
        <GlassCard className="log-form">
          <h3>Log {selectedDay.name}</h3>
          <table>
            <thead>
              <tr>
                <th>Exercise</th>
                <th>Weight (lb)</th>
                <th>Reps done</th>
              </tr>
            </thead>
            <tbody>
              {selectedDay.exercises.map((exercise) => (
                <tr key={exercise.id}>
                  <td>
                    <strong>{exercise.name}</strong>
                    <div className="muted">
                      {exercise.muscle_group} · {exercise.sets} × {exercise.rep_range_low}-
                      {exercise.rep_range_high}
                    </div>
                  </td>
                  <td>
                    <input
                      type="number"
                      min={0}
                      inputMode="decimal"
                      placeholder={String(lastResult.get(exercise.id)?.weight_lb ?? "")}
                      aria-label={`${exercise.name} weight (lb)`}
                      value={weights[exercise.id] ?? ""}
                      onChange={(event) =>
                        setWeights((current) => ({ ...current, [exercise.id]: event.target.value }))
                      }
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      min={0}
                      inputMode="numeric"
                      placeholder={String(lastResult.get(exercise.id)?.reps_done ?? "")}
                      aria-label={`${exercise.name} reps done`}
                      value={reps[exercise.id] ?? ""}
                      onChange={(event) =>
                        setReps((current) => ({ ...current, [exercise.id]: event.target.value }))
                      }
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {error && <p className="form-error">{error}</p>}
          <button type="button" onClick={handleLogSession} disabled={logging}>
            Save session
          </button>
        </GlassCard>
      )}

      <GlassCard className="progress-section">
        <h3>Progress</h3>
        <select
          value={selectedExerciseId ?? ""}
          onChange={(event) => setSelectedExerciseId(Number(event.target.value))}
        >
          {allExercises.map((exercise) => (
            <option key={exercise.id} value={exercise.id}>
              {exercise.name}
            </option>
          ))}
        </select>
        {selectedExerciseId && <ExerciseProgressChart exerciseId={selectedExerciseId} />}
      </GlassCard>

      <GlassCard className="session-log">
        <h3>Session log</h3>
        {sessions.length === 0 ? (
          <p className="muted">No sessions logged yet.</p>
        ) : (
          sessions.map((session) => {
            const day = routine.gym_days.find((d) => d.id === session.gym_day_id);
            return (
              <div key={session.id} className="session-entry">
                <h4>
                  {new Date(session.logged_at).toLocaleDateString()} · {day?.name ?? "—"}
                </h4>
                <table>
                  <thead>
                    <tr>
                      <th>Exercise</th>
                      <th>Weight (lb)</th>
                      <th>Reps</th>
                    </tr>
                  </thead>
                  <tbody>
                    {session.results.map((result) => (
                      <tr key={result.exercise_definition_id}>
                        <td>
                          {allExercises.find((e) => e.id === result.exercise_definition_id)?.name ??
                            "?"}
                        </td>
                        <td>{result.weight_lb}</td>
                        <td>{result.reps_done}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          })
        )}
      </GlassCard>
    </section>
  );
}

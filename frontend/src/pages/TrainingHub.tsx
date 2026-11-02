import { useEffect, useState } from "react";

import { ApiError, getAppleHealthStatus, getLegacyExport, getTrainingSummary } from "../api/client";
import { GlassCard } from "../components/GlassCard";
import type { AppleHealthStatus, TrainingSummary } from "../types";

const miles = (meters: number | null | undefined) => meters == null ? "—" : (meters / 1609.344).toFixed(1);
const minutes = (seconds: number | null) => seconds == null ? "—" : Math.round(seconds / 60);
const count = (value: number | null) => value == null ? "—" : value;
const localISO = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
const status = { ok: "Connected", not_connected: "Not connected", unavailable: "Temporarily unavailable" };

function pace(secondsPerKm: number | null | undefined) {
  if (secondsPerKm == null) return null;
  const seconds = Math.round(secondsPerKm * 1.609344);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")} /mi`;
}

export function TrainingHub() {
  const [anchor, setAnchor] = useState(localISO(new Date()));
  const [summary, setSummary] = useState<TrainingSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [exporting, setExporting] = useState(false);
  const [apple, setApple] = useState<AppleHealthStatus | null>(null);
  const [appleError, setAppleError] = useState(false);

  useEffect(() => {
    let active = true;
    setAppleError(false);
    getAppleHealthStatus().then((value) => { if (active) setApple(value); })
      .catch(() => { if (active) { setApple(null); setAppleError(true); } });
    return () => { active = false; };
  }, [refresh]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setSummary(null);
    getTrainingSummary(anchor).then((value) => {
      if (active) setSummary(value);
    }).catch((err: unknown) => {
      if (active) setError(err instanceof ApiError && err.status === 404
        ? "Your lifting and running sources haven't been connected yet. Your existing routines and history are available under Routines."
        : "Your training summary couldn't be loaded. Please try again.");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [anchor, refresh]);

  function changeWeek(offset: number) {
    const date = new Date(`${anchor}T12:00:00`);
    date.setDate(date.getDate() + offset * 7);
    setAnchor(localISO(date));
  }

  async function exportHistory() {
    setExporting(true);
    try {
      const data = await getLegacyExport();
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = "gym-legacy-export.json";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      setError("Your history export couldn't be downloaded. Please try again.");
    } finally {
      setExporting(false);
    }
  }

  return <section className="training-hub" aria-label="Training overview">
    <div className="section-heading">
      <div><p className="eyebrow">Lift. Run. See the whole week.</p><h2>Your training</h2></div>
      <button type="button" onClick={() => setRefresh((n) => n + 1)} disabled={loading}>Refresh</button>
    </div>
    <nav className="week-navigation" aria-label="Choose training week">
      <button type="button" onClick={() => changeWeek(-1)} aria-label="Previous week">←</button>
      <label>Week containing<input type="date" value={anchor} onChange={(e) => { if (e.target.value) setAnchor(e.target.value); }} /></label>
      <button type="button" onClick={() => changeWeek(1)} aria-label="Next week">→</button>
    </nav>
    {loading && <p role="status">Loading your training…</p>}
    {error && <GlassCard><p role="status">{error}</p></GlassCard>}
    {(apple?.configured || appleError) && <GlassCard>
      <h3>Apple Watch sync</h3>
      {appleError ? <p role="status">Sync status couldn't be loaded. Try Refresh.</p> : apple && <>
        <p>{apple.counts.completed ?? 0} imported · {(apple.counts.queued ?? 0) + (apple.counts.processing ?? 0)} pending · {apple.counts.failed ?? 0} need attention</p>
        <p className="muted small">Keep Tailscale connected on your iPhone and this computer awake. Health Auto Export may wait until your phone is unlocked.</p>
        {apple.changed > 0 && <p role="status">{apple.changed} changed re-export(s) need review. Previously imported runs have been kept.</p>}
        {apple.recent.length > 0 && <p className="muted small">Last received {new Date(Math.max(...apple.recent.map((item) => item.received)) * 1000).toLocaleString()}</p>}
        {(apple.counts.failed ?? 0) > 0 && <p role="status">An import needs attention. Check the private server status before re-exporting.</p>}
      </>}
    </GlassCard>}
    {summary && <>
      <p className="muted">Week of {summary.week_start} · {summary.timezone}</p>
      <div className="training-sources">
        {(["opengym", "endurain"] as const).map((source) => <GlassCard key={source}>
          <p className="eyebrow">{source === "opengym" ? "Strength" : "Running"}</p>
          <h3>{source === "opengym" ? "openGym" : "Endurain"}</h3>
          <p className={`source-state ${summary.sources[source].state}`}>{status[summary.sources[source].state]}</p>
          {summary.links[source] && <a className="training-link" href={summary.links[source]!} target="_blank" rel="noopener noreferrer">Open {source === "opengym" ? "openGym" : "Endurain"} ↗</a>}
          {summary.sources[source].fetched_at && <p className="muted small">Checked {new Date(summary.sources[source].fetched_at!).toLocaleTimeString()}</p>}
        </GlassCard>)}
      </div>
      <div className="training-stats">
        <GlassCard><p className="eyebrow">Lifting sessions</p><strong>{count(summary.totals.lifting_sessions)}</strong><p className="muted">{count(summary.totals.working_sets)} working rep sets</p></GlassCard>
        <GlassCard><p className="eyebrow">Runs</p><strong>{count(summary.totals.runs)}</strong><p className="muted">{minutes(summary.totals.running_timer_seconds)} active minutes</p></GlassCard>
        <GlassCard><p className="eyebrow">Running distance</p><strong>{miles(summary.totals.running_distance_meters)} <small>mi</small></strong><p className="muted">Longest run: {miles(summary.totals.longest_run_meters)} mi</p></GlassCard>
      </div>
      <GlassCard>
        <h3>This week's activity</h3>
        {summary.activities.length === 0 && <p className="muted">No activities available for this week. Check the connections above if your workouts are missing.</p>}
        <ul className="training-activity-list">{summary.activities.map((activity) => <li key={activity.id}>
          <div><span className={`sport-badge ${activity.sport}`}>{activity.sport === "running" ? "Run" : activity.sport === "cardio" ? "Cardio" : "Lift"}</span><strong>{activity.name}</strong><p className="muted small">{activity.local_date} · {activity.source === "opengym" ? "openGym" : "Endurain"}</p></div>
          <div className="activity-measures">{activity.sport === "lifting" ? activity.summary_only ? "Summary only · sets unknown" : `${activity.working_sets} sets` : `${miles(activity.distance_meters)} mi`}
            <p className="muted small">{activity.sport === "running" && pace(activity.pace_seconds_per_km)}{activity.average_heart_rate != null && ` · ${Math.round(activity.average_heart_rate)} bpm`}</p>
          </div>
        </li>)}</ul>
      </GlassCard>
      <GlassCard><h3>Weekly review</h3>
        {summary.observations.map((observation, i) => <p key={i}>{observation.text}</p>)}
        <p className="muted small">{summary.notes[1]}</p>
        <p className="muted small">{summary.notes[2]}</p>
      </GlassCard>
    </>}
    <GlassCard><h3>Your earlier training</h3><p className="muted">Keep your original routine and session records. Earlier weight-and-rep summaries stay separate from individual-set statistics.</p>
      <button type="button" onClick={() => void exportHistory()} disabled={exporting}>{exporting ? "Preparing export…" : "Export legacy history"}</button>
    </GlassCard>
  </section>;
}

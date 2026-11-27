import { useEffect, useState, type CSSProperties, type FormEvent, type PointerEvent } from "react";
import Icon from "./Icon";
import "../login.css";

type LoginPageProps = {
  username: string;
  password: string;
  showPassword: boolean;
  signingIn: boolean;
  error: string;
  onUsernameChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onTogglePassword: () => void;
  onSubmit: (event: FormEvent) => void;
};

export default function LoginPage({
  username,
  password,
  showPassword,
  signingIn,
  error,
  onUsernameChange,
  onPasswordChange,
  onTogglePassword,
  onSubmit,
}: LoginPageProps) {
  const [now, setNow] = useState(() => new Date());
  const [pointer, setPointer] = useState({ x: "50%", y: "45%" });

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  function handlePointerMove(event: PointerEvent<HTMLElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = `${Math.round(((event.clientX - rect.left) / rect.width) * 100)}%`;
    const y = `${Math.round(((event.clientY - rect.top) / rect.height) * 100)}%`;
    setPointer({ x, y });
  }

  return (
    <main
      className="login-shell"
      onPointerMove={handlePointerMove}
      style={{ "--mx": pointer.x, "--my": pointer.y } as CSSProperties}
    >
      <div className="login-backdrop" aria-hidden="true">
        <div className="login-aurora login-aurora-one" />
        <div className="login-aurora login-aurora-two" />
        <div className="login-aurora login-aurora-three" />
        <div className="login-grid-bg" />
        <div className="login-spotlight" />
      </div>

      <section className="login-showcase">
        <div className="login-topbar">
          <div className="brand">
            <span className="brand-mark">◈</span>
            <div>
              INTELLIGENT<span>VIDEO MANAGEMENT SYSTEM</span>
            </div>
          </div>
          <div className="login-status-pill">
            <i aria-hidden="true" />
            AUTHORIZED ACCESS
          </div>
        </div>

        <div className="login-hero">
          <div className="login-pill">
            <span className="login-pill-dot" />
            YOUR SURVEILLANCE WORKSPACE
          </div>
          <h1>
            See the whole{" "}
            <span className="login-gradient-text">picture</span>
            <span className="login-accent">.</span>
          </h1>
          <p>
            Monitor your network cameras, inspect stored recordings, and
            track host resources in real time from one private workspace.
          </p>

          <div className="login-stage-wrap" aria-hidden="true">
            <div className="stage-float-card stage-float-top">
              <span className="stage-float-icon">◉</span>
              <div>
                <strong>Live telemetry</strong>
                <small>Low-latency stream sync</small>
              </div>
            </div>

            <div className="login-stage">
              <div className="stage-hud">
                <span className="stage-hud-left">
                  <i className="stage-rec-dot" />
                  MONITORING WORKSPACE
                </span>
                <span className="stage-timecode">
                  {now.toLocaleTimeString([], { hour12: false })}
                </span>
              </div>

              <div className="stage-viewport">
                <div className="stage-radar">
                  <span className="stage-ring stage-ring-1" />
                  <span className="stage-ring stage-ring-2" />
                  <span className="stage-ring stage-ring-3" />
                  <div className="stage-sweep" />
                </div>
                <div className="stage-scanline" />
                <div className="stage-target stage-target-a">
                  <span>CAMERA MONITORING</span>
                </div>
                <div className="stage-target stage-target-b">
                  <span>RECORDING REVIEW</span>
                </div>
                <div className="stage-center-mark">＋</div>
                <div className="stage-corners">
                  <i />
                  <i />
                  <i />
                  <i />
                </div>
              </div>

              <div className="stage-footer">
                <span>Intelligent-VMS</span>
                <span className="stage-bars">
                  <i />
                  <i />
                  <i />
                  <i />
                  <i />
                </span>
              </div>
            </div>

            <div className="stage-float-card stage-float-bottom">
              <span className="stage-float-icon">◈</span>
              <div>
                <strong>One connected view</strong>
                <small>Cameras · recordings · system</small>
              </div>
            </div>
          </div>
        </div>

        <div className="login-bottom-meta">
          <span>Intelligent-VMS / MONITORING &amp; MANAGEMENT</span>
          <div className="login-feature-chips">
            <span>RBAC SECURITY</span>
            <span>AUDIT LOGS</span>
            <span>NETWORK CAMERAS</span>
          </div>
        </div>
      </section>

      <section className="login-auth-panel">
        <div className="login-form-card">
          <div className="login-shield" aria-hidden="true">
            <Icon name="roles" />
          </div>
          <span className="login-eyebrow">SECURE SIGN IN</span>
          <h2>
            Welcome back<span className="login-accent">.</span>
          </h2>
          <p className="login-subtitle">
            Enter your credentials to unlock your workspace.
          </p>

          <form className="login-form" onSubmit={onSubmit}>
            <div className="login-field">
              <label htmlFor="username">Username</label>
              <div className="login-input-wrap">
                <span className="login-input-icon" aria-hidden="true">
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                    <circle cx="12" cy="7" r="4" />
                  </svg>
                </span>
                <input
                  id="username"
                  type="text"
                  autoComplete="username"
                  value={username}
                  onChange={(event) => onUsernameChange(event.target.value)}
                  required
                  maxLength={64}
                  placeholder="Enter your username"
                />
              </div>
            </div>

            <div className="login-field">
              <label htmlFor="password">Password</label>
              <div className="login-input-wrap has-toggle">
                <span className="login-input-icon" aria-hidden="true">
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                  </svg>
                </span>
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => onPasswordChange(event.target.value)}
                  required
                  maxLength={256}
                  placeholder="Enter your password"
                />
                <button
                  type="button"
                  className="login-pw-toggle"
                  onClick={onTogglePassword}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  aria-pressed={showPassword}
                >
                  {showPassword ? "Hide" : "Show"}
                </button>
              </div>
            </div>

            {error && (
              <div className="login-error-alert" role="alert">
                <svg
                  width="15"
                  height="15"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <circle cx="12" cy="12" r="10" />
                  <line x1="12" y1="8" x2="12" y2="12" />
                  <line x1="12" y1="16" x2="12.01" y2="16" />
                </svg>
                <span>{error}</span>
              </div>
            )}

            <button className="login-submit" disabled={signingIn}>
              {signingIn ? (
                <>
                  <span className="login-spinner" aria-hidden="true" />
                  <span>Authenticating…</span>
                </>
              ) : (
                <>
                  <span>Sign in to workspace</span>
                  <span className="login-submit-arrow" aria-hidden="true">
                    →
                  </span>
                </>
              )}
            </button>
          </form>

          <div className="login-card-footer">
            <Icon name="roles" />
            <span>Access for authorized operators only</span>
          </div>
        </div>
      </section>
    </main>
  );
}

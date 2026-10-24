import type { ReactNode } from "react";
import {
  CircleAlert,
  Cloud,
  Languages,
  LoaderCircle,
  ShieldCheck,
  X,
  Zap,
} from "lucide-react";
import type { Engine, EngineStatus } from "../types/translation";
import { uiText } from "../schemas/ui";

interface EnginePanelProps {
  engine: Engine;
  engineStatus: EngineStatus | null;
  error: string;
  busy: boolean;
  canStart: boolean;
  onEngineChange: (engine: Engine) => void;
  onDismissError: () => void;
  onStart: () => void;
}

interface EngineCardProps {
  selected: boolean;
  icon: ReactNode;
  iconClassName: string;
  title: string;
  badge: string;
  description: ReactNode;
  ready: boolean;
  status: string;
  onClick: () => void;
}

function EngineCard({
  selected,
  icon,
  iconClassName,
  title,
  badge,
  description,
  ready,
  status,
  onClick,
}: EngineCardProps) {
  return (
    <button
      className={`engine-card ${selected ? "engine-selected" : ""}`}
      onClick={onClick}
      type="button"
      aria-pressed={selected}
    >
      <span className={`engine-icon ${iconClassName}`}>{icon}</span>
      <span className="engine-content">
        <span className="engine-title">
          {title} <span className="engine-badge">{badge}</span>
        </span>
        <span className="engine-description">{description}</span>
        <span
          className={`engine-state ${ready ? "state-ready" : "state-warning"}`}
        >
          <span className="tiny-dot" /> {status}
        </span>
      </span>
      <span
        className={`radio-indicator ${selected ? "radio-checked" : ""}`}
      />
    </button>
  );
}

export function EnginePanel({
  engine,
  engineStatus,
  error,
  busy,
  canStart,
  onEngineChange,
  onDismissError,
  onStart,
}: EnginePanelProps) {
  const cloudReady = Boolean(engineStatus?.gemini.configured);
  const argosReady = Boolean(engineStatus?.argos.available);

  const engineText = uiText.engine;
  const limitsTitle =
    engine === "gemini" ? engineText.cloudLimits : engineText.offlineLimits;
  const limitsDescription =
    engine === "gemini"
      ? engineText.cloudLimitsDescription
      : engineText.offlineLimitsDescription;

  return (
    <section className="panel engine-panel">
      <div className="section-heading">
        <div>
          <span className="step-label">{engineText.step}</span>
          <h2>{engineText.title}</h2>
        </div>
        <span className="subtle-tag">{engineText.tag}</span>
      </div>

      <EngineCard
        selected={engine === "gemini"}
        icon={<Cloud size={22} />}
        iconClassName="cloud-icon"
        title={engineText.cloudTitle}
        badge={engineText.gemini}
        description={engineText.cloudDescription}
        ready={cloudReady}
        status={cloudReady ? engineText.cloudReady : engineText.cloudNotReady}
        onClick={() => onEngineChange("gemini")}
      />
      <EngineCard
        selected={engine === "argos"}
        icon={<Languages size={22} />}
        iconClassName="local-icon"
        title={engineText.translationTitle}
        badge={engineText.argos}
        description={engineText.argosDescription}
        ready={argosReady}
        status={
          argosReady
            ? engineText.argosReady
            : engineText.argosUnavailable
        }
        onClick={() => onEngineChange("argos")}
      />

      <div className="limits-note">
        <ShieldCheck size={17} />
        <div>
          <strong>{limitsTitle}</strong>
          <p>{limitsDescription}</p>
        </div>
      </div>

      {error && (
        <div className="error-banner" role="alert">
          <CircleAlert size={18} />
          <span>{error}</span>
          <button
            onClick={onDismissError}
            aria-label={engineText.dismissError}
            type="button"
          >
            <X size={15} />
          </button>
        </div>
      )}

      <button
        className="primary-button"
        onClick={onStart}
        disabled={busy || !canStart}
      >
        {busy ? (
          <LoaderCircle className="spin" size={18} />
        ) : (
          <Zap size={18} />
        )}
        {busy ? engineText.starting : engineText.start}
      </button>
      <p className="privacy-note">
        <ShieldCheck size={14} />
        {engineText.privacy}
      </p>
    </section>
  );
}

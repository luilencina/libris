import { BookOpen, LogOut, Sparkles } from "lucide-react";
import { uiText } from "../schemas/ui";

interface AppHeaderProps {
  authenticated?: boolean;
  onLogout?: () => void;
  showWorkspaceStatus?: boolean;
}

export function AppHeader({
  authenticated = false,
  onLogout,
  showWorkspaceStatus = true,
}: AppHeaderProps) {
  return (
    <>
      <header className="topbar">
        <a className="brand" href="#" aria-label={uiText.header.homeLabel}>
          <span className="brand-mark">
            <BookOpen size={23} />
          </span>
          <span>
            <strong>{uiText.header.appName}</strong>
            <small>{uiText.header.subtitle}</small>
          </span>
        </a>
        <div className="topbar-status">
          {authenticated ? (
            <button className="text-button" onClick={onLogout} type="button">
              <LogOut size={14} /> Sign out
            </button>
          ) : showWorkspaceStatus ? (
            <>
              <span className="status-dot" /> {uiText.header.localWorkspace}
            </>
          ) : null}
        </div>
      </header>

      <section className="hero">
        <div className="eyebrow">
          <Sparkles size={14} /> {uiText.header.eyebrow}
        </div>
        <h1>
          {uiText.header.heroTitle}
          <br />
          <span>{uiText.header.heroTitleAccent}</span>
        </h1>
        <p className="hero-copy">
          {uiText.header.heroDescription}
        </p>
      </section>
    </>
  );
}

import { Github } from "lucide-react";
import { API_BASE_URL } from "../api";
import { AppHeader } from "./AppHeader";

interface GitHubLoginProps {
  error: string | null;
}

export function GitHubLogin({ error }: GitHubLoginProps) {
  return (
    <main className="app-shell">
      <AppHeader showWorkspaceStatus={false} />
      <section className="panel auth-panel">
        <span className="step-label">ACCOUNT</span>
        <h2>Sign in to continue</h2>
        <p className="hero-copy">
          Translation access is limited to authorized GitHub accounts.
        </p>
        {error && (
          <div className="error-banner" role="alert">
            {error === "not_allowed"
              ? "This GitHub account is not authorized."
              : "GitHub sign-in was cancelled. Try again to continue."}
          </div>
        )}
        <a className="primary-button" href={`${API_BASE_URL}/auth/github`}>
          <Github size={18} />
          Continue with GitHub
        </a>
      </section>
    </main>
  );
}

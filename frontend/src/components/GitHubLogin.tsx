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
          Sign in with your GitHub account to use Libris.
        </p>
        {error && (
          <div className="error-banner" role="alert">
            {error === "cancelled"
              ? "GitHub sign-in was cancelled. Try again to continue."
              : "GitHub sign-in could not be completed. Try again."}
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

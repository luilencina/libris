import { useState } from "react";
import { clearAuthToken, initialAuthState } from "./api";
import { AppFooter } from "./components/AppFooter";
import { AppHeader } from "./components/AppHeader";
import { EnginePanel } from "./components/EnginePanel";
import { GitHubLogin } from "./components/GitHubLogin";
import { JobQueue } from "./components/JobQueue";
import { UploadPanel } from "./components/UploadPanel";
import { useTranslationWorkspace } from "./hooks/useTranslationWorkspace";

function App() {
  const authRequired = import.meta.env.VITE_AUTH_MODE === "github";
  const [authToken, setAuthToken] = useState(initialAuthState.token);
  const workspace = useTranslationWorkspace(!authRequired || Boolean(authToken));

  const handleLogout = () => {
    clearAuthToken();
    setAuthToken(null);
    workspace.clearWorkspace();
  };

  if (authRequired && !authToken) {
    return <GitHubLogin error={initialAuthState.error} />;
  }

  return (
    <main className="app-shell">
      <AppHeader authenticated={authRequired} onLogout={handleLogout} />

      <div className="workspace">
        <UploadPanel
          selectedFile={workspace.selectedFile}
          engine={workspace.engine}
          engineStatus={workspace.engineStatus}
          sourceLanguage={workspace.sourceLanguage}
          targetLanguage={workspace.targetLanguage}
          outputFormat={workspace.outputFormat}
          onFileSelected={workspace.handleFileSelected}
          onFileRemoved={() => workspace.setSelectedFile(null)}
          onSourceLanguageChange={workspace.setSourceLanguage}
          onTargetLanguageChange={workspace.setTargetLanguage}
          onOutputFormatChange={workspace.setOutputFormat}
          onLanguagesUpdated={workspace.refresh}
        />
        <EnginePanel
          engine={workspace.engine}
          engineStatus={workspace.engineStatus}
          error={workspace.error}
          busy={workspace.busy}
          canStart={Boolean(workspace.selectedFile)}
          onEngineChange={workspace.setEngine}
          onDismissError={workspace.clearError}
          onStart={() => void workspace.handleStart()}
        />
      </div>

      {(workspace.activeJob || workspace.jobs.length > 0) && (
        <JobQueue
          jobs={workspace.jobs}
          activeJobId={workspace.activeJobId}
          queueError={workspace.queueError}
          onRefresh={() => void workspace.refresh()}
          onCancel={(jobId) => void workspace.handleCancel(jobId)}
          onDownload={(job) => void workspace.handleDownload(job)}
          onResume={(jobId) => void workspace.handleResume(jobId)}
          onDelete={(jobId) => void workspace.handleDelete(jobId)}
        />
      )}

      <AppFooter onRefresh={() => void workspace.refresh()} />
    </main>
  );
}

export default App;

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Github } from "lucide-react";
import {
  API_BASE_URL,
  cancelTranslation,
  clearAuthToken,
  deleteTranslation,
  downloadTranslation,
  getEngineStatus,
  getJob,
  getJobs,
  initialAuthState,
  resumeTranslation,
  startTranslation,
} from "./api";
import { AppFooter } from "./components/AppFooter";
import { AppHeader } from "./components/AppHeader";
import { EnginePanel } from "./components/EnginePanel";
import { JobQueue } from "./components/JobQueue";
import { UploadPanel } from "./components/UploadPanel";
import {
  cloudLanguages,
  defaultSourceLanguage,
  defaultTargetLanguage,
  getBookFormat,
} from "./schemas/translation";
import { uiText } from "./schemas/ui";
import type {
  BookFormat,
  Engine,
  EngineStatus,
  TranslationJob,
} from "./types/translation";

function App() {
  const authRequired = import.meta.env.VITE_AUTH_MODE === "github";
  const [authToken, setAuthToken] = useState(initialAuthState.token);
  const authError = initialAuthState.error;
  const [engine, setEngine] = useState<Engine>("gemini");
  const [sourceLanguage, setSourceLanguage] = useState(defaultSourceLanguage);
  const [targetLanguage, setTargetLanguage] = useState(defaultTargetLanguage);
  const [outputFormat, setOutputFormat] = useState<BookFormat>("pdf");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [engineStatus, setEngineStatus] = useState<EngineStatus | null>(null);
  const [jobs, setJobs] = useState<TranslationJob[]>([]);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [queueError, setQueueError] = useState("");
  const deletedJobIds = useRef(new Set<string>());

  const removeJobFromQueue = useCallback((jobId: string) => {
    deletedJobIds.current.add(jobId);
    setJobs((current) => current.filter((job) => job.id !== jobId));
    setActiveJobId((current) => (current === jobId ? null : current));
  }, []);

  const activeJob = useMemo(
    () => jobs.find((job) => job.id === activeJobId) ?? null,
    [jobs, activeJobId],
  );

  const refresh = useCallback(async () => {
    try {
      const [status, latestJobs] = await Promise.all([
        getEngineStatus(),
        getJobs(),
      ]);
      setEngineStatus(status);
      setJobs(latestJobs.filter((job) => !deletedJobIds.current.has(job.id)));
      setOutputFormat((current) =>
        status.formats.output.includes(current) ? current : "pdf",
      );
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? `${requestError.message} ${uiText.errors.connectionWithHint}`
          : uiText.errors.connectionFallback,
      );
    }
  }, []);

  useEffect(() => {
    if (engine === "gemini") {
      if (!cloudLanguages.some((language) => language.name === sourceLanguage)) {
        setSourceLanguage(defaultSourceLanguage);
      }
      if (!cloudLanguages.some((language) => language.name === targetLanguage)) {
        setTargetLanguage(defaultTargetLanguage);
      }
      return;
    }
    const languages = engineStatus?.argos.languages ?? [];
    if (engine !== "argos" || !languages.length) return;
    const pairs = engineStatus?.argos.pairs ?? [];
    if (
      !pairs.some(
        (pair) =>
          pair.from_name === sourceLanguage &&
          pair.to_name === targetLanguage,
      )
    ) {
      const preferredPair =
        pairs.find((pair) => pair.from_code === "en") ?? pairs[0];
      if (preferredPair) {
        setSourceLanguage(preferredPair.from_name);
        setTargetLanguage(preferredPair.to_name);
      }
    }
  }, [engine, engineStatus, sourceLanguage, targetLanguage]);

  useEffect(() => {
    if (authRequired && !authToken) return;
    void refresh();
    const interval = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(interval);
  }, [authRequired, authToken, refresh]);

  useEffect(() => {
    if (!activeJobId || (authRequired && !authToken)) return;
    let cancelled = false;

    const pollJob = async () => {
      try {
        const latest = await getJob(activeJobId);
        if (cancelled || deletedJobIds.current.has(latest.id)) return;
        setJobs((current) =>
          deletedJobIds.current.has(latest.id)
            ? current
            : [latest, ...current.filter((job) => job.id !== latest.id)],
        );
      } catch (pollError) {
        if (!cancelled) {
          setQueueError(
            pollError instanceof Error
              ? pollError.message
              : uiText.errors.connectionFallback,
          );
        }
      }
    };

    void pollJob();
    const interval = window.setInterval(() => void pollJob(), 1800);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [activeJobId, authRequired, authToken]);

  const handleFileSelected = (file?: File) => {
    setError("");
    if (!file) return;
    const format = getBookFormat(file.name);
    if (!format) {
      setError(uiText.errors.unsupportedBook);
      return;
    }
    if (!engineStatus?.formats.input.includes(format)) {
      setError(
        format === "mobi"
          ? uiText.upload.mobiRequiresCalibre
          : uiText.errors.unsupportedBook,
      );
      return;
    }
    setSelectedFile(file);
  };

  const cloudReady = Boolean(engineStatus?.gemini.configured);
  const argosReady = Boolean(
    engineStatus?.argos.pairs.some(
      (pair) =>
        pair.from_name === sourceLanguage && pair.to_name === targetLanguage,
    ),
  );

  const handleStart = async () => {
    if (!selectedFile) {
      setError(uiText.errors.chooseBook);
      return;
    }

    if (engine === "gemini" && !cloudReady) {
      setError(uiText.errors.gemini);
      return;
    }

    if (engine === "argos" && !argosReady) {
      setError(uiText.errors.argos);
      return;
    }

    setBusy(true);
    setError("");

    try {
      const job = await startTranslation({
        file: selectedFile,
        engine,
        sourceLanguage,
        targetLanguage,
        outputFormat,
      });

      setJobs((current) => [
        job,
        ...current.filter((item) => item.id !== job.id),
      ]);

      setActiveJobId(job.id);
      setSelectedFile(null);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : uiText.errors.start,
      );
    } finally {
      setBusy(false);
    }
  };

  const handleCancel = async (jobId: string) => {
    try {
      await cancelTranslation(jobId);
      setQueueError("");
      await refresh();
    } catch (requestError) {
      setQueueError(
        requestError instanceof Error
          ? requestError.message
          : uiText.errors.cancel,
      );
    }
  };

  const handleResume = async (jobId: string) => {
    try {
      const job = await resumeTranslation(jobId);
      setJobs((current) => [
        job,
        ...current.filter((item) => item.id !== job.id),
      ]);
      setActiveJobId(jobId);
      setError("");
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : uiText.errors.resume,
      );
    }
  };

  const handleDelete = async (jobId: string) => {
    try {
      await deleteTranslation(jobId);
      removeJobFromQueue(jobId);
      setQueueError("");
      setError("");
    } catch (requestError) {
      setQueueError(
        requestError instanceof Error
          ? requestError.message
          : uiText.errors.delete,
      );
    }
  };

  const handleDownload = async (job: TranslationJob) => {
    try {
      await downloadTranslation(
        job.id,
        job.output_filename ?? `translated-book.${job.output_format}`,
      );
      setQueueError("");
    } catch (requestError) {
      setQueueError(
        requestError instanceof Error
          ? requestError.message
          : uiText.errors.download,
      );
    }
  };

  const handleLogout = () => {
    clearAuthToken();
    setAuthToken(null);
    setJobs([]);
    setActiveJobId(null);
  };

  if (authRequired && !authToken) {
    return (
      <main className="app-shell">
        <AppHeader showWorkspaceStatus={false} />
        <section className="panel auth-panel">
          <span className="step-label">ACCOUNT</span>
          <h2>Sign in to continue</h2>
          <p className="hero-copy">
            Translation access is limited to authorized GitHub accounts.
          </p>
          {authError && (
            <div className="error-banner" role="alert">
              {authError === "not_allowed"
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

  return (
    <main className="app-shell">
      <AppHeader authenticated={authRequired} onLogout={handleLogout} />

      <div className="workspace">
        <UploadPanel
          selectedFile={selectedFile}
          engine={engine}
          engineStatus={engineStatus}
          sourceLanguage={sourceLanguage}
          targetLanguage={targetLanguage}
          outputFormat={outputFormat}
          onFileSelected={handleFileSelected}
          onFileRemoved={() => setSelectedFile(null)}
          onSourceLanguageChange={setSourceLanguage}
          onTargetLanguageChange={setTargetLanguage}
          onOutputFormatChange={setOutputFormat}
          onLanguagesUpdated={refresh}
        />
        <EnginePanel
          engine={engine}
          engineStatus={engineStatus}
          error={error}
          busy={busy}
          canStart={Boolean(selectedFile)}
          onEngineChange={setEngine}
          onDismissError={() => setError("")}
          onStart={() => void handleStart()}
        />
      </div>

      {(activeJob || jobs.length > 0) && (
        <JobQueue
          jobs={jobs}
          activeJobId={activeJobId}
          queueError={queueError}
          onRefresh={() => void refresh()}
          onCancel={(jobId) => void handleCancel(jobId)}
          onDownload={(job) => void handleDownload(job)}
          onResume={(jobId) => void handleResume(jobId)}
          onDelete={(jobId) => void handleDelete(jobId)}
        />
      )}

      <AppFooter onRefresh={() => void refresh()} />
    </main>
  );
}

export default App;

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getEngineStatus, getJob, getJobs } from "../api";
import {
  cloudLanguages,
  defaultSourceLanguage,
  defaultTargetLanguage,
} from "../schemas/translation";
import { uiText } from "../schemas/ui";
import type {
  BookFormat,
  Engine,
  EngineStatus,
  TranslationJob,
} from "../types/translation";
import { useWorkspaceActions } from "./useWorkspaceActions";

export function useTranslationWorkspace(enabled: boolean) {
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

    const pairs = engineStatus?.argos.pairs ?? [];
    if (!pairs.length) return;

    const pairIsAvailable = pairs.some(
      (pair) =>
        pair.from_name === sourceLanguage && pair.to_name === targetLanguage,
    );
    if (pairIsAvailable) return;

    const preferredPair =
      pairs.find((pair) => pair.from_code === "en") ?? pairs[0];
    setSourceLanguage(preferredPair.from_name);
    setTargetLanguage(preferredPair.to_name);
  }, [engine, engineStatus, sourceLanguage, targetLanguage]);

  useEffect(() => {
    if (!enabled) return;

    void refresh();
    const interval = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(interval);
  }, [enabled, refresh]);

  useEffect(() => {
    if (!enabled || !activeJobId) return;
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
  }, [activeJobId, enabled]);

  const actions = useWorkspaceActions({
    engine,
    engineStatus,
    outputFormat,
    selectedFile,
    sourceLanguage,
    targetLanguage,
    refresh,
    setActiveJobId,
    setBusy,
    setError,
    setJobs,
    setQueueError,
    setSelectedFile,
    deletedJobIds,
  });

  const clearWorkspace = () => {
    setJobs([]);
    setActiveJobId(null);
    setSelectedFile(null);
    deletedJobIds.current.clear();
  };

  return {
    activeJob,
    activeJobId,
    busy,
    engine,
    engineStatus,
    error,
    jobs,
    outputFormat,
    queueError,
    refresh,
    selectedFile,
    setEngine,
    setOutputFormat,
    setSelectedFile,
    setSourceLanguage,
    setTargetLanguage,
    sourceLanguage,
    targetLanguage,
    clearWorkspace,
    clearError: () => setError(""),
    ...actions,
  };
}

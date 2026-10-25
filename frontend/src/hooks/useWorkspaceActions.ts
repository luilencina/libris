import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import {
  cancelTranslation,
  deleteTranslation,
  downloadTranslation,
  resumeTranslation,
  startTranslation,
} from "../api";
import { getBookFormat } from "../schemas/translation";
import { uiText } from "../schemas/ui";
import type {
  BookFormat,
  Engine,
  EngineStatus,
  TranslationJob,
} from "../types/translation";

interface WorkspaceActionsOptions {
  engine: Engine;
  engineStatus: EngineStatus | null;
  outputFormat: BookFormat;
  selectedFile: File | null;
  sourceLanguage: string;
  targetLanguage: string;
  refresh: () => Promise<void>;
  setActiveJobId: Dispatch<SetStateAction<string | null>>;
  setBusy: Dispatch<SetStateAction<boolean>>;
  setError: Dispatch<SetStateAction<string>>;
  setJobs: Dispatch<SetStateAction<TranslationJob[]>>;
  setQueueError: Dispatch<SetStateAction<string>>;
  setSelectedFile: Dispatch<SetStateAction<File | null>>;
  deletedJobIds: MutableRefObject<Set<string>>;
}

export function useWorkspaceActions({
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
}: WorkspaceActionsOptions) {
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

  const handleStart = async () => {
    if (!selectedFile) {
      setError(uiText.errors.chooseBook);
      return;
    }

    const cloudReady = Boolean(engineStatus?.gemini.configured);
    const argosReady = Boolean(
      engineStatus?.argos.pairs.some(
        (pair) =>
          pair.from_name === sourceLanguage &&
          pair.to_name === targetLanguage,
      ),
    );
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
      deletedJobIds.current.add(jobId);
      setJobs((current) => current.filter((job) => job.id !== jobId));
      setActiveJobId((current) => (current === jobId ? null : current));
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

  return {
    handleCancel,
    handleDelete,
    handleDownload,
    handleFileSelected,
    handleResume,
    handleStart,
  };
}

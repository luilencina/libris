import {
  Download,
  FileText,
  LoaderCircle,
  RefreshCw,
  Trash2,
  X,
} from "lucide-react";
import { bookFormatLabels } from "../schemas/translation";
import { uiText } from "../schemas/ui";
import type { TranslationJob } from "../types/translation";

interface JobQueueProps {
  jobs: TranslationJob[];
  activeJobId: string | null;
  queueError: string;
  onRefresh: () => void;
  onCancel: (jobId: string) => void;
  onDownload: (job: TranslationJob) => void;
  onResume: (jobId: string) => void;
  onDelete: (jobId: string) => void;
}

function getEngineLabel(job: TranslationJob): string {
  if (job.engine === "gemini") return uiText.engine.jobLabels.gemini;
  if (job.engine === "argos") return uiText.engine.jobLabels.argos;
  return uiText.engine.jobLabels.legacy;
}

function getProgressLabel(job: TranslationJob): string {
  if (job.status === "completed") return uiText.queue.ready;
  if (job.status === "failed") return uiText.queue.stopped;
  if (job.status === "cancelled") return uiText.queue.cancelled;
  return uiText.queue.translating;
}

interface JobCardProps {
  job: TranslationJob;
  active: boolean;
  onCancel: () => void;
  onDownload: () => void;
  onResume: () => void;
  onDelete: () => void;
}

function JobCard({
  job,
  active,
  onCancel,
  onDownload,
  onResume,
  onDelete,
}: JobCardProps) {
  const running = job.status === "running" || job.status === "queued";

  return (
    <article className={`job-card ${active ? "job-active" : ""}`}>
      <div className="job-file-icon">
        <FileText size={21} />
      </div>
      <div className="job-main">
        <div className="job-title-row">
          <strong title={job.filename}>{job.filename}</strong>
          <span className={`status-pill status-${job.status}`}>
            {running && <LoaderCircle size={12} className="spin" />}
            {uiText.queue.status[job.status]}
          </span>
        </div>
        <div className="job-meta">
          {getEngineLabel(job)}
          <span>·</span> {job.total_pages_with_text} {uiText.queue.pages}
          <span>·</span> {job.completed_chunks}/{job.total_chunks} {uiText.queue.chunks}
        </div>
        <div className="progress-track">
          <div
            className="progress-fill"
            style={{ width: `${job.progress}%` }}
          />
        </div>
        <div className="progress-caption">
          <span>{getProgressLabel(job)}</span>
          <span>{job.progress}%</span>
        </div>
        {job.error && <p className="job-error">{job.error}</p>}
        <div className="job-actions">
          {job.status === "completed" && (
            <button
              className="download-button"
              onClick={onDownload}
              type="button"
            >
              <Download size={15} />{" "}
              {uiText.queue.download(bookFormatLabels[job.output_format])}
            </button>
          )}
          {running && (
            <button className="text-button" type="button" onClick={onCancel}>
              <X size={14} /> {uiText.queue.cancel}
            </button>
          )}
          {(job.status === "failed" || job.status === "cancelled") && (
            <button
              className="text-button"
              type="button"
              onClick={onResume}
            >
              <RefreshCw size={14} /> {uiText.queue.resume}
            </button>
          )}
          <button
            className="text-button delete-button"
            type="button"
            onClick={() => {
              if (
                window.confirm(
                  running
                    ? uiText.queue.confirmCancelDelete
                    : uiText.queue.confirmDelete,
                )
              ) {
                onDelete();
              }
            }}
            aria-label={uiText.queue.deleteLabel(job.filename)}
          >
            <Trash2 size={14} />{" "}
            {running ? uiText.queue.cancelAndRemove : uiText.queue.remove}
          </button>
        </div>
      </div>
    </article>
  );
}

export function JobQueue({
  jobs,
  activeJobId,
  queueError,
  onRefresh,
  onCancel,
  onDownload,
  onResume,
  onDelete,
}: JobQueueProps) {
  return (
    <section className="panel progress-panel">
      <div className="section-heading">
        <div>
          <span className="step-label">{uiText.queue.step}</span>
          <h2>{uiText.queue.title}</h2>
        </div>
        <button
          className="icon-button"
          onClick={onRefresh}
          type="button"
          aria-label={uiText.queue.refresh}
        >
          <RefreshCw size={16} />
        </button>
      </div>

      {queueError && (
        <div className="error-banner queue-error" role="alert">
          <span>{queueError}</span>
        </div>
      )}

      <div className="jobs-list">
        {jobs.map((job) => (
          <JobCard
            key={job.id}
            job={job}
            active={activeJobId === job.id}
            onCancel={() => onCancel(job.id)}
            onDownload={() => onDownload(job)}
            onResume={() => onResume(job.id)}
            onDelete={() => onDelete(job.id)}
          />
        ))}
      </div>
    </section>
  );
}

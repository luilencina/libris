import { ChangeEvent, DragEvent, useRef, useState } from "react";
import {
  ChevronDown,
  FileText,
  FolderOpen,
  Languages,
  UploadCloud,
  X,
} from "lucide-react";
import {
  bookFormats,
  bookFormatLabels,
  cloudLanguages,
  getBookFormat,
} from "../schemas/translation";
import { uiText } from "../schemas/ui";
import type { BookFormat, Engine, EngineStatus } from "../types/translation";
import { LanguagePackageManager } from "./LanguagePackageManager";

interface UploadPanelProps {
  selectedFile: File | null;
  engine: Engine;
  engineStatus: EngineStatus | null;
  sourceLanguage: string;
  targetLanguage: string;
  outputFormat: BookFormat;
  onFileSelected: (file?: File) => void;
  onFileRemoved: () => void;
  onSourceLanguageChange: (language: string) => void;
  onTargetLanguageChange: (language: string) => void;
  onOutputFormatChange: (format: BookFormat) => void;
  onLanguagesUpdated: () => Promise<void>;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function UploadPanel({
  selectedFile,
  engine,
  engineStatus,
  sourceLanguage,
  targetLanguage,
  outputFormat,
  onFileSelected,
  onFileRemoved,
  onSourceLanguageChange,
  onTargetLanguageChange,
  onOutputFormatChange,
  onLanguagesUpdated,
}: UploadPanelProps) {
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    onFileSelected(event.target.files?.[0]);
    event.target.value = "";
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragActive(false);
    onFileSelected(event.dataTransfer.files?.[0]);
  };

  const installedLanguages = engineStatus?.argos.languages ?? [];
  const argosPairs = engine === "argos" ? engineStatus?.argos.pairs ?? [] : [];
  const sourceLanguages =
    engine === "argos"
      ? Array.from(
          new Map(
            argosPairs.map((pair) => [
              pair.from_code,
              { code: pair.from_code, name: pair.from_name },
            ]),
          ).values(),
        )
      : cloudLanguages;
  const targetLanguages =
    engine === "argos"
      ? Array.from(
          new Map(
            argosPairs
              .filter((pair) => pair.from_name === sourceLanguage)
              .map((pair) => [
                pair.to_code,
                { code: pair.to_code, name: pair.to_name },
              ]),
          ).values(),
        )
      : cloudLanguages;
  const acceptedFormats = engineStatus?.formats.input ?? ["pdf", "epub"];
  const accept = acceptedFormats
    .map((format) =>
      format === "epub"
        ? ".epub,application/epub+zip"
        : format === "mobi"
          ? ".mobi,application/x-mobipocket-ebook"
          : ".pdf,application/pdf",
    )
    .join(",");

  const handleSourceLanguageChange = (nextSource: string) => {
    onSourceLanguageChange(nextSource);
    if (
      engine === "argos" &&
      !argosPairs.some(
        (pair) =>
          pair.from_name === nextSource && pair.to_name === targetLanguage,
      )
    ) {
      const firstTarget = argosPairs.find(
        (pair) => pair.from_name === nextSource,
      )?.to_name;
      if (firstTarget) onTargetLanguageChange(firstTarget);
    }
  };

  return (
    <section className="panel upload-panel">
      <div className="section-heading">
        <div>
          <span className="step-label">{uiText.upload.step}</span>
          <h2>{uiText.upload.title}</h2>
        </div>
        <span className="subtle-tag">{uiText.upload.tag}</span>
      </div>

      <div
        className={`dropzone ${dragActive ? "dropzone-active" : ""} ${selectedFile ? "dropzone-has-file" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={handleDrop}
      >
        <input
          ref={fileInputRef}
          className="hidden-input"
          type="file"
          accept={accept}
          onChange={handleFileChange}
        />
        {selectedFile ? (
          <>
            <div className="file-icon">
              <FileText size={27} />
            </div>
            <strong className="file-name">{selectedFile.name}</strong>
            <span className="muted">{formatBytes(selectedFile.size)}</span>
            <button
              className="text-button"
              onClick={onFileRemoved}
              type="button"
            >
              <X size={14} /> {uiText.upload.remove}
            </button>
          </>
        ) : (
          <>
            <div className="upload-icon">
              <UploadCloud size={29} />
            </div>
            <strong>{uiText.upload.drop}</strong>
            <span className="muted">{uiText.upload.browse}</span>
            <button
              className="secondary-button"
              onClick={() => fileInputRef.current?.click()}
              type="button"
            >
              <FolderOpen size={16} /> {uiText.upload.choose}
            </button>
            <span className="file-limit">
              {uiText.upload.maxFileSize}
            </span>
            {!engineStatus?.formats.mobi_available && (
              <span className="file-limit">
                {uiText.upload.mobiRequiresCalibre}
              </span>
            )}
          </>
        )}
      </div>

      <div className="field-row">
        <label className="field">
          <span>{uiText.upload.sourceLanguage}</span>
          <div className="select-wrap group">
            <Languages className="shrink-0" size={17} />
            <select
              className="w-full min-w-0 cursor-pointer appearance-none border-0 bg-transparent py-3 text-sm text-slate-100 outline-none disabled:cursor-not-allowed disabled:opacity-60"
              value={sourceLanguage}
              onChange={(event) =>
                handleSourceLanguageChange(event.target.value)
              }
              disabled={!sourceLanguages.length}
              aria-label={uiText.upload.sourceLanguage}
            >
              {sourceLanguages.map((language) => (
                <option key={language.code} value={language.name}>
                  {language.name}
                </option>
              ))}
            </select>
            <ChevronDown className="shrink-0 text-slate-400 transition-transform group-focus-within:rotate-180" size={16} />
          </div>
        </label>
        <label className="field">
          <span>{uiText.upload.targetLanguage}</span>
          <div className="select-wrap group">
            <Languages className="shrink-0" size={17} />
            <select
              className="w-full min-w-0 cursor-pointer appearance-none border-0 bg-transparent py-3 text-sm text-slate-100 outline-none disabled:cursor-not-allowed disabled:opacity-60"
              value={targetLanguage}
              onChange={(event) => onTargetLanguageChange(event.target.value)}
              disabled={!targetLanguages.length}
              aria-label={uiText.upload.targetLanguage}
            >
              {targetLanguages.map((language) => (
                <option key={language.code} value={language.name}>
                  {language.name}
                </option>
              ))}
            </select>
            <ChevronDown className="shrink-0 text-slate-400 transition-transform group-focus-within:rotate-180" size={16} />
          </div>
        </label>
        <label className="field">
          <span>{uiText.upload.exportFormat}</span>
          <div className="select-wrap group">
            <FileText className="shrink-0" size={17} />
            <select
              className="w-full min-w-0 cursor-pointer appearance-none border-0 bg-transparent py-3 text-sm text-slate-100 outline-none disabled:cursor-not-allowed disabled:opacity-60"
              value={outputFormat}
              onChange={(event) =>
                onOutputFormatChange(event.target.value as BookFormat)
              }
              aria-label={uiText.upload.exportFormat}
            >
              {bookFormats.map((format) => (
                <option
                  key={format}
                  value={format}
                  disabled={!engineStatus?.formats.output.includes(format)}
                >
                  {bookFormatLabels[format]}
                  {format === "mobi" &&
                  !engineStatus?.formats.mobi_available
                    ? ` ${uiText.upload.mobiFormatHint}`
                    : ""}
                </option>
              ))}
            </select>
            <ChevronDown className="shrink-0 text-slate-400 transition-transform group-focus-within:rotate-180" size={16} />
          </div>
        </label>
      </div>
      {engine === "argos" && (
        <LanguagePackageManager
          languages={installedLanguages}
          onInstalled={onLanguagesUpdated}
        />
      )}
    </section>
  );
}

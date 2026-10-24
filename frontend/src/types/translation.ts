export type Engine = "gemini" | "argos";

export type JobStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type BookFormat = "pdf" | "epub" | "mobi";

export interface LanguageOption {
  code: string;
  name: string;
}

export interface LanguagePair {
  from_code: string;
  from_name: string;
  to_code: string;
  to_name: string;
}

export interface LanguagePackageOption {
  from_code: string;
  to_code: string;
}

export interface EngineStatus {
  gemini: {
    configured: boolean;
    model: string;
    limits_note: string;
  };
  argos: {
    available: boolean;
    languages: LanguageOption[];
    pairs: LanguagePair[];
    limits_note: string;
  };
  formats: {
    input: BookFormat[];
    output: BookFormat[];
    mobi_available: boolean;
  };
}

export interface TranslationJob {
  id: string;
  filename: string;
  engine: string;
  source_language: string;
  target_language: string;
  input_format: BookFormat;
  output_format: BookFormat;
  status: JobStatus;
  total_pages_with_text: number;
  total_chunks: number;
  completed_chunks: number;
  progress: number;
  error: string | null;
  created_at: string;
  updated_at: string;
  output_filename?: string;
}

export interface StartTranslationInput {
  file: File;
  engine: Engine;
  sourceLanguage: string;
  targetLanguage: string;
  outputFormat: BookFormat;
}

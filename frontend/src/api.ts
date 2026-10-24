import type {
  Engine,
  EngineStatus,
  LanguagePackageOption,
  StartTranslationInput,
  TranslationJob,
} from "./types/translation";
import { uiText } from "./schemas/ui";

const apiUrl = (
  import.meta.env.VITE_API_URL || "http://127.0.0.1:8000"
).replace(/\/+$/, "");

export const API_BASE_URL = apiUrl.endsWith("/api")
  ? apiUrl
  : `${apiUrl}/api`;

const AUTH_TOKEN_KEY = "novel-translator-session";

export const initialAuthState = (() => {
  const params = new URLSearchParams(window.location.hash.slice(1));
  const token = params.get("token");
  const error = params.get("auth_error");
  if (token) sessionStorage.setItem(AUTH_TOKEN_KEY, token);
  if (token || error) {
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${window.location.search}`,
    );
  }
  return {
    token: token ?? sessionStorage.getItem(AUTH_TOKEN_KEY),
    error,
  };
})();

export function clearAuthToken(): void {
  sessionStorage.removeItem(AUTH_TOKEN_KEY);
}

function apiFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  const token = sessionStorage.getItem(AUTH_TOKEN_KEY);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(input, { ...init, headers });
}

export type {
  Engine,
  EngineStatus,
  JobStatus,
  TranslationJob,
} from "./types/translation";

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(await getResponseError(response));
  }
  return response.json() as Promise<T>;
}

async function getResponseError(response: Response): Promise<string> {
  let message = uiText.errors.requestFailed(response.status);
  try {
    const payload = await response.json();
    if (typeof payload.detail === "string") message = payload.detail;
  } catch {
  }
  return message;
}

export async function getEngineStatus(): Promise<EngineStatus> {
  return parseResponse<EngineStatus>(
    await apiFetch(`${API_BASE_URL}/engines`),
  );
}

export async function getJobs(): Promise<TranslationJob[]> {
  return parseResponse<TranslationJob[]>(
    await apiFetch(`${API_BASE_URL}/translations`),
  );
}

export async function getAvailableLanguagePackages(): Promise<LanguagePackageOption[]> {
  const response = await parseResponse<{
    packages: LanguagePackageOption[];
  }>(await apiFetch(`${API_BASE_URL}/languages/available`));
  return response.packages;
}

export async function installLanguagePackage(
  sourceCode: string,
  targetCode: string,
): Promise<void> {
  await parseResponse<{ status: string }>(
    await apiFetch(`${API_BASE_URL}/languages/install`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_code: sourceCode,
        target_code: targetCode,
      }),
    }),
  );
}

export async function getJob(jobId: string): Promise<TranslationJob> {
  return parseResponse<TranslationJob>(
    await apiFetch(`${API_BASE_URL}/translations/${jobId}`),
  );
}

export async function startTranslation(
  input: StartTranslationInput,
): Promise<TranslationJob> {
  const formData = new FormData();
  formData.append("file", input.file);
  formData.append("engine", input.engine);
  formData.append("source_language", input.sourceLanguage);
  formData.append("target_language", input.targetLanguage);
  formData.append("output_format", input.outputFormat);

  return parseResponse<TranslationJob>(
    await apiFetch(`${API_BASE_URL}/translations`, {
      method: "POST",
      body: formData,
    }),
  );
}

export async function cancelTranslation(jobId: string): Promise<void> {
  await parseResponse<{ status: string }>(
    await apiFetch(`${API_BASE_URL}/translations/${jobId}/cancel`, {
      method: "POST",
    }),
  );
}

export async function deleteTranslation(jobId: string): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/translations/${jobId}`, {
    method: "DELETE",
  });
  await parseResponse<{ status: string }>(response);
}

export async function resumeTranslation(
  jobId: string,
): Promise<TranslationJob> {
  return parseResponse<TranslationJob>(
    await apiFetch(`${API_BASE_URL}/translations/${jobId}/resume`, {
      method: "POST",
    }),
  );
}

export async function downloadTranslation(
  jobId: string,
  filename: string,
): Promise<void> {
  const response = await apiFetch(
    `${API_BASE_URL}/translations/${jobId}/download`,
  );
  if (!response.ok) throw new Error(await getResponseError(response));

  const downloadUrl = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = downloadUrl;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
}

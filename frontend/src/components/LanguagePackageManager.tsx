import { useState } from "react";
import { Download, Languages } from "lucide-react";
import { getAvailableLanguagePackages, installLanguagePackage } from "../api";
import { uiText } from "../schemas/ui";
import type {
  LanguageOption,
  LanguagePackageOption,
} from "../types/translation";

interface LanguagePackageManagerProps {
  languages: LanguageOption[];
  onInstalled: () => Promise<void>;
}

export function LanguagePackageManager({
  languages,
  onInstalled,
}: LanguagePackageManagerProps) {
  const [expanded, setExpanded] = useState(false);
  const [packages, setPackages] = useState<LanguagePackageOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [installingPackage, setInstallingPackage] = useState<string | null>(
    null,
  );
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [search, setSearch] = useState("");
  const languageNames = new Map(languages.map(({ code, name }) => [code, name]));
  const matchingPackages = packages.filter((languagePackage) => {
    const searchText = search.trim().toLocaleLowerCase();
    if (!searchText) return true;
    const sourceName =
      languageNames.get(languagePackage.from_code) ?? languagePackage.from_code;
    const targetName =
      languageNames.get(languagePackage.to_code) ?? languagePackage.to_code;
    return `${sourceName} ${targetName} ${languagePackage.from_code} ${languagePackage.to_code}`
      .toLocaleLowerCase()
      .includes(searchText);
  });

  const loadPackages = async () => {
    setExpanded(true);
    setLoading(true);
    setError("");
    setSuccess("");
    try {
      setPackages(await getAvailableLanguagePackages());
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : uiText.errors.packages,
      );
    } finally {
      setLoading(false);
    }
  };

  const handleInstall = async (languagePackage: LanguagePackageOption) => {
    const key = `${languagePackage.from_code}-${languagePackage.to_code}`;
    setInstallingPackage(key);
    setError("");
    setSuccess("");
    try {
      await installLanguagePackage(
        languagePackage.from_code,
        languagePackage.to_code,
      );
      await onInstalled();
      setPackages((current) =>
        current.filter(
          (item) =>
            item.from_code !== languagePackage.from_code ||
            item.to_code !== languagePackage.to_code,
        ),
      );
      setSuccess(uiText.upload.installed);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : uiText.errors.installPackage,
      );
    } finally {
      setInstallingPackage(null);
    }
  };

  return (
    <div className="language-manager">
      <button
        className="text-button language-manager-toggle"
        type="button"
        onClick={() => {
          if (expanded) {
            setExpanded(false);
          } else {
            void loadPackages();
          }
        }}
      >
        <Languages size={14} />
        {expanded ? uiText.upload.hideLanguages : uiText.upload.addLanguages}
      </button>
      {expanded && (
        <div className="language-package-list">
          <label className="language-package-search">
            <span className="visually-hidden">
              {uiText.upload.searchLanguagesLabel}
            </span>
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={uiText.upload.searchLanguagesPlaceholder}
              aria-label={uiText.upload.searchLanguagesLabel}
            />
          </label>
          {loading && (
            <p className="inline-help">{uiText.upload.loadingPackages}</p>
          )}
          {error && <p className="language-package-error">{error}</p>}
          {success && <p className="language-package-success">{success}</p>}
          {!loading && !error && packages.length === 0 && (
            <p className="inline-help">{uiText.upload.noPackages}</p>
          )}
          {!loading && !error && packages.length > 0 && matchingPackages.length === 0 && (
            <p className="inline-help">{uiText.upload.noMatchingPackages}</p>
          )}
          {!loading && matchingPackages.map((languagePackage) => {
            const key = `${languagePackage.from_code}-${languagePackage.to_code}`;
            const sourceName =
              languageNames.get(languagePackage.from_code) ??
              languagePackage.from_code;
            const targetName =
              languageNames.get(languagePackage.to_code) ??
              languagePackage.to_code;
            return (
              <div className="language-package-row" key={key}>
                <span>
                  {sourceName} → {targetName}
                </span>
                <button
                  className="text-button"
                  type="button"
                  disabled={installingPackage !== null}
                  onClick={() => void handleInstall(languagePackage)}
                >
                  <Download size={13} />
                  {installingPackage === key
                    ? uiText.upload.installing
                    : uiText.upload.install}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

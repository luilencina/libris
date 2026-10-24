import argparse

import argostranslate.package
import argostranslate.translate


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install an Argos Translate package from English."
    )
    parser.add_argument(
        "target",
        nargs="?",
        default="pt",
        help="Target language code (default: pt).",
    )
    target_code = parser.parse_args().target.lower()

    languages = argostranslate.translate.get_installed_languages()
    source = next(
        (language for language in languages if language.code == "en"),
        None,
    )
    if source and any(
        language.code == target_code
        and source.get_translation(language) is not None
        for language in languages
    ):
        print(f"Argos package en -> {target_code} is already installed.")
        return

    print("Updating the Argos package index...")
    argostranslate.package.update_package_index()
    package = next(
        (
            item
            for item in argostranslate.package.get_available_packages()
            if item.from_code == "en" and item.to_code == target_code
        ),
        None,
    )
    if package is None:
        raise RuntimeError(
            f"No Argos Translate package is available for en -> {target_code}."
        )

    print(f"Downloading Argos package en -> {target_code}...")
    package_path = package.download()
    argostranslate.package.install_from_path(package_path)
    print(f"Argos package en -> {target_code} installed successfully.")


if __name__ == "__main__":
    main()

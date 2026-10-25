import logging
import shutil
from pathlib import Path

import argostranslate.package
import argostranslate.settings


REQUIRED_PAIRS = (
    ("en", "pt"),
    ("pt", "en"),
    ("pt", "es"),
    ("es", "pt"),
    ("en", "de"),
    ("de", "en"),
    ("en", "fr"),
    ("fr", "en"),
    ("en", "it"),
    ("it", "en"),
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("libris.argos")


def main() -> None:
    logger.info("Starting sequential Argos language package installation.")
    try:
        installed = {
            (package.from_code, package.to_code)
            for package in argostranslate.package.get_installed_packages()
            if package.type == "translate"
        }
        logger.info("Updating the official Argos package index.")
        argostranslate.package.update_package_index()
        available = {
            (package.from_code, package.to_code): package
            for package in argostranslate.package.get_available_packages()
        }
    except Exception:
        logger.exception("Could not load the Argos package index; the API can still start.")
        return

    failures = []
    for source_code, target_code in REQUIRED_PAIRS:
        pair = (source_code, target_code)
        if pair in installed:
            logger.info("Argos package %s -> %s is already installed.", *pair)
            continue

        package = available.get(pair)
        if package is None:
            logger.error(
                "The official Argos index has no package for %s -> %s.",
                *pair,
            )
            failures.append(pair)
            continue

        try:
            logger.info("Installing Argos package %s -> %s.", *pair)
            package.install()
            installed.add(pair)
            logger.info("Installed Argos package %s -> %s.", *pair)
        except Exception:
            logger.exception(
                "Could not install Argos package %s -> %s; continuing with other pairs.",
                *pair,
            )
            failures.append(pair)

    if failures:
        logger.warning(
            "Argos installation finished with %d unavailable package(s): %s",
            len(failures),
            ", ".join(f"{source} -> {target}" for source, target in failures),
        )
    else:
        logger.info("All required Argos language packages are ready.")

    try:
        package_dir = Path(argostranslate.settings.package_data_dir)
        installed_bytes = sum(
            path.stat().st_size for path in package_dir.rglob("*") if path.is_file()
        )
        disk = shutil.disk_usage(package_dir)
        logger.info(
            "Argos model directory uses %d bytes; %d bytes remain on its filesystem.",
            installed_bytes,
            disk.free,
        )
    except OSError:
        logger.exception("Could not inspect Argos package storage.")


if __name__ == "__main__":
    main()

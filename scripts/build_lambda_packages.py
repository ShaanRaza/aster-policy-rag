#!/usr/bin/env python3
"""Build deployment zip files for the two Lambda functions.

AWS Lambda runs a packaged zip file containing your handler plus all of its
dependencies. The Python runtime does not have access to `pip install`
at runtime, so every third-party dependency must be vendored into the zip.

This script automates that packaging step for both Lambdas in this project:

- `ingest_handler` — triggered by S3 events, extracts PDFs, writes chunks
  to OpenSearch.
- `query_handler`  — triggered by API Gateway, embeds the user question,
  searches OpenSearch, asks Bedrock for a grounded answer.

Each Lambda package contains:

- the handler's `app.py`
- the shared project code under `lambdas/shared`
- third-party dependencies installed from the handler's `requirements.txt`

Output zips land in `lambda_packages/<function>.zip`, ready for
`aws lambda update-function-code --zip-file fileb://...`.
"""

from __future__ import annotations

# Argument parsing for selecting which function(s) to build.
import argparse
# `shutil` is used for copying files/trees and removing directories recursively.
import shutil
# `subprocess` is used to shell out to `pip install -t <target>`.
import subprocess
# `sys.executable` ensures we use the SAME Python interpreter that's running
# this script — avoids accidentally installing into a different Python's
# site-packages.
import sys
# `zipfile` builds the final deployment archive.
import zipfile
from pathlib import Path


# Compute and freeze the absolute paths for the project. Using `parents[1]`
# gives the directory above `scripts/`, which is the project root.
ROOT = Path(__file__).resolve().parents[1]
# Where the Lambda source code lives (one subdirectory per function).
LAMBDA_ROOT = ROOT / "lambdas"
# Where the final zip files will be written.
PACKAGE_DIR = ROOT / "lambda_packages"
# A working directory where unzipped packages are assembled before zipping.
# Keeping this on disk makes it easy to inspect what is going into a build.
BUILD_DIR = ROOT / "lambda_build"


def copy_tree(source: Path, target: Path) -> None:
    """Replace `target` with a fresh copy of `source`.

    `shutil.copytree` refuses to copy into an existing directory, so we
    delete the target first if it exists. This keeps each build reproducible.
    """
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def build_function(function_dir: Path) -> Path:
    """Build one Lambda function directory into a deployable zip file.

    The build directory layout will look like:

        lambda_build/<function>/
            app.py                  <- the handler
            shared/...              <- shared Python modules
            <third-party packages>  <- installed by pip
    """
    # Name of the function (e.g., "ingest_handler"). Used for paths and zip name.
    name = function_dir.name

    # Wipe and recreate this function's build directory so we start clean.
    build_path = BUILD_DIR / name
    if build_path.exists():
        shutil.rmtree(build_path)
    build_path.mkdir(parents=True)

    # If the function has a requirements.txt, install its dependencies INTO
    # the build directory (`-t <path>`). This is the standard Lambda packaging
    # technique — all installed packages end up at the root of the zip.
    requirements = function_dir / "requirements.txt"
    if requirements.exists():
        subprocess.check_call(
            [
                sys.executable,    # same interpreter as this script
                "-m",
                "pip",
                "install",
                "-r",
                str(requirements),
                "-t",              # install into a target directory…
                str(build_path),   # …namely the build directory
            ]
        )

    # Copy the handler entrypoint (`app.py`) and the shared package next to
    # the installed dependencies. Lambda will see all of these as top-level
    # imports because they all live at the zip root.
    shutil.copy2(function_dir / "app.py", build_path / "app.py")
    copy_tree(LAMBDA_ROOT / "shared", build_path / "shared")

    # Ensure the output directory exists, then remove any previous zip to
    # avoid mixing old and new entries.
    PACKAGE_DIR.mkdir(exist_ok=True)
    zip_path = PACKAGE_DIR / f"{name}.zip"
    if zip_path.exists():
        zip_path.unlink()

    # Build the zip. `ZIP_DEFLATED` enables compression so the package stays
    # under Lambda's direct upload size limit when possible.
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        # `rglob("*")` walks every file in the build directory.
        for file_path in build_path.rglob("*"):
            # Lambda expects paths in the zip to be relative to the package
            # root, not absolute. `relative_to` strips the build prefix.
            archive.write(file_path, file_path.relative_to(build_path))

    # Return the zip path so the caller can print or further process it.
    return zip_path


def main() -> None:
    """Parse CLI args and build the requested Lambda package(s)."""
    parser = argparse.ArgumentParser(description="Build Lambda deployment zip files.")
    # Allow building just one function (faster iteration) or both at once.
    parser.add_argument(
        "--function",
        choices=["query_handler", "ingest_handler", "all"],
        default="all",
    )
    args = parser.parse_args()

    # Expand the `all` shortcut into the concrete list of functions.
    targets = ["query_handler", "ingest_handler"] if args.function == "all" else [args.function]

    # Build each function sequentially and print the resulting zip path so
    # the user can copy it into their deploy step.
    for target in targets:
        zip_path = build_function(LAMBDA_ROOT / target)
        print(f"Built {zip_path}")


if __name__ == "__main__":
    main()

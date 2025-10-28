import argparse
import os
import stat
import tarfile
import time
import zipfile
from collections.abc import Callable, Iterable
from fnmatch import fnmatch
from pathlib import Path
from pprint import pprint
from tempfile import TemporaryDirectory
from typing import Any, Optional, TypeAlias

import github as pgh
import requests
from github.Artifact import Artifact
from github.Branch import Branch
from github.Repository import Repository
from github.WorkflowRun import WorkflowRun
from tqdm import tqdm

PredicateFn: TypeAlias = Callable[..., bool]
GH_ACCESS_TOKEN = os.environ.get("FETCH_GH_ACCESS_TOKEN")


def retry_on_permission_error(max_attempts=5, initial_delay=0.1):
    """
    Retry decorator for file operations that may fail due to transient Windows file locks.
    Uses exponential backoff to handle PermissionError caused by antivirus, indexer, etc.
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            delay = initial_delay
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except (PermissionError, OSError):
                    if attempt == max_attempts - 1:
                        # Last attempt failed, re-raise the exception
                        raise
                    # Wait with exponential backoff before retrying
                    time.sleep(delay)
                    delay *= 2
            return None  # Should never reach here
        return wrapper
    return decorator


def find_first_if(iter: Iterable, pred: PredicateFn, default: Any = None):
    return next((x for x in iter if pred(x)), default)


def _download_artifact(
    run: WorkflowRun,
    artifact: Artifact,
    dest_dir: Optional[Path] = None,
) -> Path:
    if not dest_dir:
        dest_dir = Path(TemporaryDirectory(delete=False).name)

    assert (
        not dest_dir.exists()
    ) or dest_dir.is_dir(), "dest_dir exists but is not a directory!"

    dest_dir.mkdir(parents=True, exist_ok=True)

    file_name = f"{artifact.name}.zip"
    status, headers, response = run.requester.requestJson(
        "GET", artifact.archive_download_url
    )
    assert status == 302

    download_url = headers["location"]
    file_path = dest_dir / file_name

    file_path.touch(exist_ok=False)
    with file_path.open(mode="wb") as f:
        with requests.get(download_url, stream=True) as req:
            req.raise_for_status()
            total_size = int(req.headers.get("content-length", 0))

            with tqdm(
                # desc=download_url,
                desc=file_name,
                total=total_size,
                miniters=1,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
            ) as pb:
                for chunk in req.iter_content(chunk_size=4096):
                    bytes_written = f.write(chunk)
                    pb.update(bytes_written)

    return file_path


def is_tar_or_zip_file(file_path: Path):
    return tarfile.is_tarfile(file_path) or zipfile.is_zipfile(file_path)


def unpack_and_delete_archive(file_path: Path, dest_dir: Optional[Path] = None) -> Path:
    assert file_path.exists() and file_path.is_file()

    if not dest_dir:
        dest_dir = file_path.parent / file_path.stem
        dest_dir.mkdir(parents=False, exist_ok=False)
    else:
        dest_dir.mkdir(parents=True, exist_ok=True)

    def untar():
        tf = tarfile.open(file_path, mode="r")
        tf.extractall(dest_dir, filter="fully_trusted")

    def unzip():
        with zipfile.ZipFile(file_path, mode="r") as zf:
            for info in zf.infolist():
                target_path = dest_dir / info.filename

                # Get Unix file attributes (permissions and file type)
                attr = info.external_attr >> 16

                # Check if this is a symbolic link
                if stat.S_ISLNK(attr):
                    # Extract symbolic link
                    link_target = zf.read(info.filename).decode('utf-8')
                    target_path.parent.mkdir(parents=True, exist_ok=True)

                    try:
                        # Create the symlink
                        if os.name == 'nt':
                            # Windows needs to know if target is a directory
                            is_dir = link_target.endswith('/') or link_target.endswith('\\')
                            os.symlink(link_target, target_path, target_is_directory=is_dir)
                        else:
                            os.symlink(link_target, target_path)
                    except OSError:
                        # Fallback for Windows without admin/dev mode:
                        # Create regular file (preserves current behavior)
                        target_path.write_text(link_target)
                else:
                    # Extract regular file or directory
                    zf.extract(info, dest_dir)

                    # Apply permissions if stored (works on Unix/Linux/macOS)
                    if attr != 0:
                        try:
                            os.chmod(target_path, attr)
                        except OSError:
                            # Permissions may fail on some filesystems
                            pass

    if tarfile.is_tarfile(file_path):
        ok = untar()
    elif zipfile.is_zipfile(file_path):
        ok = unzip()
    else:
        assert False, "file_path is not a tar or zip file!"

    file_path.unlink(missing_ok=False)
    return dest_dir


def download_and_unpack_artifact(
    run: WorkflowRun,
    artifact: Artifact,
    dest_parent_dir: Path,
) -> Path:
    # download the artifact archive, unpack it in a new directory (same name)
    # and delete the original archive file
    dl_file_path = _download_artifact(run, artifact)
    dl_dir_path = unpack_and_delete_archive(
        dl_file_path,
        dest_dir=dest_parent_dir / dl_file_path.stem,
    )

    # if the unpacked data contains only a single archive file, unpack its
    # contents directly in the root artifact directory and delete the archive file
    entries = list(dl_dir_path.iterdir())
    if (len(entries) == 1) and is_tar_or_zip_file(entries[0]):
        unpack_and_delete_archive(entries[0], dest_dir=dl_dir_path)

    # if the only remaining entry is a single directory, move its conents
    # into the root artifact directory and delete the (now empty) directory
    entries = list(dl_dir_path.iterdir())
    if (len(entries) == 1) and entries[0].is_dir():
        for subentry in list(entries[0].iterdir()):
            # Wrap rename in retry logic to handle Windows file locks
            @retry_on_permission_error()
            def move_entry():
                subentry.rename(dl_dir_path / subentry.name)
            move_entry()

        # Wrap rmdir in retry logic to handle Windows file locks
        @retry_on_permission_error()
        def remove_dir():
            entries[0].rmdir()
        remove_dir()

    return dl_dir_path


def get_last_successful_run(
    repo: Repository,
    branch: Branch,
    artifact_name_pattern: str = "*",
) -> Optional[WorkflowRun]:
    print(
        f"Finding successful runs with artifacts for jobs matching '{artifact_name_pattern}'..."
    )

    all_runs = repo.get_workflow_runs(
        branch=branch,
        status="completed",
        exclude_pull_requests=True,
    )

    def run_matches(run: WorkflowRun) -> bool:
        if run.conclusion != "success":
            return False

        matching_jobs = [
            job for job in run.jobs() if fnmatch(job.name, artifact_name_pattern)
        ]
        if len(matching_jobs) < 1:
            return False

        matching_artifacts = [
            artifact.name
            for artifact in run.get_artifacts()
            if (
                fnmatch(artifact.name, artifact_name_pattern)
                and any([artifact.name in job.name for job in matching_jobs])
            )
        ]

        return len(matching_jobs) == len(matching_artifacts)

    with tqdm(
        all_runs, total=all_runs.totalCount, miniters=1, unit="r", leave=False
    ) as pb:
        for i, run in enumerate(all_runs):
            if run_matches(run):
                return run
            pb.update(i + 1)

    return None

    # return find_first_if(all_runs, run_matches)


def main():
    assert (
        GH_ACCESS_TOKEN is not None
    ), "Please set your FETCH_GH_ACCESS_TOKEN environment variable."

    auth_token = pgh.Auth.Token(GH_ACCESS_TOKEN)
    gh = pgh.Github(auth=auth_token)
    print(f"Logged into GitHub as: {gh.get_user().login}")

    parser = argparse.ArgumentParser(
        description="Download and extract ONNXRuntime artifacts from our GitHub build workflow jobs"
    )
    parser.add_argument(
        "-b", "--branch", default="main", help="GitHub branch name (default: main)"
    )
    parser.add_argument(
        "-r",
        "--run",
        type=int,
        help="Workflow run ID (default: latest fully successful run)",
    )
    parser.add_argument(
        "-p",
        "--pattern",
        default="*",
        help="Wildcard pattern for artifact names (default: *)",
    )
    parser.add_argument(
        "-d",
        "--dest",
        type=Path,
        help="Destination directory (default: ./run_<id>_<creation_datetime>)",
    )
    args = parser.parse_args()

    # exit()

    repo = gh.get_repo("alfatraining/ort-artifacts")
    branch = repo.get_branch(args.branch)

    target_run: Optional[WorkflowRun] = None
    if args.run:
        target_run = repo.get_workflow_run(args.run)
    else:
        target_run = get_last_successful_run(repo, branch, args.pattern)
        if not target_run:
            print(
                f"[!!] Failed to find a run with successfully created artifacts for all jobs matching '{args.pattern}'!"
            )
            exit()

    assert target_run, "target_run info could not be retrieved!"

    dest_dir_path = (
        args.dest
        if (args.dest is not None)
        else Path(f"./run_{target_run.id}_{target_run.created_at:%Y-%m-%d_%H%M}")
    )
    print(
        f"Run {target_run.id}: '{target_run.name}' ({target_run.created_at}): {target_run.status}, {target_run.conclusion}"
    )
    for a in target_run.get_artifacts():
        # print(f"\t{a.name}: {a.archive_download_url}")
        download_and_unpack_artifact(target_run, a, dest_dir_path)


if __name__ == "__main__":
    main()

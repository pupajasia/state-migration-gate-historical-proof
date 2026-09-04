#!/usr/bin/env python3
"""Resolve and optionally download exactly one GitHub release artifact.

The resolver is intentionally dependency-free so it can run on a fresh GitHub
hosted Windows runner. It fails closed on ambiguous matches, unsafe names,
unexpected hosts, oversized responses and checksum mismatches.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any, BinaryIO


API_VERSION = "2026-03-10"
DEFAULT_API_BASE = "https://api.github.com"
DEFAULT_MAX_BYTES = 1024 * 1024 * 1024
ALLOWED_REDIRECT_HOSTS = {
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
}
REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}")
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class ResolverError(ValueError):
    """Raised when release metadata or a downloaded asset is unsafe or invalid."""


def validate_repository(repository: str) -> tuple[str, str]:
    if not REPOSITORY_PATTERN.fullmatch(repository):
        raise ResolverError("repository must be in owner/name form")
    owner, name = repository.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."} or name.endswith(".git"):
        raise ResolverError("repository contains an unsupported owner or name")
    return owner, name


def validate_asset_name(name: Any) -> str:
    if not isinstance(name, str) or not name or len(name) > 255:
        raise ResolverError("asset name must be a non-empty string of at most 255 characters")
    if name in {".", ".."} or name[-1] in {" ", "."}:
        raise ResolverError(f"unsafe asset name: {name!r}")
    if any(ord(character) < 32 for character in name):
        raise ResolverError("asset name contains a control character")
    if any(character in name for character in "/\\:<>\"|?*"):
        raise ResolverError(f"unsafe asset name: {name!r}")
    stem = name.split(".", 1)[0].upper()
    if stem in WINDOWS_RESERVED_NAMES:
        raise ResolverError(f"asset name is reserved on Windows: {name!r}")
    return name


def validate_api_base(api_base: str) -> str:
    parsed = urllib.parse.urlsplit(api_base.rstrip("/"))
    if parsed.scheme != "https" or parsed.hostname != "api.github.com":
        raise ResolverError("version 1 supports only https://api.github.com")
    if parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:
        raise ResolverError("API base must not contain credentials, a port, query or fragment")
    return "https://api.github.com"


def release_endpoint(repository: str, release: str, api_base: str = DEFAULT_API_BASE) -> str:
    owner, name = validate_repository(repository)
    base = validate_api_base(api_base)
    encoded_owner = urllib.parse.quote(owner, safe="")
    encoded_name = urllib.parse.quote(name, safe="")
    if release == "latest":
        suffix = "latest"
    elif release:
        suffix = "tags/" + urllib.parse.quote(release, safe="")
    else:
        raise ResolverError("release must be 'latest' or a non-empty tag")
    return f"{base}/repos/{encoded_owner}/{encoded_name}/releases/{suffix}"


def request_headers(token: str | None, accept: str = "application/vnd.github+json") -> dict[str, str]:
    headers = {
        "Accept": accept,
        "User-Agent": "desktop-state-migration-gate/0.1",
        "X-GitHub-Api-Version": API_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def read_release_metadata(
    repository: str,
    release: str,
    token: str | None,
    timeout_seconds: int,
    api_base: str = DEFAULT_API_BASE,
    open_url: Callable[..., BinaryIO] = urllib.request.urlopen,
) -> tuple[dict[str, Any], str]:
    endpoint = release_endpoint(repository, release, api_base)
    request = urllib.request.Request(endpoint, headers=request_headers(token))
    try:
        with open_url(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise ResolverError(f"GitHub release API returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ResolverError(f"GitHub release API request failed: {exc.reason}") from exc
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResolverError("GitHub release API did not return valid UTF-8 JSON") from exc
    if not isinstance(document, dict):
        raise ResolverError("GitHub release metadata root must be an object")
    return document, endpoint


def load_metadata_file(path: pathlib.Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ResolverError(f"metadata file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ResolverError(f"metadata file is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ResolverError("release metadata root must be an object")
    return document


def parse_sha256(value: Any, field_name: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ResolverError(f"{field_name} must be a string")
    candidate = value[7:] if value.lower().startswith("sha256:") else value
    if not SHA256_PATTERN.fullmatch(candidate):
        raise ResolverError(f"{field_name} must be a SHA-256 digest")
    return candidate.lower()


def validate_release(document: dict[str, Any]) -> None:
    if not isinstance(document.get("tag_name"), str) or not document["tag_name"]:
        raise ResolverError("release metadata has no valid tag_name")
    if any(ord(character) < 32 for character in document["tag_name"]):
        raise ResolverError("release tag contains a control character")
    if not isinstance(document.get("id"), int):
        raise ResolverError("release metadata has no integer id")
    if not isinstance(document.get("assets"), list):
        raise ResolverError("release metadata has no assets array")


def select_asset(
    document: dict[str, Any],
    exact_name: str | None = None,
    name_regex: str | None = None,
) -> dict[str, Any]:
    validate_release(document)
    if bool(exact_name) == bool(name_regex):
        raise ResolverError("provide exactly one of exact_name or name_regex")
    pattern: re.Pattern[str] | None = None
    if name_regex:
        try:
            pattern = re.compile(name_regex)
        except re.error as exc:
            raise ResolverError(f"asset regex is invalid: {exc}") from exc

    matches: list[dict[str, Any]] = []
    for candidate in document["assets"]:
        if not isinstance(candidate, dict) or candidate.get("state") != "uploaded":
            continue
        raw_name = candidate.get("name")
        if not isinstance(raw_name, str):
            continue
        matched = raw_name == exact_name if exact_name is not None else bool(pattern.fullmatch(raw_name))
        if matched:
            matches.append(candidate)
    selector = exact_name if exact_name is not None else name_regex
    if not matches:
        raise ResolverError(f"no uploaded release asset matched {selector!r}")
    if len(matches) > 1:
        names = ", ".join(str(item.get("name")) for item in matches[:5])
        raise ResolverError(f"asset selector is ambiguous ({len(matches)} matches): {names}")

    asset = matches[0]
    validate_asset_name(asset.get("name"))
    if not isinstance(asset.get("id"), int):
        raise ResolverError("selected asset has no integer id")
    if not isinstance(asset.get("size"), int) or asset["size"] < 0:
        raise ResolverError("selected asset has no valid byte size")
    if not isinstance(asset.get("browser_download_url"), str):
        raise ResolverError("selected asset has no browser_download_url")
    parse_sha256(asset.get("digest"), "asset.digest")
    return asset


def validate_initial_download_url(url: str, repository: str) -> None:
    owner, name = validate_repository(repository)
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise ResolverError("asset download URL must use https://github.com")
    if parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:
        raise ResolverError("asset download URL contains unsupported URL components")
    expected_prefix = f"/{owner}/{name}/releases/download/".lower()
    if not parsed.path.lower().startswith(expected_prefix):
        raise ResolverError("asset download URL does not belong to the requested repository")


def validate_asset_api_url(url: str, repository: str, asset_id: int) -> None:
    owner, name = validate_repository(repository)
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "api.github.com":
        raise ResolverError("asset API URL must use https://api.github.com")
    if parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:
        raise ResolverError("asset API URL contains unsupported URL components")
    expected = f"/repos/{owner}/{name}/releases/assets/{asset_id}".lower()
    if parsed.path.lower() != expected:
        raise ResolverError("asset API URL does not belong to the selected repository and asset")


def validate_redirect_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or host not in ALLOWED_REDIRECT_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port
    ):
        raise ResolverError("GitHub asset redirect left the allowed HTTPS host boundary")


class SafeGitHubRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> urllib.request.Request | None:
        validate_redirect_url(new_url)
        redirected = super().redirect_request(request, file_pointer, code, message, headers, new_url)
        if redirected is not None:
            old_host = (urllib.parse.urlsplit(request.full_url).hostname or "").lower()
            new_host = (urllib.parse.urlsplit(new_url).hostname or "").lower()
            if old_host != new_host:
                redirected.remove_header("Authorization")
        return redirected


def build_download_opener() -> Callable[..., BinaryIO]:
    opener = urllib.request.build_opener(SafeGitHubRedirectHandler())
    return opener.open


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def choose_expected_digest(asset: dict[str, Any], explicit_digest: str | None) -> str | None:
    metadata_digest = parse_sha256(asset.get("digest"), "asset.digest")
    supplied_digest = parse_sha256(explicit_digest, "expected SHA-256")
    if metadata_digest and supplied_digest and metadata_digest != supplied_digest:
        raise ResolverError("explicit SHA-256 disagrees with the GitHub asset digest")
    return supplied_digest or metadata_digest


def download_asset(
    asset: dict[str, Any],
    repository: str,
    output_directory: pathlib.Path,
    token: str | None,
    timeout_seconds: int,
    max_bytes: int,
    expected_sha256: str | None = None,
    overwrite: bool = False,
    open_url: Callable[..., BinaryIO] | None = None,
) -> dict[str, Any]:
    name = validate_asset_name(asset.get("name"))
    size = asset.get("size")
    if not isinstance(size, int) or size < 0:
        raise ResolverError("selected asset has no valid byte size")
    if max_bytes < 1:
        raise ResolverError("max_bytes must be positive")
    if size > max_bytes:
        raise ResolverError(f"asset size {size} exceeds limit {max_bytes}")
    url = asset.get("browser_download_url")
    if not isinstance(url, str):
        raise ResolverError("selected asset has no browser_download_url")
    validate_initial_download_url(url, repository)
    request_url = url
    if token:
        api_url = asset.get("url")
        asset_id = asset.get("id")
        if not isinstance(api_url, str) or not isinstance(asset_id, int):
            raise ResolverError("authenticated download requires the selected asset API URL and id")
        validate_asset_api_url(api_url, repository, asset_id)
        request_url = api_url
    expected = choose_expected_digest(asset, expected_sha256)

    output_directory.mkdir(parents=True, exist_ok=True)
    destination = output_directory / name
    if destination.exists() and not overwrite:
        raise ResolverError(f"destination already exists: {destination}")

    request = urllib.request.Request(
        request_url, headers=request_headers(token, "application/octet-stream")
    )
    opener = open_url or build_download_opener()
    temporary_path: pathlib.Path | None = None
    digest = hashlib.sha256()
    total = 0
    try:
        with opener(request, timeout=timeout_seconds) as response:
            raw_length = response.headers.get("Content-Length")
            if raw_length:
                try:
                    response_length = int(raw_length)
                except ValueError as exc:
                    raise ResolverError("download returned an invalid Content-Length") from exc
                if response_length > max_bytes:
                    raise ResolverError(f"download size {response_length} exceeds limit {max_bytes}")
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{name}.", suffix=".part", dir=output_directory, delete=False
            ) as temporary:
                temporary_path = pathlib.Path(temporary.name)
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    total += len(block)
                    if total > max_bytes:
                        raise ResolverError(f"download exceeded limit {max_bytes}")
                    temporary.write(block)
                    digest.update(block)
        if total != size:
            raise ResolverError(f"downloaded byte count {total} does not match release metadata {size}")
        actual_digest = digest.hexdigest()
        if expected and actual_digest != expected:
            raise ResolverError("downloaded artifact SHA-256 does not match the expected digest")
        os.replace(temporary_path, destination)
        temporary_path = None
    except urllib.error.HTTPError as exc:
        raise ResolverError(f"GitHub asset download returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ResolverError(f"GitHub asset download failed: {exc.reason}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return {
        "downloaded": True,
        "path": str(destination.resolve()),
        "bytes": total,
        "sha256": actual_digest,
        "checksum_verified": expected is not None,
    }


def build_receipt(
    repository: str,
    release: dict[str, Any],
    asset: dict[str, Any],
    source: str,
    download: dict[str, Any] | None = None,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "receipt_version": 1,
        "status": "downloaded" if download else "resolved",
        "repository": repository,
        "source": source,
        "release": {
            "id": release["id"],
            "tag": release["tag_name"],
            "published_at": release.get("published_at"),
            "draft": release.get("draft"),
            "prerelease": release.get("prerelease"),
        },
        "asset": {
            "id": asset["id"],
            "name": asset["name"],
            "size": asset["size"],
            "content_type": asset.get("content_type"),
            "digest": asset.get("digest"),
            "browser_download_url": asset["browser_download_url"],
            "created_at": asset.get("created_at"),
            "updated_at": asset.get("updated_at"),
        },
    }
    if download:
        receipt["download"] = download
    return receipt


def write_receipt(path: pathlib.Path, receipt: dict[str, Any], overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise ResolverError(f"receipt already exists: {path}")
    temporary_path: pathlib.Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=f".{path.name}.", suffix=".part",
            dir=path.parent, delete=False
        ) as temporary:
            temporary_path = pathlib.Path(temporary.name)
            json.dump(receipt, temporary, indent=2)
            temporary.write("\n")
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def write_github_outputs(receipt: dict[str, Any]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    values = {
        "status": receipt["status"],
        "release_tag": receipt["release"]["tag"],
        "asset_name": receipt["asset"]["name"],
        "path": receipt.get("download", {}).get("path", ""),
        "sha256": receipt.get("download", {}).get("sha256", ""),
    }
    for name, value in values.items():
        if "\n" in str(value) or "\r" in str(value):
            raise ResolverError(f"GitHub output contains a line break: {name}")
    with pathlib.Path(output_path).open("a", encoding="utf-8") as handle:
        for name, value in values.items():
            handle.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve one immutable GitHub release artifact.")
    parser.add_argument("--repo", required=True, help="GitHub repository in owner/name form")
    parser.add_argument("--release", default="latest", help="Release tag or 'latest'")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--name", help="Exact release asset name")
    selector.add_argument("--regex", help="Full-match regular expression for the asset name")
    parser.add_argument("--metadata-file", type=pathlib.Path, help="Offline release API response")
    parser.add_argument("--download", action="store_true", help="Download after resolving metadata")
    parser.add_argument("--output", type=pathlib.Path, default=pathlib.Path(".state-gate-cache"))
    parser.add_argument("--receipt", type=pathlib.Path)
    parser.add_argument("--sha256", help="Required SHA-256 if metadata has no digest")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    try:
        validate_repository(args.repo)
        if args.timeout < 1 or args.timeout > 300:
            raise ResolverError("timeout must be from 1 to 300 seconds")
        if args.max_bytes < 1:
            raise ResolverError("max-bytes must be positive")
        token = os.environ.get("GITHUB_TOKEN") or None
        if args.metadata_file:
            release = load_metadata_file(args.metadata_file.resolve())
            source = str(args.metadata_file.resolve())
        else:
            release, source = read_release_metadata(args.repo, args.release, token, args.timeout)
        asset = select_asset(release, args.name, args.regex)
        result = None
        if args.download:
            result = download_asset(
                asset,
                args.repo,
                args.output.resolve(),
                token,
                args.timeout,
                args.max_bytes,
                args.sha256,
                args.overwrite,
            )
        receipt = build_receipt(args.repo, release, asset, source, result)
        if args.receipt:
            write_receipt(args.receipt.resolve(), receipt, args.overwrite)
        write_github_outputs(receipt)
    except (ResolverError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2

    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

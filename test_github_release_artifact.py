from __future__ import annotations

import hashlib
import io
import os
import pathlib
import tempfile
import unittest

import github_release_artifact as resolver


def asset(name: str, content: bytes = b"release-binary", digest: str | None = None) -> dict:
    return {
        "id": 20,
        "name": name,
        "state": "uploaded",
        "size": len(content),
        "content_type": "application/octet-stream",
        "digest": digest,
        "url": "https://api.github.com/repos/example/desktop/releases/assets/20",
        "browser_download_url": (
            "https://github.com/example/desktop/releases/download/v1.2.3/" + name
        ),
    }


def release(*assets: dict) -> dict:
    return {"id": 10, "tag_name": "v1.2.3", "assets": list(assets)}


class FakeResponse(io.BytesIO):
    def __init__(self, content: bytes, content_length: str | None = None) -> None:
        super().__init__(content)
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = content_length

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class GitHubReleaseArtifactTests(unittest.TestCase):
    def test_exact_selector_returns_single_uploaded_asset(self) -> None:
        selected = resolver.select_asset(
            release(asset("desktop.exe"), {**asset("draft.exe"), "state": "new"}),
            exact_name="desktop.exe",
        )
        self.assertEqual(selected["name"], "desktop.exe")

    def test_regex_uses_full_match_and_rejects_ambiguity(self) -> None:
        document = release(asset("desktop-x64.exe"), asset("desktop-arm64.exe"))
        with self.assertRaisesRegex(resolver.ResolverError, "ambiguous"):
            resolver.select_asset(document, name_regex=r"desktop-.*\.exe")

    def test_no_match_fails_closed(self) -> None:
        with self.assertRaisesRegex(resolver.ResolverError, "no uploaded"):
            resolver.select_asset(release(asset("desktop.zip")), exact_name="desktop.exe")

    def test_unsafe_windows_asset_name_is_rejected(self) -> None:
        with self.assertRaisesRegex(resolver.ResolverError, "unsafe asset name"):
            resolver.select_asset(release(asset("..\\desktop.exe")), name_regex=r".*")

    def test_reserved_windows_asset_name_is_rejected(self) -> None:
        with self.assertRaisesRegex(resolver.ResolverError, "reserved"):
            resolver.select_asset(release(asset("CON.txt")), exact_name="CON.txt")

    def test_release_endpoint_encodes_tag(self) -> None:
        endpoint = resolver.release_endpoint("example/desktop", "v1 release")
        self.assertEqual(
            endpoint,
            "https://api.github.com/repos/example/desktop/releases/tags/v1%20release",
        )

    def test_download_verifies_size_and_digest_then_moves_atomically(self) -> None:
        content = b"release-binary"
        expected = hashlib.sha256(content).hexdigest()
        selected = asset("desktop.exe", content, f"sha256:{expected}")

        def open_url(_request: object, timeout: int) -> FakeResponse:
            self.assertEqual(timeout, 30)
            return FakeResponse(content, str(len(content)))

        with tempfile.TemporaryDirectory() as folder:
            result = resolver.download_asset(
                selected,
                "example/desktop",
                pathlib.Path(folder),
                token="secret-not-for-receipt",
                timeout_seconds=30,
                max_bytes=100,
                open_url=open_url,
            )
            self.assertEqual(result["sha256"], expected)
            self.assertTrue(result["checksum_verified"])
            self.assertEqual((pathlib.Path(folder) / "desktop.exe").read_bytes(), content)
            self.assertEqual(list(pathlib.Path(folder).glob("*.part")), [])

    def test_checksum_mismatch_leaves_no_file_or_partial(self) -> None:
        content = b"release-binary"
        selected = asset("desktop.exe", content, "sha256:" + "0" * 64)

        def open_url(_request: object, timeout: int) -> FakeResponse:
            return FakeResponse(content, str(len(content)))

        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            with self.assertRaisesRegex(resolver.ResolverError, "does not match"):
                resolver.download_asset(
                    selected, "example/desktop", root, None, 30, 100, open_url=open_url
                )
            self.assertEqual(list(root.iterdir()), [])

    def test_metadata_size_limit_prevents_network_request(self) -> None:
        selected = asset("desktop.exe")
        called = False

        def open_url(_request: object, timeout: int) -> FakeResponse:
            nonlocal called
            called = True
            return FakeResponse(b"")

        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(resolver.ResolverError, "exceeds limit"):
                resolver.download_asset(
                    selected,
                    "example/desktop",
                    pathlib.Path(folder),
                    None,
                    30,
                    2,
                    open_url=open_url,
                )
        self.assertFalse(called)

    def test_download_url_must_belong_to_requested_repository(self) -> None:
        selected = asset("desktop.exe")
        selected["browser_download_url"] = (
            "https://github.com/attacker/project/releases/download/v1/desktop.exe"
        )
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(resolver.ResolverError, "does not belong"):
                resolver.download_asset(
                    selected, "example/desktop", pathlib.Path(folder), None, 30, 100
                )

    def test_asset_api_url_must_match_repository_and_asset_id(self) -> None:
        selected = asset("desktop.exe")
        selected["url"] = "https://api.github.com/repos/attacker/project/releases/assets/20"
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(resolver.ResolverError, "selected repository"):
                resolver.download_asset(
                    selected, "example/desktop", pathlib.Path(folder), "token", 30, 100
                )

    def test_cross_host_redirect_removes_authorization_header(self) -> None:
        handler = resolver.SafeGitHubRedirectHandler()
        request = resolver.urllib.request.Request(
            "https://api.github.com/repos/example/desktop/releases/assets/20",
            headers={
                "Authorization": "Bearer must-not-leak",
                "Accept": "application/octet-stream",
            },
        )
        redirected = handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://release-assets.githubusercontent.com/signed-object?token=opaque",
        )
        self.assertIsNotNone(redirected)
        self.assertIsNone(redirected.get_header("Authorization"))
        self.assertEqual(redirected.get_header("Accept"), "application/octet-stream")

    def test_redirect_to_unrelated_githubusercontent_host_is_rejected(self) -> None:
        with self.assertRaisesRegex(resolver.ResolverError, "allowed HTTPS host"):
            resolver.validate_redirect_url(
                "https://raw.githubusercontent.com/owner/repo/main/file"
            )

    def test_receipt_has_no_authentication_token(self) -> None:
        document = release(asset("desktop.exe"))
        receipt = resolver.build_receipt(
            "example/desktop",
            document,
            document["assets"][0],
            "https://api.github.com/repos/example/desktop/releases/latest",
        )
        self.assertNotIn("token", str(receipt).lower())
        self.assertNotIn("secret-value", str(receipt))

    def test_github_outputs_do_not_include_token_or_download_url(self) -> None:
        document = release(asset("desktop.exe"))
        receipt = resolver.build_receipt(
            "example/desktop",
            document,
            document["assets"][0],
            "https://api.github.com/repos/example/desktop/releases/latest",
            {
                "downloaded": True,
                "path": "C:\\cache\\desktop.exe",
                "bytes": 14,
                "sha256": "a" * 64,
                "checksum_verified": True,
            },
        )
        with tempfile.TemporaryDirectory() as folder:
            output = pathlib.Path(folder) / "github-output.txt"
            original = os.environ.get("GITHUB_OUTPUT")
            os.environ["GITHUB_OUTPUT"] = str(output)
            try:
                resolver.write_github_outputs(receipt)
            finally:
                if original is None:
                    os.environ.pop("GITHUB_OUTPUT", None)
                else:
                    os.environ["GITHUB_OUTPUT"] = original
            text = output.read_text(encoding="utf-8")
        self.assertIn("path=C:\\cache\\desktop.exe", text)
        self.assertNotIn("browser_download_url", text)
        self.assertNotIn("secret", text)


if __name__ == "__main__":
    unittest.main()

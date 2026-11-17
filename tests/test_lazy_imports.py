"""Passive imports use real modules in fresh children; explicit dispatch tests use synthetic collaborators."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(os.environ.get("PS5_LAZY_IMPORT_REPO", Path(__file__).resolve().parents[1])).resolve()
DEPENDENCIES = ("requests", "urllib3", "psnawp_api")


def child(mode: str, module: str, profile: Path) -> dict:
    import importlib
    import importlib.abc
    from types import SimpleNamespace

    assert not any(name.split(".")[0] in DEPENDENCIES for name in sys.modules)
    assert not (REPO / ".env.local").exists()
    os.environ.pop("PSN_NPSSO", None)
    os.environ["PS5_REMOTE_HOME"] = str(profile)
    os.environ["PS5_REMOTE_URL"] = "http://127.0.0.1:1"
    os.environ["PS5_HOST"] = ""
    sys.path.insert(0, str(REPO))
    violations, attempted_imports, sequence = [], [], []
    protected = [Path.home() / name for name in (".ps5-remote", ".pyremoteplay", ".netrc", "_netrc")]
    protected.append(REPO / ".env.local")

    def audit(event, args):
        if event.startswith("socket."):
            violations.append(event)
            raise RuntimeError("passive import attempted a socket audit event")
        if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
            target = Path(os.fsdecode(args[0])).resolve()
            if any(target == path or path in target.parents for path in protected):
                violations.append("protected-store open")
                raise RuntimeError("passive import attempted an original store/config read")

    class DeferredImport(ImportError):
        pass

    class RejectDependencies(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split(".")[0] in DEPENDENCIES:
                attempted_imports.append(fullname)
                sequence.append("import:" + fullname)
                raise DeferredImport(fullname)

    # No requests/urllib3/PSNAWP preload, socket override or successful fake import in passive checks.
    sys.addaudithook(audit)
    if mode != "audit":
        sys.meta_path.insert(0, RejectDependencies())
    imported = importlib.import_module(module)
    assert Path(imported.__file__).resolve() == REPO / (module + ".py")
    if mode in ("passive", "audit"):
        assert not attempted_imports
        assert not any(name.split(".")[0] in DEPENDENCIES for name in sys.modules)
        if module == "server":
            assert imported.psn._client is None and not imported.psn.configured
            assert not hasattr(imported, "remote")
        if module == "psn":
            assert imported.PSN()._client is None
    elif mode == "missing-token":
        for token in (None, "", "   "):
            if token is None:
                os.environ.pop("PSN_NPSSO", None)
            else:
                os.environ["PSN_NPSSO"] = token
            try:
                imported.PSN().client()
            except imported.PSNError as error:
                assert str(error) == "PlayStation Network is not connected. Add the NPSSO token on the remote page."
            else:
                raise AssertionError("missing token unexpectedly accepted")
        assert not attempted_imports
    elif mode == "first-request":
        try:
            imported._req("GET", "/synthetic-no-network")
        except DeferredImport as error:
            assert str(error) == "requests"
        else:
            raise AssertionError("request did not reach the deferred real import")
        assert attempted_imports == ["requests"]
    elif mode == "first-client":
        os.environ["PSN_NPSSO"] = "synthetic-noncredential"
        try:
            imported.PSN().client()
        except imported.PSNError as error:
            assert isinstance(error.__cause__, DeferredImport)
            assert str(error) == "PSN sign-in failed: psnawp_api. The NPSSO token may be expired."
        else:
            raise AssertionError("client did not reach the deferred real import")
        assert attempted_imports == ["psnawp_api"]
    elif mode == "search-order":
        client = SimpleNamespace(search=lambda *a, **kw: [])

        class Search(imported.PSN):
            def _load_library(self, force=False):
                return []

            def client(self):
                sequence.append("client")
                return client

        try:
            Search().store_search("synthetic search")
        except DeferredImport:
            pass
        else:
            raise AssertionError("search did not reach deferred SearchDomain import")
        assert sequence[0] == "client" and attempted_imports == ["psnawp_api"]
    elif mode == "cached-client":
        account = imported.PSN()
        sentinel = object()
        account._client = sentinel
        assert account.client() is sentinel and not attempted_imports
    elif mode in ("client-construction", "constructor-error", "search-dispatch"):
        # These explicit-path collaborator tests are separate from all real-import checks above.
        import builtins
        from unittest import mock
        real_import = builtins.__import__
        account = imported.PSN()
        calls = []
        sentinel = object()

        def factory(token):
            calls.append(token)
            if mode == "constructor-error":
                raise ValueError("synthetic rejection")
            return sentinel

        def synthetic_import(name, *args, **kwargs):
            if name == "psnawp_api":
                return SimpleNamespace(PSNAWP=factory)
            if name == "psnawp_api.models.search.games_search_datatypes":
                return SimpleNamespace(SearchDomain=SimpleNamespace(FULL_GAMES=sentinel))
            return real_import(name, *args, **kwargs)

        os.environ["PSN_NPSSO"] = " synthetic-noncredential "
        with mock.patch("builtins.__import__", side_effect=synthetic_import):
            if mode == "constructor-error":
                try:
                    account.client()
                except imported.PSNError as error:
                    assert isinstance(error.__cause__, ValueError)
                    assert str(error) == "PSN sign-in failed: synthetic rejection. The NPSSO token may be expired."
                    assert account._client is None
                else:
                    raise AssertionError("constructor error was swallowed")
            elif mode == "client-construction":
                assert account.client() is sentinel and account.client() is sentinel
                assert calls == ["synthetic-noncredential"]
            else:
                account._load_library = lambda *args: []

                def search(query, domain, **kwargs):
                    assert account._lock.locked()
                    assert query == "synthetic search" and domain is sentinel and kwargs == {"limit": 3}
                    return []

                account._client = SimpleNamespace(search=search)
                assert account.store_search("synthetic search", limit=3) == {"query": "synthetic search", "results": []}
    else:
        raise AssertionError("unknown test mode")
    # Retain forbidden events even if optional dependency code caught the rejection.
    assert not violations, violations
    assert (profile / "consoles.json").read_bytes() == b'{"account":null,"consoles":{}}'
    return {"mode": mode, "module": module, "forbidden_events": violations,
            "dependency_import_attempts": attempted_imports, "result": "PASS"}


class LazyImportsTest(unittest.TestCase):
    def check_child(self, mode, module):
        with tempfile.TemporaryDirectory(prefix="ps5-import-test-") as directory:
            profile = Path(directory)
            (profile / "consoles.json").write_bytes(b'{"account":null,"consoles":{}}')
            proc = subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), "--child", mode, module, directory],
                                  capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["result"], "PASS")
            self.assertEqual(proc.stderr, "")
        self.assertFalse(profile.exists())

    def test_real_passive_imports_do_not_load_optional_clients(self):
        for module in ("psn", "server", "mcp_server"):
            with self.subTest(module=module):
                self.check_child("passive", module)

    def test_real_imports_have_zero_socket_or_protected_store_events(self):
        for module in ("psn", "server", "mcp_server"):
            with self.subTest(module=module):
                self.check_child("audit", module)

    def test_missing_or_blank_token_precedes_optional_import(self):
        self.check_child("missing-token", "psn")

    def test_first_http_operation_reaches_deferred_import(self):
        self.check_child("first-request", "mcp_server")

    def test_first_psn_operation_reaches_deferred_import(self):
        self.check_child("first-client", "psn")

    def test_search_domain_is_deferred_until_after_client(self):
        self.check_child("search-order", "psn")

    def test_cached_client_requires_no_optional_import(self):
        self.check_child("cached-client", "psn")

    def test_client_construction_trims_token_and_caches(self):
        self.check_child("client-construction", "psn")

    def test_constructor_error_keeps_public_error_and_cause(self):
        self.check_child("constructor-error", "psn")

    def test_search_dispatch_keeps_domain_limit_result_and_lock(self):
        self.check_child("search-dispatch", "psn")


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--child":
        print(json.dumps(child(sys.argv[2], sys.argv[3], Path(sys.argv[4]))))
    else:
        unittest.main()

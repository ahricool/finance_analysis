# -*- coding: utf-8 -*-
"""Tests for the eastmoney requests patch: import safety and idempotent init."""

import unittest

import requests


class EastmoneyPatchTestCase(unittest.TestCase):
    def setUp(self) -> None:
        # Preserve global state so the monkey-patch does not leak into other tests.
        import finance_analysis.patches.eastmoney_patch as patch_module

        self._patch_module = patch_module
        self._original_request = requests.Session.request
        self._was_patched = patch_module._patch_sign.is_patched()

    def tearDown(self) -> None:
        requests.Session.request = self._original_request
        self._patch_module._patch_sign.set_patch(self._was_patched)

    def test_import_exposes_callable_patch(self) -> None:
        from finance_analysis.patches.eastmoney_patch import eastmoney_patch

        self.assertTrue(callable(eastmoney_patch))

    def test_repeated_initialization_is_idempotent(self) -> None:
        from finance_analysis.patches.eastmoney_patch import eastmoney_patch

        # Force a clean, unpatched starting state for a deterministic assertion.
        requests.Session.request = self._original_request
        self._patch_module._patch_sign.set_patch(False)

        eastmoney_patch()
        first_request = requests.Session.request
        self.assertTrue(self._patch_module._patch_sign.is_patched())
        self.assertIsNot(first_request, self._original_request)

        # Second call must be a no-op and must not re-wrap the session request.
        eastmoney_patch()
        self.assertIs(requests.Session.request, first_request)


if __name__ == "__main__":
    unittest.main()

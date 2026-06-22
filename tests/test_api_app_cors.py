# -*- coding: utf-8 -*-
"""Tests for FastAPI app CORS configuration."""

import os
import unittest
from unittest.mock import patch

from fastapi.middleware.cors import CORSMiddleware

from finance_analysis.interfaces.api.app import create_app


class AppCorsConfigTestCase(unittest.TestCase):
    """CORS configuration should stay browser-compatible."""

    def _build_app(self):
        return create_app()

    def test_allow_all_disables_credentials(self):
        with patch.dict(os.environ, {"CORS_ALLOW_ALL": "true"}, clear=False):
            app = self._build_app()

        cors = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
        self.assertEqual(cors.kwargs["allow_origins"], ["*"])
        self.assertFalse(cors.kwargs["allow_credentials"])

    def test_explicit_origin_list_keeps_credentials_enabled(self):
        with patch.dict(
            os.environ,
            {
                "CORS_ALLOW_ALL": "false",
                "CORS_ORIGINS": "http://dev.example.test,http://preview.example.test",
            },
            clear=False,
        ):
            app = self._build_app()

        cors = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
        self.assertIn("http://dev.example.test", cors.kwargs["allow_origins"])
        self.assertIn("http://preview.example.test", cors.kwargs["allow_origins"])
        self.assertTrue(cors.kwargs["allow_credentials"])


if __name__ == "__main__":
    unittest.main()

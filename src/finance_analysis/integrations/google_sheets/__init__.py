# -*- coding: utf-8 -*-
"""Google Sheets protocol: OAuth, encrypted tokens, and read-only spreadsheet access."""

from .client import GoogleSheetsClient, GoogleSheetsError, SheetBatch
from .config import SPREADSHEETS_READONLY_SCOPE, get_google_sheets_config, reset_google_sheets_config
from .oauth import GoogleOAuthError, GoogleOAuthService, GoogleTokens, OAuthState, new_code_verifier
from .spreadsheet import SpreadsheetIdError, parse_spreadsheet_id

__all__ = [
    "GoogleOAuthError",
    "GoogleOAuthService",
    "GoogleSheetsClient",
    "GoogleSheetsError",
    "GoogleTokens",
    "OAuthState",
    "SPREADSHEETS_READONLY_SCOPE",
    "SheetBatch",
    "SpreadsheetIdError",
    "get_google_sheets_config",
    "new_code_verifier",
    "parse_spreadsheet_id",
    "reset_google_sheets_config",
]

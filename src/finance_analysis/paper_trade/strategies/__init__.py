"""Independently maintained Demo strategy implementations."""

from . import perpetual_drive

WINDOW_STRATEGIES = {perpetual_drive.TYPE: perpetual_drive.evaluate}

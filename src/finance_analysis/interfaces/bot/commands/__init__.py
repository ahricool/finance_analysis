# -*- coding: utf-8 -*-
"""
===================================
命令处理器模块
===================================

包含所有机器人命令的实现。
"""

from finance_analysis.interfaces.bot.commands.base import BotCommand
from finance_analysis.interfaces.bot.commands.help import HelpCommand
from finance_analysis.interfaces.bot.commands.status import StatusCommand
from finance_analysis.interfaces.bot.commands.analyze import AnalyzeCommand
from finance_analysis.interfaces.bot.commands.market import MarketCommand
from finance_analysis.interfaces.bot.commands.batch import BatchCommand
from finance_analysis.interfaces.bot.commands.ask import AskCommand
from finance_analysis.interfaces.bot.commands.chat import ChatCommand
from finance_analysis.interfaces.bot.commands.research import ResearchCommand
from finance_analysis.interfaces.bot.commands.strategies import StrategiesCommand
from finance_analysis.interfaces.bot.commands.history import HistoryCommand

# All available commands (for auto-registration)
ALL_COMMANDS = [
    HelpCommand,
    StatusCommand,
    AnalyzeCommand,
    MarketCommand,
    BatchCommand,
    AskCommand,
    ChatCommand,
    ResearchCommand,
    StrategiesCommand,
    HistoryCommand,
]

__all__ = [
    'BotCommand',
    'HelpCommand',
    'StatusCommand',
    'AnalyzeCommand',
    'MarketCommand',
    'BatchCommand',
    'AskCommand',
    'ChatCommand',
    'ResearchCommand',
    'StrategiesCommand',
    'HistoryCommand',
    'ALL_COMMANDS',
]

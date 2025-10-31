# mcp/tools/registry.py
# -*- coding: utf-8 -*-
"""
Tool registry used by the MCP server (complete file).
"""

from __future__ import annotations

from typing import Dict, List

from .base import BaseTool, ToolExecutionError, ToolMetadata
from .schema import DescribeTableTool, ListTablesTool
from .contracts import ContractsSummaryTool, ContractsExpiringTool
from .backup import BackupJobsExpiringTool, BackupTapeSummaryTool
from .inventory import HardwareSummaryTool, SoftwareRenewalsTool
from .tickets import TicketQueueSummaryTool, TicketSlaAlertsTool
from .knowledge import KnowledgeCategorySummaryTool, KnowledgeRecentArticlesTool
from .address_book import AddressBookSearchTool, AddressBookSummaryTool
from .network import NetworkCapacitySummaryTool, NetworkHostSearchTool
from .tables import TableFetchTool, TableGetTool, TableSearchTool
from .temporal import TimeNowTool


def _build_tools() -> Dict[str, BaseTool]:
    tools: Dict[str, BaseTool] = {}

    # Schema discovery
    tools[ListTablesTool.name] = ListTablesTool()
    tools[DescribeTableTool.name] = DescribeTableTool()

    # Generic table access
    tools[TableFetchTool.name] = TableFetchTool()
    tools[TableGetTool.name] = TableGetTool()
    tools[TableSearchTool.name] = TableSearchTool()

    # Domain-specific summaries
    tools[ContractsSummaryTool.name] = ContractsSummaryTool()
    tools[ContractsExpiringTool.name] = ContractsExpiringTool()
    tools[BackupTapeSummaryTool.name] = BackupTapeSummaryTool()
    tools[BackupJobsExpiringTool.name] = BackupJobsExpiringTool()
    tools[HardwareSummaryTool.name] = HardwareSummaryTool()
    tools[SoftwareRenewalsTool.name] = SoftwareRenewalsTool()
    tools[TicketQueueSummaryTool.name] = TicketQueueSummaryTool()
    tools[TicketSlaAlertsTool.name] = TicketSlaAlertsTool()
    tools[KnowledgeRecentArticlesTool.name] = KnowledgeRecentArticlesTool()
    tools[KnowledgeCategorySummaryTool.name] = KnowledgeCategorySummaryTool()
    tools[AddressBookSearchTool.name] = AddressBookSearchTool()
    tools[AddressBookSummaryTool.name] = AddressBookSummaryTool()
    tools[NetworkCapacitySummaryTool.name] = NetworkCapacitySummaryTool()
    tools[NetworkHostSearchTool.name] = NetworkHostSearchTool()
    tools[TimeNowTool.name] = TimeNowTool()

    return tools


TOOLS: Dict[str, BaseTool] = _build_tools()


def list_tool_metadata() -> List[ToolMetadata]:
    return [tool.metadata() for tool in TOOLS.values()]


async def invoke_tool(name: str, arguments: dict) -> dict:
    tool = TOOLS.get(name)
    if not tool:
        raise ToolExecutionError(f"Unknown tool: {name}")
    result_model = await tool.invoke(arguments)
    return result_model.model_dump()

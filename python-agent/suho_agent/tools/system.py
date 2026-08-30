"""System information tools."""

from __future__ import annotations

from suho_agent.tools.base import Tool


class SystemInfoTool(Tool):
    name = "system.system_info"
    description = "Get OS, CPU, memory, and kernel information."
    category = "system"
    permission_level = "SAFE"
    parameters_schema = {"type": "object", "properties": {}}


class DiskUsageTool(Tool):
    name = "system.disk_usage"
    description = "Check disk usage for a path."
    category = "system"
    permission_level = "SAFE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "default": "/"},
        },
    }


class MemoryUsageTool(Tool):
    name = "system.memory_usage"
    description = "Get system memory usage statistics."
    category = "system"
    permission_level = "SAFE"
    parameters_schema = {"type": "object", "properties": {}}


class ProcessListTool(Tool):
    name = "system.process_list"
    description = "List running processes."
    category = "system"
    permission_level = "SAFE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "filter": {"type": "string", "description": "Filter by process name"},
        },
    }


class NetworkInfoTool(Tool):
    name = "system.network_info"
    description = "Get network interface information."
    category = "system"
    permission_level = "SAFE"
    parameters_schema = {"type": "object", "properties": {}}

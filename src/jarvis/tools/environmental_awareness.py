"""Tools for environmental awareness (system resources, network, calendar)."""

import os
import shutil
import sqlite3
import subprocess
import psutil
from typing import Any

def get_system_snapshot() -> dict[str, Any]:
    """Returns a snapshot of OS, hardware, and resource usage."""
    cpu_count = os.cpu_count()
    load_avg = os.getloadavg() if hasattr(os, 'getloadavg') else (0, 0, 0)
    mem = psutil.virtual_memory()
    disk = shutil.disk_usage("/")
    
    return {
        "os": os.name,
        "platform": str(subprocess.check_output(["uname", "-a"], text=True)).strip() if os.name != 'nt' else "Windows",
        "cpu_count": cpu_count,
        "load_average": load_avg,
        "memory": {
            "total": mem.total,
            "available": mem.available,
            "percent": mem.percent
        },
        "disk": {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free
        },
        "processes_count": len(psutil.pids())
    }

def get_network_status() -> dict[str, Any]:
    """Returns basic network status (interfaces, connectivity)."""
    # Simple connectivity check
    try:
        subprocess.check_call(["ping", "-c", "1", "8.8.8.8"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        internet = True
    except:
        internet = False
        
    return {
        "internet_reachable": internet,
        "interfaces": list(psutil.net_if_addrs().keys())
    }

def get_calendar_context(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """
    Mock calendar integration. 
    In a real scenario, this would query a calendar table or external API.
    For now, returns an empty list or placeholders.
    """
    # Placeholder for future calendar integration
    return []

def environmental_awareness_tool(conn: sqlite3.Connection, **kwargs) -> dict[str, Any]:
    """Main entry point for environmental awareness tool."""
    return {
        "system": get_system_snapshot(),
        "network": get_network_status(),
        "calendar": get_calendar_context(conn)
    }

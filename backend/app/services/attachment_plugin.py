"""Expose the personal attachment integration to plugin governance.

The generic chapter scheduler does not receive personal sessions or spending
capabilities; attachment operations stay in the authenticated import service.
"""
from types import SimpleNamespace

from app.source_plugins.models import PluginMetadata
from app.services.txtnovel_import import BASE, SOURCE_ID, SOURCE_NAME, txtnovel_import


def attachment_plugin():
    metadata = PluginMetadata.from_dict({
        "id": SOURCE_ID, "name": SOURCE_NAME, "version": "1.0.0", "type": "source",
        "author": "个人附件导入", "enabled": txtnovel_import.enabled,
        "domains": ["www.txtnovel.vip"], "baseUrls": [BASE],
        "capabilities": ["search", "full_book", "auth"],
        "auth": {"mode": "required", "personal": True},
        "content": {"access": "mixed", "category": "completed"},
        "tags": ["attachment", "personal-account"],
        "proxy": {"mode": "auto", "required": False}, "browser": {"mode": "none"},
    })
    return SimpleNamespace(metadata=metadata, capabilities=metadata.capabilities, source=txtnovel_import)


def management_plugins(scheduler):
    return {**scheduler._plugins, SOURCE_ID: attachment_plugin()}


def management_ping_scheduler(scheduler):
    return SimpleNamespace(_plugins=management_plugins(scheduler), config=scheduler.config)

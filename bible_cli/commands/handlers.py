"""Command handlers for top-level command groups."""

from __future__ import annotations

from argparse import Namespace
import json

from bible_cli.client.sync_http import SyncHTTPClient
from bible_cli.exceptions import CommandNotImplementedError
from bible_cli.utils.config import ClientConfig


class _BaseCommands:
    group_name: str
    client_config: ClientConfig
    client: SyncHTTPClient

    def __init__(self) -> None:
        self.client_config = ClientConfig.from_env()
        self.client = SyncHTTPClient(config=self.client_config.as_client_dict())    

    def execute(self, args: Namespace) -> int:
        action = getattr(args, "action", None) or "default"
        raise CommandNotImplementedError(f"{self.group_name} {action}".strip())


class HealthCommands(_BaseCommands):
    group_name = "health"

    def execute(self, args: Namespace) -> int:
        try:
            print(json.dumps(self.client.health(), ensure_ascii=True))
            return 0
        finally:
            self.client.close()


class SystemCommands(_BaseCommands):
    group_name = "system"

    def execute(self, args: Namespace) -> int:
        action = getattr(args, "action", None) or "default"
        try:
            if action == "status":
                print(json.dumps(self.client.status(), ensure_ascii=True))
                return 0
            if action == "info":
                print(json.dumps(self.client.info(), ensure_ascii=True))
                return 0
        finally:
            self.client.close()
        raise CommandNotImplementedError(f"{self.group_name} {action}".strip())


class KnowledgeCommands(_BaseCommands):
    group_name = "knowledge"

    def execute(self, args: Namespace) -> int:
        action = getattr(args, "action", None) or "default"
        try:
            if action == "list":
                print(json.dumps(self.client.knowledge_list(), ensure_ascii=True))
                return 0
            if action == "search":
                query = getattr(args, "query", None)
                print(json.dumps(self.client.knowledge_search(query=query), ensure_ascii=True))
                return 0
        finally:
            self.client.close()
        raise CommandNotImplementedError(f"{self.group_name} {action}".strip())


class MemoryCommands(_BaseCommands):
    group_name = "memory"


class SkillsCommands(_BaseCommands):
    group_name = "skills"

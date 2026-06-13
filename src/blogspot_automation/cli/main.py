from __future__ import annotations
import argparse
import json
import logging
from dataclasses import asdict

from blogspot_automation.app_logging import configure_logging
from blogspot_automation.config import get_settings
from blogspot_automation.storage import StateStore
from blogspot_automation.topic_discovery.service import discover_topics

logger = logging.getLogger(__name__)

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="blogauto", description="Blogspot automation CLI.")
    subparsers = parser.add_subparsers(dest="command")

    state_parser = subparsers.add_parser("state", help="State storage commands.")
    state_subparsers = state_parser.add_subparsers(dest="subcommand")
    state_subparsers.add_parser("init", help="Initialize local state store.")
    state_subparsers.add_parser("status", help="Show local state status.")

    subparsers.add_parser("discover-topics", help="Discover and save planned topic candidates.")
    subparsers.add_parser("list-planned-topics", help="List planned topic candidates.")
    
    show_topic_parser = subparsers.add_parser("show-topic", help="Show one discovered topic.")
    show_topic_parser.add_argument("--topic-id", required=True, dest="topic_id")

    return parser

def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level, settings.app_paths().logs_dir / "app")
    store = StateStore(settings)

    if args.command == "state" and getattr(args, "subcommand", "") == "init":
        store.initialize()
        logger.info("state store initialized")
        print(json.dumps(store.status_summary(), indent=2))
        return 0

    if args.command == "state" and getattr(args, "subcommand", "") == "status":
        print(json.dumps(store.status_summary(), indent=2))
        return 0

    if args.command == "discover-topics":
        result = discover_topics(store)
        print(json.dumps(asdict(result), indent=2))
        return 0

    if args.command == "list-planned-topics":
        planned_topics = store.list_planned_topics()
        print(json.dumps({"planned_topics": planned_topics, "count": len(planned_topics)}, indent=2, ensure_ascii=False))
        return 0

    if args.command == "show-topic":
        payload = store.get_topic_by_id(args.topic_id)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    parser.print_help()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

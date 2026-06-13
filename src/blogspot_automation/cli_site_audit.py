from __future__ import annotations

import argparse
import json

from blogspot_automation.services.site_audit_service import DEFAULT_SITEMAP_URL, audit_sitemap


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Blogspot sitemap URLs for cleanup candidates.")
    parser.add_argument("--sitemap-url", default=DEFAULT_SITEMAP_URL)
    parser.add_argument("--output-dir", default="runs/site_audit")
    parser.add_argument("--max-urls", type=int, default=500)
    args = parser.parse_args()

    result = audit_sitemap(
        sitemap_url=args.sitemap_url,
        output_dir=args.output_dir,
        max_urls=args.max_urls,
    )
    print(json.dumps({
        "summary": result.get("summary"),
        "json_path": result.get("json_path"),
        "markdown_path": result.get("markdown_path"),
        "csv_path": result.get("csv_path"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

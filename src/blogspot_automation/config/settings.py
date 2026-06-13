from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
import os
from urllib.parse import urlsplit, urlunsplit


def _load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(slots=True)
class AppPaths:
    root: Path
    contents_dir: Path
    images_dir: Path
    logs_dir: Path
    runs_dir: Path
    state_dir: Path
    sqlite_path: Path

    @classmethod
    def from_root(cls, root: Path, sqlite_path: str) -> "AppPaths":
        return cls(
            root=root,
            contents_dir=root / "contents",
            images_dir=root / "images",
            logs_dir=root / "logs",
            runs_dir=root / "runs",
            state_dir=root / "state",
            sqlite_path=root / sqlite_path,
        )


@dataclass(slots=True)
class Settings:
    app_env: str = "local"
    log_level: str = "INFO"
    data_dir: Path = Path(".").resolve()
    sqlite_path: str = "state/blogspot_automation.db"

    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_image_model: str = "gpt-image-1"
    google_ai_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash-lite"
    google_search_api_key: str | None = None
    google_search_cx: str | None = None
    enable_google_custom_search: bool = False
    naver_client_id: str | None = None
    naver_client_secret: str | None = None
    exa_api_key: str | None = None
    tavily_api_key: str | None = None
    firecrawl_api_key: str | None = None
    enable_naver_search: bool = False
    enable_naver_datalab: bool = False
    enable_tavily_search: bool = False
    enable_exa_search: bool = False
    enable_firecrawl_search: bool = False
    news_naver_search_types: str = "news,webkr"
    news_naver_max_requests: int = 18
    news_naver_display: int = 2
    news_naver_datalab_max_requests: int = 5
    news_tavily_max_requests: int = 3
    news_exa_max_requests: int = 1
    news_firecrawl_max_requests: int = 1
    imgbb_api_key: str | None = None
    enable_imgbb_upload: bool = False
    blogger_access_token: str | None = None
    blogger_client_id: str | None = None
    blogger_client_secret: str | None = None
    blogger_refresh_token: str | None = None
    blogger_blog_id: str | None = None
    blogger_dry_run: bool = False
    dry_run: bool = True
    auto_publish: bool = False
    news_publish_mode: str = "dry_run"
    news_mode: str = "news"
    news_excluded_query_groups: str = ""
    min_topic_score: int = 75
    topic_candidate_limit: int = 20
    dedup_days: int = 7
    title_candidate_count: int = 7
    runs_dir: str = "runs"
    naver_blog_url: str = "https://holyyomiai.blogspot.com/"

    def app_paths(self) -> AppPaths:
        return AppPaths.from_root(self.data_dir.resolve(), self.sqlite_path)

    def model_dump(self, mode: str = "python") -> dict[str, str | None]:
        del mode
        payload = asdict(self)
        payload["data_dir"] = str(self.data_dir)
        return payload

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv(Path(".env"))
        naver_client_id = os.getenv("NAVER_CLIENT_ID")
        naver_client_secret = os.getenv("NAVER_CLIENT_SECRET")
        exa_api_key = os.getenv("EXA_API_KEY")
        tavily_api_key = os.getenv("TAVILY_API_KEY")
        firecrawl_api_key = os.getenv("FIRECRAWL_API_KEY")
        return cls(
            app_env=os.getenv("APP_ENV", "local"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            data_dir=Path(os.getenv("DATA_DIR", ".")).resolve(),
            sqlite_path=os.getenv("SQLITE_PATH", "state/blogspot_automation.db"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
            openai_base_url=_normalize_openai_base_url(os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")),
            openai_image_model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
            google_ai_api_key=os.getenv("GOOGLE_AI_API_KEY"),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite"),
            google_search_api_key=os.getenv("GOOGLE_SEARCH_API_KEY"),
            google_search_cx=os.getenv("GOOGLE_SEARCH_CX"),
            enable_google_custom_search=os.getenv("ENABLE_GOOGLE_CUSTOM_SEARCH", "false").strip().lower()
            in {"1", "true", "yes", "on"},
            naver_client_id=naver_client_id,
            naver_client_secret=naver_client_secret,
            exa_api_key=exa_api_key,
            tavily_api_key=tavily_api_key,
            firecrawl_api_key=firecrawl_api_key,
            enable_naver_search=_env_bool(
                "ENABLE_NAVER_SEARCH",
                default=bool((naver_client_id or "").strip() and (naver_client_secret or "").strip()),
            ),
            enable_naver_datalab=_env_bool(
                "ENABLE_NAVER_DATALAB",
                default=bool((naver_client_id or "").strip() and (naver_client_secret or "").strip()),
            ),
            enable_tavily_search=_env_bool("ENABLE_TAVILY_SEARCH", default=bool((tavily_api_key or "").strip())),
            enable_exa_search=_env_bool("ENABLE_EXA_SEARCH", default=bool((exa_api_key or "").strip())),
            enable_firecrawl_search=_env_bool("ENABLE_FIRECRAWL_SEARCH", default=bool((firecrawl_api_key or "").strip())),
            news_naver_search_types=os.getenv("NEWS_NAVER_SEARCH_TYPES", "news,webkr"),
            news_naver_max_requests=_env_int("NEWS_NAVER_MAX_REQUESTS", 18),
            news_naver_display=_env_int("NEWS_NAVER_DISPLAY", 2),
            news_naver_datalab_max_requests=_env_int("NEWS_NAVER_DATALAB_MAX_REQUESTS", 5),
            news_tavily_max_requests=_env_int("NEWS_TAVILY_MAX_REQUESTS", 3),
            news_exa_max_requests=_env_int("NEWS_EXA_MAX_REQUESTS", 1),
            news_firecrawl_max_requests=_env_int("NEWS_FIRECRAWL_MAX_REQUESTS", 1),
            imgbb_api_key=os.getenv("IMGBB_API_KEY"),
            enable_imgbb_upload=os.getenv("ENABLE_IMGBB_UPLOAD", "false").lower() == "true",
            blogger_access_token=os.getenv("BLOGGER_ACCESS_TOKEN"),
            blogger_client_id=os.getenv("BLOGGER_CLIENT_ID"),
            blogger_client_secret=os.getenv("BLOGGER_CLIENT_SECRET"),
            blogger_refresh_token=os.getenv("BLOGGER_REFRESH_TOKEN"),
            blogger_blog_id=os.getenv("BLOGGER_BLOG_ID"),
            blogger_dry_run=os.getenv("BLOGGER_DRY_RUN", "false").lower() == "true",
            dry_run=os.getenv("DRY_RUN", "true").lower() == "true",
            auto_publish=os.getenv("AUTO_PUBLISH", "false").strip().lower() in {"1", "true", "yes", "on"},
            news_publish_mode=os.getenv("NEWS_PUBLISH_MODE", "dry_run").strip().lower() or "dry_run",
            news_mode=os.getenv("NEWS_MODE", "news"),
            news_excluded_query_groups=os.getenv("NEWS_EXCLUDED_QUERY_GROUPS", "").strip(),
            min_topic_score=int(os.getenv("MIN_TOPIC_SCORE", "75")),
            topic_candidate_limit=int(os.getenv("TOPIC_CANDIDATE_LIMIT", "20")),
            dedup_days=int(os.getenv("DEDUP_DAYS", "7")),
            title_candidate_count=int(os.getenv("TITLE_CANDIDATE_COUNT", "7")),
            runs_dir=os.getenv("RUNS_DIR", "runs"),
            naver_blog_url=os.getenv("NAVER_BLOG_URL", "https://holyyomiai.blogspot.com/"),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()


def _normalize_openai_base_url(value: str) -> str:
    raw = value.strip().rstrip("/")
    parsed = urlsplit(raw)
    path = parsed.path or ""
    if path == "/v1":
        return urlunsplit((parsed.scheme, parsed.netloc, "/v1", "", ""))
    if "/v1" in path:
        path = path[: path.index("/v1") + 3]
    else:
        path = "/v1"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default

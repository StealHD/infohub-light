"""Core data models for Horizon."""

from copy import deepcopy
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any, Union, Literal
from pydantic import BaseModel, HttpUrl, Field, field_validator, model_validator

from .rsshub import (
    DEFAULT_RSSHUB_BASE_URL,
    RSSHUB_PROVIDER,
    is_managed_rsshub_config,
    normalize_managed_rsshub_config,
    normalize_rsshub_base_url,
    rsshub_feed_url,
)

_ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_PREFIXES = ("sk-", "sk_", "AIza", "xai-", "gsk_", "hf_", "tp-")


class SourceType(str, Enum):
    """Supported information source types."""

    GITHUB = "github"
    HACKERNEWS = "hackernews"
    RSS = "rss"
    REDDIT = "reddit"
    TELEGRAM = "telegram"
    TWITTER = "twitter"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    OPENBB = "openbb"
    OSSINSIGHT = "ossinsight"


class ContentItem(BaseModel):
    """Unified content item model from any source."""

    id: str  # Format: {source}:{subtype}:{native_id}
    source_type: SourceType
    title: str
    url: HttpUrl
    content: Optional[str] = None
    author: Optional[str] = None
    published_at: datetime
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # AI analysis results
    ai_score: Optional[float] = None  # 0-10 importance score
    ai_reason: Optional[str] = None
    ai_summary: Optional[str] = None
    ai_summary_zh: Optional[str] = None
    ai_category: Optional[str] = None
    ai_is_featured: bool = False
    ai_action_suggestion: Optional[str] = None
    ai_tags: List[str] = Field(default_factory=list)
    ai_channel: Optional[str] = None
    ai_topics: List[str] = Field(default_factory=list)
    ai_signal_strength: Optional[str] = None
    ai_signal_type: Optional[str] = None
    ai_entities: List[str] = Field(default_factory=list)


class AIProvider(str, Enum):
    """Supported AI providers."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    AZURE = "azure"
    ALI = "ali"
    GEMINI = "gemini"
    DOUBAO = "doubao"
    MINIMAX = "minimax"
    DEEPSEEK = "deepseek"
    XIAOMI = "xiaomi"
    OLLAMA = "ollama"


class AIConfig(BaseModel):
    """AI client configuration."""

    enabled: bool = True
    provider: AIProvider
    model: str
    base_url: Optional[str] = None
    api_key_env: str
    temperature: float = 0.3
    max_tokens: int = 4096
    throttle_sec: float = 0.0
    analysis_concurrency: int = 1
    enrichment_concurrency: int = 1
    analysis_content_chars: int = Field(default=1000, ge=100, le=10000)
    analysis_comments_chars: int = Field(default=1500, ge=0, le=20000)
    summary_max_chars: int = Field(default=200, ge=100, le=500)
    analysis_max_output_tokens: int = Field(default=800, ge=256, le=2048)
    enrichment_content_chars: int = Field(default=4000, ge=500, le=30000)
    languages: List[str] = Field(default_factory=lambda: ["en"])
    # Azure OpenAI specific; required when provider == AZURE
    azure_endpoint_env: Optional[str] = None
    api_version: Optional[str] = None


class AnalysisMode(str, Enum):
    """How a source item should participate in AI analysis."""

    FULL = "full"
    PERSONAL_ONLY = "personal_only"


class RSSHubConfig(BaseModel):
    """Workspace RSSHub service connection."""

    base_url: str = DEFAULT_RSSHUB_BASE_URL

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return normalize_rsshub_base_url(value)


class ServiceSourceConfig(BaseModel):
    """Service catalog identity carried through source adapters."""

    source_id: Optional[str] = None
    subscription_id: Optional[str] = None
    source_key: Optional[str] = None
    source_display_name: Optional[str] = None
    catalog_source_type: Optional[str] = None
    analysis_mode: AnalysisMode = AnalysisMode.FULL
    source_priority: int = Field(default=0, ge=0, le=100)
    service_fetch_window_hours: Optional[int] = Field(
        default=None,
        ge=1,
        le=720,
        exclude=True,
    )


class GitHubSourceConfig(ServiceSourceConfig):
    """GitHub source configuration."""

    type: str  # "user_events", "repo_releases", etc.
    username: Optional[str] = None
    owner: Optional[str] = None
    repo: Optional[str] = None
    enabled: bool = True
    channel: Optional[str] = None
    topics: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    personal_tags: List[str] = Field(default_factory=list)


class HackerNewsConfig(ServiceSourceConfig):
    """Hacker News configuration."""

    enabled: bool = True
    fetch_top_stories: int = 30
    min_score: int = 100


class RSSSourceConfig(ServiceSourceConfig):
    """RSS feed source configuration."""

    name: str
    url: HttpUrl
    provider: str = "direct"
    site: Optional[str] = None
    route_key: Optional[str] = None
    params: Dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    category: Optional[str] = None
    channel: Optional[str] = None
    topics: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    personal_tags: List[str] = Field(default_factory=list)
    enforce_public_network: bool = False
    keep_latest_item: bool = False

    @model_validator(mode="after")
    def validate_provider_contract(self) -> "RSSSourceConfig":
        if self.provider == RSSHUB_PROVIDER:
            normalize_managed_rsshub_config(
                {
                    "provider": self.provider,
                    "site": self.site,
                    "route_key": self.route_key,
                    "params": self.params,
                }
            )
            return self
        if self.provider != "direct":
            raise ValueError("unsupported RSS provider")
        if self.site is not None or self.route_key is not None or self.params:
            raise ValueError("direct RSS cannot contain RSSHub route fields")
        return self


class RedditSubredditConfig(ServiceSourceConfig):
    """Configuration for monitoring a specific subreddit."""

    subreddit: str
    enabled: bool = True
    sort: str = "hot"  # hot, new, top, rising
    time_filter: str = (
        "day"  # hour, day, week, month, year, all (only for top/controversial)
    )
    fetch_limit: int = 25
    min_score: int = 10
    channel: Optional[str] = None
    topics: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    personal_tags: List[str] = Field(default_factory=list)


class RedditUserConfig(ServiceSourceConfig):
    """Configuration for monitoring a specific Reddit user."""

    username: str  # without u/ prefix
    enabled: bool = True
    sort: str = "new"
    fetch_limit: int = 10
    channel: Optional[str] = None
    topics: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    personal_tags: List[str] = Field(default_factory=list)


class RedditConfig(BaseModel):
    """Reddit source configuration."""

    enabled: bool = True
    subreddits: List[RedditSubredditConfig] = Field(default_factory=list)
    users: List[RedditUserConfig] = Field(default_factory=list)
    fetch_comments: int = 5  # top comments per post, 0 to disable


class TelegramChannelConfig(ServiceSourceConfig):
    """Configuration for monitoring a specific Telegram channel."""

    channel: str  # channel username, e.g. "zaihuapd"
    enabled: bool = True
    fetch_limit: int = 20
    hub_channel: Optional[str] = None
    topics: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    personal_tags: List[str] = Field(default_factory=list)


class TelegramConfig(BaseModel):
    """Telegram source configuration."""

    enabled: bool = True
    channels: List[TelegramChannelConfig] = Field(default_factory=list)


class TwitterConfig(ServiceSourceConfig):
    """Twitter source configuration via Apify."""

    enabled: bool = True
    apify_token_env: str = "APIFY_TOKEN"
    actor_id: str = "altimis~scweet"
    users: List[str] = Field(default_factory=list)
    fetch_limit: int = 10
    fetch_reply_text: bool = False
    max_replies_per_tweet: int = 3
    max_tweets_to_expand: int = 10
    reply_min_likes: int = 0


class ApifySocialPlatform(str, Enum):
    """Social platforms fetched through Apify actors."""

    X = "x"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    TELEGRAM = "telegram"


class ApifyActorConfig(BaseModel):
    """Apify actor selection for one social platform."""

    actor_id: str


class ApifySocialActorsConfig(BaseModel):
    """Default Apify actors used by the social source adapter."""

    x: ApifyActorConfig = Field(
        default_factory=lambda: ApifyActorConfig(actor_id="xquik/x-tweet-scraper")
    )
    instagram: ApifyActorConfig = Field(
        default_factory=lambda: ApifyActorConfig(actor_id="apify/instagram-api-scraper")
    )
    facebook: ApifyActorConfig = Field(
        default_factory=lambda: ApifyActorConfig(actor_id="whoareyouanas/facebook-group-scraper")
    )
    telegram: ApifyActorConfig = Field(
        default_factory=lambda: ApifyActorConfig(actor_id="thescrapelab/apify-telegram-scraper")
    )


class ApifySocialSubscriptionConfig(ServiceSourceConfig):
    """One public social subscription fetched through Apify."""

    platform: ApifySocialPlatform
    kind: str
    target: str
    token_env: Optional[str] = None
    fetch_limit: int = Field(default=20, ge=1, le=100)
    enabled: bool = True
    tags: List[str] = Field(default_factory=list)
    channel: Optional[str] = None
    topics: List[str] = Field(default_factory=list)
    personal_tags: List[str] = Field(default_factory=list)
    analysis_mode: AnalysisMode = AnalysisMode.FULL
    fetch_profile_details: bool = False

    @field_validator("token_env")
    @classmethod
    def validate_token_env(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        name = str(value).strip()
        if not name:
            return None
        if name.startswith(_SECRET_PREFIXES) or not _ENV_VAR_RE.fullmatch(name):
            raise ValueError("apify_social subscription token_env must be an environment variable name")
        return name

    @model_validator(mode="after")
    def validate_platform_kind(self) -> "ApifySocialSubscriptionConfig":
        allowed = {
            ApifySocialPlatform.X: {"profile", "keyword"},
            ApifySocialPlatform.INSTAGRAM: {"profile", "hashtag"},
            ApifySocialPlatform.FACEBOOK: {"page", "group", "post"},
            ApifySocialPlatform.TELEGRAM: {"channel"},
        }
        if self.kind not in allowed[self.platform]:
            allowed_values = ", ".join(sorted(allowed[self.platform]))
            raise ValueError(
                f"apify_social kind for {self.platform.value} must be one of {allowed_values}"
            )
        if not self.target.strip():
            raise ValueError("apify_social target cannot be empty")
        self.target = self.target.strip()
        return self


class ApifySocialConfig(BaseModel):
    """Unified Apify-backed social source configuration."""

    enabled: bool = False
    token_env: str = "APIFY_TOKEN"
    token_envs: List[str] = Field(default_factory=lambda: ["APIFY_TOKEN"])
    timeout_seconds: int = Field(default=180, ge=1, le=900)
    actors: ApifySocialActorsConfig = Field(default_factory=ApifySocialActorsConfig)
    subscriptions: List[ApifySocialSubscriptionConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_token_envs(self) -> "ApifySocialConfig":
        names: list[str] = []
        for raw in self.token_envs or []:
            name = str(raw).strip()
            if name and name not in names:
                names.append(name)
        primary = str(self.token_env or "").strip()
        if primary and primary not in names:
            names.insert(0, primary)
        if not names:
            names = ["APIFY_TOKEN"]
        self.token_env = names[0]
        self.token_envs = names
        return self


class OpenBBWatchlist(BaseModel):
    """A named watchlist of tickers fetched from one OpenBB provider.

    Each watchlist produces one news.company() call per run, so group
    symbols by provider rather than creating one watchlist per symbol.
    """

    name: str
    symbols: List[str] = Field(default_factory=list)
    enabled: bool = True
    provider: str = "yfinance"
    fetch_limit: int = 20
    category: Optional[str] = None
    channel: Optional[str] = None
    topics: List[str] = Field(default_factory=list)


class OpenBBConfig(ServiceSourceConfig):
    """OpenBB Platform source configuration.

    Uses the installed `openbb` SDK to fetch news and filings for a set of
    tickers. The SDK is an optional dependency; if it is not installed the
    scraper will no-op with a console warning rather than crash the run.

    Provider credentials (FMP, Benzinga, Polygon, Intrinio, Tiingo, etc.)
    are resolved by openbb from environment variables / its own user
    settings file, so Horizon does not need to pass them explicitly.
    """

    enabled: bool = True
    watchlists: List[OpenBBWatchlist] = Field(default_factory=list)
    fetch_filings: bool = False
    filings_provider: str = "sec"


class OSSInsightConfig(ServiceSourceConfig):
    """OSS Insight trending repos source configuration.

    Pulls top star-gain repositories from the OSS Insight public API and
    emits them as ContentItems. Optional `keywords` filter limits results
    to repos whose description, repo name, or collection names contain at
    least one of the listed substrings (case-insensitive). Leave
    `keywords` empty to ingest everything trending in the configured
    languages.
    """

    enabled: bool = False
    period: str = "past_24_hours"  # past_24_hours, past_28_days
    languages: List[str] = Field(
        default_factory=lambda: ["All", "Python", "TypeScript"]
    )
    keywords: List[str] = Field(default_factory=list)
    min_stars: int = 5
    max_items: int = 30


class SourcesConfig(BaseModel):
    """All sources configuration."""

    github: List[GitHubSourceConfig] = Field(default_factory=list)
    hackernews: HackerNewsConfig = Field(default_factory=HackerNewsConfig)
    rss: List[RSSSourceConfig] = Field(default_factory=list)
    reddit: RedditConfig = Field(default_factory=RedditConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    twitter: Optional[TwitterConfig] = None
    apify_social: ApifySocialConfig = Field(default_factory=ApifySocialConfig)
    openbb: Optional[OpenBBConfig] = None
    ossinsight: OSSInsightConfig = Field(default_factory=OSSInsightConfig)


class WebhookConfig(BaseModel):
    """Webhook notification configuration."""

    url_env: Optional[str] = (
        None  # Environment variable name containing the webhook URL
    )
    request_body: Optional[Union[str, dict, list]] = (
        None  # POST body: real JSON object or string with #{key} placeholders; if empty, will use GET
    )
    headers: Optional[str] = None  # Custom headers, "Key: Value" per line
    delivery: str = "summary"  # summary, or summary_and_items
    overview_position: str = "first"  # For summary_and_items: first, or last
    platform: str = "generic"  # generic, feishu, lark, dingtalk, slack, discord
    layout: str = "markdown"  # markdown, or collapsible
    fallback_layout: str = (
        "markdown"  # Layout to use when the requested layout is unsupported
    )
    languages: Optional[List[str]] = (
        None  # Optional language filter for webhook delivery; defaults to all AI languages
    )
    enabled: bool = False

    @field_validator("delivery")
    @classmethod
    def validate_delivery(cls, v: str) -> str:
        allowed = {"summary", "summary_and_items"}
        if v not in allowed:
            raise ValueError(f"webhook.delivery must be one of {allowed}, got '{v}'")
        return v

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        allowed = {"generic", "feishu", "lark", "dingtalk", "slack", "discord"}
        if v not in allowed:
            raise ValueError(f"webhook.platform must be one of {allowed}, got '{v}'")
        return v

    @field_validator("layout")
    @classmethod
    def validate_layout(cls, v: str) -> str:
        allowed = {"markdown", "collapsible"}
        if v not in allowed:
            raise ValueError(f"webhook.layout must be one of {allowed}, got '{v}'")
        return v

    @field_validator("fallback_layout")
    @classmethod
    def validate_fallback_layout(cls, v: str) -> str:
        allowed = {"markdown", "collapsible"}
        if v not in allowed:
            raise ValueError(
                f"webhook.fallback_layout must be one of {allowed}, got '{v}'"
            )
        return v

    @field_validator("overview_position")
    @classmethod
    def validate_overview_position(cls, v: str) -> str:
        allowed = {"first", "last"}
        if v not in allowed:
            raise ValueError(
                f"webhook.overview_position must be one of {allowed}, got '{v}'"
            )
        return v


class EmailConfig(BaseModel):
    """Email configuration for updates/subscriptions."""

    imap_server: str
    imap_port: int = 993
    imap_enabled: bool = True
    smtp_server: str
    smtp_port: int = 465
    smtp_username: Optional[str] = None
    email_address: str
    password_env: str = "EMAIL_PASSWORD"
    sender_name: str = "Horizon Daily"
    subscribe_keyword: str = "SUBSCRIBE"
    unsubscribe_keyword: str = "UNSUBSCRIBE"
    enabled: bool = False


class FilteringConfig(BaseModel):
    """Content filtering configuration."""

    ai_score_threshold: float = 7.0
    featured_score_threshold: float = 7.5
    daily_push_score_threshold: float = 8.5
    daily_push_limit: int = 10
    homepage_min_score: float = 6.0
    time_window_hours: int = 24
    feed_window_days: Literal[7, 14, 30] = 7
    rss_initial_fetch_window_hours: Literal[168, 720] = 168
    recent_item_limit: int = 20

    @field_validator("feed_window_days", mode="before")
    @classmethod
    def validate_feed_window_days(cls, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("feed_window_days must be the integer 7, 14, or 30")
        if value not in {7, 14, 30}:
            raise ValueError("feed_window_days must be the integer 7, 14, or 30")
        return value

    @field_validator("rss_initial_fetch_window_hours", mode="before")
    @classmethod
    def validate_rss_initial_fetch_window_hours(cls, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                "rss_initial_fetch_window_hours must be the integer 168 or 720"
            )
        return value


class PremiumAnalysisConfig(BaseModel):
    """Optional high-score article deep storage/fetch configuration."""

    enabled: bool = False
    full_fetch_score_threshold: float = Field(default=8.5, ge=0, le=10)
    max_full_fetch_per_run: int = Field(default=10, ge=0, le=100)
    max_full_text_chars: int = Field(default=12000, ge=1000, le=50000)
    full_fetch_concurrency: int = Field(default=2, ge=1, le=10)
    keep_premium_articles: int = Field(default=1000, ge=10, le=100000)
    keep_full_text_days: int = Field(default=90, ge=1, le=3650)


class ArticleGraphConfig(BaseModel):
    """Optional low-cost relationship graph for premium articles."""

    enabled: bool = False
    premium_score_threshold: float = Field(default=8.5, ge=0, le=10)
    active_window_days: int = Field(default=30, ge=1, le=3650)
    extended_window_days: int = Field(default=90, ge=1, le=3650)
    max_active_nodes: int = Field(default=300, ge=1, le=5000)
    max_visible_nodes: int = Field(default=30, ge=1, le=300)
    max_visible_edges: int = Field(default=100, ge=0, le=1000)
    relation_top_k: int = Field(default=3, ge=1, le=20)
    min_relation_score: float = Field(default=0.55, ge=0, le=1)
    strong_relation_score: float = Field(default=0.75, ge=0, le=1)
    snapshot_min_new_premium_articles: int = Field(default=3, ge=0, le=100)
    snapshot_max_age_hours: int = Field(default=6, ge=1, le=168)
    enable_embedding: bool = False
    enable_ai_group_summary: bool = False


class Config(BaseModel):
    """Main configuration model."""

    version: str = "1.0"
    ai: AIConfig
    rsshub: RSSHubConfig = Field(default_factory=RSSHubConfig)
    sources: SourcesConfig
    filtering: FilteringConfig
    tags: List[str] = Field(default_factory=list)
    personal_tags: List[str] = Field(default_factory=list)
    premium_analysis: PremiumAnalysisConfig = Field(default_factory=PremiumAnalysisConfig)
    article_graph: ArticleGraphConfig = Field(default_factory=ArticleGraphConfig)
    email: Optional[EmailConfig] = None
    webhook: Optional[WebhookConfig] = None

    @model_validator(mode="before")
    @classmethod
    def resolve_managed_rsshub_sources(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = deepcopy(value)
        rsshub = data.get("rsshub")
        if rsshub is None:
            rsshub = {}
        if not isinstance(rsshub, dict):
            raise ValueError("rsshub must be an object")
        base_url = normalize_rsshub_base_url(
            rsshub.get("base_url", DEFAULT_RSSHUB_BASE_URL)
        )
        data["rsshub"] = {**rsshub, "base_url": base_url}
        sources = data.get("sources")
        rss_sources = sources.get("rss") if isinstance(sources, dict) else None
        if not isinstance(rss_sources, list):
            return data
        for index, source in enumerate(rss_sources):
            if not is_managed_rsshub_config(source):
                continue
            normalized = normalize_managed_rsshub_config(source)
            normalized["url"] = rsshub_feed_url(base_url, normalized)
            normalized["name"] = str(
                normalized.get("name")
                or source.get("source_display_name")
                or normalize_managed_rsshub_config(source)["url"]
            )
            normalized["enforce_public_network"] = False
            rss_sources[index] = normalized
        return data

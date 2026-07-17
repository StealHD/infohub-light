"""Source catalog type metadata and validation.

The catalog stores only non-secret source configuration plus a secret
environment variable reference. This module keeps those contracts in one place
so API writes, config imports, and worker payloads use the same rules.
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlparse

from ..security import (
    public_data_contains_credentials,
    url_contains_credentials,
)


_ENV_VAR_RE = re.compile(r"^[A-Z_][A-Z0-9_]{1,127}$")
_SECRET_PREFIXES = ("sk-", "sk_", "AIza", "xai-", "gsk_", "hf_", "tp-")
SUPPORTED_GUIDE_LOCALES = ("zh-CN", "en")
_FORBIDDEN_AGENT_CONFIG_KEYS = {
    "secret",
    "secret_env",
    "token",
    "token_env",
    "api_key",
    "password",
    "cookie",
    "cookies",
    "authorization",
    "headers",
}
_CREDENTIAL_ERROR = "credentials are not accepted; configure secrets in Web"
_UNSUPPORTED_SOURCE_TYPE_ERROR = "unsupported source type"
_SOURCE_REQUIRES_WEB_SETUP_ERROR = "source_requires_web_setup"
_OPAQUE_CATALOG_DISPLAY_NAME = "Web-managed source"
_OPAQUE_CATALOG_PUBLIC_TARGET = "web_setup_required"
_SUPPORTED_REDDIT_SORTS = {"hot", "new", "top", "rising", "controversial"}
_SUPPORTED_REDDIT_TIME_FILTERS = {"hour", "day", "week", "month", "year", "all"}
_APIFY_KINDS = {
    "x": {"profile", "keyword"},
    "instagram": {"profile", "hashtag"},
    "facebook": {"page", "group", "post"},
    "telegram": {"channel"},
}


class SourceConfigError(ValueError):
    """Raised when a catalog source config is invalid."""


@dataclass(frozen=True)
class SourceFieldDefinition:
    """Safe UI metadata for one non-secret source configuration field."""

    name: str
    label: str
    input_type: str
    required: bool
    default: Any
    options: tuple[Any, ...]
    minimum: int | None
    maximum: int | None
    help: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "input_type": self.input_type,
            "required": self.required,
            "default": self.default,
            "options": list(self.options),
            "min": self.minimum,
            "max": self.maximum,
            "help": self.help,
        }


@dataclass(frozen=True)
class SourceTypeDefinition:
    type: str
    label: str
    description: str
    required_fields: tuple[str, ...]
    template: dict[str, Any]
    fields: tuple[SourceFieldDefinition, ...]
    supports_secret_env: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "label": self.label,
            "description": self.description,
            "required_fields": list(self.required_fields),
            "template": dict(self.template),
            "fields": [field.as_dict() for field in self.fields],
            "supports_secret_env": self.supports_secret_env,
        }

    def guide_summary(self, locale: str) -> dict[str, Any]:
        """Return safe, localized setup summary for an agent-facing flow."""

        copy = _GUIDE_METADATA[self.type][_guide_locale(locale)]
        return {
            "type": self.type,
            "label": copy["label"],
            "description": copy["description"],
            "self_service": copy["self_service"],
            "requires_web_setup": copy["requires_web_setup"],
        }

    def guide_detail(self, locale: str) -> dict[str, Any]:
        """Return safe, localized setup instructions without secret controls."""

        copy = _GUIDE_METADATA[self.type][_guide_locale(locale)]
        result = self.guide_summary(locale) | {
            "required_fields": list(self.required_fields),
            "fields": [],
            "web_setup_note": copy["web_setup_note"],
        }
        for field in self.fields:
            field_copy = copy["fields"][field.name]
            result["fields"].append(
                field.as_dict()
                | {
                    "label": field_copy["label"],
                    "help": field_copy["help"],
                    "accepted_formats": list(field_copy["accepted_formats"]),
                    "examples": list(field_copy["examples"]),
                    "how_to_find": field_copy["how_to_find"],
                }
            )
        return result


@dataclass(frozen=True)
class AgentSourceTypeDefinition:
    """Public Agent setup type mapped to one catalog storage type.

    Agent setup uses a deliberately smaller, user-facing taxonomy than the
    REST catalog.  The mapping is kept here so callers never need to infer a
    catalog type from a displayed label.
    """

    type: str
    catalog_source_type: str
    required_fields: tuple[str, ...]
    fields: tuple[SourceFieldDefinition, ...]
    guide_metadata: dict[str, dict[str, Any]]

    def execution_policy(self) -> dict[str, Any]:
        """Return the operation boundary that normalization consumers must obey."""

        metadata = self.guide_metadata["en"]
        self_service = bool(metadata["self_service"])
        policy = {
            "resolution_mode": (
                "create_or_existing" if self_service else "existing_visible_only"
            ),
            "self_service": self_service,
            "requires_web_setup": bool(metadata["requires_web_setup"]),
        }
        if self.type in {"rss", "website"}:
            # Agent-created URLs must retain the public-network fetch path even
            # when the eventual source owner is an owner or administrator.
            policy["public_network_only"] = True
        return policy

    def guide_summary(self, locale: str) -> dict[str, Any]:
        copy = self.guide_metadata[_guide_locale(locale)]
        return {
            "type": self.type,
            "label": copy["label"],
            "description": copy["description"],
            "self_service": copy["self_service"],
            "requires_web_setup": copy["requires_web_setup"],
            "required_fields": list(self.required_fields),
        }

    def guide_detail(self, locale: str) -> dict[str, Any]:
        copy = self.guide_metadata[_guide_locale(locale)]
        result = self.guide_summary(locale) | {
            "required_fields": list(self.required_fields),
            "fields": [],
            "web_setup_note": copy["web_setup_note"],
        }
        for field in self.fields:
            field_copy = copy["fields"][field.name]
            result["fields"].append(
                field.as_dict()
                | {
                    "label": field_copy["label"],
                    "help": field_copy["help"],
                    "accepted_formats": list(field_copy["accepted_formats"]),
                    "examples": list(field_copy["examples"]),
                    "how_to_find": field_copy["how_to_find"],
                }
            )
        return result


def _field(
    name: str,
    label: str,
    input_type: str,
    *,
    required: bool = False,
    default: Any = None,
    options: tuple[Any, ...] = (),
    minimum: int | None = None,
    maximum: int | None = None,
    help: str,
) -> SourceFieldDefinition:
    return SourceFieldDefinition(
        name=name,
        label=label,
        input_type=input_type,
        required=required,
        default=default,
        options=options,
        minimum=minimum,
        maximum=maximum,
        help=help,
    )


_SOURCE_TYPES: tuple[SourceTypeDefinition, ...] = (
    SourceTypeDefinition(
        type="rss",
        label="RSS/Atom",
        description="Direct RSS or Atom feed URL.",
        required_fields=("url",),
        template={"name": "Example Feed", "url": "https://example.com/feed.xml"},
        fields=(
            _field(
                "url",
                "Feed URL",
                "url",
                required=True,
                help="HTTP or HTTPS RSS/Atom URL without embedded credentials.",
            ),
            _field(
                "name",
                "Feed name",
                "text",
                help="Optional display name; the feed URL is used when omitted.",
            ),
            _field(
                "keep_latest_item",
                "Keep latest item",
                "boolean",
                default=False,
                help="When the time window is empty, return and retain the newest dated feed item.",
            ),
        ),
        supports_secret_env=True,
    ),
    SourceTypeDefinition(
        type="github_release",
        label="GitHub Releases",
        description="Repository release feed from the GitHub REST API.",
        required_fields=("owner", "repo"),
        template={"owner": "openai", "repo": "codex"},
        fields=(
            _field(
                "owner",
                "Repository owner",
                "text",
                required=True,
                help="GitHub organization or account name.",
            ),
            _field(
                "repo",
                "Repository",
                "text",
                required=True,
                help="GitHub repository name without the owner prefix.",
            ),
        ),
        supports_secret_env=True,
    ),
    SourceTypeDefinition(
        type="github_user",
        label="GitHub User Events",
        description="Public GitHub user activity events.",
        required_fields=("username",),
        template={"username": "openai"},
        fields=(
            _field(
                "username",
                "Username",
                "text",
                required=True,
                help="Public GitHub account name.",
            ),
        ),
        supports_secret_env=True,
    ),
    SourceTypeDefinition(
        type="reddit_subreddit",
        label="Reddit Subreddit",
        description="Public subreddit posts through Reddit JSON endpoints.",
        required_fields=("subreddit",),
        template={"subreddit": "LocalLLaMA", "sort": "hot"},
        fields=(
            _field(
                "subreddit",
                "Subreddit",
                "text",
                required=True,
                help="Subreddit name, with or without the r/ prefix.",
            ),
            _field(
                "sort",
                "Sort",
                "select",
                default="hot",
                options=("hot", "new", "top", "rising", "controversial"),
                help="Reddit listing order.",
            ),
            _field(
                "time_filter",
                "Time filter",
                "select",
                default="day",
                options=("hour", "day", "week", "month", "year", "all"),
                help="Time range used by Reddit ranking modes.",
            ),
            _field(
                "fetch_limit",
                "Fetch limit",
                "number",
                default=25,
                minimum=1,
                maximum=100,
                help="Maximum posts requested per fetch.",
            ),
            _field(
                "min_score",
                "Minimum score",
                "number",
                default=10,
                minimum=0,
                help="Discard posts below this Reddit score.",
            ),
        ),
    ),
    SourceTypeDefinition(
        type="reddit_user",
        label="Reddit User",
        description="Public Reddit user posts.",
        required_fields=("username",),
        template={"username": "spez", "sort": "new"},
        fields=(
            _field(
                "username",
                "Username",
                "text",
                required=True,
                help="Reddit account name, with or without the u/ prefix.",
            ),
            _field(
                "sort",
                "Sort",
                "select",
                default="new",
                options=("hot", "new", "top", "rising", "controversial"),
                help="Reddit listing order.",
            ),
            _field(
                "fetch_limit",
                "Fetch limit",
                "number",
                default=10,
                minimum=1,
                maximum=100,
                help="Maximum posts requested per fetch.",
            ),
        ),
    ),
    SourceTypeDefinition(
        type="telegram_channel",
        label="Telegram Public Channel",
        description="Public Telegram channel web preview.",
        required_fields=("channel",),
        template={"channel": "durov"},
        fields=(
            _field(
                "channel",
                "Channel",
                "text",
                required=True,
                help="Public Telegram channel name, with or without @.",
            ),
            _field(
                "fetch_limit",
                "Fetch limit",
                "number",
                default=20,
                minimum=1,
                maximum=100,
                help="Maximum channel posts requested per fetch.",
            ),
        ),
    ),
    SourceTypeDefinition(
        type="apify_social",
        label="Apify Social",
        description="Apify-backed public social target.",
        required_fields=("platform", "kind", "target"),
        template={"platform": "x", "kind": "profile", "target": "openai"},
        fields=(
            _field(
                "platform",
                "Platform",
                "select",
                required=True,
                options=("x", "instagram", "facebook", "telegram"),
                help="Social platform handled by the Apify source.",
            ),
            _field(
                "kind",
                "Target kind",
                "select",
                required=True,
                options=(
                    "profile",
                    "keyword",
                    "hashtag",
                    "page",
                    "group",
                    "post",
                    "channel",
                ),
                help="Target kind; available values depend on the selected platform.",
            ),
            _field(
                "target",
                "Target",
                "text",
                required=True,
                help=(
                    "Public profile, keyword, hashtag, page, group, post, "
                    "or channel identifier."
                ),
            ),
            _field(
                "fetch_limit",
                "Fetch limit",
                "number",
                default=20,
                minimum=1,
                maximum=100,
                help="Maximum social items requested per fetch.",
            ),
            _field(
                "analysis_mode",
                "Analysis mode",
                "select",
                default="full",
                options=("full", "personal_only"),
                help="Choose normal analysis or personal-only collection.",
            ),
        ),
        supports_secret_env=True,
    ),
    SourceTypeDefinition(
        type="hackernews",
        label="Hacker News",
        description="Hacker News top stories from the public Firebase API.",
        required_fields=(),
        template={"fetch_top_stories": 30, "min_score": 100},
        fields=(
            _field(
                "fetch_top_stories",
                "Top stories to fetch",
                "number",
                default=30,
                minimum=1,
                maximum=500,
                help="Number of top-story identifiers requested before filtering.",
            ),
            _field(
                "min_score",
                "Minimum score",
                "number",
                default=100,
                minimum=0,
                help="Discard stories below this Hacker News score.",
            ),
        ),
    ),
)

_BY_TYPE = {item.type: item for item in _SOURCE_TYPES}


def _guide_locale(locale: str) -> str:
    return locale if locale in SUPPORTED_GUIDE_LOCALES else "en"


def _guide_field(
    en_label: str,
    zh_label: str,
    en_help: str,
    zh_help: str,
    en_formats: tuple[str, ...],
    zh_formats: tuple[str, ...],
    en_examples: tuple[str, ...],
    zh_examples: tuple[str, ...],
    en_how_to_find: str,
    zh_how_to_find: str,
) -> dict[str, dict[str, Any]]:
    return {
        "en": {
            "label": en_label,
            "help": en_help,
            "accepted_formats": en_formats,
            "examples": en_examples,
            "how_to_find": en_how_to_find,
        },
        "zh-CN": {
            "label": zh_label,
            "help": zh_help,
            "accepted_formats": zh_formats,
            "examples": zh_examples,
            "how_to_find": zh_how_to_find,
        },
    }


def _guide_source(
    en_label: str,
    zh_label: str,
    en_description: str,
    zh_description: str,
    *,
    self_service: bool,
    requires_web_setup: bool,
    en_web_setup_note: str,
    zh_web_setup_note: str,
    fields: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    return {
        "en": {
            "label": en_label,
            "description": en_description,
            "self_service": self_service,
            "requires_web_setup": requires_web_setup,
            "web_setup_note": en_web_setup_note,
            "fields": {name: copy["en"] for name, copy in fields.items()},
        },
        "zh-CN": {
            "label": zh_label,
            "description": zh_description,
            "self_service": self_service,
            "requires_web_setup": requires_web_setup,
            "web_setup_note": zh_web_setup_note,
            "fields": {name: copy["zh-CN"] for name, copy in fields.items()},
        },
    }


_GUIDE_METADATA: dict[str, dict[str, dict[str, Any]]] = {
    "rss": _guide_source(
        "RSS/Atom",
        "RSS/Atom 订阅",
        "Add a public RSS or Atom feed URL.",
        "添加公开的 RSS 或 Atom 订阅地址。",
        self_service=True,
        requires_web_setup=False,
        en_web_setup_note="Authenticated feeds must be configured in Web.",
        zh_web_setup_note="需要登录或授权的订阅请在 Web 中配置。",
        fields={
            "url": _guide_field(
                "Feed URL", "订阅地址",
                "Use a public HTTP or HTTPS RSS/Atom URL.", "请输入公开的 HTTP 或 HTTPS RSS/Atom 地址。",
                ("https://host/path.xml",), ("https://域名/路径.xml",),
                ("https://example.com/feed.xml",), ("https://example.com/feed.xml",),
                "Copy the feed link from the publisher's RSS page.", "从发布者的 RSS 页面复制订阅链接。",
            ),
            "name": _guide_field(
                "Feed name", "订阅名称",
                "Optional display name.", "可选的显示名称。",
                ("plain text",), ("普通文本",),
                ("Example Feed",), ("示例订阅",),
                "Use a short name that helps you recognize the feed.", "填写便于识别的简短名称。",
            ),
            "keep_latest_item": _guide_field(
                "Keep latest item", "保留最新内容",
                "When no item is in the time window, keep the newest dated item.", "时间窗口内没有内容时，保留最新的带日期内容。",
                ("true or false",), ("true 或 false",),
                ("false",), ("false",),
                "Leave the default unless you need the newest item retained.", "通常保持默认；需要保留最新内容时再开启。",
            ),
        },
    ),
    "github_release": _guide_source(
        "GitHub Releases",
        "GitHub 发布版本",
        "Follow releases from a public GitHub repository.",
        "关注公开 GitHub 仓库的发布版本。",
        self_service=True,
        requires_web_setup=False,
        en_web_setup_note="Private or authenticated repositories must be configured in Web.",
        zh_web_setup_note="私有或需要授权的仓库请在 Web 中配置。",
        fields={
            "owner": _guide_field(
                "Repository owner", "仓库所有者",
                "GitHub organization or account name.", "GitHub 组织或账号名称。",
                ("owner",), ("所有者",), ("openai",), ("openai",),
                "Use the first segment of owner/repository.", "使用 owner/repository 中的第一段。",
            ),
            "repo": _guide_field(
                "Repository", "仓库名称",
                "Repository name without the owner prefix.", "不含所有者前缀的仓库名称。",
                ("repository",), ("仓库名",), ("codex",), ("codex",),
                "Use the second segment of owner/repository.", "使用 owner/repository 中的第二段。",
            ),
        },
    ),
    "github_user": _guide_source(
        "GitHub User Events",
        "GitHub 用户动态",
        "Follow public activity from a GitHub account.",
        "关注 GitHub 账号的公开动态。",
        self_service=True,
        requires_web_setup=False,
        en_web_setup_note="Accounts requiring authenticated access must be configured in Web.",
        zh_web_setup_note="需要授权访问的账号请在 Web 中配置。",
        fields={
            "username": _guide_field(
                "Username", "用户名",
                "Public GitHub account name.", "公开 GitHub 账号名称。",
                ("username", "https://github.com/username"), ("用户名", "https://github.com/用户名"),
                ("openai", "https://github.com/openai"), ("openai", "https://github.com/openai"),
                "Copy the account name from its public GitHub profile URL.", "从公开 GitHub 主页地址中复制账号名称。",
            ),
        },
    ),
    "reddit_subreddit": _guide_source(
        "Reddit Subreddit",
        "Reddit 社区",
        "Follow posts from a public Reddit community.",
        "关注公开 Reddit 社区的帖子。",
        self_service=True,
        requires_web_setup=False,
        en_web_setup_note="Only public communities are supported.",
        zh_web_setup_note="仅支持公开社区。",
        fields={
            "subreddit": _guide_field(
                "Subreddit", "社区名称",
                "A public subreddit name or URL.", "公开的 subreddit 名称或网址。",
                ("name", "r/name", "https://reddit.com/r/name"), ("名称", "r/名称", "公开社区网址"),
                ("LocalLLaMA", "r/LocalLLaMA", "https://reddit.com/r/LocalLLaMA"), ("LocalLLaMA", "r/LocalLLaMA", "https://reddit.com/r/LocalLLaMA"),
                "Copy the community name from its public Reddit page.", "从公开 Reddit 社区页面复制名称。",
            ),
            "sort": _guide_field(
                "Sort", "排序方式", "Reddit listing order.", "Reddit 帖子列表排序方式。",
                ("hot", "new", "top", "rising", "controversial"), ("hot", "new", "top", "rising", "controversial"),
                ("hot",), ("hot",), "Choose how posts are listed.", "选择帖子列表的排序方式。",
            ),
            "time_filter": _guide_field(
                "Time filter", "时间范围", "Time range for ranking modes.", "排名模式使用的时间范围。",
                ("hour", "day", "week", "month", "year", "all"), ("hour", "day", "week", "month", "year", "all"),
                ("day",), ("day",), "Use the range required for your ranking view.", "按需要选择排名的时间范围。",
            ),
            "fetch_limit": _guide_field(
                "Fetch limit", "抓取数量", "Maximum posts per fetch.", "每次最多抓取的帖子数。",
                ("integer from 1 to 100",), ("1 到 100 的整数",), ("25",), ("25",),
                "Use a smaller value for a narrower feed.", "希望内容更精简时使用较小数值。",
            ),
            "min_score": _guide_field(
                "Minimum score", "最低评分", "Discard posts below this score.", "过滤低于该评分的帖子。",
                ("non-negative integer",), ("非负整数",), ("10",), ("10",),
                "Choose the minimum score you consider useful.", "填写你认为有价值的最低评分。",
            ),
        },
    ),
    "reddit_user": _guide_source(
        "Reddit User",
        "Reddit 用户",
        "Follow posts from a public Reddit user.",
        "关注公开 Reddit 用户的帖子。",
        self_service=True,
        requires_web_setup=False,
        en_web_setup_note="Only public user posts are supported.",
        zh_web_setup_note="仅支持公开用户帖子。",
        fields={
            "username": _guide_field(
                "Username", "用户名", "Public Reddit account name.", "公开 Reddit 账号名称。",
                ("name", "u/name", "https://reddit.com/u/name"), ("名称", "u/名称", "公开用户网址"),
                ("spez", "u/spez", "https://reddit.com/u/spez"), ("spez", "u/spez", "https://reddit.com/u/spez"),
                "Copy the name from the user's public Reddit page.", "从用户公开 Reddit 页面复制名称。",
            ),
            "sort": _guide_field(
                "Sort", "排序方式", "Reddit listing order.", "Reddit 帖子列表排序方式。",
                ("hot", "new", "top", "rising", "controversial"), ("hot", "new", "top", "rising", "controversial"),
                ("new",), ("new",), "Choose how posts are listed.", "选择帖子列表的排序方式。",
            ),
            "fetch_limit": _guide_field(
                "Fetch limit", "抓取数量", "Maximum posts per fetch.", "每次最多抓取的帖子数。",
                ("integer from 1 to 100",), ("1 到 100 的整数",), ("10",), ("10",),
                "Use a smaller value for a narrower feed.", "希望内容更精简时使用较小数值。",
            ),
        },
    ),
    "telegram_channel": _guide_source(
        "Telegram Public Channel",
        "Telegram 公开频道",
        "Follow a public Telegram channel.",
        "关注公开 Telegram 频道。",
        self_service=True,
        requires_web_setup=False,
        en_web_setup_note="Private channels must be configured in Web.",
        zh_web_setup_note="私有频道请在 Web 中配置。",
        fields={
            "channel": _guide_field(
                "Channel", "频道名称", "Public Telegram channel name or URL.", "公开 Telegram 频道名称或网址。",
                ("name", "@name", "https://t.me/name"), ("名称", "@名称", "公开频道网址"),
                ("durov", "@durov", "https://t.me/durov"), ("durov", "@durov", "https://t.me/durov"),
                "Copy the final path segment from the public channel URL.", "从公开频道网址中复制最后一段名称。",
            ),
            "fetch_limit": _guide_field(
                "Fetch limit", "抓取数量", "Maximum channel posts per fetch.", "每次最多抓取的频道帖子数。",
                ("integer from 1 to 100",), ("1 到 100 的整数",), ("20",), ("20",),
                "Use a smaller value for a narrower feed.", "希望内容更精简时使用较小数值。",
            ),
        },
    ),
    "apify_social": _guide_source(
        "Apify Social",
        "Apify 社交来源",
        "A preconfigured public social target.",
        "预先配置好的公开社交目标。",
        self_service=False,
        requires_web_setup=True,
        en_web_setup_note="Subscribe to a visible preconfigured source or use Web to request setup.",
        zh_web_setup_note="请订阅可见的预配置来源，或在 Web 中申请配置。",
        fields={
            "platform": _guide_field(
                "Platform", "平台", "Social platform for the preconfigured target.", "预配置目标所在的社交平台。",
                ("x", "instagram", "facebook", "telegram"), ("x", "instagram", "facebook", "telegram"),
                ("x",), ("x",), "Use the platform shown by the visible source.", "使用可见来源显示的平台。",
            ),
            "kind": _guide_field(
                "Target kind", "目标类型", "Target category available for the platform.", "该平台支持的目标类别。",
                ("profile", "keyword", "hashtag", "page", "group", "post", "channel"), ("profile", "keyword", "hashtag", "page", "group", "post", "channel"),
                ("profile",), ("profile",), "Use the target kind shown by the visible source.", "使用可见来源显示的目标类型。",
            ),
            "target": _guide_field(
                "Target", "目标", "Public profile, keyword, hashtag, page, group, post, or channel identifier.", "公开 profile、keyword、hashtag、page、group、post 或 channel 标识。",
                ("public identifier",), ("公开标识",), ("openai",), ("openai",),
                "Use the target shown by the visible source.", "使用可见来源显示的目标。",
            ),
            "fetch_limit": _guide_field(
                "Fetch limit", "抓取数量", "Maximum social items per fetch.", "每次最多抓取的社交内容数。",
                ("integer from 1 to 100",), ("1 到 100 的整数",), ("20",), ("20",),
                "Use the value approved for the preconfigured source.", "使用预配置来源允许的数值。",
            ),
            "analysis_mode": _guide_field(
                "Analysis mode", "分析模式", "Choose normal analysis or personal-only collection.", "选择常规分析或仅个人收集。",
                ("full", "personal_only"), ("full", "personal_only"), ("full",), ("full",),
                "Use personal_only when the item should skip shared analysis.", "需要跳过共享分析时使用 personal_only。",
            ),
        },
    ),
    "hackernews": _guide_source(
        "Hacker News",
        "Hacker News",
        "Follow the public Hacker News top stories.",
        "关注公开 Hacker News 热门内容。",
        self_service=True,
        requires_web_setup=False,
        en_web_setup_note="No account or identity field is needed.",
        zh_web_setup_note="无需账号或身份字段。",
        fields={
            "fetch_top_stories": _guide_field(
                "Top stories to fetch", "抓取热门数量", "Number of top-story identifiers requested before filtering.", "筛选前请求的热门内容标识数量。",
                ("integer from 1 to 500",), ("1 到 500 的整数",), ("30",), ("30",),
                "Leave the default for the standard top-story feed.", "标准热门订阅可保持默认。",
            ),
            "min_score": _guide_field(
                "Minimum score", "最低评分", "Discard stories below this score.", "过滤低于该评分的内容。",
                ("non-negative integer",), ("非负整数",), ("100",), ("100",),
                "Choose the minimum score you consider useful.", "填写你认为有价值的最低评分。",
            ),
        },
    ),
}


_AGENT_GUIDE_METADATA: dict[str, dict[str, dict[str, Any]]] = {
    "rss": _GUIDE_METADATA["rss"],
    "telegram": _GUIDE_METADATA["telegram_channel"],
    "github": _guide_source(
        "GitHub Releases",
        "GitHub 发布版本",
        "Follow releases from a public GitHub repository.",
        "关注公开 GitHub 仓库的发布版本。",
        self_service=True,
        requires_web_setup=False,
        en_web_setup_note="Private repositories or token-only access must be configured in Web.",
        zh_web_setup_note="私有仓库或仅令牌可访问的仓库请在 Web 中配置。",
        fields={
            "repository": _guide_field(
                "Repository", "仓库", "Public owner/repository name or URL.", "公开 owner/repository 名称或网址。",
                ("owner/repository", "https://github.com/owner/repository"), ("owner/repository", "https://github.com/owner/repository"),
                ("openai/codex", "https://github.com/openai/codex"), ("openai/codex", "https://github.com/openai/codex"),
                "Copy the repository path from its public GitHub page.", "从公开 GitHub 页面复制仓库路径。",
            ),
        },
    ),
    "reddit": _GUIDE_METADATA["reddit_subreddit"],
    "twitter": _guide_source(
        "X / Twitter",
        "X / Twitter",
        "Follow a public X account through a preconfigured Apify source.",
        "通过预配置的 Apify 来源关注公开 X 账号。",
        self_service=False,
        requires_web_setup=True,
        en_web_setup_note="X sources require Web setup because they use a managed Apify credential.",
        zh_web_setup_note="X 来源使用托管的 Apify 凭据，需在 Web 中配置。",
        fields={
            "handle": _guide_field(
                "Handle", "账号", "Public X handle or profile URL.", "公开 X 账号或主页网址。",
                ("name", "@name", "https://x.com/name"), ("名称", "@名称", "https://x.com/名称"),
                ("openai", "@openai", "https://x.com/openai"), ("openai", "@openai", "https://x.com/openai"),
                "Copy the handle from the public X profile URL.", "从公开 X 主页网址复制账号。",
            ),
        },
    ),
    "website": _guide_source(
        "Website Feed",
        "网站订阅源",
        "Add a public RSS or Atom feed published by a website.",
        "添加网站发布的公开 RSS 或 Atom 订阅源。",
        self_service=True,
        requires_web_setup=False,
        en_web_setup_note="Authenticated feeds must be configured in Web.",
        zh_web_setup_note="需要登录或授权的订阅请在 Web 中配置。",
        fields={
            "url": _guide_field(
                "Feed URL", "订阅地址", "Public HTTP or HTTPS RSS/Atom URL.", "公开 HTTP 或 HTTPS RSS/Atom 地址。",
                ("https://host/path.xml",), ("https://域名/路径.xml",),
                ("https://example.com/feed.xml",), ("https://example.com/feed.xml",),
                "Copy the feed link from the publisher's RSS page.", "从发布者的 RSS 页面复制订阅链接。",
            ),
        },
    ),
    "youtube": _guide_source(
        "YouTube Feed",
        "YouTube 订阅源",
        "Add a public YouTube RSS feed URL.",
        "添加公开的 YouTube RSS 订阅地址。",
        self_service=True,
        requires_web_setup=False,
        en_web_setup_note="Private or authenticated channels must be configured in Web.",
        zh_web_setup_note="私有或需授权的频道请在 Web 中配置。",
        fields={
            "url": _guide_field(
                "YouTube feed URL", "YouTube 订阅地址", "Public YouTube RSS feed URL.", "公开 YouTube RSS 订阅地址。",
                ("https://www.youtube.com/feeds/videos.xml?channel_id=...",), ("https://www.youtube.com/feeds/videos.xml?channel_id=...",),
                ("https://www.youtube.com/feeds/videos.xml?channel_id=UCabcdefghijklmnopqrstuv",), ("https://www.youtube.com/feeds/videos.xml?channel_id=UCabcdefghijklmnopqrstuv",),
                "Copy the public RSS feed URL for the channel.", "复制频道公开 RSS 订阅地址。",
            ),
        },
    ),
    "apify": _GUIDE_METADATA["apify_social"],
}


_AGENT_SOURCE_TYPES: tuple[AgentSourceTypeDefinition, ...] = (
    AgentSourceTypeDefinition("rss", "rss", ("url",), _BY_TYPE["rss"].fields, _AGENT_GUIDE_METADATA["rss"]),
    AgentSourceTypeDefinition("telegram", "telegram_channel", ("channel",), _BY_TYPE["telegram_channel"].fields, _AGENT_GUIDE_METADATA["telegram"]),
    AgentSourceTypeDefinition(
        "github", "github_release", ("repository",),
        (_field("repository", "Repository", "text", required=True, help="Public GitHub owner/repository name or URL."),),
        _AGENT_GUIDE_METADATA["github"],
    ),
    AgentSourceTypeDefinition("reddit", "reddit_subreddit", ("subreddit",), _BY_TYPE["reddit_subreddit"].fields, _AGENT_GUIDE_METADATA["reddit"]),
    AgentSourceTypeDefinition(
        "twitter", "apify_social", ("handle",),
        (_field("handle", "Handle", "text", required=True, help="Public X account handle or profile URL."),),
        _AGENT_GUIDE_METADATA["twitter"],
    ),
    AgentSourceTypeDefinition("website", "rss", ("url",), _BY_TYPE["rss"].fields[:1], _AGENT_GUIDE_METADATA["website"]),
    AgentSourceTypeDefinition("youtube", "rss", ("url",), _BY_TYPE["rss"].fields[:1], _AGENT_GUIDE_METADATA["youtube"]),
    AgentSourceTypeDefinition("apify", "apify_social", _BY_TYPE["apify_social"].required_fields, _BY_TYPE["apify_social"].fields[:3], _AGENT_GUIDE_METADATA["apify"]),
)
_AGENT_BY_TYPE = {item.type: item for item in _AGENT_SOURCE_TYPES}


def list_source_types() -> list[dict[str, Any]]:
    """Return source type metadata for API clients."""

    return [item.as_dict() for item in _SOURCE_TYPES]


def get_source_setup_guide(
    source_type: str | None = None,
    locale: str = "zh-CN",
) -> dict[str, Any]:
    """Return the safe, bilingual source setup guide for MCP proposal flows."""

    selected_locale = _guide_locale(locale)
    if source_type is None:
        return {
            "locale": selected_locale,
            "source_types": [item.guide_summary(selected_locale) for item in _AGENT_SOURCE_TYPES],
        }
    definition = _AGENT_BY_TYPE.get(str(source_type))
    if definition is None:
        raise SourceConfigError(_UNSUPPORTED_SOURCE_TYPE_ERROR)
    return {
        "locale": selected_locale,
        "source_type": definition.guide_detail(selected_locale),
    }


def _safe_urlparse(value: str) -> Any:
    """Parse untrusted URL-shaped text under the public SourceConfigError contract."""

    try:
        return urlparse(value)
    except ValueError as exc:
        raise SourceConfigError("invalid URL") from exc


def _contains_secret_shape(value: Any) -> bool:
    """Detect secret-like values without persisting or returning them."""

    return public_data_contains_credentials(value)


def _validate_public_url_inputs(value: Any) -> None:
    """Reject credentials from every URL before aliases can discard them."""

    if isinstance(value, dict):
        for key, item in value.items():
            _validate_public_url_inputs(key)
            _validate_public_url_inputs(item)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            _validate_public_url_inputs(item)
        return
    if not isinstance(value, str):
        return
    if url_contains_credentials(value):
        raise SourceConfigError(_CREDENTIAL_ERROR)


_ENCODED_PATH_SEPARATOR_RE = re.compile(r"%(?:2f|5c)", flags=re.IGNORECASE)
_GITHUB_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$")
_GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def _github_path(value: str, *, kind: str) -> tuple[str, str] | str:
    raw = value.strip()
    parsed = _safe_urlparse(raw)
    text = raw
    if parsed.scheme:
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.netloc.lower() not in {"github.com", "www.github.com"}
            or parsed.query
            or parsed.fragment
            or parsed.params
        ):
            raise SourceConfigError(f"{kind} must be a public GitHub URL or name")
        text = parsed.path
    elif parsed.query or parsed.fragment or parsed.params:
        raise SourceConfigError(f"{kind} must be a public GitHub URL or name")
    if _ENCODED_PATH_SEPARATOR_RE.search(text):
        raise SourceConfigError(f"{kind} must be a public GitHub URL or name")
    decoded = unquote(text)
    if "//" in decoded or any(
        ord(character) < 32 or ord(character) == 127 for character in decoded
    ):
        raise SourceConfigError(f"{kind} must be a public GitHub URL or name")
    text = decoded.strip("/")
    parts = [part for part in text.split("/") if part]
    if kind == "repository":
        if len(parts) != 2:
            raise SourceConfigError("repository must be owner/repository")
        owner, repo = parts
        if repo.lower().endswith(".git"):
            # GitHub's standard HTTPS clone form and its common bare equivalent
            # both identify the repository without the transport suffix.
            repo = repo[:-4]
        if (
            len(owner) > 39
            or not _GITHUB_OWNER_RE.fullmatch(owner)
            or "--" in owner
            or repo in {".", ".."}
            or not _GITHUB_REPO_RE.fullmatch(repo)
        ):
            raise SourceConfigError("repository must be owner/repository")
        return owner, repo
    if len(parts) != 1:
        raise SourceConfigError("username must be a GitHub account name")
    return parts[0]


def _reddit_name(value: str, *, user: bool) -> str:
    text = value.strip()
    parsed = _safe_urlparse(text)
    prefix = "u" if user else "r"
    if parsed.scheme:
        host = parsed.netloc.lower()
        if parsed.scheme not in {"http", "https"} or host not in {
            "reddit.com",
            "www.reddit.com",
            "old.reddit.com",
        }:
            raise SourceConfigError("subreddit must be a public subreddit name or root URL")
        if parsed.query or parsed.fragment or parsed.params:
            raise SourceConfigError("subreddit must be a public subreddit name or root URL")
        match = re.fullmatch(r"/r/([A-Za-z0-9_]{3,21})/?", parsed.path, re.IGNORECASE)
        if prefix != "r" or match is None:
            raise SourceConfigError("subreddit must be a public subreddit name or root URL")
        return match.group(1)

    bare_match = re.fullmatch(
        rf"(?:{prefix}/)?([A-Za-z0-9_]{{3,21}})/?",
        text,
        re.IGNORECASE,
    )
    if bare_match is None:
        raise SourceConfigError("subreddit must be a public subreddit name or root URL")
    return bare_match.group(1)


_TELEGRAM_PUBLIC_HANDLE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
_TELEGRAM_RESERVED_ROUTES = {
    "addemoji",
    "addlist",
    "addstickers",
    "bg",
    "boost",
    "confirmphone",
    "contact",
    "giftcode",
    "invoice",
    "iv",
    "joinchat",
    "login",
    "proxy",
    "setlanguage",
    "share",
    "socks",
    "s",
}
_TWITTER_PUBLIC_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")


def _telegram_channel(value: str) -> str:
    text = value.strip().strip("/")
    parsed = _safe_urlparse(text)
    if parsed.scheme:
        if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {
            "t.me",
            "www.t.me",
            "telegram.me",
            "www.telegram.me",
        }:
            raise SourceConfigError("channel must be a public Telegram URL or name")
        parts = [part for part in parsed.path.split("/") if part]
        if (
            len(parts) != 1
            or parsed.path != f"/{parts[0]}"
            or parts[0].startswith("+")
            or parsed.params
            or parsed.query
            or parsed.fragment
            or "?" in text
            or "#" in text
        ):
            raise SourceConfigError("channel must be a public Telegram channel name")
        text = parts[0]
    channel = text.lstrip("@")
    if (
        channel.lower() in _TELEGRAM_RESERVED_ROUTES
        or not _TELEGRAM_PUBLIC_HANDLE_RE.fullmatch(channel)
    ):
        raise SourceConfigError("channel must be a public Telegram channel name")
    return channel


def _twitter_handle(value: str) -> str:
    text = value.strip().strip("/")
    parsed = _safe_urlparse(text)
    if parsed.scheme:
        if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {
            "x.com", "www.x.com", "twitter.com", "www.twitter.com",
        }:
            raise SourceConfigError("handle must be a public X URL or name")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 1:
            raise SourceConfigError("handle must be a public X account name")
        text = parts[0]
    handle = text.lstrip("@")
    if not _TWITTER_PUBLIC_HANDLE_RE.fullmatch(handle):
        raise SourceConfigError("handle must be a public X account name")
    return handle


_YOUTUBE_FEED_HOSTS = {"youtube.com", "www.youtube.com"}
_YOUTUBE_FEED_PATH = "/feeds/videos.xml"
_YOUTUBE_CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
# YouTube's public feed identities use 34-character user playlists (`PL`)
# or 24-character channel-derived uploads/likes/favorites playlists.
_YOUTUBE_PLAYLIST_ID_LENGTHS = {"PL": 34, "UU": 24, "LL": 24, "FL": 24}
_YOUTUBE_URLSAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _valid_youtube_playlist_id(value: str) -> bool:
    expected_length = _YOUTUBE_PLAYLIST_ID_LENGTHS.get(value[:2])
    return (
        expected_length is not None
        and len(value) == expected_length
        and _YOUTUBE_URLSAFE_ID_RE.fullmatch(value) is not None
    )


def _youtube_feed_url(value: str) -> str:
    """Validate a YouTube feed identity and return its canonical RSS URL."""

    parsed = _safe_urlparse(value.strip())
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() not in _YOUTUBE_FEED_HOSTS
        or parsed.path != _YOUTUBE_FEED_PATH
        or parsed.params
        or parsed.fragment
        or len(pairs) != 1
    ):
        raise SourceConfigError("url must be a public YouTube feed URL")
    identity_name, identity_value = pairs[0]
    valid_identity = (
        _YOUTUBE_CHANNEL_ID_RE.fullmatch(identity_value) is not None
        if identity_name == "channel_id"
        else _valid_youtube_playlist_id(identity_value)
        if identity_name == "playlist_id"
        else False
    )
    if not valid_identity:
        raise SourceConfigError("url must be a public YouTube feed URL")
    return f"https://www.youtube.com{_YOUTUBE_FEED_PATH}?{urlencode(pairs)}"


def _normalize_agent_aliases(source_type: str, config: dict[str, Any]) -> dict[str, Any]:
    data = dict(config)
    if source_type == "github" and "repository" in data:
        owner, repo = _github_path(data.pop("repository"), kind="repository")
        data["owner"] = owner
        data["repo"] = repo
    elif source_type == "reddit" and "subreddit" in data:
        data["subreddit"] = _reddit_name(data["subreddit"], user=False)
    elif source_type == "telegram" and "channel" in data:
        data["channel"] = _telegram_channel(data["channel"])
    elif source_type == "twitter" and "handle" in data:
        data = {
            "platform": "x",
            "kind": "profile",
            "target": _twitter_handle(data["handle"]),
        }
    elif source_type == "youtube" and "url" in data:
        data["url"] = _youtube_feed_url(data["url"])
    return data


def _validate_agent_field_types(
    definition: AgentSourceTypeDefinition, config: dict[str, Any]
) -> None:
    fields = {field.name: field for field in definition.fields}
    unknown = set(config) - set(fields)
    if unknown:
        raise SourceConfigError("unsupported fields: " + ", ".join(sorted(unknown)))
    for name, value in config.items():
        field = fields[name]
        if field.input_type in {"text", "url", "select"} and not isinstance(value, str):
            raise SourceConfigError(f"{name} must be a string")
        if field.input_type == "number" and (
            isinstance(value, bool) or not isinstance(value, int)
        ):
            raise SourceConfigError(f"{name} must be an integer")
        if field.input_type == "boolean" and not isinstance(value, bool):
            raise SourceConfigError(f"{name} must be a boolean")


_HISTORICAL_IPV4_COMPONENT_RE = re.compile(r"(?:0[xX][0-9A-Fa-f]+|[0-9]+)")


def _historical_ipv4_literal(host: str) -> ipaddress.IPv4Address | None:
    """Parse inet_aton-style IPv4 text locally, without treating domains as IPs."""

    parts = host.split(".")
    if not 1 <= len(parts) <= 4 or any(
        _HISTORICAL_IPV4_COMPONENT_RE.fullmatch(part) is None for part in parts
    ):
        return None

    values: list[int] = []
    try:
        for part in parts:
            if part.lower().startswith("0x"):
                base = 16
            elif len(part) > 1 and part.startswith("0"):
                base = 8
            else:
                base = 10
            values.append(int(part, base))
    except ValueError:
        return None

    component_limits = {
        1: (0xFFFFFFFF,),
        2: (0xFF, 0xFFFFFF),
        3: (0xFF, 0xFF, 0xFFFF),
        4: (0xFF, 0xFF, 0xFF, 0xFF),
    }[len(values)]
    if any(value > limit for value, limit in zip(values, component_limits)):
        return None

    if len(values) == 1:
        address = values[0]
    elif len(values) == 2:
        address = (values[0] << 24) | values[1]
    elif len(values) == 3:
        address = (values[0] << 24) | (values[1] << 16) | values[2]
    else:
        address = (
            (values[0] << 24)
            | (values[1] << 16)
            | (values[2] << 8)
            | values[3]
        )
    return ipaddress.IPv4Address(address)


def _validate_public_network_literal(value: str) -> None:
    """Reject local hostnames and non-public IP literals without resolving DNS."""

    parsed = _safe_urlparse(value.strip())
    try:
        raw_host = parsed.hostname
    except ValueError as exc:
        raise SourceConfigError("url must target the public network") from exc
    if not raw_host:
        return
    # Backslashes in the authority are interpreted as path separators by some
    # downstream URL implementations, which can turn an apparent hostname
    # into a local literal. Reject before hostname classification.
    if "\\" in parsed.netloc or "\\" in raw_host:
        raise SourceConfigError("url must target the public network")
    # Hostname percent escapes can be decoded by downstream URL implementations
    # into local literals. Reject them, including IPv6 zone identifiers, before
    # local literal classification rather than rewriting the accepted URL.
    if "%" in raw_host:
        raise SourceConfigError("url must target the public network")
    normalized_host = unicodedata.normalize("NFKC", raw_host).lower().rstrip(".")
    try:
        host = normalized_host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise SourceConfigError("url must target the public network") from exc
    if host == "localhost" or host.endswith(".localhost"):
        raise SourceConfigError("url must target the public network")
    try:
        literal = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        literal = _historical_ipv4_literal(host)
        if literal is None:
            return
    if (
        not literal.is_global
        or literal.is_loopback
        or literal.is_private
        or literal.is_link_local
        or literal.is_unspecified
        or literal.is_reserved
        or literal.is_multicast
    ):
        raise SourceConfigError("url must target the public network")


def normalize_source_setup_input(
    source_type: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Normalize agent-supplied public setup inputs before catalog validation."""

    source_type = str(source_type or "").strip()
    if source_type not in _AGENT_BY_TYPE:
        raise SourceConfigError(_UNSUPPORTED_SOURCE_TYPE_ERROR)
    if not isinstance(config, dict):
        raise SourceConfigError("config must be an object")
    raw = dict(config)
    if _contains_secret_shape(raw):
        raise SourceConfigError(_CREDENTIAL_ERROR)
    _validate_public_url_inputs(raw)
    definition = _AGENT_BY_TYPE[source_type]
    if source_type == "apify" and set(raw) - {"platform", "kind", "target"}:
        raise SourceConfigError(_SOURCE_REQUIRES_WEB_SETUP_ERROR)
    _validate_agent_field_types(definition, raw)
    aliased = _normalize_agent_aliases(source_type, raw)
    if source_type in {"rss", "website"} and isinstance(aliased.get("url"), str):
        _validate_public_network_literal(aliased["url"])
    normalized = validate_source_config(definition.catalog_source_type, aliased)
    policy = definition.execution_policy()
    if not policy["self_service"]:
        identity_fields = {
            key: normalized[key]
            for key in ("platform", "kind", "target")
            if key in normalized
        }
        return {
            "lookup_identity": {
                "catalog_source_type": definition.catalog_source_type,
                "config": identity_fields,
            },
            "policy": policy,
        }
    return {
        "catalog_source_type": definition.catalog_source_type,
        "config": normalized,
        "policy": policy,
    }


def validate_normalized_source_setup(
    source_type: str,
    catalog_source_type: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Validate a planner-normalized setup without retaining the raw request.

    Persisted mutation plans contain the public Agent type and its normalized
    catalog config.  Restoration uses this reverse check to prove the mapping,
    catalog config, and execution policy still match the registry contract.
    """

    definition = _AGENT_BY_TYPE.get(str(source_type))
    if definition is None:
        raise SourceConfigError(_UNSUPPORTED_SOURCE_TYPE_ERROR)
    if str(catalog_source_type) != definition.catalog_source_type:
        raise SourceConfigError(_UNSUPPORTED_SOURCE_TYPE_ERROR)
    if not isinstance(config, dict):
        raise SourceConfigError("config must be an object")
    if source_type == "rss":
        reverse_input = {
            key: config[key]
            for key in ("url", "name", "keep_latest_item")
            if key in config
        }
    elif source_type == "telegram":
        reverse_input = {
            key: config[key]
            for key in ("channel", "fetch_limit")
            if key in config
        }
    elif source_type == "github":
        owner = config.get("owner")
        repo = config.get("repo")
        if not isinstance(owner, str) or not isinstance(repo, str):
            raise SourceConfigError(
                "normalized source config does not match Agent contract"
            )
        reverse_input = {"repository": f"{owner}/{repo}"}
    elif source_type == "reddit":
        reverse_input = {
            key: config[key]
            for key in (
                "subreddit",
                "sort",
                "time_filter",
                "fetch_limit",
                "min_score",
            )
            if key in config
        }
    elif source_type == "twitter":
        reverse_input = {"handle": config.get("target")}
    elif source_type in {"website", "youtube"}:
        reverse_input = {"url": config.get("url")}
    elif source_type == "apify":
        reverse_input = {
            key: config[key]
            for key in ("platform", "kind", "target")
            if key in config
        }
    else:  # pragma: no cover - registry membership above closes this branch
        raise SourceConfigError(_UNSUPPORTED_SOURCE_TYPE_ERROR)

    rebuilt = normalize_source_setup_input(source_type, reverse_input)
    policy = definition.execution_policy()
    expected = (
        {
            "catalog_source_type": definition.catalog_source_type,
            "config": config,
            "policy": policy,
        }
        if policy["self_service"]
        else {
            "lookup_identity": {
                "catalog_source_type": definition.catalog_source_type,
                "config": config,
            },
            "policy": policy,
        }
    )
    if rebuilt != expected:
        raise SourceConfigError(
            "normalized source config does not match Agent contract"
        )
    return rebuilt


def validate_public_source_metadata(value: dict[str, Any]) -> None:
    """Reject credential shapes in safe-to-display planner metadata."""

    if not isinstance(value, dict):
        raise SourceConfigError("source metadata must be an object")
    if _contains_secret_shape(value):
        raise SourceConfigError(_CREDENTIAL_ERROR)
    _validate_public_url_inputs(value)


def project_catalog_source_public_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Project a stored catalog row without echoing unsafe legacy metadata."""

    source_type = str(source.get("type") or "")
    safe_type = source_type if source_type in _BY_TYPE else "unknown"

    def opaque() -> dict[str, Any]:
        return {
            "display_name": _OPAQUE_CATALOG_DISPLAY_NAME,
            "type": safe_type,
            "public_target": _OPAQUE_CATALOG_PUBLIC_TARGET,
        }

    display_name = source.get("display_name")
    config = source.get("config")
    if not isinstance(display_name, str) or not isinstance(config, dict):
        return opaque()
    classification_input = {
        "display_name": display_name,
        "config": config,
    }
    try:
        if _contains_secret_shape(classification_input):
            return opaque()
        _validate_public_url_inputs(classification_input)

        if source_type == "rss":
            setup = normalize_source_setup_input(
                "rss",
                {
                    key: config[key]
                    for key in ("url", "name", "keep_latest_item")
                    if key in config
                },
            )
            public_target: Any = setup["config"]["url"]
        elif source_type == "github_release":
            setup = normalize_source_setup_input(
                "github",
                {"repository": f"{config.get('owner', '')}/{config.get('repo', '')}"},
            )
            normalized = setup["config"]
            public_target = f"{normalized['owner']}/{normalized['repo']}"
        elif source_type == "github_user":
            normalized = validate_source_config(source_type, config)
            public_target = normalized["username"]
        elif source_type == "reddit_subreddit":
            setup = normalize_source_setup_input(
                "reddit",
                {
                    key: config[key]
                    for key in (
                        "subreddit",
                        "sort",
                        "time_filter",
                        "fetch_limit",
                        "min_score",
                    )
                    if key in config
                },
            )
            public_target = setup["config"]["subreddit"]
        elif source_type == "reddit_user":
            normalized = validate_source_config(source_type, config)
            public_target = normalized["username"]
        elif source_type == "telegram_channel":
            setup = normalize_source_setup_input(
                "telegram",
                {
                    key: config[key]
                    for key in ("channel", "fetch_limit")
                    if key in config
                },
            )
            public_target = setup["config"]["channel"]
        elif source_type == "apify_social":
            setup = normalize_source_setup_input(
                "apify",
                {
                    key: config[key]
                    for key in ("platform", "kind", "target")
                    if key in config
                },
            )
            identity = setup["lookup_identity"]["config"]
            public_target = {
                key: identity.get(key) for key in ("platform", "kind", "target")
            }
        elif source_type == "hackernews":
            normalized = validate_source_config(source_type, config)
            public_target = {
                key: normalized[key]
                for key in ("fetch_top_stories", "min_score")
            }
        else:
            return opaque()
    except (KeyError, SourceConfigError, TypeError, ValueError):
        return opaque()

    return {
        "display_name": display_name,
        "type": safe_type,
        "public_target": public_target,
    }


def validate_secret_env_name(value: str | None) -> str | None:
    """Validate that a value is an environment variable name, not a secret."""

    if value is None or value == "":
        return None
    name = str(value).strip()
    if name.startswith(_SECRET_PREFIXES) or not _ENV_VAR_RE.fullmatch(name):
        raise SourceConfigError("secret_env must be an environment variable name, not a secret value")
    return name


def _text(config: dict[str, Any], key: str, label: str | None = None) -> str:
    value = str(config.get(key) or "").strip()
    if not value:
        raise SourceConfigError(f"{label or key} is required")
    return value


def _bool(value: Any, *, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _int(
    config: dict[str, Any],
    key: str,
    *,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    try:
        value = int(config.get(key, default))
    except (TypeError, ValueError) as exc:
        raise SourceConfigError(f"{key} must be an integer") from exc
    if minimum is not None and value < minimum:
        raise SourceConfigError(f"{key} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise SourceConfigError(f"{key} must be at most {maximum}")
    return value


def _list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _base_config(config: dict[str, Any]) -> dict[str, Any]:
    data = dict(config or {})
    data["enabled"] = _bool(data.get("enabled"), default=True)
    for key in ("topics", "tags", "personal_tags"):
        if key in data:
            data[key] = _list(data.get(key))
    if "token_env" in data:
        data["token_env"] = validate_secret_env_name(data.get("token_env"))
    return data


def _validate_http_url(url: str) -> str:
    if "${" in url:
        raise SourceConfigError("RSS URLs cannot contain environment-variable placeholders")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SourceConfigError("url must be an http or https URL")
    if parsed.username is not None or parsed.password is not None:
        raise SourceConfigError("RSS URLs cannot contain credentials")
    return url


def _validate_choice(value: str, allowed: set[str], label: str) -> str:
    if value not in allowed:
        raise SourceConfigError(f"{label} must be one of {', '.join(sorted(allowed))}")
    return value


def validate_source_config(source_type: str, config: dict[str, Any] | None) -> dict[str, Any]:
    """Validate and normalize source catalog config for one source type."""

    source_type = str(source_type or "").strip()
    if source_type not in _BY_TYPE:
        raise SourceConfigError(_UNSUPPORTED_SOURCE_TYPE_ERROR)
    data = _base_config(config or {})

    if source_type == "rss":
        url = _validate_http_url(_text(data, "url", "url"))
        data["url"] = url
        data["name"] = str(data.get("name") or url).strip()
        data["keep_latest_item"] = _bool(
            data.get("keep_latest_item"), default=False
        )
        return data

    if source_type == "github_release":
        data["owner"] = _text(data, "owner", "owner")
        data["repo"] = _text(data, "repo", "repo")
        data["type"] = "repo_releases"
        return data

    if source_type == "github_user":
        data["username"] = _text(data, "username", "username")
        data["type"] = "user_events"
        return data

    if source_type == "reddit_subreddit":
        data["subreddit"] = _text(data, "subreddit", "subreddit").removeprefix("r/").strip()
        data["sort"] = _validate_choice(str(data.get("sort") or "hot"), _SUPPORTED_REDDIT_SORTS, "sort")
        data["time_filter"] = _validate_choice(
            str(data.get("time_filter") or "day"),
            _SUPPORTED_REDDIT_TIME_FILTERS,
            "time_filter",
        )
        data["fetch_limit"] = _int(data, "fetch_limit", default=25, minimum=1, maximum=100)
        data["min_score"] = _int(data, "min_score", default=10, minimum=0)
        return data

    if source_type == "reddit_user":
        data["username"] = _text(data, "username", "username").removeprefix("u/").strip()
        data["sort"] = _validate_choice(str(data.get("sort") or "new"), _SUPPORTED_REDDIT_SORTS, "sort")
        data["fetch_limit"] = _int(data, "fetch_limit", default=10, minimum=1, maximum=100)
        return data

    if source_type == "telegram_channel":
        data["channel"] = _text(data, "channel", "channel").lstrip("@").strip()
        data["fetch_limit"] = _int(data, "fetch_limit", default=20, minimum=1, maximum=100)
        return data

    if source_type == "apify_social":
        platform = str(data.get("platform") or "").strip().lower()
        if platform not in _APIFY_KINDS:
            raise SourceConfigError("platform must be one of facebook, instagram, telegram, x")
        kind = str(data.get("kind") or "").strip().lower()
        _validate_choice(kind, _APIFY_KINDS[platform], "kind")
        target = _text(data, "target", "target")
        data["platform"] = platform
        data["kind"] = kind
        data["target"] = target
        data["fetch_limit"] = _int(data, "fetch_limit", default=20, minimum=1, maximum=100)
        analysis_mode = str(data.get("analysis_mode") or "full").strip()
        if analysis_mode not in {"full", "personal_only"}:
            raise SourceConfigError("analysis_mode must be full or personal_only")
        data["analysis_mode"] = analysis_mode
        return data

    if source_type == "hackernews":
        data["fetch_top_stories"] = _int(data, "fetch_top_stories", default=30, minimum=1, maximum=500)
        data["min_score"] = _int(data, "min_score", default=100, minimum=0)
        return data

    raise SourceConfigError(_UNSUPPORTED_SOURCE_TYPE_ERROR)


def source_key(source_type: str, config: dict[str, Any]) -> str:
    """Build a stable identity key for idempotent catalog writes."""

    normalized = validate_source_config(source_type, config)
    if source_type == "rss":
        return f"rss:{normalized['url']}"
    if source_type == "github_release":
        return f"github_release:{normalized['owner'].lower()}/{normalized['repo'].lower()}"
    if source_type == "github_user":
        return f"github_user:{normalized['username'].lower()}"
    if source_type == "reddit_subreddit":
        return f"reddit_subreddit:{normalized['subreddit'].lower()}"
    if source_type == "reddit_user":
        return f"reddit_user:{normalized['username'].lower()}"
    if source_type == "telegram_channel":
        return f"telegram_channel:{normalized['channel'].lower()}"
    if source_type == "apify_social":
        return (
            "apify_social:"
            f"{normalized['platform']}:{normalized['kind']}:{normalized['target'].lower()}"
        )
    if source_type == "hackernews":
        return "hackernews:top"
    raise SourceConfigError(_UNSUPPORTED_SOURCE_TYPE_ERROR)


def build_source_payload(source: dict[str, Any]) -> dict[str, Any]:
    """Return a worker/test payload from one catalog source row."""

    source_type = str(source.get("type") or "")
    payload = validate_source_config(source_type, source.get("config") or {})
    payload["source_type"] = source_type
    if source.get("id"):
        payload["source_id"] = str(source["id"])
    if source.get("display_name"):
        payload["source_display_name"] = str(source["display_name"])
    payload["catalog_source_type"] = source_type
    secret_env = validate_secret_env_name(source.get("secret_env"))
    if secret_env and not payload.get("token_env"):
        payload["token_env"] = secret_env
    return payload

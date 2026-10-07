"""Structured plugin error types and error codes.

Follows docs/architecture/source-plugin-contract.md exactly.
"""

from __future__ import annotations


class PluginValidationError(Exception):
    """Plugin metadata or interface validation failed."""
    code = "PLUGIN_VALIDATION_ERROR"


class PluginExecutionError(Exception):
    """Plugin raised an unexpected runtime exception."""
    code = "PLUGIN_RUNTIME_ERROR"


class PluginTimeout(Exception):
    """Plugin execution exceeded timeout."""
    code = "PLUGIN_TIMEOUT"


class FetchNetworkError(Exception):
    """Network-level fetch failure (DNS, connection, TLS)."""
    code = "FETCH_NETWORK_ERROR"


class FetchHttp4xx(Exception):
    """HTTP 4xx client error."""
    code = "FETCH_HTTP_4XX"


class FetchHttp5xx(Exception):
    """HTTP 5xx server error."""
    code = "FETCH_HTTP_5XX"


class SourceRemoved(Exception):
    """Site explicitly withdrew access to this book's content."""
    code = "SOURCE_REMOVED"


class ParseEmpty(Exception):
    """Parser returned empty result."""
    code = "PARSE_EMPTY"


class ParseError(Exception):
    """Parser failed to extract expected structure."""
    code = "PARSE_ERROR"


class AuthRequired(Exception):
    """Source requires authentication for this content."""
    code = "AUTH_REQUIRED"


class LoginRequired(Exception):
    """Source requires login for this content."""
    code = "LOGIN_REQUIRED"


class PaidContentRequired(Exception):
    """Chapter/content requires payment."""
    code = "PAID_CONTENT_REQUIRED"


class BrowserRequired(Exception):
    """Source requires browser/manual-login access."""
    code = "BROWSER_REQUIRED"

    def __init__(
        self,
        message: str = "Browser verification required",
        *,
        url: str = "",
        status_code: int | None = None,
        body_sample: str = "",
    ):
        super().__init__(message)
        self.url = url
        self.status_code = status_code
        self.body_sample = body_sample


class CloudflareRequired(Exception):
    """Source requires Cloudflare bypass."""
    code = "CLOUDFLARE_REQUIRED"

    def __init__(
        self,
        message: str = "Cloudflare verification required",
        *,
        url: str = "",
        status_code: int | None = None,
        body_sample: str = "",
    ):
        super().__init__(message)
        self.url = url
        self.status_code = status_code
        self.body_sample = body_sample


class RateLimited(Exception):
    """Source returned rate-limit response."""
    code = "RATE_LIMITED"


class UnsupportedSource(Exception):
    """Source uses unsupported syntax or structure."""
    code = "UNSUPPORTED_SOURCE"


class SmokeContractError(Exception):
    """Smoke fixture output did not match declared expectations."""
    code = "SMOKE_CONTRACT_ERROR"


class SmokeFixtureMissing(Exception):
    """Smoke fixture spec or files are missing."""
    code = "SMOKE_FIXTURE_MISSING"


ERROR_CODE_MAP: dict[str, type[Exception]] = {
    "PLUGIN_VALIDATION_ERROR": PluginValidationError,
    "PLUGIN_RUNTIME_ERROR": PluginExecutionError,
    "PLUGIN_TIMEOUT": PluginTimeout,
    "FETCH_NETWORK_ERROR": FetchNetworkError,
    "FETCH_HTTP_4XX": FetchHttp4xx,
    "FETCH_HTTP_5XX": FetchHttp5xx,
    "SOURCE_REMOVED": SourceRemoved,
    "PARSE_EMPTY": ParseEmpty,
    "PARSE_ERROR": ParseError,
    "AUTH_REQUIRED": AuthRequired,
    "LOGIN_REQUIRED": LoginRequired,
    "PAID_CONTENT_REQUIRED": PaidContentRequired,
    "BROWSER_REQUIRED": BrowserRequired,
    "CLOUDFLARE_REQUIRED": CloudflareRequired,
    "RATE_LIMITED": RateLimited,
    "UNSUPPORTED_SOURCE": UnsupportedSource,
    "SMOKE_CONTRACT_ERROR": SmokeContractError,
    "SMOKE_FIXTURE_MISSING": SmokeFixtureMissing,
}

ERROR_HINTS: dict[str, str] = {
    "FETCH_NETWORK_ERROR": "检查站点网络、DNS、TLS、代理或 fixture URL 映射。",
    "FETCH_HTTP_4XX": "检查请求路径、参数、Headers、登录状态或站点反爬规则。",
    "FETCH_HTTP_5XX": "目标站点服务异常，可稍后重试或切换来源。",
    "PLUGIN_TIMEOUT": "检查站点响应时间、解析逻辑耗时或调低单源并发。",
    "SOURCE_REMOVED": "原站已停止提供该书正文，可选择其他可用书源或正版渠道。",
    "PARSE_EMPTY": "检查 selector、fixture HTML 或目标站 DOM 是否变化。",
    "PARSE_ERROR": "检查解析逻辑和返回数据结构。",
    "AUTH_REQUIRED": "该内容需要认证，先完成插件登录流程。",
    "LOGIN_REQUIRED": "该内容需要登录，先完成手动登录并保存 cookie。",
    "PAID_CONTENT_REQUIRED": "该内容需要付费账号或购买记录。",
    "BROWSER_REQUIRED": "该站需要浏览器态访问，后续接入受控浏览器流程。",
    "CLOUDFLARE_REQUIRED": "该站存在 Cloudflare 或类似挑战，需要浏览器态辅助。",
    "RATE_LIMITED": "目标站点限流，降低频率或等待后重试。",
    "PLUGIN_RUNTIME_ERROR": "检查插件代码异常和 traceback。",
    "SMOKE_CONTRACT_ERROR": "检查 smoke.yaml 期望值、fixture 内容和插件输出。",
    "SMOKE_FIXTURE_MISSING": "检查 smoke.yaml URL/file 配置和 smoke/fixtures 文件。",
}


def normalize_failure(
    *,
    source_id: str,
    stage: str,
    code: str,
    message: str,
    url: str = "",
    extra: dict | None = None,
) -> dict:
    normalized_code = code if code in ERROR_HINTS or code in ERROR_CODE_MAP else "PLUGIN_RUNTIME_ERROR"
    return {
        "sourceId": source_id,
        "stage": stage,
        "code": normalized_code,
        "message": message,
        "url": url,
        "hint": ERROR_HINTS.get(normalized_code, ERROR_HINTS["PLUGIN_RUNTIME_ERROR"]),
        "extra": extra or {},
    }




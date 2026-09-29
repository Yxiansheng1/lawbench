"""配置：全部来自环境变量（部署时由 WinSW 的服务配置注入），不读写配置文件。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

# 产品代码只允许访问的地址（CLAUDE.md"产品不外连"；Spec 14.3、15）。395 只连 6000D 和本机推理后端。
ALLOWED_REMOTE = {("192.168.8.77", 8000), ("10.126.126.1", 8000)}
LOCAL_HOSTS = {"127.0.0.1"}

# 本服务如果产生临时文件，一律以此为前缀；启动清理按前缀删除（Spec 6.2）
TEMP_PREFIX = "prep395-"


class ConfigError(ValueError):
    pass


def check_url(url: str, what: str) -> str:
    u = urlsplit(url)
    if u.scheme != "http" or not u.hostname:
        raise ConfigError(f"{what} 必须是 http://主机:端口 形式")
    host, port = u.hostname, u.port or 80
    if host in LOCAL_HOSTS or (host, port) in ALLOWED_REMOTE:
        return url.rstrip("/")
    raise ConfigError(f"{what} 不在允许访问的地址内（只允许 6000D 与 127.0.0.1）")


@dataclass
class Settings:
    llm_base: str = "http://192.168.8.77:8000"          # 6000D 网关（Key 校验用）
    backend: str = "llama"                               # llama | fake（fake 只用于开发和测试）
    ocr_url: str = "http://127.0.0.1:9101"               # 视觉模型 llama-server
    llm9b_url: str = "http://127.0.0.1:9102"             # 9B llama-server
    ocr_model: str = "ocr"
    llm9b_model: str = "llm9b"
    ocr_concurrency: int = 2
    queue_max: int = 20
    ocr_timeout_s: float = 120.0
    extract_timeout_s: float = 120.0
    key_cache_ttl_s: float = 30.0
    key_check_timeout_s: float = 10.0
    max_body_bytes: int = 10 * 1024 * 1024
    max_long_side: int = 2480
    max_text_chars: int = 16000
    home: Path = field(default_factory=lambda: Path(r"C:\prep395"))
    log_dir: Path | None = None
    admin_user: str = ""
    admin_pass_sha256: str = ""                          # 管理员口令的 SHA-256（十六进制），不存明文
    retry_after_s: int = 5

    def __post_init__(self) -> None:
        self.llm_base = check_url(self.llm_base, "6000D 地址")
        self.ocr_url = check_url(self.ocr_url, "OCR 后端地址")
        self.llm9b_url = check_url(self.llm9b_url, "9B 后端地址")
        for u in (self.ocr_url, self.llm9b_url):
            if urlsplit(u).hostname not in LOCAL_HOSTS:
                raise ConfigError("推理后端只能在本机 127.0.0.1")
        if self.backend not in ("fake", "llama"):
            raise ConfigError("PREP395_BACKEND 只能是 fake 或 llama")
        if self.ocr_concurrency < 1 or self.queue_max < 0:
            raise ConfigError("并发数至少为 1，排队上限不能为负")
        self.home = Path(self.home)
        self.log_dir = Path(self.log_dir) if self.log_dir else self.home / "logs"

    @property
    def key_check_url(self) -> str:
        base = self.llm_base[:-3] if self.llm_base.endswith("/v1") else self.llm_base
        return base + "/v1/chat/completions"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        e = os.environ if env is None else env
        kw: dict = {}
        mapping = {
            "PREP395_LLM_BASE": ("llm_base", str),
            "PREP395_BACKEND": ("backend", str),
            "PREP395_OCR_URL": ("ocr_url", str),
            "PREP395_LLM9B_URL": ("llm9b_url", str),
            "PREP395_OCR_MODEL": ("ocr_model", str),
            "PREP395_LLM9B_MODEL": ("llm9b_model", str),
            "PREP395_OCR_CONCURRENCY": ("ocr_concurrency", int),
            "PREP395_QUEUE_MAX": ("queue_max", int),
            "PREP395_OCR_TIMEOUT": ("ocr_timeout_s", float),
            "PREP395_HOME": ("home", Path),
            "PREP395_LOG_DIR": ("log_dir", Path),
            "PREP395_ADMIN_USER": ("admin_user", str),
            "PREP395_ADMIN_PASS_SHA256": ("admin_pass_sha256", str),
        }
        for env_name, (attr, conv) in mapping.items():
            v = e.get(env_name)
            if v:
                kw[attr] = conv(v)
        return cls(**kw)

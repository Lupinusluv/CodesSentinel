"""Settings.cors_origin_list 逻辑测试。

v0.5.0 部署关键：生产环境 CORS 若放行空列表，前端所有请求会被浏览器拦死。
本测试锁定 dev / prod 两种模式下的 origin 解析。
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

_BASE = {
    "deepseek_api_key": "x",
    "dashscope_api_key": "x",
    "database_url": "postgresql+asyncpg://u:p@h/db",
    # 显式给 webhook secret，避免测试依赖宿主机 .env，且满足 production fail-closed 校验。
    "github_webhook_secret": "x",
}


def _settings(**kw) -> Settings:
    return Settings(**{**_BASE, **kw})


def test_dev_always_allows_localhost():
    s = _settings(app_env="development", cors_origins="")
    assert s.cors_origin_list == ["http://localhost:5173"]


def test_prod_parses_comma_separated_origins():
    s = _settings(app_env="production", cors_origins="http://1.2.3.4:5173, http://example.com")
    assert s.cors_origin_list == ["http://1.2.3.4:5173", "http://example.com"]


def test_prod_empty_origins_is_empty_list():
    s = _settings(app_env="production", cors_origins="")
    assert s.cors_origin_list == []


def test_prod_ignores_blank_entries():
    s = _settings(app_env="production", cors_origins="http://a:5173, ,  ")
    assert s.cors_origin_list == ["http://a:5173"]


def test_prod_requires_webhook_secret():
    """fail-closed：production 下 github_webhook_secret 为空必须启动即失败，
    避免验签被静默跳过（fail-open）。dev 不受限。"""
    with pytest.raises(ValidationError, match="GITHUB_WEBHOOK_SECRET"):
        _settings(app_env="production", github_webhook_secret="")


def test_dev_allows_empty_webhook_secret():
    s = _settings(app_env="development", github_webhook_secret="")
    assert s.app_env == "development"

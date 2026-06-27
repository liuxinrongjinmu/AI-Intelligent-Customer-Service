"""
配置校验 单元测试

测试 validate_config 函数对各种配置状态的检测能力。
Pydantic Settings 通过 monkeypatch settings 对象的属性来模拟不同配置。
"""
import pytest
import backend.config as config_module


class TestConfigValidation:
    """配置校验测试"""

    def test_deepseek_api_key_missing_returns_errors(self, monkeypatch):
        """DEEPSEEK_API_KEY 未配置时返回 errors"""
        monkeypatch.setattr(config_module.settings, "deepseek_api_key", "")
        monkeypatch.setattr(config_module.settings, "admin_api_key", "valid-admin-key")
        monkeypatch.setattr(config_module.settings, "gateway_ip_whitelist", "10.0.0.0/8")
        # 同步模块级变量
        monkeypatch.setattr(config_module, "DEEPSEEK_API_KEY", "")
        monkeypatch.setattr(config_module, "ADMIN_API_KEY", "valid-admin-key")

        warnings, errors = config_module.validate_config()
        assert any("DEEPSEEK_API_KEY 未配置" in e for e in errors)

    def test_admin_api_key_default_returns_warnings(self, monkeypatch):
        """ADMIN_API_KEY 使用默认弱密钥时返回 warnings"""
        monkeypatch.setattr(config_module.settings, "deepseek_api_key", "sk-valid-key")
        monkeypatch.setattr(config_module.settings, "admin_api_key", "change-me-admin-key")
        monkeypatch.setattr(config_module.settings, "gateway_ip_whitelist", "10.0.0.0/8")
        monkeypatch.setattr(config_module, "DEEPSEEK_API_KEY", "sk-valid-key")
        monkeypatch.setattr(config_module, "ADMIN_API_KEY", "change-me-admin-key")

        warnings, errors = config_module.validate_config()
        assert any("ADMIN_API_KEY 使用默认弱密钥" in w for w in warnings)

    def test_gateway_ip_whitelist_missing_returns_warnings(self, monkeypatch):
        """GATEWAY_IP_WHITELIST 未配置时返回 warnings"""
        monkeypatch.setattr(config_module.settings, "deepseek_api_key", "sk-valid-key")
        monkeypatch.setattr(config_module.settings, "admin_api_key", "valid-admin-key")
        monkeypatch.setattr(config_module.settings, "gateway_ip_whitelist", "")

        warnings, errors = config_module.validate_config()
        assert any("建议配置 GATEWAY_IP_WHITELIST" in w for w in warnings)

    def test_gateway_ip_whitelist_default_returns_warnings(self, monkeypatch):
        """GATEWAY_IP_WHITELIST 使用默认值时返回 warnings"""
        monkeypatch.setattr(config_module.settings, "deepseek_api_key", "sk-valid-key")
        monkeypatch.setattr(config_module.settings, "admin_api_key", "valid-admin-key")
        monkeypatch.setattr(
            config_module.settings,
            "gateway_ip_whitelist",
            "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16",
        )

        warnings, errors = config_module.validate_config()
        assert any("使用默认值" in w for w in warnings)

    def test_all_config_valid_returns_empty_errors(self, monkeypatch):
        """所有配置正常时返回空 errors"""
        monkeypatch.setattr(config_module.settings, "deepseek_api_key", "sk-valid-key")
        monkeypatch.setattr(config_module.settings, "admin_api_key", "valid-admin-key")
        monkeypatch.setattr(config_module.settings, "gateway_ip_whitelist", "10.0.1.0/24")

        warnings, errors = config_module.validate_config()
        assert errors == []

    def test_jwt_secret_missing_in_jwt_mode_returns_warning(self, monkeypatch):
        """JWT 模式下 JWT_SECRET 未配置时返回 warnings"""
        monkeypatch.setattr(config_module.settings, "deepseek_api_key", "sk-valid-key")
        monkeypatch.setattr(config_module.settings, "admin_api_key", "valid-admin-key")
        monkeypatch.setattr(config_module.settings, "gateway_ip_whitelist", "10.0.0.0/8")
        monkeypatch.setattr(config_module.settings, "gateway_auth_mode", "jwt")
        monkeypatch.setattr(config_module, "_JWT_SECRET_RESOLVED", "")

        warnings, errors = config_module.validate_config()
        assert any("JWT_SECRET 未配置" in w for w in warnings)

    def test_jwt_secret_configured_no_warning(self, monkeypatch):
        """JWT_SECRET 已配置时不返回相关 warnings"""
        monkeypatch.setattr(config_module.settings, "deepseek_api_key", "sk-valid-key")
        monkeypatch.setattr(config_module.settings, "admin_api_key", "valid-admin-key")
        monkeypatch.setattr(config_module.settings, "gateway_ip_whitelist", "10.0.0.0/8")
        monkeypatch.setattr(config_module.settings, "gateway_auth_mode", "jwt")
        monkeypatch.setattr(config_module, "_JWT_SECRET_RESOLVED", "valid-jwt-secret-key")

        warnings, errors = config_module.validate_config()
        assert not any("JWT_SECRET" in w for w in warnings)

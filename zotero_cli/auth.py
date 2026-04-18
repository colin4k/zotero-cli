"""
Zotero CLI 认证模块
从 ~/.hermes/.env 或环境变量读取 API Key，自动加载代理设置。
"""
import os
import functools


@functools.lru_cache(maxsize=1)
def load_env():
    """从 ~/.hermes/.env 加载环境变量（仅执行一次）"""
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key not in os.environ:
                        os.environ[key] = val


def get_api_key() -> str:
    """获取 Zotero API Key"""
    load_env()
    key = os.environ.get("ZOTERO_API_KEY", "")
    if not key:
        raise ValueError(
            "未找到 ZOTERO_API_KEY。\n"
            "请在 ~/.hermes/.env 中添加: ZOTERO_API_KEY=your_key\n"
            "或在环境变量中设置: export ZOTERO_API_KEY=your_key"
        )
    return key


def ensure_api_key() -> str:
    """获取 API Key，失败则打印错误并退出"""
    import sys
    try:
        return get_api_key()
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)

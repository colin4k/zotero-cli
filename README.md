# zotero-cli

[![PyPI version](https://img.shields.io/badge/pip%20install-zotero--cli-blue)](https://github.com/colin4k/zotero-cli)
![Python 3.8+](https://img.shields.io/badge/python-3.8+-green.svg)

Zotero Web API 命令行工具，通过 Python stdlib 实现完整的文献库管理（零外部依赖）。

## 安装

```bash
cd ~/workspace/zotero-cli
pip install -e .
```

## 配置

在 `~/.hermes/.env` 中添加：
```
ZOTERO_API_KEY=your_key_here
```

获取 API Key：https://www.zotero.org/settings/keys → Create New Key → Library Access: Read + Write

## 命令

```bash
zotero check                      # 诊断检查
zotero library                    # 库概览
zotero collections                # 列出集合
zotero search -q "关键词"          # 关键词搜索
zotero search -t "标签"            # 标签搜索
zotero search -c "集合名"          # 集合搜索
zotero upload --file book.pdf     # 上传文件
zotero upload --files /dir/       # 批量上传
zotero upload --file f.pdf --collection "AI" --tags "AI,LLM" --note "笔记"
```

## API

```python
from zotero_cli.api import ZoteroAPI

api = ZoteroAPI()
api.check()                     # 诊断
api.search_items(query="AI")    # 搜索
api.upload_file("book.pdf", collection="AI阅读", tags="AI", note="笔记")
```

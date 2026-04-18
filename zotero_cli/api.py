"""
Zotero Web API 封装
封装所有 API 操作：读、写、搜索、文件上传。
"""
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
import urllib.error
from typing import Optional

from .auth import get_api_key

API_BASE = "https://api.zotero.org"


class ZoteroAPI:
    """Zotero Web API 客户端"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or get_api_key()
        self._user_id: Optional[int] = None

    @property
    def user_id(self) -> int:
        if self._user_id is None:
            self._user_id = self._get_user_id()
        return self._user_id

    def _get_user_id(self) -> int:
        """获取用户 ID"""
        req = urllib.request.Request(f"{API_BASE}/keys/current")
        req.add_header("Zotero-API-Key", self.api_key)
        req.add_header("Zotero-API-Version", "3")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data["userID"]

    def _request(self, method: str, path: str, data=None,
                 headers=None, raw=False, timeout=30):
        """通用请求方法"""
        url = f"{API_BASE}/users/{self.user_id}/{path.lstrip('/')}"
        req = urllib.request.Request(url, method=method)
        req.add_header("Zotero-API-Key", self.api_key)
        req.add_header("Zotero-API-Version", "3")

        if headers:
            for k, v in headers.items():
                req.add_header(k, v)

        if data is not None:
            if isinstance(data, bytes):
                req.data = data
            elif isinstance(data, (dict, list)):
                req.data = json.dumps(data, ensure_ascii=False).encode("utf-8")
                if "Content-Type" not in (headers or {}):
                    req.add_header("Content-Type", "application/json")
            else:
                req.data = data.encode("utf-8") if isinstance(data, str) else data

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if raw:
                    return resp.read(), resp.headers
                body = resp.read()
                if body:
                    return json.loads(body.decode("utf-8")), resp.headers
                return {}, resp.headers
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace").strip()
            raise ZoteroAPIError(e.code, body) from e
        except urllib.error.URLError as e:
            raise ZoteroAPIError(0, f"网络错误: {e.reason}") from e

    # ── 查询操作 ──

    def check(self) -> dict:
        """诊断检查，返回用户信息、权限、库统计"""
        # 验证当前 key
        key_info, _ = self._request("GET", "keys/current")
        user_access = key_info.get("access", {}).get("user", {})
        username = key_info.get("username", "")

        # 获取库统计
        _, items_headers = self._request("GET", "items?limit=1")
        _, coll_headers = self._request("GET", "collections?limit=1")

        return {
            "user_id": key_info.get("userID", self.user_id),
            "username": username,
            "api_key_prefix": self.api_key[:8] + "..." + self.api_key[-4:],
            "library_access": user_access.get("library", False),
            "file_access": user_access.get("files", False),
            "note_access": user_access.get("notes", False),
            "write_access": user_access.get("write", False),
            "total_items": items_headers.get("Total-Results", "?"),
            "total_collections": coll_headers.get("Total-Results", "?"),
            "library_version": items_headers.get("Last-Modified-Version", "?"),
        }

    def get_library_version(self) -> int:
        """获取当前库版本"""
        _, headers = self._request("GET", "items?limit=1")
        return int(headers.get("Last-Modified-Version", "0"))

    def search_items(self, query: Optional[str] = None,
                     tag: Optional[str] = None,
                     collection: Optional[str] = None,
                     limit: int = 20) -> list:
        """搜索条目"""
        if query:
            q = urllib.parse.quote(query)
            items, _ = self._request("GET", f"items?q={q}&limit={limit}&sort=title&direction=asc")
            return items
        elif tag:
            t = urllib.parse.quote(tag)
            items, _ = self._request("GET", f"items?tag={t}&limit={limit}")
            return items
        elif collection:
            return self.search_by_collection(collection, limit)
        return []

    def search_by_collection(self, name: str, limit: int = 50) -> list:
        """按集合名搜索"""
        key = self._find_collection_key(name)
        if key is None:
            raise ZoteroAPIError(0, f"集合不存在: {name}")
        items, _ = self._request("GET", f"collections/{key}/items?limit={limit}")
        return items

    def list_collections(self) -> list:
        """列出所有集合"""
        items, _ = self._request("GET", "collections?limit=200")
        return items

    def get_recent_items(self, limit: int = 10) -> list:
        """获取最近添加的条目"""
        items, _ = self._request("GET", f"items?limit={limit}&sort=dateAdded&direction=desc")
        return items

    def get_attachments_sample(self, limit: int = 100) -> list:
        """获取附件样本（用于统计）"""
        items, _ = self._request("GET", f"items?itemType=attachment&limit={limit}")
        return items

    def _find_collection_key(self, name: str) -> Optional[str]:
        """查找集合 key"""
        collections, _ = self._request("GET", f"collections?search={urllib.parse.quote(name)}&limit=100")
        for c in collections:
            if c["data"]["name"] == name:
                return c["data"]["key"]
        return None

    # ── 写入操作 ──

    def ensure_collection(self, name: str) -> str:
        """确保集合存在，返回 key"""
        key = self._find_collection_key(name)
        if key:
            return key
        version = self.get_library_version()
        headers = {
            "If-Unmodified-Since-Version": str(version),
            "Zotero-Write-Token": os.urandom(16).hex(),
        }
        result, _ = self._request("POST", "collections",
                                  data=[{"name": name}],
                                  headers=headers)
        if result.get("successful", {}).get("0"):
            coll_data = result["successful"]["0"]
            return coll_data.get("key") if isinstance(coll_data, dict) else coll_data
        raise ZoteroAPIError(0, f"创建集合失败: {result}")

    def upload_file(self, file_path: str, title: Optional[str] = None,
                    collection: Optional[str] = None, tags: Optional[str] = None,
                    note: Optional[str] = None, parent_key: Optional[str] = None) -> dict:
        """
        完整文件上传流程：
        1. 创建 attachment 条目
        2. 获取上传授权
        3. 上传文件内容
        4. 注册上传
        5. 关联集合、添加笔记
        """
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        file_md5 = hashlib.md5(open(file_path, "rb").read()).hexdigest()
        file_mtime = int(os.path.getmtime(file_path) * 1000)
        ext = os.path.splitext(filename)[1].lower()
        mime_types = {
            ".pdf": "application/pdf", ".epub": "application/epub+zip",
            ".snb": "application/x-snb", ".txt": "text/plain",
            ".html": "text/html", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        content_type = mime_types.get(ext, "application/octet-stream")
        item_title = title or os.path.splitext(filename)[0]

        # Step 1: 创建 attachment 条目
        version = self.get_library_version()
        item = {
            "itemType": "attachment",
            "linkMode": "imported_file",
            "title": item_title,
            "accessDate": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "note": "",
            "tags": [{"tag": t.strip(), "type": 1} for t in tags.split(",") if t.strip()] if tags else [],
            "relations": {},
            "contentType": content_type,
            "charset": "",
            "filename": filename,
            "md5": None,
            "mtime": None,
        }
        if parent_key:
            item["parentItem"] = parent_key

        headers = {
            "If-Unmodified-Since-Version": str(version),
            "Zotero-Write-Token": os.urandom(16).hex(),
        }
        result, _ = self._request("POST", "items", data=[item], headers=headers)
        if not result.get("successful", {}).get("0"):
            raise ZoteroAPIError(0, f"创建条目失败: {result}")
        item_data = result["successful"]["0"]
        item_key = item_data.get("key") if isinstance(item_data, dict) else item_data

        # Step 2: 获取上传授权
        auth_data = urllib.parse.urlencode({
            "md5": file_md5, "filename": filename,
            "filesize": str(file_size), "mtime": str(file_mtime),
        })
        req = urllib.request.Request(
            f"{API_BASE}/users/{self.user_id}/items/{item_key}/file",
            data=auth_data.encode("utf-8"), method="POST")
        req.add_header("Zotero-API-Key", self.api_key)
        req.add_header("Zotero-API-Version", "3")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("If-None-Match", "*")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                auth_result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise ZoteroAPIError(e.code, f"上传授权失败: {body}") from e

        if auth_result.get("exists") == 1:
            # 文件已存在，但仍需关联集合和笔记
            if collection:
                coll_key = self.ensure_collection(collection)
                version = self.get_library_version()
                item_data, _ = self._request("GET", f"items/{item_key}")
                current_colls = item_data.get("data", {}).get("collections", [])
                if coll_key not in current_colls:
                    current_colls.append(coll_key)
                item_update = {
                    "key": item_key,
                    "version": item_data.get("data", {}).get("version", 0),
                    "collections": current_colls,
                }
                headers = {
                    "If-Unmodified-Since-Version": str(version),
                    "Zotero-Write-Token": os.urandom(16).hex(),
                }
                self._request("POST", "items", data=[item_update], headers=headers)

            if note:
                version = self.get_library_version()
                # 检查父条目类型，attachment 不能有子笔记
                parent_data, _ = self._request("GET", f"items/{item_key}")
                parent_type = parent_data.get("data", {}).get("itemType", "")
                
                if parent_type in ("attachment", "note"):
                    # attachment 的笔记直接存为独立条目
                    note_item = {
                        "itemType": "note",
                        "note": f"<p>{note}</p>",
                        "tags": [{"tag": "auto-note", "type": 1}],
                    }
                else:
                    note_item = {
                        "itemType": "note",
                        "note": f"<p>{note}</p>",
                        "parentItem": item_key,
                    }
                self._request("POST", "items", data=[note_item],
                             headers={"If-Unmodified-Since-Version": str(version)})

            return {"key": item_key, "status": "exists", "title": item_title, "filename": filename}

        upload_url = auth_result["url"]
        prefix = auth_result.get("prefix", "")
        suffix = auth_result.get("suffix", "")
        upload_key = auth_result.get("uploadKey")

        # Step 3: 上传文件
        with open(file_path, "rb") as f:
            file_content = f.read()
        upload_body = prefix.encode() + file_content + suffix.encode()

        req = urllib.request.Request(upload_url, data=upload_body, method="POST")
        req.add_header("Content-Type", auth_result.get("contentType", content_type))
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                pass
        except urllib.error.URLError as e:
            raise ZoteroAPIError(0, f"文件上传失败: {e}") from e

        # Step 4: 注册上传
        reg_data = urllib.parse.urlencode({"upload": upload_key})
        req = urllib.request.Request(
            f"{API_BASE}/users/{self.user_id}/items/{item_key}/file",
            data=reg_data.encode("utf-8"), method="POST")
        req.add_header("Zotero-API-Key", self.api_key)
        req.add_header("Zotero-API-Version", "3")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("If-None-Match", "*")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                pass
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise ZoteroAPIError(e.code, f"注册上传失败: {body}") from e

        # Step 5: 关联集合
        if collection:
            coll_key = self.ensure_collection(collection)
            version = self.get_library_version()
            # 更新条目的 collections 字段
            item_data, _ = self._request("GET", f"items/{item_key}")
            current_colls = item_data.get("data", {}).get("collections", [])
            if coll_key not in current_colls:
                current_colls.append(coll_key)
            item_update = {
                "key": item_key,
                "version": item_data.get("data", {}).get("version", 0),
                "collections": current_colls,
            }
            headers = {
                "If-Unmodified-Since-Version": str(version),
                "Zotero-Write-Token": os.urandom(16).hex(),
            }
            self._request("POST", "items", data=[item_update], headers=headers)

        # Step 6: 添加笔记
        if note:
            version = self.get_library_version()
            parent_type = item.get("itemType", "attachment")
            
            if parent_type in ("attachment", "note"):
                note_item = {
                    "itemType": "note",
                    "note": f"<p>{note}</p>",
                    "tags": [{"tag": "auto-note", "type": 1}],
                }
            else:
                note_item = {
                    "itemType": "note",
                    "note": f"<p>{note}</p>",
                    "parentItem": item_key,
                }
            self._request("POST", "items", data=[note_item],
                         headers={"If-Unmodified-Since-Version": str(version)})

        return {"key": item_key, "status": "uploaded", "title": item_title, "filename": filename}


class ZoteroAPIError(Exception):
    """API 错误"""
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"HTTP {code}: {message}" if code else message)

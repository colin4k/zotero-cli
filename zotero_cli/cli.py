"""
Zotero CLI 命令行入口
用法:
    zotero check                      # 诊断检查
    zotero library                    # 库概览
    zotero collections                # 列出所有集合
    zotero search -q "关键词"          # 关键词搜索
    zotero search -t "标签"            # 标签搜索
    zotero search -c "集合名"          # 集合搜索
    zotero upload --file book.pdf      # 上传文件
    zotero upload --files /dir/        # 批量上传
"""
import argparse
import json
import sys
import time

from .auth import ensure_api_key
from .api import ZoteroAPI, ZoteroAPIError


def format_item(item: dict) -> str:
    """格式化条目显示"""
    data = item.get("data", {})
    item_type = data.get("itemType", "unknown")

    if item_type == "attachment":
        title = data.get("title", "Untitled")
        filename = data.get("filename", "")
        tags = data.get("tags", [])
        parent = data.get("parentItem", "")
        tag_str = ", ".join([
            t.get("tag", "") if isinstance(t, dict) else str(t)
            for t in tags[:3]
        ]) if tags else ""
        line = f"  📎 {title}"
        if filename and filename != title:
            line += f" ({filename})"
        if tag_str:
            line += f" [{tag_str}]"
        if parent:
            line += f" (parent: {parent[:8]})"
        return line

    elif item_type in ("book", "journalArticle", "report"):
        title = data.get("title", "Untitled")
        creators = data.get("creators", [])
        author_str = ""
        if creators:
            names = []
            for c in creators[:2]:
                if isinstance(c, dict):
                    if c.get("lastName"):
                        names.append(c["lastName"])
                    elif c.get("name"):
                        names.append(c["name"])
                elif isinstance(c, str):
                    names.append(c)
            author_str = f" - {', '.join(names)}" if names else ""
        year = data.get("date", "")[:4]
        year_str = f" ({year})" if year else ""
        tags = data.get("tags", [])
        tag_str = ", ".join([
            t.get("tag", "") if isinstance(t, dict) else str(t)
            for t in tags[:3]
        ]) if tags else ""
        tag_line = f"\n     🏷️  {tag_str}" if tag_str else ""
        return f"  📖 {title}{author_str}{year_str}{tag_line}"

    else:
        title = data.get("title", data.get("note", "Untitled"))[:60]
        return f"  📄 {title} ({item_type})"


def cmd_check(args, api: ZoteroAPI):
    """诊断检查"""
    info = api.check()
    print("=" * 50)
    print("📚 Zotero 诊断检查")
    print("=" * 50)
    print(f"\n1️⃣  用户: {info['user_id']}")
    print(f"2️⃣  API Key: {info['api_key_prefix']}")
    print(f"3️⃣  权限: 读={info['library_read']}, 写={info['library_write']}")
    print(f"4️⃣  库统计: {info['total_items']} 条目, {info['total_collections']} 集合")
    print(f"5️⃣  库版本: {info['library_version']}")
    print("\n" + "=" * 50)
    if info['library_read'] and info['library_write']:
        print("✅ 一切正常")
    else:
        print("⚠️  权限不完整，请在 zotero.org 修改 API Key 权限")
    print("=" * 50)


def cmd_library(args, api: ZoteroAPI):
    """库概览"""
    check = api.check()
    collections = api.list_collections()
    recent = api.get_recent_items(10)
    attachments = api.get_attachments_sample(200)

    print("=" * 50)
    print("📚 Zotero 库概览")
    print("=" * 50)
    print(f"\n📄 总条目: {check['total_items']}")
    print(f"📁 集合: {len(collections)}")

    print(f"\n📁 集合列表:")
    if collections:
        # 计算每个集合的条目数
        for c in collections[:50]:
            name = c["data"]["name"]
            key = c["data"]["key"]
            parent = c["data"].get("parentCollection", False)
            parent_info = " (子集合)" if parent else ""
            try:
                items, _ = api._request("GET", f"collections/{key}/items?limit=1")
                count = len(items)
            except:
                count = "?"
            print(f"  📂 {name}{parent_info} — {count}")
        if len(collections) > 50:
            print(f"  ... +{len(collections) - 50} 个集合")
    else:
        print("  (暂无)")

    print(f"\n🕐 最近添加:")
    for item in recent:
        data = item.get("data", {})
        icon = {"attachment": "📎", "book": "📖", "journalArticle": "📖"}.get(data.get("itemType", ""), "📄")
        date = data.get("dateAdded", "")[:10]
        filename = data.get("filename", "")
        title = data.get("title", "Untitled")
        extra = f" ({filename})" if filename and filename != title else ""
        print(f"  {icon} [{date}] {title}{extra}")

    # 文件类型统计
    ext_count = {}
    for a in attachments:
        fn = a.get("data", {}).get("filename", "")
        if not fn:
            continue
        ext = "." + fn.rsplit(".", 1)[-1].lower()
        ext_count[ext] = ext_count.get(ext, 0) + 1
    if ext_count:
        print(f"\n📊 附件类型 (样本):")
        for ext, count in sorted(ext_count.items(), key=lambda x: -x[1]):
            print(f"  {ext}: {count}")
    print(f"\n{'=' * 50}")


def cmd_collections(args, api: ZoteroAPI):
    """列出集合"""
    collections = api.list_collections()
    if args.json:
        print(json.dumps(collections, ensure_ascii=False, indent=2))
        return
    for c in collections:
        name = c["data"]["name"]
        parent = c["data"].get("parentCollection", False)
        parent_info = "  └─" if parent else "  ├─"
        print(f"{parent_info} {name}")
    print(f"\n共 {len(collections)} 个集合")


def cmd_search(args, api: ZoteroAPI):
    """搜索条目"""
    try:
        items = api.search_items(
            query=args.query, tag=args.tag,
            collection=args.collection, limit=args.limit,
        )
    except ZoteroAPIError as e:
        print(f"❌ {e}")
        sys.exit(1)

    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return

    label = args.query or args.tag or args.collection
    print(f"🔍 搜索: \"{label}\" ({len(items)} 个结果)\n")
    if not items:
        print("  (无结果)")
        return
    for item in items:
        print(format_item(item))
        print(f"     key: {item['key']}")
        print()
    print(f"共 {len(items)} 个条目")


def cmd_upload(args, api: ZoteroAPI):
    """上传文件"""
    files = []
    if args.file:
        if not __import__('os').path.isfile(args.file):
            print(f"❌ 文件不存在: {args.file}")
            sys.exit(1)
        files.append((args.file, args.title))
    if args.files:
        if not __import__('os').path.isdir(args.files):
            print(f"❌ 目录不存在: {args.files}")
            sys.exit(1)
        for f in sorted(__import__('os').listdir(args.files)):
            if f.lower().endswith((".pdf", ".epub", ".snb", ".txt", ".html", ".docx")):
                files.append((__import__('os').path.join(args.files, f), None))

    if not files:
        print("❌ 没有可上传的文件")
        sys.exit(1)

    print(f"📚 已连接 Zotero Web API (用户: {api.user_id})")
    print(f"📥 待上传: {len(files)} 个文件\n")

    results = {"success": 0, "exists": 0, "error": 0}
    for file_path, title in files:
        filename = __import__('os').path.basename(file_path)
        print(f"{'=' * 40}")
        print(f"📄 {filename}")
        try:
            result = api.upload_file(
                file_path, title=title,
                collection=args.collection,
                tags=args.tags, note=args.note,
                parent_key=args.parent,
            )
            if result["status"] == "exists":
                print(f"  ⏭️  已存在: {result['key']}")
                results["exists"] += 1
            else:
                print(f"  ✅ 上传成功: {result['key']}")
                results["success"] += 1
        except ZoteroAPIError as e:
            print(f"  ❌ {e}")
            results["error"] += 1
        time.sleep(1)

    print(f"\n{'=' * 40}")
    print(f"  ✅ 成功: {results['success']}  ⏭️  跳过: {results['exists']}  ❌ 失败: {results['error']}")
    print(f"{'=' * 40}")


COMMANDS = {
    "check": (cmd_check, "诊断检查（API Key、权限、库统计）"),
    "library": (cmd_library, "库概览（集合、最近添加、文件统计）"),
    "collections": (cmd_collections, "列出所有集合"),
    "search": (cmd_search, "搜索条目（关键词/标签/集合）"),
    "upload": (cmd_upload, "上传文件到 Zotero（含集合、标签、笔记）"),
}


def main():
    parser = argparse.ArgumentParser(
        prog="zotero",
        description="Zotero Web API CLI - 文献库管理工具",
    )
    parser.add_argument("--json", action="store_true", dest="global_json",
                       help="全局 JSON 输出模式")

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # check
    p = subparsers.add_parser("check", help="诊断检查")
    p.set_defaults(func=cmd_check)

    # library
    p = subparsers.add_parser("library", help="库概览")
    p.set_defaults(func=cmd_library)

    # collections
    p = subparsers.add_parser("collections", help="列出所有集合")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_collections)

    # search
    p = subparsers.add_parser("search", help="搜索条目")
    p.add_argument("-q", "--query", help="关键词搜索")
    p.add_argument("-t", "--tag", help="按标签搜索")
    p.add_argument("-c", "--collection", help="按集合搜索")
    p.add_argument("-n", "--limit", type=int, default=20, help="返回数量")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_search)

    # upload
    p = subparsers.add_parser("upload", help="上传文件")
    p.add_argument("--file", help="单个文件路径")
    p.add_argument("--files", help="批量上传目录路径")
    p.add_argument("--title", help="标题（单文件时覆盖文件名）")
    p.add_argument("--collection", help="目标集合（不存在自动创建）")
    p.add_argument("--tags", help="逗号分隔的标签，如: AI,LLM")
    p.add_argument("--note", help="附加笔记内容")
    p.add_argument("--parent", help="父条目 key（作为子附件）")
    p.set_defaults(func=cmd_upload)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    api_key = ensure_api_key()
    api = ZoteroAPI(api_key)

    try:
        args.func(args, api)
    except ZoteroAPIError as e:
        print(f"❌ API 错误: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n⚠️  已取消")
        sys.exit(130)


if __name__ == "__main__":
    main()

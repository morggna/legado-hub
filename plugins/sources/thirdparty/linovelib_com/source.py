"""Public Bilinovel mobile pages, with versioned paragraph-order restoration."""
from __future__ import annotations

import ast
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from app.source_plugins.errors import ParseEmpty, ParseError, SourceRemoved


def _integer(expression: str) -> int:
    """Parse arithmetic constants from chapterlog; never execute site JavaScript."""
    if len(expression) > 160:
        raise ParseError("正文排序参数过长")
    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            value = node.value
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            left, right = visit(node.left), visit(node.right)
            value = left + right if isinstance(node.op, ast.Add) else left - right if isinstance(node.op, ast.Sub) else left * right
        else:
            raise ParseError("正文排序脚本格式已变化")
        if abs(value) > 2**53:
            raise ParseError("正文排序参数超出安全范围")
        return value
    try:
        return visit(ast.parse(expression.strip(), mode="eval").body)
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise ParseError("正文排序脚本格式已变化") from exc


def _shuffle_template(script: str) -> tuple[int, int, int, int, int, int]:
    # Site protocol also documented by MIT-licensed bili_novel_packer.
    identifier = r"[_$a-zA-Z0-9]+"
    seed = re.search(
        rf"var\s+{identifier}\s*=\s*[^;]*?Number\s*\(\s*{identifier}\s*\)\s*,\s*([^,)]+?)\s*\)\s*,\s*([^,)]+?)\s*\)\s*,", script,
    )
    lcg = re.search(
        rf"({identifier})\s*=\s*[^;]*?\(\s*\1\s*,\s*([^,)]+?)\s*\)\s*,\s*([^,)]+?)\s*\)\s*,\s*([^;)]+?)\s*\)\s*;", script,
    )
    if not seed or not lcg:
        raise ParseError("哔哩正文排序脚本已变化，停止返回可能乱序的正文")
    # The numeric declaration immediately before the shuffle function is the
    # unchanged-prefix length. Read it from this version, rather than assume 20.
    prefixes = list(re.finditer(
        rf"var\s+{identifier}\s*=\s*([0-9a-fxX+*()\s-]+);\s*function\s+{identifier}\s*\(",
        script[max(0, lcg.start() - 3000):lcg.start()],
    ))
    if not prefixes:
        raise ParseError("正文排序脚本缺少固定段落参数")
    fixed = _integer(prefixes[-1].group(1))
    multiplier, offset = map(_integer, seed.groups())
    a, c, mod = map(_integer, lcg.groups()[1:])
    if not (0 <= fixed <= 100 and 0 < multiplier <= 10000 and 0 <= offset <= 100000
            and 0 < a < mod <= 2**31 and 0 <= c < mod):
        raise ParseError("正文排序参数无效")
    return fixed, multiplier, offset, a, c, mod


def _restore(content, chapter_id: int, template: tuple[int, ...]) -> None:
    fixed, multiplier, offset, a, c, mod = template
    children = list(content.children)
    slots = [i for i, node in enumerate(children)
             if isinstance(node, Tag) and node.name == "p" and node.decode_contents().strip()]
    if len(slots) <= fixed:
        return
    tail = list(range(fixed, len(slots)))
    seed = chapter_id * multiplier + offset
    for i in range(len(tail) - 1, 0, -1):
        seed = (seed * a + c) % mod
        j = seed * (i + 1) // mod
        tail[i], tail[j] = tail[j], tail[i]
    order = list(range(fixed)) + tail
    original = [children[i] for i in slots]
    for i, target in enumerate(order):
        children[slots[target]] = original[i]
    content.clear()
    for node in children:
        content.append(node)


class Source:
    id = "linovelib_com"
    name = "哔哩轻小说"
    contract_version = "1.0"
    last_modified = "2026-10-07"
    base_url = "https://www.bilinovel.com"
    _hosts = {"www.bilinovel.com", "www.bilinovel.net", "www.linovelib.com",
              "w.linovelib.com", "tw.linovelib.com", "linovelib.com"}
    _headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
        "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9",
        "Cookie": "night=0", "Referer": base_url,
    }

    @classmethod
    def _url(cls, value: str, pattern: str, *, fragment: bool = False) -> str:
        try:
            parsed = urlsplit(urljoin(cls.base_url, value))
            if (parsed.scheme not in {"http", "https"} or parsed.hostname not in cls._hosts
                    or parsed.username or parsed.password or parsed.port or parsed.query
                    or (parsed.fragment and not fragment) or not re.fullmatch(pattern, parsed.path)):
                raise ValueError()
        except ValueError as exc:
            raise ParseError("不是有效的哔哩轻小说页面地址") from exc
        return cls.base_url + parsed.path + ("#" + parsed.fragment if fragment and parsed.fragment else "")

    async def _fetch(self, ctx, url: str) -> BeautifulSoup:
        html = await ctx.access.stealth.fetch_text(url, headers=self._headers, impersonate="chrome124")
        return BeautifulSoup(html, "lxml")

    @staticmethod
    def _text(node) -> str:
        return node.get_text(" ", strip=True) if node else ""

    async def search(self, ctx, keyword: str, page: int) -> list[dict]:
        keyword = keyword.strip()
        if not keyword or page != 1:
            return []
        if keyword.startswith(("https://", "http://")):
            url = self._url(keyword, r"/novel/\d+(?:\.html|/catalog)")
            book_id = re.search(r"/novel/(\d+)", url).group(1)
            return [await self.detail(ctx, f"{self.base_url}/novel/{book_id}.html")]
        if re.fullmatch(r"\d+", keyword):
            return [await self.detail(ctx, f"{self.base_url}/novel/{int(keyword)}.html")]
        # The native search requires a browser-only guard. Public indexed search
        # uses the host bridge; its index may lag new/renamed books.
        hits = await ctx.access.search_provider(
            keyword, target_domain="www.linovelib.com", query_site_path="/novel/",
            url_patterns=[r"/novel/\d+\.html", r"/novel/\d+/catalog"],
            provider_order=["duckduckgo_ddgs"], limit=10,
        )
        seen, items = set(), []
        for hit in hits:
            try:
                url = self._url(hit.url, r"/novel/\d+(?:\.html|/catalog)")
            except ParseError:
                continue
            book_id = re.search(r"/novel/(\d+)", url).group(1)
            if book_id in seen:
                continue
            seen.add(book_id)
            item = await self.detail(ctx, f"{self.base_url}/novel/{book_id}.html")
            haystack = " ".join([item["name"], item["author"], item["extra"]["aliases"]])
            if ctx.to_simplified(keyword).casefold() in ctx.to_simplified(haystack).casefold():
                items.append(item)
            if len(seen) >= 5:
                break
        return items

    async def detail(self, ctx, book_url: str) -> dict:
        book_url = self._url(book_url, r"/novel/\d+\.html")
        soup = await self._fetch(ctx, book_url)
        def meta(key):
            node = soup.select_one(f'meta[property="{key}"]')
            return str(node.get("content", "")).strip() if node else ""
        name, author = meta("og:novel:book_name"), meta("og:novel:author")
        if not name or not author:
            raise ParseError("哔哩轻小说详情缺少书名或作者，页面可能受限")
        toc_url = self._url(meta("og:novel:read_url"), r"/novel/\d+/catalog")
        if re.search(r"/novel/(\d+)", toc_url).group(1) != re.search(r"/novel/(\d+)", book_url).group(1):
            raise ParseError("详情目录不属于当前书籍")
        chapters = await self.toc(ctx, toc_url)
        return {
            "sourceId": self.id, "bookUrl": book_url, "tocUrl": toc_url,
            "name": name, "author": author, "coverUrl": urljoin(book_url, meta("og:image")),
            "intro": self._text(soup.select_one("#bookSummary content")) or meta("og:description"),
            "kind": meta("og:novel:category"), "bookStatus": meta("og:novel:status"),
            "lastChapter": meta("og:novel:latest_chapter_name"),
            "chapterCount": len(chapters), "authRequired": False,
            "extra": {"aliases": self._text(soup.select_one(".bkname-body")),
                      "unavailableChapters": sum(c["isLocked"] for c in chapters)},
        }

    async def toc(self, ctx, book_url: str) -> list[dict]:
        url = self._url(book_url, r"/novel/\d+(?:\.html|/catalog)")
        book_id = re.search(r"/novel/(\d+)", url).group(1)
        toc_url = f"{self.base_url}/novel/{book_id}/catalog"
        soup = await self._fetch(ctx, toc_url)
        chapters, seen, volume = [], set(), ""
        for node in soup.select("#volumes li.chapter-bar, #volumes li.jsChapter"):
            if "chapter-bar" in node.get("class", []):
                volume = self._text(node.select_one("h3"))
                continue
            link = node.select_one("a.chapter-li-a")
            if not link or not self._text(link):
                raise ParseError("目录条目缺少标题")
            href = str(link.get("href", ""))
            locked = bool(re.fullmatch(r"javascript:cid\(\d+\)", href))
            if locked:
                # Retain the real catalog document as an unavailable location;
                # this is never fetched or represented as a real chapter address.
                chapter_url = f"{toc_url}#unavailable-{len(chapters) + 1}"
            else:
                chapter_url = self._url(href, rf"/novel/{book_id}/\d+\.html")
            if chapter_url in seen:
                raise ParseError("原站目录存在重复条目")
            seen.add(chapter_url)
            chapters.append({
                "sourceId": self.id, "index": len(chapters) + 1,
                "title": f"{volume} {self._text(link)}".strip() + ("【原站未开放】" if locked else ""),
                "chapterUrl": chapter_url, "isVip": False, "isLocked": locked,
                "extra": {"volume": volume, "unavailable": locked},
            })
        if not chapters:
            raise ParseEmpty("哔哩轻小说目录为空或页面受限")
        return chapters

    async def chapter(self, ctx, chapter_url: str) -> dict:
        url = self._url(chapter_url, r"/novel/\d+/(?:\d+\.html|catalog)", fragment=True)
        if re.fullmatch(r"/novel/\d+/catalog", urlsplit(url).path):
            raise SourceRemoved("原站该章节未提供公开阅读地址，请到原站确认")
        if urlsplit(url).fragment:
            raise ParseError("章节地址不应包含片段")
        book_id, chapter_id = re.fullmatch(r"/novel/(\d+)/(\d+)(?:_\d+)?\.html", urlsplit(url).path).groups()
        current, visited, paragraphs, images, templates, title = url, set(), [], [], {}, ""
        for _ in range(100):
            if current in visited:
                raise ParseError("章节分页循环，拒绝返回残缺正文")
            visited.add(current)
            soup = await self._fetch(ctx, current)
            content = soup.select_one("#acontent")
            heading = self._text(soup.select_one("#atitle"))
            if not content or not heading:
                raise ParseError("哔哩轻小说未返回章节正文")
            if re.search(r"(?:内容|內容)(?:加载|加載)失敗|(?:内容|內容)(?:加载|加載)失败", content.get_text()):
                raise ParseError("原站正文加载失败，拒绝缓存截断章节")
            volume = self._text(soup.select_one(".atitle h3"))
            if not volume:
                raise ParseError("正文缺少卷名，无法核对目录章节")
            title = title or f"{volume} {heading}"
            params = " ".join(s.get_text() for s in soup.select("script:not([src])") if "var ReadParams=" in s.get_text())
            def param(key):
                match = re.search(rf"\b{key}\s*:\s*'([^']*)'", params)
                return match.group(1) if match else ""
            if param("articleid") != book_id or param("chapterid") != chapter_id:
                raise ParseError("正文或分页不属于当前章节")
            script = soup.find("script", src=re.compile(r"chapterlog\.js\?v"))
            if not script:
                raise ParseError("章节缺少正文排序脚本")
            # Script query is a version key; validate separately from page URLs.
            sp = urlsplit(urljoin(self.base_url, script["src"]))
            if sp.hostname not in self._hosts or sp.path != "/themes/zhmb/js/chapterlog.js" or not re.fullmatch(r"v[\w.]+", sp.query) or sp.scheme != "https" or sp.username or sp.password or sp.port or sp.fragment:
                raise ParseError("正文排序脚本地址无效")
            script_url = self.base_url + sp.path + "?" + sp.query
            if script_url not in templates:
                js = await ctx.access.stealth.fetch_text(script_url, headers=self._headers, impersonate="chrome124")
                templates[script_url] = _shuffle_template(js)
            _restore(content, int(chapter_id), templates[script_url])
            for node in content.find_all(["script", "div", "ins", "center"]):
                node.decompose()
            for node in content.children:
                if not isinstance(node, Tag):
                    continue
                for image in ([node] if node.name == "img" else node.find_all("img")):
                    image_url = urljoin(current, image.get("data-src") or image.get("src") or "")
                    ip = urlsplit(image_url)
                    if ip.scheme != "https" or ip.hostname not in {"img3.readpai.com", "img.linovelib.com", "www.bilinovel.com"} or ip.username or ip.password:
                        raise ParseError("插图地址无效")
                    images.append(image_url)
                    paragraphs.append(f"[插图 {len(images)}] {image_url}")
                text = self._text(node)
                if text:
                    paragraphs.append(text)
            next_url = self._url(param("url_next"), r"/novel/\d+/(?:\d+(?:_\d+)?\.html|catalog)")
            path = urlsplit(next_url).path
            if not path.startswith(f"/novel/{book_id}/"):
                raise ParseError("分页导航指向另一本书")
            if not re.fullmatch(rf"/novel/{book_id}/{chapter_id}_\d+\.html", path):
                break
            previous_page = int(param("page")) if param("page").isdigit() else 0
            next_page = int(re.search(r"_(\d+)\.html$", path).group(1))
            if next_page != previous_page + 1:
                raise ParseError("分页序号不连续，拒绝返回残缺正文")
            current = next_url
        else:
            raise ParseError("章节分页超出上限")
        if not paragraphs:
            raise ParseEmpty("章节正文为空")
        return {"sourceId": self.id, "chapterUrl": url, "title": title,
                "content": "\n\n".join(paragraphs), "format": "text", "authRequired": False, "isPaid": False,
                "extra": {"pageCount": len(visited), "illustrationUrls": images}}

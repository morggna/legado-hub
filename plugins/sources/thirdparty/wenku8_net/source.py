"""Wenku8 public reading adapter; search uses the host's public search provider."""
from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from app.source_plugins.errors import ParseError, ParseEmpty, SourceRemoved


class Source:
    id = "wenku8_net"
    name = "轻小说文库"
    contract_version = "1.0"
    last_modified = "2026-10-07"
    base_url = "https://www.wenku8.net"

    @classmethod
    def _url(cls, value: str, pattern: str) -> str:
        parsed = urlsplit(urljoin(cls.base_url, value))
        if (parsed.scheme not in {"https", "http"}
                or parsed.hostname not in {"www.wenku8.net", "wenku8.net"}
                or parsed.username or parsed.password or parsed.port
                or not re.fullmatch(pattern, parsed.path)):
            raise ParseError("不是有效的轻小说文库页面地址")
        return cls.base_url + parsed.path

    async def _fetch(self, ctx, url: str) -> BeautifulSoup:
        data = await ctx.access.stealth.fetch_bytes(url)
        # Fixtures/browser exports are UTF-8; the actual site declares GBK.
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = ctx.decode_text(data, "gb18030")
        return BeautifulSoup(text, "lxml")

    @staticmethod
    def _text(node) -> str:
        return node.get_text(" ", strip=True) if node else ""

    async def search(self, ctx, keyword: str, page: int) -> list[dict]:
        keyword = ctx.to_simplified(keyword.strip())
        if page != 1 or not keyword:
            return []
        if re.fullmatch(r"\d+", keyword):
            return [await self.detail(ctx, f"{self.base_url}/book/{int(keyword)}.htm")]
        if keyword.startswith(("https://", "http://")):
            return [await self.detail(ctx, keyword)]
        # The site's own search redirects anonymous users to login. Public
        # index search avoids storing a shared Wenku8 account/cookie.
        hits = await ctx.access.search_provider(
            keyword, target_domain="www.wenku8.net",
            url_patterns=[r"/book/\d+\.htm"],
            provider_order=["duckduckgo_ddgs"], query_site_path="/book/", limit=10,
        )
        items, seen = [], set()
        candidates = 0
        for hit in hits:
            if keyword.casefold() not in ctx.to_simplified(hit.title).casefold():
                continue
            try:
                url = self._url(hit.url, r"/book/\d+\.htm")
            except (ValueError, ParseError):
                continue
            if url in seen:
                continue
            seen.add(url)
            candidates += 1
            try:
                detail = await self.detail(ctx, url)
                if keyword.casefold() in (detail["name"] + " " + detail["author"]).casefold():
                    items.append(detail)
            except Exception as exc:
                ctx.trace("search_detail_error", url=url, message=str(exc))
            if candidates >= 3:
                break
        return items

    async def detail(self, ctx, book_url: str) -> dict:
        book_url = self._url(book_url, r"/book/\d+\.htm")
        soup = await self._fetch(ctx, book_url)
        main = soup.select_one("#content > div")
        name = self._text(main.select_one("table b")) if main else ""
        toc_link = main.find("a", href=re.compile(r"/novel/\d+/\d+/index\.htm$")) if main else None
        if not name or not toc_link:
            raise ParseError("轻小说文库未提供可读目录，可能已下架或页面受限")
        info = {}
        for td in main.select("td"):
            if td.find("table") or td.find("td"):
                continue
            value = self._text(td)
            if "：" in value and len(value) < 100:
                key, value = value.split("：", 1)
                info[key] = value
        intro_label = main.find("span", string="内容简介：")
        intro = intro_label.find_next_sibling("span") if intro_label else None
        cover = main.select_one('img[src*="/image/"]')
        toc_url = self._url(toc_link["href"], r"/novel/\d+/\d+/index\.htm")
        chapters = await self.toc(ctx, toc_url)
        return {
            "sourceId": self.id, "bookUrl": book_url, "tocUrl": toc_url,
            "name": name, "author": info.get("小说作者", ""),
            "bookStatus": info.get("文章状态", ""),
            "kind": info.get("文库分类", ""), "wordCount": info.get("全文长度", ""),
            "updateTime": info.get("最后更新", ""),
            "intro": intro.get_text("\n", strip=True) if intro else "",
            "coverUrl": str(cover["src"]).replace("http://", "https://", 1) if cover else "",
            "chapterCount": len(chapters), "lastChapter": chapters[-1]["title"],
            "authRequired": False, "extra": {},
        }

    async def toc(self, ctx, toc_url: str) -> list[dict]:
        toc_url = self._url(toc_url, r"/novel/\d+/\d+/index\.htm")
        soup = await self._fetch(ctx, toc_url)
        chapters, seen, volume = [], set(), ""
        directory = toc_url.rsplit("/", 1)[0]
        for td in soup.select("table.css td"):
            if "vcss" in td.get("class", []):
                volume = self._text(td)
                continue
            link = td.select_one("a[href]") if "ccss" in td.get("class", []) else None
            if not link or not self._text(link):
                continue
            url = self._url(urljoin(toc_url, link["href"]), r"/novel/\d+/\d+/\d+\.htm")
            if url.rsplit("/", 1)[0] != directory:
                raise ParseError("目录中的章节属于另一本书")
            if url in seen:
                continue
            seen.add(url)
            chapters.append({
                "sourceId": self.id, "index": len(chapters) + 1,
                "title": f"{volume} {self._text(link)}".strip(), "chapterUrl": url,
                "isVip": False, "isLocked": False, "extra": {"volume": volume},
            })
        if not chapters:
            raise ParseEmpty("轻小说文库目录为空或页面受限")
        return chapters

    @staticmethod
    def _parse_full_book(data: bytes, chapters: list[dict], name: str) -> list[dict]:
        # This is the site's UTF-8 export, not an HTML page or a best-effort decode.
        if len(data) > 32 * 1024 * 1024:
            raise ParseError("文库 TXT 超过解析上限")
        try:
            text = data.decode("utf-8-sig").replace("\r\n", "\n")
        except UnicodeDecodeError as exc:
            raise ParseError("文库 TXT 编码错误") from exc
        lines = text.splitlines()
        if not lines or lines[0] != "★☆★☆★☆轻小说文库(Www.WenKu8.Com)☆★☆★☆★":
            raise ParseError("不是文库完整 TXT")
        footer = "更多精彩热门日本轻小说、动漫小说，尽在轻小说文库(Www.WenKu8.Com)"
        while lines and not lines[-1].strip():
            lines.pop()
        if len(lines) < 3 or lines[-1] != footer or not re.fullmatch(r"[◆◇]+", lines[-2]):
            raise ParseError("文库 TXT 缺少结束标记")
        lines = lines[:-2]
        def normalize_heading(value):
            # Book 1213 retains numeric HTML references in the native TXT
            # headings; decode only these references, never rewrite prose.
            value = re.sub(r"&#(?:[0-9]{1,7}|[xX][0-9a-fA-F]{1,6});",
                           lambda match: unescape(match.group()), value)
            # Book 3765: HTML uses • in names while its TXT uses ·.
            return value.replace("•", "·")

        titles = [normalize_heading(c["title"]) for c in chapters]
        if not titles:
            raise ParseError("整本目录为空")
        originals = {}
        for chapter, heading in zip(chapters, titles):
            originals.setdefault(heading, set()).add(chapter["title"])
        if any(len(values) != 1 for values in originals.values()):
            raise ParseError("目录标题归一后产生歧义")
        observed = []
        for index, line in enumerate(lines):
            heading = normalize_heading(line)
            if heading in originals:
                observed.append((index, heading))
        # Repeated Interlude headings are real entries in book 1213. Validate
        # every occurrence and the entire ordered sequence before mapping to
        # the frozen source URLs; never select a fuzzy match or a guessed index.
        if [heading for _, heading in observed] != titles:
            raise ParseError("文库 TXT 与完整目录序列不一致")
        offsets = [index for index, _ in observed]
        header = [line for line in lines[1:offsets[0]] if line.strip()]
        if header != [f"<{name}>"]:
            raise ParseError("文库 TXT 书名不一致")
        result = []
        for chapter, start, end in zip(chapters, offsets, offsets[1:] + [len(lines)]):
            body = "\n\n".join(line.strip() for line in lines[start+1:end] if line.strip())
            # Image-only chapters have a heading but no text in the native export.
            if body:
                result.append({**chapter, "content": body, "format": "text"})
        return result

    async def full_book(self, ctx, book_url: str, chapters: list[dict], *, name: str) -> list[dict]:
        book_url = self._url(book_url, r"/book/\d+\.htm")
        book_id = int(book_url.rsplit("/", 1)[1].split(".")[0])
        directory = f"{self.base_url}/novel/{book_id // 1000}/{book_id}/"
        for chapter in chapters:
            url = self._url(chapter["chapterUrl"], r"/novel/\d+/\d+/\d+\.htm")
            if url.rsplit("/", 1)[0] + "/" != directory:
                raise ParseError("整本目录属于另一本书")
        if not chapters:
            raise ParseEmpty("整本目录为空")
        # A retained directory does not mean the site still provides the book.
        # Respect an explicit withdrawal notice before accessing native exports.
        await self.chapter(ctx, chapters[0]["chapterUrl"])
        # Public static TXT endpoint, also used by Wenku8 clients; no account cookie.
        data = await ctx.access.stealth.fetch_bytes(
            f"https://dl1.wenku8.com/down/txtutf8/{book_id // 1000}/{book_id}.txt"
        )
        return self._parse_full_book(data, chapters, name)

    async def chapter(self, ctx, chapter_url: str) -> dict:
        chapter_url = self._url(chapter_url, r"/novel/\d+/\d+/\d+\.htm")
        soup = await self._fetch(ctx, chapter_url)
        title, body = self._text(soup.select_one("#title")), soup.select_one("#content")
        if not title or body is None:
            raise ParseError("轻小说文库正文结构缺失，可能已下架或页面受限")
        # Evidence: dedicated contentdp elements at both ends are site ads.
        # Keep translator credits and ordinary prose mentioning the site.
        for node in body.select("#contentdp, script, style"):
            node.decompose()
        images = []
        for img in body.select("img"):
            url = urljoin(chapter_url, str(img.get("src", "")))
            if urlsplit(url).scheme not in {"https", "http"}:
                img.decompose()
                continue
            images.append(url)
            img.replace_with(f"\n[插图 {len(images)}]\n{url}\n")
        for br in body.select("br"):
            br.replace_with("\n")
        content = "\n\n".join(line.strip() for line in body.get_text().splitlines() if line.strip())
        if content.strip() == "因版权问题，文库不再提供该小说的阅读！":
            raise SourceRemoved("原站因版权问题已停止提供本书阅读，目录仍保留")
        if not content:
            raise ParseEmpty("轻小说文库正文为空")
        return {
            "sourceId": self.id, "chapterUrl": chapter_url, "title": title,
            "content": content, "format": "text", "authRequired": False, "isPaid": False,
            "extra": {"illustrationUrls": images} if images else {},
        }

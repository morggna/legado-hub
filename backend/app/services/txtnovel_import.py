"""Host-owned attachment provider: private sessions and explicit one-shot spending.

This is not a chapter plugin: the site offers account-gated RAR downloads.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from Crypto.Cipher import AES
from fastapi import HTTPException

from app import config
from app.services.local_book_import import import_book
from app.services.text_convert import to_simplified

BASE = "http://www.txtnovel.vip/"
SOURCE_ID = "txtnovel_vip"
SOURCE_NAME = "书香门第（附件）"


def site_url(url):
    result = urljoin(BASE, url)
    parsed = urlsplit(result)
    if parsed.scheme not in {"http", "https"} or parsed.hostname != "www.txtnovel.vip" or parsed.port not in {None, 80, 443} or parsed.username or parsed.password:
        raise HTTPException(502, "书源返回了非本站地址")
    return result


def soup(data):
    return BeautifulSoup(data.decode("gb18030", errors="replace"), "html.parser")


def book_metadata(title, thread_id):
    match = re.search(r"《(.+?)》.*?作者[：:]\s*(.+?)(?=/译者|【|$)", title)
    if not match:
        return None
    return {"bookId": f"attachment-txtnovel-{thread_id}", "sourceId": SOURCE_ID, "sourceName": SOURCE_NAME,
            "threadId": str(thread_id), "name": to_simplified(match[1]), "author": to_simplified(match[2].strip()),
            "bookUrl": BASE + f"thread-{thread_id}-1-1.html", "attachmentSource": True, "sourceCount": 1}


def parse_search(data):
    document = soup(data)
    items = []
    for row in document.select('#threadlist li'):
        title = row.select_one('h3 a')
        if title and re.fullmatch(r"\d+", row.get('id', '')):
            book = book_metadata(title.get_text('', strip=True), row['id'])
            if book:
                intro = row.select('p')
                book['intro'] = to_simplified(intro[1].get_text(' ', strip=True)) if len(intro) > 1 else ''
                items.append(book)
    next_page = document.select_one('.pg a.nxt')
    return items, site_url(next_page['href']) if next_page else None


def parse_detail(data, thread_id):
    document = soup(data)
    title = document.select_one('#thread_subject')
    book = book_metadata(title.get_text('', strip=True), thread_id) if title else None
    if not book:
        raise HTTPException(502, "帖子不可访问或不是可识别的书籍")
    attachments = []
    for row in document.select('.attnm'):
        link = row.select_one('a[href]')
        if not link:
            continue
        url = site_url(link['href'])
        query = parse_qs(urlsplit(url).query)
        aid = query.get('aid', [''])[0]
        if query.get('id') != ['yxf_attachdownconfirm:index'] or not aid.isdecimal():
            continue
        name = link.get_text(' ', strip=True)
        if not name.lower().endswith(('.rar', '.zip', '.7z', '.txt')):
            continue
        tip = row.select_one('.tip_c')
        price = tip.get_text(' ', strip=True) if tip else ''
        cost = re.search(r'下载积分:\s*(.+)', price)
        attachments.append({'attachmentId': aid, 'name': name, 'costText': cost[1].strip() if cost else '以论坛下载确认页为准'})
    book['attachments'] = attachments
    return book


class PrivateSessionStore:
    def __init__(self, root=None):
        self.root = Path(root) if root else config.CONFIG_DIR / 'attachment_accounts'

    def key(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.root / '.key'
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return path.read_bytes()
        key = secrets.token_bytes(32)
        with os.fdopen(fd, 'wb') as f:
            f.write(key)
        return key

    def path(self, user_id):
        return self.root / (hashlib.sha256(user_id.encode()).hexdigest() + '.session')

    def read(self, user_id):
        try:
            data = self.path(user_id).read_bytes()
            cipher = AES.new(self.key(), AES.MODE_GCM, nonce=data[:16])
            cipher.update(user_id.encode())
            return json.loads(cipher.decrypt_and_verify(data[32:], data[16:32]))
        except FileNotFoundError:
            return None
        except (ValueError, KeyError):
            raise HTTPException(409, "保存的书源会话无法读取，请重新绑定")

    def save(self, user_id, payload):
        cipher = AES.new(self.key(), AES.MODE_GCM)
        cipher.update(user_id.encode())
        ciphertext, tag = cipher.encrypt_and_digest(json.dumps(payload).encode())
        path = self.path(user_id)
        temp = path.with_suffix('.' + secrets.token_hex(8) + '.tmp')
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(cipher.nonce + tag + ciphertext)
        temp.replace(path)

    def remove(self, user_id):
        self.path(user_id).unlink(missing_ok=True)


class TxtNovelImportService:
    def __init__(self, store=None, downloads=None, transport=None, interval=1.2):
        self.store = store or PrivateSessionStore()
        self.downloads = downloads
        self.transport = transport
        self.interval = interval
        self._network_lock = asyncio.Lock()
        self._last_request = 0
        self._search_pages = {}

    def status(self, user_id):
        session = self.store.read(user_id)
        return {'bound': bool(session), 'username': session['username'] if session else None}

    def client(self, session=None):
        client = httpx.AsyncClient(timeout=30, follow_redirects=False, transport=self.transport,
                                   headers={'User-Agent': 'Mozilla/5.0'})
        for cookie in (session or {}).get('cookies', []):
            client.cookies.set(**cookie)
        return client

    async def request(self, client, method, url, *, limit=2*1024*1024, **kwargs):
        url = site_url(url)
        for _ in range(6):
            async with self._network_lock:
                delay = self.interval - (time.monotonic() - self._last_request)
                if delay > 0:
                    await asyncio.sleep(delay)
                self._last_request = time.monotonic()
                async with client.stream(method, url, **kwargs) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        url = site_url(urljoin(url, response.headers.get('location', '')))
                        if response.status_code in {301, 302, 303}:
                            method, kwargs = 'GET', {}
                        continue
                    if response.status_code != 200:
                        raise HTTPException(502, "书香门第暂时无法访问")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > limit:
                            raise HTTPException(502, "书源响应过大")
                    return bytes(data)
        raise HTTPException(502, "书源重定向过多")

    @staticmethod
    def authenticated(document):
        return bool(document.select_one('a[href*="action=logout"]'))

    async def login(self, user_id, username, password):
        async with self.client() as client:
            document = soup(await self.request(client, 'GET', BASE))
            form = document.select_one('#lsform')
            if not form:
                raise HTTPException(502, "书源登录表单已改变")
            data = {e['name']: e.get('value', '') for e in form.select('input[type="hidden"][name]')}
            data.update(fastloginfield='username', username=username, password=password, cookietime='2592000')
            try:
                encoded = urlencode(data, encoding='gbk').encode('ascii')
            except UnicodeError:
                raise HTTPException(400, "账号或密码包含论坛不支持的字符")
            response = await self.request(client, 'POST', form['action'], content=encoded,
                                          headers={'Content-Type': 'application/x-www-form-urlencoded', 'Referer': BASE})
            document = soup(response)
            if not self.authenticated(document):
                raise HTTPException(400, "书源登录未成功，请核对账号密码或在论坛处理验证码")
            session = {'username': username, 'cookies': [{'name': c.name, 'value': c.value, 'domain': c.domain, 'path': c.path} for c in client.cookies.jar]}
            self.store.save(user_id, session)
            return self.status(user_id)

    def session(self, user_id):
        session = self.store.read(user_id)
        if not session:
            raise HTTPException(409, "请先绑定书香门第账号")
        return session

    async def search(self, user_id, keyword, page):
        session = self.session(user_id)
        key = (user_id, keyword)
        async with self.client(session) as client:
            if page == 1:
                data = await self.request(client, 'GET', 'search.php?mod=forum')
                document = soup(data)
                form = document.select_one('form.searchform')
                if not form:
                    raise HTTPException(409, "论坛登录已过期或账号没有搜索权限，请重新绑定")
                fields = {e['name']: e.get('value', '') for e in form.select('input[type="hidden"][name]')}
                fields['srchtxt'] = keyword
                try:
                    encoded = urlencode(fields, encoding='gbk').encode('ascii')
                except UnicodeError:
                    raise HTTPException(400, "搜索词包含论坛不支持的字符")
                data = await self.request(client, 'POST', form['action'], content=encoded, headers={'Content-Type': 'application/x-www-form-urlencoded'})
                pages = {}
            else:
                expires, pages = self._search_pages.get(key, (0, {}))
                url = pages.get(page)
                if not url or expires < time.time():
                    return []
                data = await self.request(client, 'GET', url)
            document = soup(data)
            message = document.select_one('#messagetext')
            if message:
                raise HTTPException(429, to_simplified(message.get_text(' ', strip=True))[:200])
            items, next_url = parse_search(data)
            if next_url:
                pages[page+1] = next_url
            self._search_pages = {k: v for k,v in self._search_pages.items() if v[0] > time.time()}
            if len(self._search_pages) > 100:
                self._search_pages.pop(next(iter(self._search_pages)))
            self._search_pages[key] = (time.time()+600, pages)
            return items

    def sign(self, payload):
        data = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode()).decode()
        signature = hmac.new(self.store.key(), b'txtnovel-quote:' + data.encode(), hashlib.sha256).hexdigest()
        return data + '.' + signature

    def verify(self, token, user_id):
        try:
            data, signature = token.rsplit('.', 1)
            expected = hmac.new(self.store.key(), b'txtnovel-quote:' + data.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, signature):
                raise ValueError()
            payload = json.loads(base64.urlsafe_b64decode(data))
            if payload['user'] != user_id or payload['expires'] < time.time():
                raise ValueError()
            return payload
        except (ValueError, KeyError, TypeError):
            raise HTTPException(400, "下载确认已过期或无效，请重新查看附件")

    async def preview(self, user_id, thread_id):
        session = self.session(user_id)
        async with self.client(session) as client:
            detail = parse_detail(await self.request(client, 'GET', f'thread-{thread_id}-1-1.html'), thread_id)
            fingerprint = hashlib.sha256(json.dumps(session, sort_keys=True).encode()).hexdigest()
            for attachment in detail['attachments']:
                attachment['confirmationToken'] = self.sign({'user': user_id, 'thread': thread_id, 'attachment': attachment['attachmentId'], 'cost': attachment['costText'], 'session': fingerprint, 'expires': time.time()+900, 'nonce': secrets.token_hex(16)})
            return detail

    async def download(self, user_id, token):
        quote = self.verify(token, user_id)
        receipt = self.store.root / ('receipt-' + quote['nonce'] + '.json')
        raw_file = self.store.root / ('attachment-' + quote['nonce'] + '.bin')
        if receipt.exists():
            saved = json.loads(receipt.read_text())
            if saved['user'] != user_id:
                raise HTTPException(403, "下载记录不属于当前用户")
            if saved['state'] == 'completed':
                downloads = self.downloads
                if downloads is None:
                    from app.services.book_downloads import book_downloads
                    downloads = book_downloads
                book = downloads.repository.get(user_id, saved['bookId'])
                if book:
                    return book
            if saved['state'] == 'downloaded' and raw_file.is_file():
                # Recovery uses the saved file, never a second forum debit.
                book = await asyncio.to_thread(import_book, user_id, saved['metadata'], raw_file.read_bytes(), self.downloads)
                receipt.write_text(json.dumps({'user': user_id, 'state': 'completed', 'bookId': book['bookId']}))
                raw_file.unlink(missing_ok=True)
                return book
            raise HTTPException(409, "这次下载确认已使用；不会重复扣金币，请查看书库或论坛下载记录")
        session = self.session(user_id)
        fingerprint = hashlib.sha256(json.dumps(session, sort_keys=True).encode()).hexdigest()
        if fingerprint != quote['session']:
            raise HTTPException(409, "书源账号已变更，请重新确认下载")
        downloads = self.downloads
        if downloads is None:
            from app.services.book_downloads import book_downloads
            downloads = book_downloads
        existing = next((book for book in downloads.repository.shelf(user_id)
                         if book.get('imported') and book.get('sourceId') == SOURCE_ID
                         and book.get('threadId') == quote['thread']
                         and book.get('attachmentId') == quote['attachment']
                         and downloads.cached(user_id, book['bookId'], 'toc.json')), None)
        if existing:
            return existing
        async with self.client(session) as client:
            detail = parse_detail(await self.request(client, 'GET', f"thread-{quote['thread']}-1-1.html"), quote['thread'])
            attachment = next((a for a in detail['attachments'] if a['attachmentId'] == quote['attachment']), None)
            if not attachment or attachment['costText'] != quote['cost']:
                raise HTTPException(409, "附件或积分提示已改变，请重新查看并确认")
            data = await self.request(client, 'GET', f"plugin.php?id=yxf_attachdownconfirm:index&aid={quote['attachment']}")
            link = soup(data).select_one('#wp a[href*="mod=attachment"]')
            if not link:
                raise HTTPException(409, "论坛没有提供下载链接，请检查账号权限")
            download_url = site_url(link['href'])
            query = parse_qs(urlsplit(download_url).query)
            if query.get('mod') != ['attachment'] or urlsplit(download_url).path != '/forum.php':
                raise HTTPException(502, "下载地址格式已改变")
            # Durable O_EXCL claim BEFORE the spending request. Retries and
            # process crashes cannot automatically spend this confirmation twice.
            try:
                fd = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                raise HTTPException(409, "这次下载确认已使用；不会重复扣金币，请查看书库或论坛下载记录")
            with os.fdopen(fd, 'w') as f:
                json.dump({'user': user_id, 'state': 'requested', 'thread': quote['thread'], 'attachment': quote['attachment']}, f)
            try:
                payload = await self.request(client, 'GET', download_url, limit=8*1024*1024)
                metadata = {k: v for k,v in detail.items() if k != 'attachments'}
                metadata['attachmentId'] = quote['attachment']
                fd = os.open(raw_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as f:
                    f.write(payload)
                receipt.write_text(json.dumps({'user': user_id, 'state': 'downloaded', 'metadata': metadata}))
                book = await asyncio.to_thread(import_book, user_id, metadata, payload, self.downloads)
            except Exception as exc:
                # Do not expose URLs/cookies, and do not silently retry a debit.
                raise HTTPException(502, "下载或导入未完成，论坛可能已扣金币；不会自动重试，请先检查论坛下载记录") from exc
            receipt.write_text(json.dumps({'user': user_id, 'state': 'completed', 'bookId': book['bookId']}))
            raw_file.unlink(missing_ok=True)
            return book


txtnovel_import = TxtNovelImportService()

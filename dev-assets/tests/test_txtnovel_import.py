import io
import json
import zipfile
from types import SimpleNamespace
from urllib.parse import unquote_to_bytes
import httpx
import pytest
from fastapi import FastAPI, HTTPException
from app.api import auth, direct, attachment_sources
from app.services.book_downloads import BookDownloadService
from app.services.direct_aggregation import AggregateReadingService
from app.services.local_book_import import split_chapters, unpack_text
from app.services.txtnovel_import import PrivateSessionStore, TxtNovelImportService, parse_search, parse_detail, site_url
from app.services.user_auth import UserAuthService
from app.storage.db import initialize_database
from app.storage.direct_reading import DirectReadingRepository

TITLE = '《测试小说》作者：测试作者【完结】'
DETAIL = f'<span id="thread_subject">{TITLE}</span><p class="attnm"><a href="plugin.php?id=yxf_attachdownconfirm:index&aid=123">测试.rar</a><div class="tip_c">下载积分: 金币 -1 枚</div></p>'.encode('gbk')
SEARCH = f'<div id="threadlist"><li id="456"><h3><a>{TITLE}</a></h3><p>回复</p><p>介绍</p></li><li id="789"><h3><a>求书专用帖</a></h3></li></div><div class="pg"><a class="nxt" href="search.php?mod=forum&searchid=1&page=2">下一页</a></div>'.encode('gbk')
FORM = b'<form class="searchform" action="search.php?mod=forum"><input name="formhash" type="hidden" value="hash"><input name="searchsubmit" type="hidden" value="yes"></form>'
TEXT = '书名\n\n前言内容\n\n一\n\n' + '正文段落\n\n' * 10 + '二\n\n' + '第二部分\n\n' * 10 + '三\n\n' + '最后正文\n\n' * 10

def archive(text=TEXT, names=('book.txt',)):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        for name in names: z.writestr(name, text)
    return stream.getvalue()

@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / 'app.db'
    initialize_database(db)
    repo = DirectReadingRepository(db)
    accounts = UserAuthService(db)
    a = accounts.create_user('Alice', 'password-alice')['userId']
    b = accounts.create_user('Bob', 'password-bob')['userId']
    downloads = BookDownloadService(repository=repo, root=tmp_path / 'books')
    debit, requests = [], []
    def responder(request):
        requests.append((request.method, str(request.url)))
        path = request.url.path
        if path == '/': return httpx.Response(200, content=b'<form id="lsform" action="member.php?login=yes"><input name="quickforward" type="hidden" value="yes"></form>')
        if path == '/member.php': return httpx.Response(200, content=b'<a href="member.php?action=logout">logout</a>', headers={'Set-Cookie': 'auth=cookie-secret; Path=/'})
        if path == '/search.php':
            if request.method == 'POST':
                assert '测试'.encode('gbk') in unquote_to_bytes(request.content.decode())
                return httpx.Response(200, content=SEARCH)
            return httpx.Response(200, content=SEARCH if 'page=2' in str(request.url) else FORM)
        if path.startswith('/thread-'): return httpx.Response(200, content=DETAIL)
        if path == '/plugin.php': return httpx.Response(200, content=b'<div id="wp"><a href="forum.php?mod=attachment&aid=signed">download</a></div>')
        if path == '/forum.php':
            debit.append(1)
            return httpx.Response(200, content=archive())
        raise AssertionError(request)
    store = PrivateSessionStore(tmp_path / 'sessions')
    service = TxtNovelImportService(store, downloads, httpx.MockTransport(responder), interval=0)
    store.save(a, {'username': 'forum-A', 'cookies': [{'name': 'auth', 'value': 'cookie-secret', 'domain': 'www.txtnovel.vip', 'path': '/'}]})
    for module in (attachment_sources, direct):
        monkeypatch.setattr(module, 'txtnovel_import', service)
        monkeypatch.setattr(module, 'auth_service', accounts)
    monkeypatch.setattr(auth, 'auth_service', accounts)
    monkeypatch.setattr(direct, 'direct_repository', repo)
    monkeypatch.setattr(direct, 'book_downloads', downloads)
    async def empty_search(*args):
        if False:
            yield {}
    reader = SimpleNamespace(search=empty_search, sources=lambda: [], book_target=lambda _: (_ for _ in ()).throw(HTTPException(404, 'invalid source')))
    monkeypatch.setattr(direct, 'direct_reading', reader)
    monkeypatch.setattr(direct, 'aggregate_reading', AggregateReadingService(reader, repo))
    app = FastAPI()
    app.state.entrypoint = 'combined'
    app.include_router(auth.router)
    app.include_router(direct.router)
    return service, repo, downloads, a, b, debit, requests, app

def test_session_encryption_user_boundary(env):
    service, _, _, a, b, *_ = env
    assert service.status(a) == {'bound': True, 'username': 'forum-A', 'enabled': True}
    assert not service.status(b)['bound']
    payload = service.store.path(a).read_bytes()
    assert b'cookie-secret' not in payload
    assert service.store.path(a).stat().st_mode & 0o777 == 0o600
    service.store.path(b).write_bytes(payload)
    with pytest.raises(HTTPException): service.status(b)

async def test_plugin_management_disables_attachment_operations(env, monkeypatch):
    from app.api import console
    from app.core.app_config import AppConfig
    from app.services import attachment_plugin

    service, _, _, a, _, debit, requests, _ = env
    enabled = {}
    cfg = SimpleNamespace(
        is_plugin_enabled=lambda key, default=True: enabled.get(key, default),
        set_plugin_enabled=lambda key, value: enabled.update({key: value}),
    )
    monkeypatch.setattr(AppConfig, 'get', lambda: cfg)
    monkeypatch.setattr(attachment_plugin, 'txtnovel_import', service)
    scheduler = SimpleNamespace(_plugins={}, config={})
    monkeypatch.setattr(console, '_plugin_scheduler', scheduler)
    item = console.list_plugins()['items'][0]
    assert (item['pluginId'], item['origin'], item['category'], item['attachmentSource']) == ('txtnovel_vip', 'custom', 'completed', True)
    assert console.enable_plugin('txtnovel_vip', {'enabled': False})['enabled'] is False
    assert console.get_plugin('txtnovel_vip')['enabled'] is False
    assert service.status(a)['bound'] is True
    for operation in (
        lambda: service.login(a, 'forum-A', 'unused'),
        lambda: service.search(a, '测试', 1),
        lambda: service.preview(a, '456'),
        lambda: service.download(a, 'unused'),
    ):
        with pytest.raises(HTTPException, match='书香门第插件已停用'):
            await operation()
    assert requests == [] and debit == []
    service.store.remove(a)
    assert service.status(a)['bound'] is False
    assert console.batch_enable_plugins({'pluginIds': ['txtnovel_vip'], 'enabled': True})['results'][0]['enabled'] is True
    assert console.get_plugin('txtnovel_vip')['enabled'] is True


def test_parsers_safe_url():
    items, next_url = parse_search(SEARCH)
    assert len(items) == 1 and items[0]['name'] == '测试小说'
    assert items[0]['author'] == '测试作者' and 'page=2' in next_url
    assert parse_detail(DETAIL, '456')['attachments'][0]['costText'] == '金币 -1 枚'
    for url in ('http://localhost/admin', '//evil.example/', 'http://www.txtnovel.vip:4567/private', 'file:///etc/passwd'):
        with pytest.raises(HTTPException): site_url(url)

def test_encoding_archive_paths():
    assert unpack_text(archive(names=('../../never-written.txt',)))[1] == TEXT
    assert unpack_text(TEXT.encode('gbk'))[1] == TEXT
    for data in (archive(names=('a.txt', 'b.txt')), b'<html>' + b'login required' * 30, b'Rar!broken'):
        with pytest.raises(HTTPException): unpack_text(data)

def test_chapter_splitting_preserves_text():
    chapters = split_chapters(TEXT, '书名')
    assert [c['title'] for c in chapters] == ['前言', '一', '二', '三']
    assert [c['index'] for c in chapters] == list(range(4))
    assert '最后正文' in chapters[-1]['content']
    assert len(split_chapters('他说一。\n二是答案。\n三人同行。' * 10, '书')) == 1
    assert len(split_chapters('第一章 开始\n正文\n第二章 结尾\n最后', '书')) == 2

async def test_login_search_pagination_without_debit(env):
    service, _, _, a, b, debit, *_ = env
    await service.login(b, 'forum-B', 'private-password')
    assert 'private-password' not in json.dumps(service.store.read(b))
    assert (await service.search(a, '测试', 1))[0]['threadId'] == '456'
    assert len(await service.search(a, '测试', 2)) == 1
    assert await service.search(b, '测试', 2) == []
    assert (await service.preview(a, '456'))['attachments']
    assert not debit

async def test_explicit_download_token_replay(env):
    service, repo, downloads, a, b, debit, *_ = env
    token = (await service.preview(a, '456'))['attachments'][0]['confirmationToken']
    for user, value in ((b, token), (a, token + 'x')):
        with pytest.raises(HTTPException): await service.download(user, value)
    assert not debit
    book = await service.download(a, token)
    assert book['imported'] and len(debit) == 1
    assert (await service.download(a, token))['bookId'] == book['bookId']
    new_token = (await service.preview(a, '456'))['attachments'][0]['confirmationToken']
    assert (await service.download(a, new_token))['bookId'] == book['bookId']
    assert len(debit) == 1 and repo.shelf(b) == []
    assert not downloads.cached(b, book['bookId'], 'toc.json')
    assert downloads.cached(a, book['bookId'], 'toc.json')['chapters'][-1]['title'] == '三'
    assert downloads.file(a, book['bookId']).read_text() == TEXT
    with pytest.raises(HTTPException): downloads.file(b, book['bookId'])

async def test_network_failure_no_repeat_debit(env, monkeypatch):
    service, _, _, a, _, debit, *_ = env
    token = (await service.preview(a, '456'))['attachments'][0]['confirmationToken']
    original = service.request
    async def fail(client, method, url, **kwargs):
        if 'mod=attachment' in url:
            debit.append(1)
            raise httpx.ReadTimeout('failed')
        return await original(client, method, url, **kwargs)
    monkeypatch.setattr(service, 'request', fail)
    for _ in range(2):
        with pytest.raises(HTTPException): await service.download(a, token)
    assert len(debit) == 1

async def test_session_change_invalidates_quote(env):
    service, _, _, a, *_ = env
    token = (await service.preview(a, '456'))['attachments'][0]['confirmationToken']
    service.store.save(a, {'username': 'other', 'cookies': []})
    with pytest.raises(HTTPException) as error: await service.download(a, token)
    assert error.value.status_code == 409

async def test_personal_reader_api(env):
    service, repo, downloads, a, b, debit, requests, app = env
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://testserver') as client:
        assert (await client.get('/api/direct/attachments/txtnovel/account')).status_code == 401
        await client.post('/api/auth/login', json={'username': 'Alice', 'password': 'password-alice'})
        assert (await client.get('/api/direct/sources')).json()['items'][0]['id'] == 'txtnovel_vip'
        result = await client.get('/api/direct/search', params={'keyword': '测试', 'sources': 'txtnovel_vip'})
        assert '测试小说' in result.text and not debit
        preview = (await client.get('/api/direct/attachments/txtnovel/preview?threadId=456')).json()
        assert (await client.post('/api/direct/attachments/txtnovel/download', json={})).status_code == 422
        result = await client.post('/api/direct/attachments/txtnovel/download', json={'confirmationToken': preview['attachments'][0]['confirmationToken']})
        assert result.status_code == 200, result.text
        book = result.json()
        prefix = '/api/direct/books/' + book['bookId']
        for route in ('/detail', '/toc', '/overview', '/chapters/0', '/chapters/2', '/chapters/3', '/progress', '/download/file'):
            response = await client.get(prefix + route)
            assert response.status_code == 200, (route, response.text)
        assert (await client.put(prefix + '/progress', json={'chapterIndex': 2, 'position': .4, 'revision': 0})).status_code == 200
        assert len(debit) == 1
        request_count = len(requests)
        await client.post('/api/auth/login', json={'username': 'Bob', 'password': 'password-bob'})
        assert (await client.get('/api/direct/sources')).json()['items'] == []
        for route in ('/detail', '/toc', '/overview', '/chapters/0', '/progress', '/download/file'):
            assert (await client.get(prefix + route)).status_code == 404
        assert len(requests) == request_count

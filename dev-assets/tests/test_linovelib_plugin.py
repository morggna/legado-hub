from pathlib import Path

import pytest

from app.services.library_books import LibraryBooksService
from app.source_plugins.context import PluginContext
from app.source_plugins.errors import ParseError, SourceRemoved
from app.source_plugins.loader import PluginLoader
from app.source_plugins.smoke import FixtureFetcher, _fixture_map, load_smoke_spec, run_fixture_smoke

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / 'plugins/sources/thirdparty/linovelib_com'
BASE = 'https://www.bilinovel.com'
BOOK = BASE + '/novel/3095.html'
TOC = BASE + '/novel/3095/catalog'
LONG = BASE + '/novel/3095/154933.html'


@pytest.fixture
def adapter():
    plugin = PluginLoader(PLUGIN).load_all()['linovelib_com']
    spec = load_smoke_spec(PLUGIN)
    fetcher = FixtureFetcher(_fixture_map(PLUGIN, spec), spec['searchProviderHits'])
    return plugin, PluginContext(fetcher, plugin.metadata.id)


async def test_fixture_chain(adapter):
    plugin, _ = adapter
    result = await run_fixture_smoke(plugin, PLUGIN)
    assert result['pass'], result


async def test_search_subscription_metadata_and_aliases(adapter, tmp_path):
    plugin, ctx = adapter
    item, = await plugin.source.search(ctx, '败北女角', 1)
    assert item['author'] == '雨森焚火'
    assert item['bookStatus'] == '连载'
    assert item['chapterCount'] == 221
    assert item['extra']['unavailableChapters'] == 9
    assert '温水和彦' in item['intro']
    assert item['extra']['aliases'] == '败犬女主太多了！'
    payload = LibraryBooksService(tmp_path/'unused.db')._payload_from_group({'items': [{**item, 'sourceName': plugin.metadata.name}]})
    assert payload['totalChaptersAtSubscribe'] == 221
    assert payload['bookStatus'] == '连载'
    assert all(payload['sources'][0][k] for k in ('bookUrl', 'tocUrl', 'lastChapter', 'bookStatus'))
    assert await plugin.source.search(ctx, '败犬女主', 1) == [item]
    assert await plugin.source.search(ctx, '3095', 1) == [item]
    assert await plugin.source.search(ctx, 'https://www.linovelib.com/novel/3095/catalog', 1) == [item]
    assert await plugin.source.search(ctx, '不存在的书', 1) == []
    assert await plugin.source.search(ctx, '败北女角', 2) == []


async def test_catalog_retains_volumes_and_unavailable_entries(adapter):
    plugin, ctx = adapter
    chapters = await plugin.source.toc(ctx, TOC)
    assert len(chapters) == 221 == len({c['chapterUrl'] for c in chapters})
    assert [c['index'] for c in chapters] == list(range(1, 222))
    assert len({c['extra']['volume'] for c in chapters}) == 12
    locked = [c for c in chapters if c['isLocked']]
    assert len(locked) == 9
    for chapter in locked:
        assert chapter['chapterUrl'].startswith(TOC+'#unavailable-')
        assert '原站未开放' in chapter['title']
        with pytest.raises(SourceRemoved):
            await plugin.source.chapter(ctx, chapter['chapterUrl'])


async def test_long_chapter_all_nine_pages_and_browser_order(adapter):
    plugin, ctx = adapter
    result = await plugin.source.chapter(ctx, LONG)
    assert result['extra']['pageCount'] == 9
    assert len(result['content']) > 24000
    # Oracle captured from visible paragraphs in a normal desktop browser,
    # after the site's own chapterlog completed, excluding zero-size decoys.
    expected = ['印象中她在转学第一天自我介绍时，就马上大喊着『啊～！你就是那个痴汉！』之类的，与绔田大吵一架。',
                '话说回来，她要转学了喔？英国？转折也太快了吧？', '「为什么妳会知道这种事啊？」',
                '「我就是知道！因为，我也一直对草介……」', '八奈见咬紧嘴唇，垂下脸。', '「杏菜，我——」',
                '「别说了，没关系。」', '八奈见坚强地抬起脸，站起身把自行车的钥匙摆到桌上。',
                '「去找她吧。华恋正在等你喔。」', '「……没关系吗？」',
                '「华恋是个好女孩嘛。不让人家幸福，我可不会饶你喔。」',
                '「谢谢妳。我这就去向华恋表达我的心意。」', '「加油喔。万一你被甩了，我会好心听你诉苦的。」',
                '「……抱歉，杏菜。」', '语毕，绔田便冲出了餐厅。一次也不曾回头看向八奈见。']
    assert result['content'].split('\n\n')[20:35] == expected
    assert result['content'].count(expected[0]) == 1
    assert '加载失败' not in result['content']
    # Versioned script is requested once within this chapter operation.
    assert sum('chapterlog.js' in t['url'] for t in ctx._fetcher._traces) == 1


async def test_illustrations_and_short_body(adapter):
    plugin, ctx = adapter
    result = await plugin.source.chapter(ctx, BASE+'/novel/3095/154931.html')
    # The site exposes nine images and withholds the rest in #hidden-images.
    # Only the public visible set is returned, with translator credits intact.
    assert len(result['extra']['illustrationUrls']) == 9
    assert result['extra']['illustrationUrls'][-1].endswith('/200734.jpg')
    assert '公子夜殇' in result['content']
    assert '[插图 1]' in result['content']
    assert all(u in result['content'] for u in result['extra']['illustrationUrls'])
    short = await plugin.source.chapter(ctx, BASE+'/novel/3095/154932.html')
    assert len(short['content']) > 250
    assert short['extra']['pageCount'] == 1


async def test_real_mushoku_titles_match_catalog_including_volume(adapter):
    from app.services.direct_aggregation import AggregateReadingService
    plugin, original = adapter
    data = original._fetcher._url_to_text.copy()
    for path, file in [('catalog', 'mushoku-toc.html'), ('122012.html', 'mushoku-illustrations.html'),
                       ('235372.html', 'mushoku-design.html')]:
        data[BASE+'/novel/2013/'+path] = (PLUGIN/'smoke/fixtures'/file).read_text()
    ctx = PluginContext(FixtureFetcher(data), plugin.metadata.id)
    toc = await plugin.source.toc(ctx, BASE+'/novel/2013/catalog')
    for index in (0, 15):
        chapter = await plugin.source.chapter(ctx, toc[index]['chapterUrl'])
        assert chapter['title'] == toc[index]['title']
        assert AggregateReadingService().same_chapter(toc[index]['title'], chapter['title'])
        assert '幼年期' in chapter['title']


def test_authenticated_api_search_add_and_aggregate_reader(adapter, tmp_path, monkeypatch):
    """Exercise the actual shelf reader path, not just raw single-source APIs."""
    import json
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api import direct as api
    from app.services.direct_aggregation import AggregateReadingService
    from app.services.direct_reading import DirectReadingService
    from app.services.user_auth import UserAuthService
    from app.source_plugins.scheduler import PluginScheduler
    from app.storage.db import initialize_database
    from app.storage.direct_reading import DirectReadingRepository
    plugin, ctx = adapter
    db = tmp_path/'reader.db'
    initialize_database(db)
    auth = UserAuthService(db)
    auth.bootstrap_admin('tester', 'reader-test-password')
    uid = auth.get_user_by_username('tester')['userId']
    scheduler = PluginScheduler(PluginLoader(PLUGIN), config={})
    # Fixture transport has no network; request pacing has separate regressions.
    monkeypatch.setattr(scheduler, '_rate_limiter_for', lambda plugin: None)
    monkeypatch.setattr(scheduler, '_make_ctx', lambda source: PluginContext(
        FixtureFetcher(ctx._fetcher._url_to_text.copy(), ctx._fetcher.search_provider_hits), source))
    reader = DirectReadingService(scheduler)
    repository = DirectReadingRepository(db)
    aggregate = AggregateReadingService(reader, repository)
    monkeypatch.setattr(api, 'direct_reading', reader)
    monkeypatch.setattr(api, 'aggregate_reading', aggregate)
    monkeypatch.setattr(api, 'direct_repository', repository)
    monkeypatch.setattr(api, 'book_downloads', SimpleNamespace(cached=lambda *args: None))
    monkeypatch.setattr(api.auth_service, 'require_user', lambda request: SimpleNamespace(user_id=uid))
    monkeypatch.setattr('app.services.live_acceptance.get_plugin_scheduler', lambda: scheduler)
    client = TestClient(app, base_url='http://localhost')
    r = client.get('/api/direct/search', params={'keyword': '败北女角', 'sources': 'linovelib_com'})
    assert r.status_code == 200, r.text
    event = next(json.loads(line[6:]) for line in r.text.splitlines() if line.startswith('data: ') and line != 'data: {}')
    assert event['items'] and not event.get('error'), event
    r = client.post('/api/direct/shelf', json={'sourceBookIds': event['groups'][0]['sourceBookIds']})
    assert r.status_code == 200, r.text
    book = r.json()['bookId']
    assert book.startswith('agg-')
    r = client.get(f'/api/direct/books/{book}/toc')
    assert r.status_code == 200 and len(r.json()['chapters']) == 221
    for index in (0, 2):
        r = client.get(f'/api/direct/books/{book}/chapters/{index}')
        assert r.status_code == 200, r.text
        assert r.json()['aggregation']['selectedSourceId'] == 'linovelib_com'
        assert len(r.json()['content']) > (24000 if index == 2 else 250)
    client.close()


@pytest.mark.parametrize('variant', ['truncated', 'loop', 'cross-book', 'missing-page', 'script-change'])
async def test_incomplete_or_unknown_protocol_is_error(adapter, variant):
    plugin, original = adapter
    data = original._fetcher._url_to_text.copy()
    if variant == 'truncated':
        data[LONG] = (PLUGIN/'smoke/fixtures/truncated.html').read_text()
    elif variant == 'loop':
        data[LONG] = data[LONG].replace("url_next:'/novel/3095/154933_2.html'", "url_next:'/novel/3095/154933_1.html'")
    elif variant == 'cross-book':
        data[LONG] = data[LONG].replace("url_next:'/novel/3095/154933_2.html'", "url_next:'/novel/3096/154933_2.html'")
    elif variant == 'missing-page':
        data[BASE+'/novel/3095/154933_2.html'] = '<html>内容为空</html>'
    elif variant == 'script-change':
        data[BASE+'/themes/zhmb/js/chapterlog.js?v1006c1.82'] = 'alert("changed")'
    with pytest.raises(ParseError):
        await plugin.source.chapter(PluginContext(FixtureFetcher(data), plugin.metadata.id), LONG)


@pytest.mark.parametrize('url', ['https://evil.test/novel/3095.html', 'https://www.bilinovel.com.evil.test/novel/3095.html',
                                'https://user@www.bilinovel.com/novel/3095.html', 'http://127.0.0.1/novel/3095.html',
                                'https://www.bilinovel.com/novel/3095.html?proxy=evil', 'https://www.bilinovel.com/login.php'])
async def test_reject_nonbook_urls(adapter, url):
    plugin, ctx = adapter
    with pytest.raises(ParseError):
        await plugin.source.search(ctx, url, 1)


async def test_request_style_cookie_and_script_arithmetic_are_safe(adapter):
    plugin, original = adapter
    calls = []
    class Capture(FixtureFetcher):
        async def fetch_text(self, url, **kwargs):
            calls.append(kwargs)
            return await super().fetch_text(url, **kwargs)
    ctx = PluginContext(Capture(original._fetcher._url_to_text), plugin.metadata.id)
    await plugin.source.chapter(ctx, BASE+'/novel/3095/154932.html')
    assert all(c['headers']['Cookie'] == 'night=0' and c['impersonate'] == 'chrome124' for c in calls)
    integer = plugin.module._integer
    assert integer('0x10*2-3') == 29
    for expression in ('__import__("os").system("bad")', '2**100', '1/0', 'True'):
        with pytest.raises(ParseError):
            integer(expression)

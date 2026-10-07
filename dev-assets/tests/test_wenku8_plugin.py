from pathlib import Path

import pytest
from app.source_plugins.context import PluginContext
from app.source_plugins.errors import ParseError, ParseEmpty
from app.source_plugins.loader import PluginLoader
from app.source_plugins.smoke import FixtureFetcher, _fixture_map, load_smoke_spec, run_fixture_smoke
from app.services.library_books import LibraryBooksService

pytestmark = pytest.mark.asyncio

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / 'plugins/sources/thirdparty/wenku8_net'
BASE = 'https://www.wenku8.net'
BOOK = BASE + '/book/3057.htm'
TOC = BASE + '/novel/3/3057/index.htm'
CHAPTER = BASE + '/novel/3/3057/125416.htm'


@pytest.fixture
def adapter():
    plugin = PluginLoader(PLUGIN).load_all()['wenku8_net']
    spec = load_smoke_spec(PLUGIN)
    fetcher = FixtureFetcher(_fixture_map(PLUGIN, spec), spec['searchProviderHits'])
    return plugin, PluginContext(fetcher, plugin.metadata.id)


async def test_complete_fixture_chain(adapter):
    plugin, _ = adapter
    result = await run_fixture_smoke(plugin, PLUGIN)
    assert result['pass'], result


async def test_search_and_subscription_preserve_complete_metadata(adapter, tmp_path):
    plugin, ctx = adapter
    items = await plugin.source.search(ctx, '败北女角', 1)
    assert len(items) == 1
    item = items[0]
    assert item['author'] == '雨森焚火'
    assert item['bookStatus'] == '连载中'
    assert item['chapterCount'] == 234
    assert item['intro'].startswith('平常担任')
    assert item['wordCount'] == '1273455字'
    assert item['coverUrl'].startswith('https://img.wenku8.com/')
    payload = LibraryBooksService(tmp_path / 'unused.db')._payload_from_group({'items':[{**item,'sourceName':plugin.metadata.name}]})
    assert payload['totalChaptersAtSubscribe'] == 234
    assert payload['bookStatus'] == '连载中'
    assert all(payload['sources'][0][key] for key in ('bookId','sourceId','sourceName','bookUrl','tocUrl','lastChapter','bookStatus'))


async def test_link_id_and_search_page(adapter):
    plugin, ctx = adapter
    by_link = await plugin.source.search(ctx, BOOK, 1)
    assert by_link == await plugin.source.search(ctx, '3057', 1)
    assert await plugin.source.search(ctx, '败犬', 2) == []
    assert await plugin.source.search(ctx, '', 1) == []


@pytest.mark.parametrize('url', ['https://evil.test/book/3057.htm','https://www.wenku8.net.evil.test/book/3057.htm','http://127.0.0.1/book/3057.htm','https://user@www.wenku8.net/book/3057.htm','https://www.wenku8.net/login.php'])
async def test_reject_foreign_or_nonbook_urls(adapter, url):
    plugin, ctx = adapter
    with pytest.raises(ParseError):
        await plugin.source.search(ctx, url, 1)


async def test_volumes_and_illustrations_are_not_dropped(adapter):
    plugin, ctx = adapter
    chapters = await plugin.source.toc(ctx, TOC)
    assert len(chapters) == len({ch['chapterUrl'] for ch in chapters}) == 234
    assert chapters[0]['title'] == '第一卷 序'
    assert chapters[17]['title'] == '第二卷 序'
    assert [c['index'] for c in chapters] == list(range(1, 235))
    images = await plugin.source.chapter(ctx, BASE+'/novel/3/3057/125425.htm')
    assert len(images['extra']['illustrationUrls']) > 5
    assert '[插图 1]' in images['content']
    assert all(url in images['content'] for url in images['extra']['illustrationUrls'])


async def test_gbk_and_targeted_watermark_removal(adapter):
    plugin, ctx = adapter
    class GbkFetcher(FixtureFetcher):
        async def fetch_bytes(self, url, **kwargs):
            return (await self.fetch_text(url, **kwargs)).encode('gb18030')
    data = ctx._fetcher._url_to_text.copy()
    data[CHAPTER] = data[CHAPTER].replace('第一学期', '我在轻小说文库看到这句话。第一学期')
    result = await plugin.source.chapter(PluginContext(GbkFetcher(data), plugin.metadata.id), CHAPTER)
    assert '我在轻小说文库看到这句话。第一学期' in result['content']
    assert '图源：公子夜殇' in result['content']
    assert '本文来自' not in result['content']
    assert '为你一网打尽' not in result['content']
    assert '\n\n' in result['content']
    assert '\ufffd' not in result['content']


@pytest.mark.parametrize('html', ['<title>Just a moment...</title>','<form>请登录</form>','<div id="title">正文</div><div id="content"><ul id="contentdp">广告</ul></div>'])
async def test_restricted_or_empty_pages_are_errors(adapter, html):
    plugin, _ = adapter
    ctx = PluginContext(FixtureFetcher({CHAPTER: html}), plugin.metadata.id)
    with pytest.raises((ParseError, ParseEmpty)):
        await plugin.source.chapter(ctx, CHAPTER)


# Synthetic format fixture; contains no copied novel text.
def native_fixture(titles=('第一卷 序', '第一卷 插图', '第二卷 尾声')):
    chapters = [{'title': title, 'chapterUrl': BASE + f'/novel/3/3057/{i}.htm'} for i, title in enumerate(titles)]
    data = ('★☆★☆★☆轻小说文库(Www.WenKu8.Com)☆★☆★☆★\r\n\r\n<测试书>\r\n\r\n'
            + titles[0] + '\r\n\r\n    译者署名\r\n    测试正文一\r\n\r\n'
            + titles[1] + '\r\n\r\n'
            + titles[2] + '\r\n\r\n    测试正文二\r\n'
            + '◆◇◆◇\r\n更多精彩热门日本轻小说、动漫小说，尽在轻小说文库(Www.WenKu8.Com)').encode()
    return chapters, data


async def test_native_endpoint_and_empty_illustration_fallback(adapter, monkeypatch):
    plugin, ctx = adapter
    chapters, data = native_fixture()
    urls = []
    async def fetch(url, **kwargs):
        urls.append(url)
        if '/novel/' in url:
            return '<div id="title">序</div><div id="content">测试正文</div>'.encode()
        return data
    monkeypatch.setattr(ctx.access.stealth, 'fetch_bytes', fetch)
    result = await plugin.source.full_book(ctx, BOOK, chapters, name='测试书')
    assert urls == [chapters[0]['chapterUrl'], 'https://dl1.wenku8.com/down/txtutf8/3/3057.txt']
    assert [c['title'] for c in result] == ['第一卷 序', '第二卷 尾声']
    assert result[0]['content'] == '译者署名\n\n测试正文一'
    assert '轻小说文库' not in result[-1]['content']


@pytest.mark.parametrize('damage', ['html', 'truncated', 'missing', 'duplicate', 'order', 'encoding', 'wrong_book'])
async def test_native_rejects_unreliable_files(adapter, damage):
    plugin, _ = adapter
    chapters, data = native_fixture()
    text = data.decode()
    if damage == 'html':
        data = b'<html>Login</html>'
    elif damage == 'truncated':
        data = data[:-100]
    elif damage == 'missing':
        data = text.replace('第二卷 尾声', '第二卷 旧尾声').encode()
    elif damage == 'duplicate':
        data = text.replace('测试正文一', '测试正文一\r\n第一卷 序').encode()
    elif damage == 'order':
        chapters = list(reversed(chapters))
    elif damage == 'encoding':
        data += b'\xff'
    else:
        data = text.replace('<测试书>', '<另一本书>').encode()
    with pytest.raises(ParseError):
        plugin.source._parse_full_book(data, chapters, '测试书')


async def test_native_rejects_cross_book_toc_before_network(adapter):
    plugin, ctx = adapter
    chapters, _ = native_fixture()
    chapters[0]['chapterUrl'] = BASE + '/novel/3/3058/1.htm'
    with pytest.raises(ParseError, match='另一本书'):
        await plugin.source.full_book(ctx, BOOK, chapters, name='测试书')


async def test_removed_notice_is_not_prose_and_native_download_respects_it(adapter, monkeypatch):
    from app.source_plugins.errors import SourceRemoved
    plugin, ctx = adapter
    chapters, _ = native_fixture()
    urls = []
    async def fetch(url, **kwargs):
        urls.append(url)
        return '<div id="title">序</div><div id="content">因版权问题，文库不再提供该小说的阅读！</div>'.encode()
    monkeypatch.setattr(ctx.access.stealth, 'fetch_bytes', fetch)
    with pytest.raises(SourceRemoved):
        await plugin.source.chapter(ctx, chapters[0]['chapterUrl'])
    with pytest.raises(SourceRemoved):
        await plugin.source.full_book(ctx, BOOK, chapters, name='测试书')
    assert all('dl1.wenku8.com' not in url for url in urls)


async def test_native_name_middle_dot_variant_preserves_toc_title_and_body(adapter):
    plugin, _ = adapter
    chapters, data = native_fixture(('第二卷 「妮娜•布里兹」', '第二卷 插图', '第三卷 尾声'))
    data = data.replace('妮娜•布里兹'.encode(), '妮娜·布里兹'.encode())
    data = data.replace('测试正文一'.encode(), '正文保留姓名吉诺•布里兹及标点。'.encode())
    result = plugin.source._parse_full_book(data, chapters, '测试书')
    assert result[0]['title'] == '第二卷 「妮娜•布里兹」'
    assert result[0]['chapterUrl'] == chapters[0]['chapterUrl']
    assert '正文保留姓名吉诺•布里兹及标点。' in result[0]['content']


@pytest.mark.parametrize('damage', ['toc_collision', 'file_collision', 'other_punctuation'])
async def test_native_typography_normalization_does_not_weaken_completeness(adapter, damage):
    plugin, _ = adapter
    chapters, data = native_fixture(('第二卷 「妮娜•布里兹」', '第二卷 插图', '第三卷 尾声'))
    if damage == 'toc_collision':
        chapters[1]['title'] = '第二卷 「妮娜·布里兹」'
    elif damage == 'file_collision':
        data = data.replace('测试正文一'.encode(), '测试正文一\r\n第二卷 「妮娜·布里兹」'.encode())
    else:
        data = data.replace('妮娜•布里兹'.encode(), '妮娜-布里兹'.encode())
    with pytest.raises(ParseError):
        plugin.source._parse_full_book(data, chapters, '测试书')


async def test_native_numeric_entities_in_headings_leave_prose_intact(adapter):
    plugin, _ = adapter
    chapters, data = native_fixture(('第六卷 ⓪ 序', '第六卷 插图', '第七卷 尾声♥'))
    data = data.replace('⓪'.encode(), b'&#9450;').replace('♥'.encode(), b'&#x2665;')
    data = data.replace('测试正文一'.encode(), b'Literal &#9450; stays in prose.')
    result = plugin.source._parse_full_book(data, chapters, '测试书')
    assert result[0]['title'] == '第六卷 ⓪ 序'
    assert result[-1]['title'] == '第七卷 尾声♥'
    assert 'Literal &#9450; stays in prose.' in result[0]['content']


def repeated_heading_fixture():
    titles=['第十二卷 interlude…','第十二卷 第一章','第十二卷 interlude…','第十二卷 第二章','第十二卷 interlude…']
    chapters=[{'title':t,'chapterUrl':BASE+f'/novel/3/3057/{i}.htm'} for i,t in enumerate(titles)]
    text='★☆★☆★☆轻小说文库(Www.WenKu8.Com)☆★☆★☆★\n\n<测试书>\n\n'
    text+='\n\n'.join(f'{title}\n\n    段落 {i}' for i,title in enumerate(titles))
    text+='\n◆◇◆◇\n更多精彩热门日本轻小说、动漫小说，尽在轻小说文库(Www.WenKu8.Com)'
    return chapters,text.encode()


async def test_native_repeated_interludes_require_full_sequence_and_bind_unique_urls(adapter):
    plugin, _ = adapter
    chapters,data=repeated_heading_fixture()
    result=plugin.source._parse_full_book(data,chapters,'测试书')
    assert [c['chapterUrl'] for c in result] == [c['chapterUrl'] for c in chapters]
    assert [c['title'] for c in result] == [c['title'] for c in chapters]
    assert [c['content'] for c in result] == [f'段落 {i}' for i in range(5)]


@pytest.mark.parametrize('damage',['missing','extra','reordered'])
async def test_native_repeated_interludes_reject_incomplete_or_reordered_occurrences(adapter,damage):
    plugin, _ = adapter
    chapters,data=repeated_heading_fixture()
    text=data.decode()
    if damage=='missing':
        text=text.replace('第十二卷 interlude…\n\n    段落 2','第十二卷 不同标题\n\n    段落 2')
    elif damage=='extra':
        text=text.replace('    段落 2','    段落 2\n\n第十二卷 interlude…\n\n    多余段落')
    else:
        text=text.replace('第十二卷 第一章','第十二卷 暂存').replace('第十二卷 第二章','第十二卷 第一章').replace('第十二卷 暂存','第十二卷 第二章')
    with pytest.raises(ParseError):
        plugin.source._parse_full_book(text.encode(),chapters,'测试书')

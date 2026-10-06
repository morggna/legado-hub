import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.direct_aggregation import AggregateReadingService, grouped_books, identity
from app.services.direct_reading import DirectReadingService
from app.services.book_downloads import BookDownloadService
from app.services.user_auth import UserAuthService
from app.storage.direct_reading import DirectReadingRepository
from app.storage.db import initialize_database
from app.source_plugins.id_codec import encode_book_id

BODY = '\n'.join(f'山河万里行人远去。沿路的风景各有不同，少年驻足细看。这是旅途中的第{i}处风景。' for i in range(24))


class Sources:
    def __init__(self):
        self._plugins = {}
        self.calls = []
        self.tocs = {}
        self.bodies = {}
        self.authors = {}
        for source in 'abcd':
            meta = SimpleNamespace(id=source, name=source, enabled=True, domains=[f'{source}.example'], base_urls=[], auth={'mode': 'none'}, content={'access':'free'}, is_official_source=lambda:False)
            self._plugins[source] = SimpleNamespace(metadata=meta, capabilities=['search','detail','toc','chapter'])
            self.tocs[source] = ['第一章 出发','第二章 旅途','第三章 归来']
            self.bodies[source] = BODY

    async def detail(self, source, url):
        self.calls.append(('detail',source))
        return {'data': {'name':'山河', 'author':self.authors.get(source,'李某'), 'coverUrl':f'https://{source}.example/cover.jpg'}}

    async def toc(self, source, url):
        self.calls.append(('toc',source))
        return {'chapters':[{'title':t,'rawChapterUrl':f'https://{source}.example/{i}'} for i,t in enumerate(self.tocs[source])]}

    async def chapter(self, source, url):
        i = int(url.rsplit('/',1)[1]); self.calls.append(('chapter',source,i))
        if isinstance(self.bodies[source],Exception): raise self.bodies[source]
        return {'title':self.tocs[source][i], 'content':self.bodies[source]}

    async def search_one(self, source, keyword, page):
        return {'items':[{'name':'山河','author':'李某','bookUrl':f'https://{source}.example/book','coverUrl':f'https://{source}.example/cover.jpg'}]}


def ids(sources='abc'):
    return [encode_book_id(s,f'https://{s}.example/book') for s in sources]


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path/'app.db'; initialize_database(db)
    auth = UserAuthService(db); auth.bootstrap_admin('admin', 'a-strong-password')
    user = auth.get_user_by_username('admin')['userId']
    other = auth.create_user('other','another-password')['userId']
    scheduler = Sources(); repo = DirectReadingRepository(db)
    monkeypatch.setattr('app.services.live_acceptance.get_plugin_scheduler', lambda:scheduler)
    reader = DirectReadingService(scheduler)
    return AggregateReadingService(reader,repo), scheduler, user, other


async def test_metadata_only_add_deduplicates_sources_and_retains_cover(env):
    service, source, user, _ = env
    one = await service.add(user,ids('ab'))
    two = await service.add(user,ids('bc'))
    assert one['bookId'] == two['bookId'] and two['sourceCount'] == 3
    assert len(service.repository.shelf(user)) == 1
    assert one['coverUrl'] == 'https://a.example/cover.jpg'
    assert all(c[0] == 'detail' for c in source.calls)


def test_identity_independent_of_sources_and_unknown_authors_not_crossed(env):
    a = dict(name='山河',author='作者：李某',bookId=ids('a')[0],sourceId='a')
    b = dict(a,author=' 李某 ',bookId=ids('b')[0],sourceId='b')
    c = dict(a,author='张某',bookId=ids('c')[0],sourceId='c')
    d = dict(a,author='',bookId=ids('d')[0],sourceId='d')
    assert identity(a) == identity(b)
    assert len(grouped_books([a,b],'山河')) == 1
    assert len(grouped_books([a,b,c,d],'山河')) == 3
    assert grouped_books([a,b],'山河')[0]['bookId'] == grouped_books([b],'山河')[0]['bookId']


async def test_only_current_chapter_compares_and_selects_majority_then_persists(env):
    service, source, user, other = env
    book = await service.add(user,ids())
    source.bodies['a'] = '完全不一样的另一篇文章。'*80
    reader = service.for_user(user)
    result = await reader.chapter(book['bookId'],1)
    assert result['content'] == BODY
    assert result['aggregation']['mode'] == 'consensus'
    assert result['aggregation']['selectedSourceId'] in 'bc'
    assert {c[2] for c in source.calls if c[0]=='chapter'} == {1}
    source.calls.clear()
    reopened = AggregateReadingService(service.reader, DirectReadingRepository(service.repository.db_path))
    assert (await reopened.for_user(user).chapter(book['bookId'],1)) == result
    assert source.calls == []
    with pytest.raises(HTTPException) as exc:
        await service.for_user(other).chapter(book['bookId'],1)
    assert exc.value.status_code == 404


async def test_missing_chapter_aligns_by_title_and_never_reads_neighbour(env):
    service, source, user, _ = env
    source.tocs['a'].pop(1)
    book = await service.add(user, ids())
    result = await service.for_user(user).chapter(book['bookId'],1)
    assert result['title'] == '第二章 旅途'
    assert ('chapter','a',1) not in source.calls
    assert result['aggregation']['supportCount'] == 1


async def test_missing_catalog_entry_is_inserted_before_progress_exists(env):
    service, source, user, _ = env
    source.tocs['a'] = ['第一章 出发','第三章 归来','第四章 回家']
    source.tocs['b'] = ['第一章 出发','第二章 旅途','第三章 归来']
    book = await service.add(user,ids('ab'))
    toc = await service.for_user(user).toc(book['bookId'])
    assert [c['title'] for c in toc['chapters']] == ['第一章 出发','第二章 旅途','第三章 归来','第四章 回家']
    assert not any(c[0] == 'chapter' for c in source.calls)


async def test_refresh_never_shifts_existing_progress_and_appends_new_chapter(env):
    service, source, user, _ = env
    book = await service.add(user,ids('a'))
    toc = await service.for_user(user).toc(book['bookId'])
    new = [{'title':'序章','index':0,'url':'https://a.example/new'}, *toc['chapters'], {'title':'第四章 回家','index':4,'url':'https://a.example/end'}]
    refreshed = service.canonical([(book['sources'][0],new)],toc)
    assert [c['title'] for c in refreshed['chapters'][:3]] == source.tocs['a']
    assert len(refreshed['chapters']) == 4


async def test_source_failure_falls_back_and_all_conflicting_sources_fail(env):
    service, source, user, _ = env
    book = await service.add(user,ids())
    source.bodies['a'] = RuntimeError('disconnected')
    source.bodies['b'] = RuntimeError('disconnected')
    result = await service.for_user(user).chapter(book['bookId'],0)
    assert result['aggregation']['mode'] == 'degraded'
    source.bodies.update(a='甲乙丙丁戊己庚辛壬癸'*70,b='山川日月天地玄黄宇宙'*70,c='春夏秋冬梅兰竹菊风雨'*70)
    with pytest.raises(HTTPException) as exc:
        await service.for_user(user).chapter(book['bookId'],1)
    assert exc.value.status_code == 502


async def test_expands_to_fourth_source_if_initial_consensus_not_stable(env):
    service, source, user, _ = env
    book = await service.add(user,ids('abcd'))
    source.bodies['a'] = '完全不同的文章文字。'*90
    result = await service.for_user(user).chapter(book['bookId'],2)
    assert result['aggregation']['attemptedCount'] == 4
    assert result['aggregation']['supportCount'] == 2


async def test_download_uses_same_aggregation_and_is_private(env,tmp_path):
    service, source, user, other = env
    book = await service.add(user,ids())
    source.bodies['a'] = '完全不同的文章文字。'*90
    downloads = BookDownloadService(service.for_user(user), service.repository, tmp_path/'downloads')
    downloads.enqueue(user,book['bookId'])
    await downloads.run(user,book['bookId'])
    job = service.repository.download(user,book['bookId'])
    assert job['state'] == 'completed', job
    text = downloads.file(user,book['bookId']).read_text()
    assert BODY in text and source.bodies['a'] not in text
    with pytest.raises(HTTPException): downloads.file(other,book['bookId'])


async def test_legacy_id_progress_and_cover_survive_enrichment(env):
    service, source, user, _ = env
    original = await service.reader.detail(ids('a')[0])
    service.repository.save(user,original)
    service.repository.update_progress(user,original['bookId'],1,.5,0)
    book = await service.add(user,ids())
    assert book['bookId'] == original['bookId']
    assert service.repository.progress(user,book['bookId'])['position'] == .5
    assert len(service.repository.shelf(user)) == 1


async def test_different_authors_and_forged_source_urls_cannot_be_merged(env):
    service, source, user, _ = env
    source.authors['b']='另一位作者'
    with pytest.raises(HTTPException) as exc: await service.add(user,ids('ab'))
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException):
        await service.add(user,[encode_book_id('a','https://evil.example/book')])
    assert not service.repository.shelf(user)


async def test_concurrent_first_reads_freeze_one_toc_and_share_chapter_work(env):
    service, source, user, _ = env
    book = await service.add(user,ids())
    reader = service.for_user(user)
    a,b = await asyncio.gather(reader.chapter(book['bookId'],0),reader.chapter(book['bookId'],0))
    assert a == b
    assert len([c for c in source.calls if c[0]=='chapter']) == 3
    assert not service._locks and not service._chapter_tasks


async def test_new_sources_invalidate_degraded_chapter_cache(env):
    service, source, user, _ = env
    book = await service.add(user, ids('a'))
    first = await service.for_user(user).chapter(book['bookId'], 0)
    assert first['aggregation']['mode'] == 'degraded'
    book = await service.add(user, ids('abc'))
    second = await service.for_user(user).chapter(book['bookId'], 0)
    assert second['aggregation']['mode'] == 'consensus'
    assert second['aggregation']['supportCount'] == 2


async def test_search_identity_excludes_a_source_with_incorrect_detail(env):
    service, source, user, _ = env
    source.authors['b'] = '不同作者'
    expected = identity({'name':'山河','author':'李某'})
    book = await service.add(user, ids('abc'), expected_identity=expected)
    assert book['sourceCount'] == 2
    assert ids('b')[0] not in book['sourceBookIds']


async def test_discovery_cannot_resurrect_a_removed_book(env):
    service, source, user, _ = env
    with pytest.raises(HTTPException) as exc:
        await service.add(user, ids('ab'), existing_book_id=ids('a')[0])
    assert exc.value.status_code == 404
    assert service.repository.shelf(user) == []

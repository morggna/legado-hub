"""Product source groups, independent of authentication and provider ownership.

The two light-novel integrations and the personal attachment account are
custom sources. Other IDs outside this built-in inventory are custom too.
"""
BUILTIN_SOURCE_IDS = frozenset({
    '0xs_net',
    '69shuba_com',
    '69shuba_tw',
    '96dushu_com',
    'aiqu654_com',
    'aishu99_com',
    'biquge365_net',
    'czbooks_net',
    'dongtanxs_com',
    'dxtxt_cc',
    'feishubook_com',
    'hjwzw_com',
    'ixdzs8_com',
    'lingdiankanshu_com',
    'mingzw_tw',
    'qianyezw_com',
    'qidian_com_web',
    'qiexs_cc',
    'quanben5_com',
    'quexs_org',
    'shuhaige_net',
    'shumilou_co',
    'shumilou_top',
    'sto_com',
    'sudugu_org',
    'suixkan_com',
    'ttkan_co',
    'xiaoshuohu_com',
    'xinjianpan_com',
    'xs63b_com',
    'yeban360_com',
    'zhswx_tw',
})


def source_origin(source_id):
    return "builtin" if source_id in BUILTIN_SOURCE_IDS else "custom"


def source_category(meta):
    if meta.id in {"quanben5_com", "txtnovel_vip"}:
        return "completed"
    if meta.id in {"wenku8_net", "linovelib_com"}:
        return "light_novel"
    if source_origin(meta.id) == "builtin":
        return "ongoing"
    tags = set(getattr(meta, "tags", []) or [])
    configured = meta.content.get("category")
    if configured in {"light_novel", "completed", "ongoing"}:
        return configured
    if "light-novel" in tags:
        return "light_novel"
    return "completed" if "completed" in tags else "ongoing"

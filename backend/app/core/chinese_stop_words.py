"""Shared Chinese stop-word sets for keyword extraction."""

from __future__ import annotations

# Wordcloud / basic frequency extraction
WORDCLOUD_STOP_WORDS: frozenset[str] = frozenset(
    "的 了 在 是 我 有 和 就 不 人 都 一 个 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己 这 他 她 它 们 那 什么 怎么 哪 为什么 可以 因为 所以 但是 如果 虽然 而且 还是 只是 已经 比较 非常 一起 需要 可能 应该 或者 然后 不过 其实 目前 根据 方面 通过 进行 使用 以及 一些 更加 相关 存在 包括 不同 主要 关于 其中 对于 同时 问题 情况 内容 结果 信息 用户 数据 功能 服务 产品 公司 企业 品牌 提供 是否 如何 这样 那样 之后 以前 以后 之前 之中 之外 之内".split()
)

# Sentiment phrase extraction adds domain-noise terms on top of the base set.
SENTIMENT_EXTRA_STOP_WORDS: frozenset[str] = frozenset(
    "回答 推荐 选择 适合 适合谁 适合您 基于 最新 市场 行业 头部 代表 传媒 广告 电梯 媒体 投放 覆盖 全国 区域 本地 中小 客户 目标 受众 预算 规模 属性 分类 整理 对比 速览 主流 核心 优势 地位 特点 定位 一句话 表格 公司类型 如下 以下 第一 第二 第三 第四 第五".split()
)

SENTIMENT_STOP_WORDS: frozenset[str] = WORDCLOUD_STOP_WORDS | SENTIMENT_EXTRA_STOP_WORDS

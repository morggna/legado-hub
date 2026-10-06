"""Pure upstream aggregation policy shared by batch and on-demand readers.

Extracted without changing selection, sentence-order or TOC ranking rules.
"""
from __future__ import annotations
import re
from typing import Any

CROSS_SOURCE_INITIAL_COMPARE_COUNT = 3
CANDIDATE_TITLE_MAX_INDEX_DRIFT = 30


class CandidateSelectionPolicy:
    def _select_consistent_candidate(
        self,
        candidates: list[dict[str, Any]],
        *,
        allow_degraded: bool = False,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """Select the best supported candidate, optionally degrading to priority order."""
        from app.services.aggregate_alignment import (
            CROSS_SOURCE_CONTENT_SIMILARITY_THRESHOLD,
            analyze_sentence_order_consensus,
            cross_source_content_similarity,
        )

        consensus: list[dict[str, Any]] = []
        from app.services.aggregate_line_consensus import direct_consensus_gap_count

        sentence_order_audits = analyze_sentence_order_consensus(candidates)
        eligible_candidates: list[dict[str, Any]] = []
        for candidate in candidates:
            source_id = str(candidate.get("source_id", "") or "")
            sentence_order = sentence_order_audits.get(source_id, {})
            alignment_json = dict(candidate.get("alignment_json") or {})
            alignment_json["sentenceOrder"] = sentence_order
            candidate["alignment_json"] = alignment_json
            if not sentence_order.get("rejected"):
                eligible_candidates.append(candidate)

        ranked: list[tuple[int, int, float, int, dict[str, Any]]] = []
        for index, candidate in enumerate(candidates):
            source_id = str(candidate.get("source_id", "") or "")
            sentence_order = sentence_order_audits.get(source_id, {})
            if sentence_order.get("rejected"):
                consensus.append({
                    "sourceId": source_id,
                    "supportingSourceIds": [],
                    "supportCount": 0,
                    "averageSimilarity": 0.0,
                    "sentenceOrderStatus": "rejected_order_mismatch",
                    "sentenceOrder": sentence_order,
                })
                continue
            scores: list[float] = []
            peers: list[str] = []
            for peer in eligible_candidates:
                if peer is candidate:
                    continue
                score = cross_source_content_similarity(
                    candidate.get("content", ""), peer.get("content", "")
                )
                if score >= CROSS_SOURCE_CONTENT_SIMILARITY_THRESHOLD:
                    scores.append(score)
                    peers.append(str(peer.get("source_id", "")))
            consensus.append({
                "sourceId": candidate.get("source_id", ""),
                "supportingSourceIds": peers,
                "supportCount": len(peers),
                "averageSimilarity": round(sum(scores) / len(scores), 4) if scores else 0.0,
                "sentenceOrderStatus": sentence_order.get("status", "insufficient_evidence"),
            })
            if scores:
                direct_gap_count = direct_consensus_gap_count(
                    str(candidate.get("content", "") or ""),
                    eligible_candidates,
                    selected_source_id=str(candidate.get("source_id", "") or ""),
                )
                consensus[-1]["directConsensusGapCount"] = direct_gap_count
                ranked.append((
                    len(scores),
                    direct_gap_count,
                    sum(scores) / len(scores),
                    index,
                    candidate,
                ))
        if not ranked:
            if allow_degraded and len(eligible_candidates) in (1, 2):
                return eligible_candidates[0], consensus
            return None, consensus
        ranked.sort(key=lambda item: (-item[0], item[1], -item[2], item[3]))
        return ranked[0][4], consensus

    @staticmethod
    def _has_stable_candidate_consensus(
        consensus: list[dict[str, Any]],
        *,
        candidate_count: int,
        require_unanimous: bool,
    ) -> bool:
        """Require three-source unanimity first, then a strict majority after expansion."""
        active_consensus = [
            item for item in consensus
            if item.get("sentenceOrderStatus") != "rejected_order_mismatch"
        ]
        active_count = len(active_consensus)
        if active_count < 2:
            return False
        if require_unanimous:
            return all(
                int(item.get("supportCount", 0) or 0) == active_count - 1
                for item in active_consensus
            )
        return any(
            (int(item.get("supportCount", 0) or 0) + 1) >= CROSS_SOURCE_INITIAL_COMPARE_COUNT
            and (int(item.get("supportCount", 0) or 0) + 1) * 2 > active_count
            for item in active_consensus
        )

    def _match_candidate_toc_entries(
        self,
        *,
        cand_chapters: list[dict[str, Any]],
        target_index: int,
        target_title: str,
    ) -> list[dict[str, Any]]:
        title_matches: list[tuple[tuple[int, float, int], int, dict[str, Any]]] = []
        index_fallbacks: list[tuple[int, dict[str, Any]]] = []
        target_ordinal = self._chapter_ordinal_from_title(target_title)
        for position, ch in enumerate(cand_chapters, start=1):
            if not isinstance(ch, dict):
                continue
            ch_index = int(ch.get("index") or position)
            index_gap = abs(ch_index - int(target_index or 0))
            if target_index and index_gap > CANDIDATE_TITLE_MAX_INDEX_DRIFT:
                continue
            title = str(ch.get("title", "") or "")
            rank = self._candidate_title_match_rank(target_title, title)
            if rank is not None:
                title_matches.append((rank, index_gap, ch))
                continue
            candidate_ordinal = self._chapter_ordinal_from_title(title)
            if (
                ch_index
                and target_index
                and index_gap <= 2
                and (target_ordinal is None or candidate_ordinal is None)
            ):
                index_fallbacks.append((index_gap, ch))
        title_matches.sort(
            key=lambda item: (
                item[0][0],
                -item[0][1],
                item[1],
                item[0][2],
            )
        )
        if title_matches:
            return [item[2] for item in title_matches[:3]]
        index_fallbacks.sort(key=lambda item: item[0])
        return [item[1] for item in index_fallbacks[:3]]

    def _candidate_title_match_rank(
        self,
        target_title: str,
        candidate_title: str,
    ) -> tuple[int, float, int] | None:
        from app.services.aggregate_alignment import (
            chapter_name_similarity,
            chapter_title_similarity,
        )

        if not target_title or not candidate_title:
            return None
        similarity = chapter_title_similarity(target_title, candidate_title)
        target_ordinal = self._chapter_ordinal_from_title(target_title)
        candidate_ordinal = self._chapter_ordinal_from_title(candidate_title)
        if target_ordinal is not None and candidate_ordinal is not None:
            ordinal_gap = abs(target_ordinal - candidate_ordinal)
            # A mirror may number chapters across the whole book while the
            # official TOC restarts at each volume. The TOC index bounds this
            # name match before we use it as a snapshot or live candidate.
            name_similarity = chapter_name_similarity(target_title, candidate_title)
            if name_similarity >= 0.8:
                return (0, name_similarity, ordinal_gap)
            if similarity >= 0.75 and ordinal_gap <= 5:
                return (1, similarity, ordinal_gap)
            if ordinal_gap <= 2:
                return (2, similarity, ordinal_gap)
            return None
        if similarity >= 0.75:
            return (0, similarity, 0)
        return None

    def _chapter_ordinal_from_title(self, title: str) -> int | None:
        from app.services.aggregate_alignment import _parse_chinese_number

        match = re.search(r"第\s*([零〇一二两三四五六七八九十百千万\d]+)\s*[章节回卷篇部集]", str(title or ""))
        if not match:
            return None
        return _parse_chinese_number(match.group(1))

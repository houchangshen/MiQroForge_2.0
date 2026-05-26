"""agents/node_generator/manual_index.py — 软件手册层级索引。

基于 bm25s 的段落级搜索，支持 5 种导航操作：
  list_chapters()        → 章节目录 + 大小 + 摘要
  get_chapter_outline()  → section 标题列表
  search()               → BM25 关键词搜索
  get_section()          → 指定 section 完整内容
  find_command_docs()    → 命令/关键词定位

依赖：bm25s[core]（numpy + PyStemmer）
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Section:
    """手册中的一个 section。"""
    section_id: str          # 如 "7.26" 或 "page-734"
    title: str               # section 标题
    page: int | None = None  # PDF 页码（如果有）
    line_start: int = 0      # 在文件中的起始行
    line_end: int = 0        # 在文件中的结束行
    content: str = ""        # section 内容


@dataclass
class ChapterInfo:
    """章节元数据。"""
    name: str                # 文件名（如 "geometry_optimization.md"）
    display_name: str        # 人类可读名
    size_kb: float           # 文件大小 KB
    section_count: int       # section 数量
    summary: str = ""        # 首段摘要


def _merge_adjacent_sections(sections: list[Section]) -> list[Section]:
    """合并相邻的标题相同或非常相似的 section。
    
    解决 ORCA 等 PDF 手册跨页切割导致的内容碎片化问题：
    多个连续页面的标题都是 "ORCA Manual, Release 6.0" 时合并为一个 section。
    """
    if len(sections) <= 1:
        return sections
    
    merged: list[Section] = []
    current = sections[0]
    
    for next_sec in sections[1:]:
        # 判断是否应该合并：标题完全相同，或忽略括号内差异后相同
        curr_title = current.title.strip()
        next_title = next_sec.title.strip()
        
        same = (
            curr_title == next_title
            or _normalize_title(curr_title) == _normalize_title(next_title)
        )
        
        if same:
            # 合并：扩展行范围，拼接内容
            current.line_end = next_sec.line_end
            current.content = current.content + "\n" + next_sec.content
            # 保留更具体的 section_id
            if next_sec.section_id > current.section_id:
                current.section_id = next_sec.section_id
        else:
            merged.append(current)
            current = next_sec
    
    merged.append(current)
    return merged


def _normalize_title(title: str) -> str:
    """标准化标题用于比较：去括号内容、去多余空格、小写。"""
    import re as _re
    t = _re.sub(r'\([^)]*\)', '', title)  # 去掉括号内容
    t = _re.sub(r'\s+', ' ', t).strip().lower()
    return t


# ═══════════════════════════════════════════════════════════════════════════
# Section 解析
# ═══════════════════════════════════════════════════════════════════════════

# 匹配 ## Page N（ORCA/Gaussian PDF 提取的页码标记）
_RE_PAGE = re.compile(r"^##\s+Page\s+(\d+)", re.MULTILINE)

# 匹配 # Heading 或 ## Heading（markdown 标题）
_RE_HEADING = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)

# 匹配带编号的 section（如 7.26.1 Geometry Optimization）
_RE_SECTION_NUM = re.compile(r"^(\d+(?:\.\d+)*)\s+(.+)$", re.MULTILINE)

# 匹配 Gaussian 数值输出行 — title 已去掉 ## 前缀，匹配科学记数法（如 -3.11369582D-17）等
_RE_NUMERIC_OUTPUT = re.compile(r"^[-+]?(?:\d+\.?\d*[A-Z][-+]?\d+|:DEL\]|\s*=)")

# lynx HTML→text 转换产生的 artifact 标记
_RE_LYNX_ARTIFACT = re.compile(r"\[DEL:|:DEL\]")

# 匹配自旋/角动量期望值行（如 "<Sx>= 0.0000" 或 "<L.S>= 0.000000000000E+00"）
_RE_SPIN_EXPECT = re.compile(r"^<[A-Za-z.*^]+\d*\s*\*?\s*\d*\s*>\s*=")


def _compute_code_block_lines(lines: list[str]) -> set[int]:
    """计算所有位于 code fence (```) 内部的行的行号集合。"""
    code_lines: set[int] = set()
    in_block = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_block:
                code_lines.add(i)  # closing fence 也算在内
                in_block = False
            else:
                code_lines.add(i)  # opening fence 也算在内
                in_block = True
        elif in_block:
            code_lines.add(i)
    return code_lines


def _is_valid_heading(title: str) -> bool:
    """判断一个 heading 标题是否为有效的文档标题（而非数值输出/artifact）。"""
    if not title:
        return False
    # 跳过 lynx artifact
    if _RE_LYNX_ARTIFACT.search(title):
        return False
    # 跳过 Gaussian 数值输出（如 "-3.11369582D-17  2.7239..."，已去掉 ## 前缀）
    if _RE_NUMERIC_OUTPUT.match(title):
        return False
    # 跳过自旋/角动量期望值（如 "<Sx>= 0.0000"）
    if _RE_SPIN_EXPECT.match(title):
        return False
    # 跳过纯数值/等号行（如 "= 0.0000 = 0.0000 = 1.0000 [DEL: ..."）
    if title.strip().startswith("=") and any(c.isdigit() for c in title):
        return False
    return True


def _parse_sections(content: str, filename: str) -> list[Section]:
    """将 markdown 内容分割为 sections。"""
    lines = content.split("\n")
    sections: list[Section] = []

    # 策略：按 ## Page N 分割（PDF 提取的文档用这种格式）
    # 如果没有 Page 标记，则按 # Heading 分割
    # 使用 match 在 content 中的实际字节位置计算行号（而非 enumerate 索引）
    page_markers = [(content[:m.start()].count("\n"), int(m.group(1)))
                    for m in _RE_PAGE.finditer(content)]

    if page_markers:
        # 按 Page 分割
        for idx, (line_idx, page_num) in enumerate(page_markers):
            # 找到下一个 page marker 或文件末尾（使用实际行号）
            if idx + 1 < len(page_markers):
                end_line = page_markers[idx + 1][0]
            else:
                end_line = len(lines)

            # 提取 page 内容，跳过 ## Page N 行本身
            section_lines = lines[line_idx + 1:end_line]
            section_text = "\n".join(section_lines).strip()

            if not section_text:
                continue

            # 尝试从内容中提取 section 标题
            title = f"Page {page_num}"
            first_heading = _RE_HEADING.search(section_text)
            if first_heading:
                candidate = first_heading.group(2).strip()
                if _is_valid_heading(candidate):
                    title = candidate
            if title == f"Page {page_num}":
                # 尝试提取第一行非空文本作为标题
                for sl in section_lines:
                    sl_stripped = sl.strip()
                    if sl_stripped and not sl_stripped.startswith("#"):
                        # 跳过 artifact 行
                        if not _RE_LYNX_ARTIFACT.search(sl_stripped):
                            title = sl_stripped[:80]
                            break

            sections.append(Section(
                section_id=f"page-{page_num}",
                title=title,
                page=page_num,
                line_start=line_idx,
                line_end=end_line,
                content=section_text,
            ))
        # 合并相邻的相同/相似标题的 section（解决 ORCA PDF 跨页切割问题）
        sections = _merge_adjacent_sections(sections)
    else:
        # 按 # Heading 分割
        # 预计算 code block 行号，用于跳过代码块内的伪标题
        code_block_lines = _compute_code_block_lines(lines)

        headings = list(_RE_HEADING.finditer(content))
        for idx, match in enumerate(headings):
            line_idx = content[:match.start()].count("\n")

            # 跳过 code block 内的伪标题
            if line_idx in code_block_lines:
                continue

            title = match.group(2).strip()

            # 跳过无效 heading（数值输出、artifact 等）
            if not _is_valid_heading(title):
                continue

            if idx + 1 < len(headings):
                end_line = content[:headings[idx + 1].start()].count("\n")
            else:
                end_line = len(lines)

            section_text = "\n".join(lines[line_idx:end_line]).strip()

            # 尝试提取 section 编号
            section_id = title.lower().replace(" ", "-")[:40]
            num_match = _RE_SECTION_NUM.match(title)
            if num_match:
                section_id = num_match.group(1)

            sections.append(Section(
                section_id=section_id,
                title=title,
                line_start=line_idx,
                line_end=end_line,
                content=section_text,
            ))

    # 如果没有任何分割标记，整个文件作为一个 section
    if not sections:
        sections.append(Section(
            section_id="full",
            title=filename.replace(".md", "").replace("_", " ").title(),
            line_start=0,
            line_end=len(lines),
            content=content.strip(),
        ))

    return sections


def _extract_summary(content: str, max_chars: int = 300) -> str:
    """提取内容的前几行作为摘要。"""
    lines = content.strip().split("\n")
    summary_lines = []
    char_count = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # 跳过页码标记
        if stripped.startswith("## Page"):
            continue
        summary_lines.append(stripped)
        char_count += len(stripped)
        if char_count >= max_chars or len(summary_lines) >= 3:
            break
    return " ".join(summary_lines)[:max_chars]


# ═══════════════════════════════════════════════════════════════════════════
# ManualIndex
# ═══════════════════════════════════════════════════════════════════════════

class ManualIndex:
    """软件手册的层级索引，基于 bm25s 的段落级搜索。"""

    def __init__(self, manual_dir: str | Path):
        self.manual_dir = Path(manual_dir)
        self._chapters: dict[str, ChapterInfo] = {}
        self._sections: dict[str, list[Section]] = {}  # chapter → sections
        self._corpus: list[str] = []       # 段落文本（用于 BM25）
        self._corpus_meta: list[dict] = [] # 每段的元数据
        self._bm25 = None
        self._bm25_retriever = None
        self._index_dir = self.manual_dir / ".bm25_index"
        self._built = False

    def build(self) -> None:
        """构建索引（如果已缓存则跳过）。"""
        if self._built:
            return

        if not self.manual_dir.exists():
            self._built = True
            return

        # 扫描所有 .md 文件
        md_files = sorted(self.manual_dir.glob("*.md"))
        if not md_files:
            self._built = True
            return

        # 检查缓存
        cache_file = self._index_dir / "meta.json"
        if self._is_cache_valid(cache_file, md_files):
            try:
                self._load_cache()
                self._built = True
                return
            except Exception:
                pass

        # 构建索引
        self._build_from_files(md_files)
        self._save_cache()
        self._built = True

    def _is_cache_valid(self, cache_file: Path, md_files: list[Path]) -> bool:
        """检查缓存是否仍然有效。"""
        if not cache_file.exists():
            return False
        try:
            meta = json.loads(cache_file.read_text("utf-8"))
            cached_mtime = meta.get("mtime", {})
            for f in md_files:
                if str(f.name) not in cached_mtime:
                    return False
                if cached_mtime[str(f.name)] != f.stat().st_mtime:
                    return False
            return True
        except Exception:
            return False

    def _build_from_files(self, md_files: list[Path]) -> None:
        """从文件构建索引。"""
        import bm25s

        self._chapters = {}
        self._sections = {}
        self._corpus = []
        self._corpus_meta = []

        for md_file in md_files:
            try:
                content = md_file.read_text("utf-8")
            except Exception:
                continue

            filename = md_file.name
            display_name = filename.replace(".md", "").replace("_", " ").title()
            size_kb = md_file.stat().st_size / 1024

            sections = _parse_sections(content, filename)
            self._sections[filename] = sections
            self._chapters[filename] = ChapterInfo(
                name=filename,
                display_name=display_name,
                size_kb=round(size_kb, 1),
                section_count=len(sections),
                summary=_extract_summary(content),
            )

            # 为每个 section 创建 BM25 文档
            for section in sections:
                doc_text = f"{section.title}\n{section.content}"
                self._corpus.append(doc_text)
                self._corpus_meta.append({
                    "chapter": filename,
                    "section_id": section.section_id,
                    "title": section.title,
                    "page": section.page,
                })

        # 构建 BM25 索引
        if self._corpus:
            try:
                stemmer = Stemmer.Stemmer("english")
            except Exception:
                stemmer = None

            tokens = bm25s.tokenize(
                self._corpus,
                stopwords="en",
                stemmer=stemmer,
            )
            self._bm25_retriever = bm25s.BM25()
            self._bm25_retriever.index(tokens)

    def _save_cache(self) -> None:
        """保存索引缓存。"""
        try:
            self._index_dir.mkdir(parents=True, exist_ok=True)

            # 保存元数据
            meta = {
                "mtime": {
                    name: (self.manual_dir / name).stat().st_mtime
                    for name in self._chapters
                    if (self.manual_dir / name).exists()
                },
                "chapters": {k: asdict(v) for k, v in self._chapters.items()},
            }
            (self._index_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), "utf-8"
            )

            # 保存 BM25 索引
            if self._bm25_retriever:
                self._bm25_retriever.save(str(self._index_dir / "bm25"))

            # 保存 sections（内容太大，只保存元数据）
            sections_meta = {}
            for chapter, secs in self._sections.items():
                sections_meta[chapter] = [
                    {"section_id": s.section_id, "title": s.title, "page": s.page,
                     "line_start": s.line_start, "line_end": s.line_end}
                    for s in secs
                ]
            (self._index_dir / "sections.json").write_text(
                json.dumps(sections_meta, ensure_ascii=False, indent=2), "utf-8"
            )
        except Exception:
            pass

    def _load_cache(self) -> None:
        """从缓存加载索引。"""
        import bm25s

        meta = json.loads((self._index_dir / "meta.json").read_text("utf-8"))
        self._chapters = {
            k: ChapterInfo(**v) for k, v in meta["chapters"].items()
        }

        # 加载 sections 元数据 + 从原文件重建内容
        sections_meta = json.loads(
            (self._index_dir / "sections.json").read_text("utf-8")
        )
        self._sections = {}
        self._corpus = []
        self._corpus_meta = []

        for chapter, secs_meta in sections_meta.items():
            filepath = self.manual_dir / chapter
            if not filepath.exists():
                continue
            content = filepath.read_text("utf-8")
            lines = content.split("\n")

            secs = []
            for sm in secs_meta:
                section_lines = lines[sm["line_start"]:sm["line_end"]]
                section_content = "\n".join(section_lines).strip()
                sec = Section(
                    section_id=sm["section_id"],
                    title=sm["title"],
                    page=sm.get("page"),
                    line_start=sm["line_start"],
                    line_end=sm["line_end"],
                    content=section_content,
                )
                secs.append(sec)
                self._corpus.append(f"{sec.title}\n{sec.content}")
                self._corpus_meta.append({
                    "chapter": chapter,
                    "section_id": sec.section_id,
                    "title": sec.title,
                    "page": sec.page,
                })
            self._sections[chapter] = secs

        # 加载 BM25 索引
        bm25_path = self._index_dir / "bm25"
        if bm25_path.exists() and self._corpus:
            self._bm25_retriever = bm25s.BM25.load(str(bm25_path))

    # ── 公开 API ──────────────────────────────────────────────────────────

    def list_chapters(self) -> list[dict]:
        """返回章节目录。"""
        self.build()
        return [
            {
                "name": info.name,
                "display_name": info.display_name,
                "size_kb": info.size_kb,
                "section_count": info.section_count,
                "summary": info.summary,
            }
            for info in self._chapters.values()
        ]

    def get_chapter_outline(self, chapter: str) -> list[dict]:
        """返回章节的 section 标题列表。"""
        self.build()
        sections = self._sections.get(chapter, [])
        return [
            {
                "section_id": s.section_id,
                "title": s.title,
                "page": s.page,
                "line_start": s.line_start,
            }
            for s in sections
        ]

    def search(self, query: str, top_k: int = 5, min_rel_score: float = 0.2) -> list[dict]:
        """BM25 搜索，返回匹配的 section 片段。
        
        增强：
        - 分数归一化（top=1.0），过滤低于 min_rel_score 的结果
        - 跨章节 MMR 去重：优先选择不同章节的结果
        """
        self.build()
        if not self._bm25_retriever or not self._corpus:
            return []

        import bm25s

        try:
            try:
                stemmer = Stemmer.Stemmer("english")
            except Exception:
                stemmer = None

            query_tokens = bm25s.tokenize(
                [query], stopwords="en", stemmer=stemmer
            )
            # 检索更多候选（供 MMR 去重后选择）
            fetch_k = min(top_k * 3, len(self._corpus))
            results, scores = self._bm25_retriever.retrieve(
                query_tokens, k=fetch_k
            )
        except Exception:
            return []

        # 构建候选列表
        candidates: list[dict] = []
        max_score = 0.0
        for idx, score in zip(results[0], scores[0]):
            if idx < 0 or idx >= len(self._corpus_meta):
                continue
            score_f = float(score)
            if score_f > max_score:
                max_score = score_f
            meta = self._corpus_meta[idx]
            corpus_text = self._corpus[idx]
            snippet = corpus_text[:500]
            if len(corpus_text) > 500:
                snippet += "..."
            candidates.append({
                "chapter": meta["chapter"],
                "section_id": meta["section_id"],
                "title": meta["title"],
                "page": meta.get("page"),
                "snippet": snippet,
                "score": score_f,
            })

        if not candidates:
            return []

        # 归一化分数并过滤低分
        if max_score > 0:
            candidates = [
                c for c in candidates
                if (c["score"] / max_score) >= min_rel_score
            ]
            for c in candidates:
                c["score"] = round(c["score"] / max_score, 3)

        if not candidates:
            return []

        # MMR 跨章节去重：首条始终是最高分，后续优先选不同章节
        seen_chapters: set[str] = set()
        hits: list[dict] = []
        hits.append(candidates[0])
        seen_chapters.add(candidates[0]["chapter"])

        for c in candidates[1:]:
            if c["chapter"] not in seen_chapters:
                hits.append(c)
                seen_chapters.add(c["chapter"])
                if len(hits) >= top_k:
                    break

        # 如果去重后不够 top_k，用同章节的补充
        if len(hits) < top_k:
            for c in candidates[1:]:
                if c not in hits:
                    hits.append(c)
                    if len(hits) >= top_k:
                        break

        return hits[:top_k]

    def get_section(self, chapter: str, section_id: str) -> dict:
        """返回指定 section 的完整内容。"""
        self.build()
        sections = self._sections.get(chapter, [])
        for s in sections:
            if s.section_id == section_id:
                return {
                    "chapter": chapter,
                    "section_id": s.section_id,
                    "title": s.title,
                    "page": s.page,
                    "content": s.content,
                }
        return {"error": f"Section '{section_id}' not found in '{chapter}'"}

    def find_command_docs(self, keyword: str, top_k: int = 5) -> list[dict]:
        """搜索特定命令/关键词的文档位置。"""
        self.build()
        if not self._bm25_retriever or not self._corpus:
            return []

        # 对于精确关键词搜索，直接在 corpus 中查找
        keyword_lower = keyword.lower()
        matches = []
        for idx, text in enumerate(self._corpus):
            if keyword_lower in text.lower():
                meta = self._corpus_meta[idx]
                # 找到关键词周围的上下文
                pos = text.lower().find(keyword_lower)
                start = max(0, pos - 100)
                end = min(len(text), pos + len(keyword) + 200)
                context = text[start:end]
                if start > 0:
                    context = "..." + context
                if end < len(text):
                    context = context + "..."

                matches.append({
                    "chapter": meta["chapter"],
                    "section_id": meta["section_id"],
                    "title": meta["title"],
                    "page": meta.get("page"),
                    "context": context,
                })

        return matches[:top_k]


# ═══════════════════════════════════════════════════════════════════════════
# 模块级工具函数
# ═══════════════════════════════════════════════════════════════════════════

# 延迟导入 Stemmer（只在需要时）
try:
    import Stemmer
except ImportError:
    Stemmer = None  # type: ignore


# 单例缓存
_index_cache: dict[str, ManualIndex] = {}


def list_available_manuals() -> list[str]:
    """扫描 docs/software_manuals/ 下所有可用软件手册。
    
    优先列出已有 BM25 缓存的，也包含有 .md 源文件但尚未构建索引的
    （首次搜索时会 lazy-build）。
    """
    project_root = Path(__file__).parent.parent.parent.parent
    manuals_root = project_root / "docs" / "software_manuals"
    if not manuals_root.exists():
        return []
    available = []
    for d in manuals_root.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        has_index = (d / ".bm25_index").exists()
        has_md = bool(list(d.glob("*.md")))
        if has_index or has_md:
            available.append(d.name)
    return sorted(available)


def get_manual_index(software: str) -> ManualIndex | None:
    """获取指定软件的手册索引（单例缓存，首次调用自动构建 BM25 索引）。"""
    software = software.lower()
    if software in _index_cache:
        return _index_cache[software]

    from pathlib import Path
    project_root = Path(__file__).parent.parent.parent.parent
    manual_dir = project_root / "docs" / "software_manuals" / software

    if not manual_dir.exists():
        return None

    idx = ManualIndex(manual_dir)
    # 首次调用时自动构建索引（内部有缓存机制，已构建则跳过）
    idx.build()
    _index_cache[software] = idx
    return idx

"""agents/node_generator/shared/memory.py — Node Generator Agent 经验记忆系统。

ChromaDB embedding 检索 + JSONL 人类可读备份。每次生成节点后保存经验，
下次生成时通过语义相似度检索相关经验注入 system prompt。

存储（两层）:
  1. ChromaDB: userdata/vectorstore/chroma/ → collection mf_memory_<software>
  2. JSONL:    userdata/node_gen_memory/<software>.jsonl（人类可读 + 数据恢复）

检索: 纯 embedding 相似度 — 只对 task 做向量化，不做任何 key 过滤。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════
# EmbeddingMemoryStore — ChromaDB embedding 检索
# ═══════════════════════════════════════════════════════════════════════════

class EmbeddingMemoryStore:
    """基于 ChromaDB embedding 的经验记忆存储。

    只对 task 做 embedding 检索，不做任何 metadata 过滤。
    """

    def __init__(self, software: str):
        self._software = software.lower()
        self._collection = None
        self._jsonl_path: Path | None = None

    def _ensure_collection(self):
        """延迟初始化 ChromaDB collection。"""
        if self._collection is not None:
            return

        from vectorstore.config import get_chroma_persist_dir
        persist_dir = get_chroma_persist_dir()

        import chromadb
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        client = chromadb.PersistentClient(path=str(persist_dir))
        embedding_fn = DefaultEmbeddingFunction()
        collection_name = f"mf_memory_{self._software}"

        try:
            self._collection = client.get_collection(
                name=collection_name,
                embedding_function=embedding_fn,
            )
        except Exception:
            self._collection = client.create_collection(
                name=collection_name,
                embedding_function=embedding_fn,
                metadata={"hnsw:space": "cosine"},
            )

    def _ensure_jsonl_path(self):
        if self._jsonl_path is not None:
            return
        from api.config import get_settings
        settings = get_settings()
        self._jsonl_path = settings.shared_root / "node_gen_memory" / f"{self._software}.jsonl"

    def add(self, entry: dict) -> None:
        """添加一条经验（ChromaDB + JSONL 双写）。"""
        self._ensure_collection()
        self._ensure_jsonl_path()

        task = entry.get("task", "")
        if not task:
            return

        entry_id = str(uuid.uuid4())
        entry["timestamp"] = datetime.now().isoformat()

        # 将 lessons 序列化（ChromaDB metadata 不支持 list）
        meta = {k: v for k, v in entry.items() if k != "task"}
        if "lessons" in meta and isinstance(meta["lessons"], list):
            meta["lessons_json"] = json.dumps(meta["lessons"], ensure_ascii=False)

        # 1. ChromaDB — embed both task AND lessons for better retrieval
        try:
            doc_text = task
            if meta.get("lessons_json"):
                lessons_list = json.loads(meta["lessons_json"])
                doc_text = task + " | " + " ".join(lessons_list)
            self._collection.add(
                ids=[entry_id],
                documents=[doc_text],         # ← embed task + lessons combined
                metadatas=[meta],
            )
        except Exception:
            pass

        # 2. JSONL 备份（人类可读 + 数据恢复）
        try:
            self._jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def query(self, task: str, n: int = 5) -> list[dict]:
        """纯 embedding 检索 — 按 task+lessons 语义相似度，带 software 过滤。
        
        优先返回匹配当前 software 的经验，同时包含少量其他 software 的
        高相关结果（跨软件学习）。

        Returns:
            list of entry dicts with 'task', 'lessons', 'result', 'software' keys.
        """
        self._ensure_collection()

        if not task or self._collection is None:
            return []

        try:
            count = self._collection.count()
            if count == 0:
                return []
            n_fetch = min(n * 2, count)  # 多取一些做 software 过滤
            results = self._collection.query(
                query_texts=[task],
                n_results=n_fetch,
                include=["metadatas", "documents"],
            )
        except Exception:
            return []

        metadatas = results.get("metadatas", [[]])[0] or []
        docs = results.get("documents", [[]])[0] or []

        # 分离：同 software 优先，其他 software 补充
        same_sw: list[dict] = []
        other_sw: list[dict] = []
        for i, meta in enumerate(metadatas):
            if meta is None:
                continue
            lessons = []
            if "lessons_json" in meta:
                try:
                    lessons = json.loads(meta["lessons_json"])
                except Exception:
                    pass
            entry = {
                "task": docs[i] if i < len(docs) else meta.get("task", ""),
                "lessons": lessons,
                "result": meta.get("result", ""),
                "software": meta.get("software", self._software),
            }
            if entry["software"] == self._software:
                same_sw.append(entry)
            else:
                other_sw.append(entry)

        # 同 software 优先，不够再用其他软件补充
        entries = same_sw[:n]
        if len(entries) < n:
            entries.extend(other_sw[:n - len(entries)])

        return entries

    def count(self) -> int:
        """返回经验条目总数。"""
        self._ensure_collection()
        try:
            return self._collection.count()
        except Exception:
            return 0

    def delete_by_id(self, entry_id: str) -> bool:
        """按 ChromaDB ID 删除单条经验。同时更新 JSONL 备份。"""
        self._ensure_collection()
        try:
            self._collection.delete(ids=[entry_id])
            self._sync_jsonl_from_chroma()
            return True
        except Exception:
            return False

    def delete_all(self) -> bool:
        """清空该 software 的所有经验条目。"""
        self._ensure_collection()
        try:
            # ChromaDB 不支持 truncate collection，用 get + delete 实现
            all_data = self._collection.get(include=[])
            all_ids = all_data.get("ids", [])
            if all_ids:
                self._collection.delete(ids=all_ids)
            # 清空 JSONL
            self._ensure_jsonl_path()
            if self._jsonl_path and self._jsonl_path.exists():
                self._jsonl_path.write_text("")
            return True
        except Exception:
            return False

    def delete_by_task_prefix(self, task_prefix: str) -> int:
        """删除 task 以指定前缀开头的所有经验。返回删除数量。"""
        self._ensure_collection()
        try:
            all_data = self._collection.get(include=["documents"])
            all_ids = all_data.get("ids", [])
            docs = all_data.get("documents", [])
            to_delete = []
            for i, doc in enumerate(docs):
                if doc and doc.startswith(task_prefix):
                    to_delete.append(all_ids[i])
            if to_delete:
                self._collection.delete(ids=to_delete)
                self._sync_jsonl_from_chroma()
            return len(to_delete)
        except Exception:
            return 0

    def list_all(self) -> list[dict]:
        """列出该 software 的所有经验条目（含 ID，供删除用）。"""
        self._ensure_collection()
        try:
            all_data = self._collection.get(include=["metadatas", "documents"])
            ids = all_data.get("ids", [])
            docs = all_data.get("documents", [])
            metas = all_data.get("metadatas", [])
            entries = []
            for i in range(len(ids)):
                entry_lessons = []
                meta = metas[i] if i < len(metas) else {}
                if meta and "lessons_json" in meta:
                    try:
                        entry_lessons = json.loads(meta["lessons_json"])
                    except Exception:
                        pass
                entries.append({
                    "id": ids[i],
                    "task": docs[i] if i < len(docs) else "",
                    "lessons": entry_lessons,
                    "result": meta.get("result", "") if meta else "",
                    "software": meta.get("software", self._software) if meta else self._software,
                })
            return entries
        except Exception:
            return []

    def _sync_jsonl_from_chroma(self):
        """从 ChromaDB 重建 JSONL 备份（用于 delete 后同步）。"""
        self._ensure_jsonl_path()
        try:
            entries = self.list_all()
            # 去掉 'id' 字段再写 JSONL（id 是 ChromaDB 内部字段）
            jsonl_entries = []
            for e in entries:
                jsonl_entries.append({
                    "task": e["task"],
                    "lessons": e["lessons"],
                    "result": e["result"],
                    "software": e["software"],
                })
            if self._jsonl_path:
                self._jsonl_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._jsonl_path, "w", encoding="utf-8") as f:
                    for entry in jsonl_entries:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# 工厂函数 + 经验提取
# ═══════════════════════════════════════════════════════════════════════════

def get_experience_store(software: str) -> EmbeddingMemoryStore:
    """获取指定软件的经验存储（工厂函数）。

    注意：不同 software 对应不同的 ChromaDB collection。
    用 "general" 作为无明确 software 时的默认值。
    """
    sw = software.lower() if software else "general"
    return EmbeddingMemoryStore(sw)


def build_experience_entry(
    task: str,
    software: str,
    result: str,
    lessons: list[str],
) -> dict:
    """构建一条经验条目。

    Parameters:
        task: 任务描述（embedding 源 + 检索 key）
        software: 软件名（用于分 collection）
        result: "success" | "failure"
        lessons: 经验教训列表
    """
    return {
        "task": task[:500] if task else "",
        "software": software.lower() if software else "general",
        "result": result,
        "lessons": lessons,
    }

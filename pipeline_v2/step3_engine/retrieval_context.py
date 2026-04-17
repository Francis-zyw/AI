"""
Step3 Retrieval Context Builder
基于知识库为 Step3 提供检索增强上下文
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Sequence

from pipeline_v2.knowledge_base import (
    DEFAULT_TOP_K,
    DEFAULT_VECTOR_DIM,
    build_hashed_embedding,
    cosine_similarity,
)

DEFAULT_MAX_CONTEXT_CHARS = 3200


def _load_knowledge_db(knowledge_db_path: str | Path) -> sqlite3.Connection:
    """加载知识库数据库连接"""
    return sqlite3.connect(str(knowledge_db_path), check_same_thread=False)


def _vector_from_json(vector_json: str) -> List[float]:
    """从 JSON 字符串解析向量"""
    try:
        return json.loads(vector_json)
    except (json.JSONDecodeError, TypeError):
        return []


def _metadata_from_json(metadata_json: str) -> Dict[str, Any]:
    """从 JSON 字符串解析元数据"""
    try:
        return json.loads(metadata_json)
    except (json.JSONDecodeError, TypeError):
        return {}


def _shorten_text(text: str, max_chars: int = 400) -> str:
    """缩短文本以适应上下文限制"""
    value = " ".join(str(text or "").split()).strip()
    if len(value) <= max_chars:
        return value
    return f"{value[: max_chars - 1].rstrip()}…"


def query_knowledge_entries(
    conn: sqlite3.Connection,
    query_text: str,
    stages: Sequence[str] | None = None,
    component_type: str = "",
    chapter_title: str = "",
    top_k: int = DEFAULT_TOP_K,
) -> List[Dict[str, Any]]:
    """
    基于向量相似度检索知识库条目
    
    Args:
        conn: 数据库连接
        query_text: 查询文本
        stages: 限定检索的阶段类型，如 ["step1_row", "step2_mapping"]
        component_type: 限定构件类型
        chapter_title: 限定章节标题
        top_k: 返回最相关的 K 条
    
    Returns:
        检索结果列表，按相似度排序
    """
    query_vector = build_hashed_embedding(query_text, dim=DEFAULT_VECTOR_DIM)
    
    # 构建 WHERE 子句
    where_clauses = []
    params: List[Any] = []
    
    if stages:
        placeholders = ", ".join("?" for _ in stages)
        where_clauses.append(f"stage IN ({placeholders})")
        params.extend(stages)
    
    if component_type:
        where_clauses.append("component_type = ?")
        params.append(component_type)
    
    if chapter_title:
        where_clauses.append("chapter_title = ?")
        params.append(chapter_title)
    
    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
    
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT entry_id, stage, title, content, source_path, source_ref,
               chapter_title, component_type, metadata_json, vector_json
        FROM knowledge_entries
        WHERE {where_sql}
        """,
        params
    )
    
    results: List[Dict[str, Any]] = []
    for row in cursor.fetchall():
        entry_vector = _vector_from_json(row[9])
        if not entry_vector:
            continue
        
        similarity = cosine_similarity(query_vector, entry_vector)
        metadata = _metadata_from_json(row[8])
        
        results.append({
            "entry_id": row[0],
            "stage": row[1],
            "title": row[2],
            "content": _shorten_text(row[3], 600),
            "source_path": row[4],
            "source_ref": row[5],
            "chapter_title": row[6],
            "component_type": row[7],
            "metadata": metadata,
            "similarity": round(similarity, 4),
        })
    
    # 按相似度排序并返回 top_k
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:top_k]


def query_wiki_pages(
    conn: sqlite3.Connection,
    query_text: str,
    page_types: Sequence[str] | None = None,
    component_type: str = "",
    top_k: int = DEFAULT_TOP_K,
) -> List[Dict[str, Any]]:
    """
    基于向量相似度检索 Wiki 页面
    
    Args:
        conn: 数据库连接
        query_text: 查询文本
        page_types: 限定页面类型，如 ["component", "chapter"]
        component_type: 限定构件类型
        top_k: 返回最相关的 K 条
    
    Returns:
        检索结果列表，按相似度排序
    """
    query_vector = build_hashed_embedding(query_text, dim=DEFAULT_VECTOR_DIM)
    
    # 构建 WHERE 子句
    where_clauses = []
    params: List[Any] = []
    
    if page_types:
        placeholders = ", ".join("?" for _ in page_types)
        where_clauses.append(f"page_type IN ({placeholders})")
        params.extend(page_types)
    
    if component_type:
        where_clauses.append("component_type = ?")
        params.append(component_type)
    
    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
    
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT slug, page_type, title, content, component_type, source_refs_json, vector_json
        FROM wiki_pages
        WHERE {where_sql}
        """,
        params
    )
    
    results: List[Dict[str, Any]] = []
    for row in cursor.fetchall():
        page_vector = _vector_from_json(row[6])
        if not page_vector:
            continue
        
        similarity = cosine_similarity(query_vector, page_vector)
        source_refs = json.loads(row[5]) if row[5] else []
        
        results.append({
            "slug": row[0],
            "page_type": row[1],
            "title": row[2],
            "content": _shorten_text(row[3], 800),
            "component_type": row[4],
            "source_refs": source_refs,
            "similarity": round(similarity, 4),
        })
    
    # 按相似度排序并返回 top_k
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:top_k]


def build_step1_entry_hits(
    conn: sqlite3.Connection,
    project_code: str,
    project_name: str,
    project_features: str,
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    """检索 Step1 原始清单条目"""
    # 组合查询文本
    query_parts = [project_code, project_name, project_features]
    query_text = " | ".join(p for p in query_parts if p)
    
    return query_knowledge_entries(
        conn=conn,
        query_text=query_text,
        stages=["step1_row"],
        top_k=top_k,
    )


def build_step2_entry_hits(
    conn: sqlite3.Connection,
    component_type: str,
    project_name: str,
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    """检索 Step2 构件映射结果"""
    query_text = f"{component_type} {project_name}"
    
    return query_knowledge_entries(
        conn=conn,
        query_text=query_text,
        stages=["step2_mapping", "step2_synonym"],
        component_type=component_type,
        top_k=top_k,
    )


def build_component_wiki_hits(
    conn: sqlite3.Connection,
    component_type: str,
    project_features: str,
    top_k: int = 2,
) -> List[Dict[str, Any]]:
    """检索构件 Wiki 知识页"""
    query_text = f"{component_type} {project_features}"
    
    return query_wiki_pages(
        conn=conn,
        query_text=query_text,
        page_types=["component"],
        component_type=component_type,
        top_k=top_k,
    )


def build_chapter_wiki_hits(
    conn: sqlite3.Connection,
    chapter_title: str,
    project_name: str,
    top_k: int = 2,
) -> List[Dict[str, Any]]:
    """检索章节 Wiki 知识页"""
    query_text = f"{chapter_title} {project_name}"
    
    return query_wiki_pages(
        conn=conn,
        query_text=query_text,
        page_types=["chapter"],
        top_k=top_k,
    )


def build_component_catalog_hits(
    conn: sqlite3.Connection,
    component_type: str,
    top_k: int = 1,
) -> List[Dict[str, Any]]:
    """检索构件目录属性信息"""
    return query_knowledge_entries(
        conn=conn,
        query_text=component_type,
        stages=["component_catalog"],
        component_type=component_type,
        top_k=top_k,
    )


def build_database_principles(conn: sqlite3.Connection) -> Dict[str, Any]:
    """获取数据库核心执行理念"""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT entry_id, title, content, metadata_json
        FROM knowledge_entries
        WHERE stage = 'project_doctrine'
        LIMIT 1
        """
    )
    row = cursor.fetchone()
    if not row:
        return {
            "title": "AI 对量核心执行理念",
            "content": "原始资料优先于推测。检索命中的规则、映射、属性是判断的主要证据。不允许虚构构件、属性代码、计算项目代码。",
        }
    
    metadata = _metadata_from_json(row[3])
    return {
        "entry_id": row[0],
        "title": row[1],
        "content": _shorten_text(row[2], 800),
        "metadata": metadata,
    }


def build_retrieval_context_for_row(
    conn: sqlite3.Connection,
    row: Dict[str, Any],
    local_row: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    为单条清单行构建完整的检索上下文
    
    Args:
        conn: 知识库数据库连接
        row: Step1 清单行数据
        local_row: 本地规则初判结果（可选）
    
    Returns:
        检索上下文字典
    """
    project_code = str(row.get("project_code", "")).strip()
    project_name = str(row.get("project_name", "")).strip()
    project_features = str(row.get("project_features", "")).strip()
    chapter_title = str(row.get("chapter_title", "")).strip() or str(row.get("section_path", "")).strip()
    
    # 从本地规则获取构件类型
    component_type = ""
    if local_row:
        component_type = str(local_row.get("resolved_component_name", "")).strip()
    if not component_type:
        component_type = str(row.get("component_type", "")).strip()
    
    context: Dict[str, Any] = {
        "database_principles": build_database_principles(conn),
        "step1_entry_hits": build_step1_entry_hits(
            conn, project_code, project_name, project_features
        ),
        "chapter_wiki_hits": build_chapter_wiki_hits(
            conn, chapter_title, project_name
        ),
    }
    
    # 如果有构件类型，检索构件相关信息
    if component_type:
        context["step2_entry_hits"] = build_step2_entry_hits(
            conn, component_type, project_name
        )
        context["component_wiki_hits"] = build_component_wiki_hits(
            conn, component_type, project_features
        )
        context["component_catalog_hits"] = build_component_catalog_hits(
            conn, component_type
        )
    else:
        context["step2_entry_hits"] = []
        context["component_wiki_hits"] = []
        context["component_catalog_hits"] = []
    
    return context


def build_retrieval_context_batch(
    knowledge_db_path: str | Path,
    step1_rows: Sequence[Dict[str, Any]],
    local_rows_by_row_id: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Dict[str, Any]]:
    """
    为一批清单行构建检索上下文
    
    Args:
        knowledge_db_path: 知识库数据库路径
        step1_rows: Step1 清单行列表
        local_rows_by_row_id: 按 row_id 索引的本地规则结果
    
    Returns:
        按 row_id 索引的检索上下文字典
    """
    conn = _load_knowledge_db(knowledge_db_path)
    try:
        results: Dict[str, Dict[str, Any]] = {}
        for row in step1_rows:
            row_id = row.get("row_id", "")
            if not row_id:
                continue
            
            local_rows = local_rows_by_row_id.get(row_id, [])
            local_row = local_rows[0] if local_rows else None
            
            results[row_id] = build_retrieval_context_for_row(conn, row, local_row)
        
        return results
    finally:
        conn.close()


def format_retrieval_context_for_prompt(context: Dict[str, Any]) -> str:
    """将检索上下文格式化为 Prompt 可用的文本"""
    lines: List[str] = []
    
    # 数据库原则
    principles = context.get("database_principles", {})
    lines.append("【数据库核心执行理念】")
    lines.append(f"标题: {principles.get('title', '')}")
    lines.append(f"内容: {principles.get('content', '')}")
    lines.append("")
    
    # Step1 条目命中
    lines.append("【Step1 原始清单条目检索结果】")
    for i, hit in enumerate(context.get("step1_entry_hits", []), 1):
        lines.append(f"  [{i}] 相似度: {hit.get('similarity', 0)}")
        lines.append(f"      标题: {hit.get('title', '')}")
        lines.append(f"      内容: {hit.get('content', '')}")
        lines.append(f"      来源: {hit.get('source_ref', '')}")
        lines.append("")
    
    # Step2 条目命中
    lines.append("【Step2 构件映射检索结果】")
    for i, hit in enumerate(context.get("step2_entry_hits", []), 1):
        lines.append(f"  [{i}] 相似度: {hit.get('similarity', 0)}")
        lines.append(f"      阶段: {hit.get('stage', '')}")
        lines.append(f"      标题: {hit.get('title', '')}")
        lines.append(f"      构件: {hit.get('component_type', '')}")
        lines.append(f"      内容: {hit.get('content', '')}")
        lines.append("")
    
    # 构件 Wiki 命中
    lines.append("【构件 Wiki 知识页检索结果】")
    for i, hit in enumerate(context.get("component_wiki_hits", []), 1):
        lines.append(f"  [{i}] 相似度: {hit.get('similarity', 0)}")
        lines.append(f"      标题: {hit.get('title', '')}")
        lines.append(f"      构件: {hit.get('component_type', '')}")
        lines.append(f"      内容: {hit.get('content', '')}")
        lines.append("")
    
    # 章节 Wiki 命中
    lines.append("【章节 Wiki 知识页检索结果】")
    for i, hit in enumerate(context.get("chapter_wiki_hits", []), 1):
        lines.append(f"  [{i}] 相似度: {hit.get('similarity', 0)}")
        lines.append(f"      标题: {hit.get('title', '')}")
        lines.append(f"      内容: {hit.get('content', '')}")
        lines.append("")
    
    # 构件目录命中
    lines.append("【构件目录属性检索结果】")
    for i, hit in enumerate(context.get("component_catalog_hits", []), 1):
        lines.append(f"  [{i}] 相似度: {hit.get('similarity', 0)}")
        lines.append(f"      构件: {hit.get('component_type', '')}")
        lines.append(f"      内容: {hit.get('content', '')}")
        lines.append("")
    
    return "\n".join(lines)

"""
Test script for Step3 retrieval context builder
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path("/Users/zhangkaiye/AI数据/AI智能提量/智能提量处理流程/智能提量工具").resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline_v2.step3_engine.retrieval_context import (
    build_retrieval_context_batch,
    format_retrieval_context_for_prompt,
)

# 测试配置
KNOWLEDGE_DB_PATH = "/Users/zhangkaiye/AI数据/知识库中心/projects/智能提量工具/project_knowledge_v1/knowledge.db"

# 模拟 Step1 行数据
test_step1_rows = [
    {
        "row_id": "R0001",
        "project_code": "010501003",
        "project_name": "直行墙",
        "project_features": "1.混凝土种类:商品混凝土 2.混凝土强度等级:C30 3.墙厚:200mm",
        "measurement_unit": "m3",
        "quantity_rule": "按设计图示尺寸以体积计算",
        "work_content": "混凝土制作、运输、浇筑、振捣、养护",
        "chapter_title": "混凝土及钢筋混凝土工程",
    },
    {
        "row_id": "R0002",
        "project_code": "010502001",
        "project_name": "矩形柱",
        "project_features": "1.混凝土种类:商品混凝土 2.混凝土强度等级:C35",
        "measurement_unit": "m3",
        "quantity_rule": "按设计图示尺寸以体积计算",
        "work_content": "混凝土制作、运输、浇筑、振捣、养护",
        "chapter_title": "混凝土及钢筋混凝土工程",
    },
]

# 模拟本地规则结果
test_local_rows_by_row_id = {
    "R0001": [
        {
            "row_id": "R0001",
            "resolved_component_name": "砼墙",
            "source_component_name": "直行墙",
        }
    ],
    "R0002": [
        {
            "row_id": "R0002",
            "resolved_component_name": "柱",
            "source_component_name": "矩形柱",
        }
    ],
}


def test_retrieval_context():
    """测试检索上下文构建"""
    print("=" * 60)
    print("Testing retrieval context builder")
    print("=" * 60)
    
    # 检查知识库是否存在
    if not Path(KNOWLEDGE_DB_PATH).exists():
        print(f"ERROR: Knowledge database not found: {KNOWLEDGE_DB_PATH}")
        return False
    
    print(f"Knowledge DB: {KNOWLEDGE_DB_PATH}")
    print(f"Test rows: {len(test_step1_rows)}")
    
    try:
        # 构建检索上下文
        context_by_row_id = build_retrieval_context_batch(
            knowledge_db_path=KNOWLEDGE_DB_PATH,
            step1_rows=test_step1_rows,
            local_rows_by_row_id=test_local_rows_by_row_id,
        )
        
        print(f"\nRetrieval context built for {len(context_by_row_id)} rows")
        
        # 打印每个行的检索结果
        for row_id, context in context_by_row_id.items():
            print(f"\n{'-' * 60}")
            print(f"Row: {row_id}")
            print(f"{'-' * 60}")
            
            # 数据库原则
            principles = context.get("database_principles", {})
            print(f"\n[Database Principles]")
            print(f"  Title: {principles.get('title', '')}")
            
            # Step1 命中
            step1_hits = context.get("step1_entry_hits", [])
            print(f"\n[Step1 Entry Hits: {len(step1_hits)}]")
            for hit in step1_hits[:2]:
                print(f"  - {hit.get('title', '')} (similarity: {hit.get('similarity', 0)})")
            
            # Step2 命中
            step2_hits = context.get("step2_entry_hits", [])
            print(f"\n[Step2 Entry Hits: {len(step2_hits)}]")
            for hit in step2_hits[:2]:
                print(f"  - {hit.get('title', '')} (similarity: {hit.get('similarity', 0)})")
            
            # 构件 Wiki 命中
            component_hits = context.get("component_wiki_hits", [])
            print(f"\n[Component Wiki Hits: {len(component_hits)}]")
            for hit in component_hits[:2]:
                print(f"  - {hit.get('title', '')} (similarity: {hit.get('similarity', 0)})")
            
            # 章节 Wiki 命中
            chapter_hits = context.get("chapter_wiki_hits", [])
            print(f"\n[Chapter Wiki Hits: {len(chapter_hits)}]")
            for hit in chapter_hits[:2]:
                print(f"  - {hit.get('title', '')} (similarity: {hit.get('similarity', 0)})")
            
            # 构件目录命中
            catalog_hits = context.get("component_catalog_hits", [])
            print(f"\n[Component Catalog Hits: {len(catalog_hits)}]")
            for hit in catalog_hits[:2]:
                print(f"  - {hit.get('component_type', '')} (similarity: {hit.get('similarity', 0)})")
        
        # 测试格式化输出
        print(f"\n{'=' * 60}")
        print("Formatted context preview (first row):")
        print(f"{'=' * 60}")
        first_context = list(context_by_row_id.values())[0]
        formatted = format_retrieval_context_for_prompt(first_context)
        print(formatted[:2000])  # 只打印前2000字符
        print("...")
        
        print(f"\n{'=' * 60}")
        print("TEST PASSED!")
        print(f"{'=' * 60}")
        return True
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_retrieval_context()
    sys.exit(0 if success else 1)

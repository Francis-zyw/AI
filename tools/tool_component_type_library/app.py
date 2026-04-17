#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构件类型管理工具 v1.2.2 - Streamlit版
用于管理建筑工程构件类型及其属性，支持与国标清单项目特征匹配

更新日志 v1.2.2:
- 修复：编辑/批量编辑后保持当前标签页
- 修复：编辑模式在所有标签页共享
- 修复：批量编辑在无数据时可用
- 修复：操作后保持在当前标签页

更新日志 v1.2.1:
- 修复：编辑模式切换问题
- 修复：数据类型修改功能
- 修复：值修改功能
- 优化：编辑界面交互
"""

import streamlit as st
import pandas as pd
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

try:
    from .convert_excel_to_jsonl import save_components as write_component_files
    from .excel_parser import detect_sheet_type as shared_detect_sheet_type
    from .excel_parser import import_excel_file as shared_import_excel_file
    from .paths import get_component_library_jsonl, get_component_source_dir
except ImportError:
    from convert_excel_to_jsonl import save_components as write_component_files
    from excel_parser import detect_sheet_type as shared_detect_sheet_type
    from excel_parser import import_excel_file as shared_import_excel_file
    from paths import get_component_library_jsonl, get_component_source_dir

# 版本信息
VERSION = "1.2.2"

# 设置页面配置
st.set_page_config(
    page_title=f"构件类型管理工具 v{VERSION}",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定义CSS样式
st.markdown("""
<style>
    .main-header {
        font-size: 2rem;
        font-weight: bold;
        color: #1f77b4;
        margin-bottom: 0.5rem;
    }
    .version-badge {
        background-color: #e8f4f8;
        color: #1f77b4;
        padding: 0.2rem 0.6rem;
        border-radius: 1rem;
        font-size: 0.8rem;
        margin-left: 0.5rem;
    }
    .data-type-text { color: #0d6efd; font-weight: bold; }
    .data-type-number { color: #dc3545; font-weight: bold; }
    .dropdown-badge {
        background-color: #e8f4f8;
        color: #1f77b4;
        padding: 0.2rem 0.5rem;
        border-radius: 0.3rem;
        font-size: 0.8rem;
        margin: 0.1rem;
        display: inline-block;
    }
    .mode-active {
        background-color: #1f77b4 !important;
        color: white !important;
    }
</style>
""", unsafe_allow_html=True)

# ============ 数据文件操作 ============

def get_data_file():
    """获取主流程统一输入目录下的数据文件路径。"""
    return get_component_library_jsonl()

def load_components() -> List[Dict]:
    """从JSONL文件加载所有构件类型"""
    jsonl_file = get_data_file()
    
    if not jsonl_file.exists():
        return []
    
    components = []
    try:
        with open(jsonl_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    data = migrate_old_structure(data)
                    components.append(data)
    except Exception as e:
        st.error(f"加载数据失败: {e}")
        return []
    
    return components

def migrate_old_structure(data: Dict) -> Dict:
    """将旧版本数据结构迁移到新结构"""
    if 'properties' not in data:
        return data
    
    props = data['properties']
    
    if isinstance(props, dict) and ('attributes' in props or 'calculations' in props or 'core_params' in props):
        return data
    
    if isinstance(props, list):
        data['properties'] = {
            'attributes': [
                {'name': p.get('name', ''), 'code': p.get('code', ''), 'data_type': 'text', 
                 'values': p.get('dropdown_values', [])}
                for p in props if p.get('name') or p.get('code')
            ],
            'calculations': [],
            'core_params': []
        }
    
    return data

def save_components(components: List[Dict]) -> bool:
    """保存构件类型列表到 JSONL/JSON 文件。"""
    jsonl_file = get_data_file()
    
    try:
        write_component_files(components, jsonl_file)
        return True
    except Exception as e:
        st.error(f"保存数据失败: {e}")
        return False

# ============ Sheet类型识别 ============

def detect_sheet_type(sheet_name: str) -> Optional[str]:
    """根据Sheet名称自动识别类型"""
    return shared_detect_sheet_type(sheet_name)

def import_excel_file(file, sheet_types: Dict[str, str] = None) -> Optional[Dict]:
    """从Excel文件导入构件类型"""
    component = shared_import_excel_file(file, sheet_types)
    if component is None:
        st.error("导入Excel失败，请检查文件格式和Sheet内容")
    return component

def merge_properties(existing: Dict, new: Dict) -> Tuple[Dict, Dict]:
    """合并属性，相同CODE覆盖，不同CODE新增"""
    merged = {'attributes': [], 'calculations': [], 'core_params': []}
    stats = {'attributes': {'added': 0, 'updated': 0}, 'calculations': {'added': 0, 'updated': 0}, 
             'core_params': {'added': 0, 'updated': 0}}
    
    for key in ['attributes', 'calculations', 'core_params']:
        existing_items = existing.get(key, [])
        new_items = new.get(key, [])
        
        existing_map = {item.get('code', ''): i for i, item in enumerate(existing_items) if item.get('code')}
        
        merged[key] = list(existing_items)
        
        for new_item in new_items:
            code = new_item.get('code', '')
            if code and code in existing_map:
                idx = existing_map[code]
                merged[key][idx] = new_item
                stats[key]['updated'] += 1
            else:
                merged[key].append(new_item)
                stats[key]['added'] += 1
    
    return merged, stats

# ============ Session State ============

def init_session_state():
    """初始化session state"""
    if 'components' not in st.session_state:
        st.session_state.components = load_components()
    if 'selected_component' not in st.session_state:
        st.session_state.selected_component = None
    if 'edit_mode' not in st.session_state:
        st.session_state.edit_mode = False
    if 'batch_edit_mode' not in st.session_state:
        st.session_state.batch_edit_mode = False
    if 'active_tab' not in st.session_state:
        st.session_state.active_tab = 0  # 0=属性, 1=计算项目, 2=核心项目

# ============ 主界面 ============

def main():
    init_session_state()
    
    # 页面标题
    col_title, col_version = st.columns([6, 1])
    with col_title:
        st.markdown(f'<div class="main-header">🏗️ 构件类型管理工具<span class="version-badge">v{VERSION}</span></div>', 
                   unsafe_allow_html=True)
    with col_version:
        st.caption(f"更新: 2026-03-09")
    
    # 侧边栏
    with st.sidebar:
        render_sidebar()
    
    # 主内容区
    col1, col2 = st.columns([1, 2])
    
    with col1:
        render_component_list()
    
    with col2:
        if st.session_state.selected_component:
            render_component_detail()

def render_sidebar():
    """渲染侧边栏"""
    st.header("📋 功能菜单")
    
    components = st.session_state.components
    
    # 统计信息
    st.metric("构件类型总数", len(components))
    
    if components:
        total_attrs = sum(len(c['properties'].get('attributes', [])) for c in components)
        total_calcs = sum(len(c['properties'].get('calculations', [])) for c in components)
        total_core = sum(len(c['properties'].get('core_params', [])) for c in components)
        
        col1, col2, col3 = st.columns(3)
        col1.metric("属性", total_attrs)
        col2.metric("计算", total_calcs)
        col3.metric("核心", total_core)
    
    st.divider()
    
    # 导入功能
    st.subheader("📥 导入功能")
    
    with st.expander("导入单个Excel文件"):
        uploaded_file = st.file_uploader("选择Excel文件", type=['xls', 'xlsx', 'xlsm'], key="single_upload")
        
        if uploaded_file is not None:
            handle_single_import(uploaded_file)
    
    with st.expander("批量导入文件夹"):
        folder_path = st.text_input("文件夹路径", placeholder="如: /home/user/excel_files", key="folder_path")
        
        if folder_path and st.button("📂 开始批量导入", use_container_width=True):
            handle_batch_import(folder_path)
    
    st.divider()
    
    # 新建构件类型
    st.subheader("🆕 新建构件类型")
    new_type_name = st.text_input("构件类型名称", placeholder="如: 新型墙体", key="new_type_name")
    
    if new_type_name and st.button("➕ 创建", use_container_width=True):
        handle_create_component(new_type_name)
    
    st.divider()
    
    # 保存和导出
    if st.button("💾 保存所有更改", type="primary", use_container_width=True):
        if save_components(st.session_state.components):
            st.success("✅ 数据已保存")
    
    if components and st.button("📤 导出JSONL", use_container_width=True):
        jsonl_file = get_data_file()
        with open(jsonl_file, 'rb') as f:
            st.download_button(label="下载JSONL文件", data=f, file_name='components.jsonl', 
                              mime='application/jsonlines+json', use_container_width=True)

def handle_single_import(uploaded_file):
    """处理单文件导入"""
    try:
        xl = pd.ExcelFile(uploaded_file)
        sheet_names = xl.sheet_names
        
        st.write(f"**检测到 {len(sheet_names)} 个Sheet:**")
        
        sheet_types = {}
        
        for sheet_name in sheet_names:
            detected_type = detect_sheet_type(sheet_name)
            
            col1, col2 = st.columns([1, 2])
            with col1:
                st.write(f"📄 {sheet_name}")
            with col2:
                sheet_type = st.selectbox(
                    "类型",
                    options=[None, 'attributes', 'calculations', 'core_params'],
                    format_func=lambda x: {None: '❓ 跳过', 'attributes': '📋 项目特征/属性',
                                          'calculations': '🔢 计算项目', 'core_params': '⚙️ 属性默认值/核心项目'}.get(x, x),
                    index=['attributes', 'calculations', 'core_params'].index(detected_type) + 1 if detected_type else 0,
                    key=f"sheet_type_{sheet_name}"
                )
                sheet_types[sheet_name] = sheet_type
        
        component_type = Path(uploaded_file.name).stem
        existing = next((c for c in st.session_state.components if c['component_type'] == component_type), None)
        
        if existing:
            st.warning(f"⚠️ 构件类型 '{component_type}' 已存在！")
            
            import_mode = st.radio(
                "导入模式",
                options=['merge', 'replace'],
                format_func=lambda x: {'merge': '🟡 智能合并（相同CODE覆盖，不同CODE新增）',
                                      'replace': '🔴 完全替换（删除原有，使用新数据）'}.get(x),
                key="import_mode"
            )
        else:
            import_mode = 'replace'
            st.info(f"📥 将导入新构件类型: {component_type}")
        
        if st.button("✅ 确认导入", type="primary", use_container_width=True):
            new_component = import_excel_file(uploaded_file, sheet_types)
            
            if new_component:
                if existing and import_mode == 'merge':
                    merged_props, stats = merge_properties(existing['properties'], new_component['properties'])
                    existing['properties'] = merged_props
                    existing['updated_at'] = datetime.now().isoformat()
                    existing['source_file'] = new_component['source_file']
                    
                    total_added = sum(s['added'] for s in stats.values())
                    total_updated = sum(s['updated'] for s in stats.values())
                    
                    st.success(f"✅ 已合并: 新增{total_added}个, 更新{total_updated}个")
                else:
                    if existing:
                        idx = st.session_state.components.index(existing)
                        st.session_state.components[idx] = new_component
                    else:
                        st.session_state.components.append(new_component)
                    
                    st.success(f"✅ 已导入: {component_type}")
                
                if save_components(st.session_state.components):
                    st.rerun()
    
    except Exception as e:
        st.error(f"导入失败: {e}")

def handle_batch_import(folder_path: str):
    """处理批量导入"""
    folder = Path(folder_path)
    
    if not folder.exists():
        st.error(f"❌ 文件夹不存在: {folder_path}")
        return
    
    excel_files = list(folder.glob("*.xls")) + list(folder.glob("*.xlsx")) + list(folder.glob("*.xlsm"))
    
    if not excel_files:
        st.warning(f"⚠️ 文件夹中没有Excel文件: {folder_path}")
        return
    
    st.info(f"📂 找到 {len(excel_files)} 个Excel文件")
    
    success_count = 0
    failed_files = []
    
    progress_bar = st.progress(0)
    
    for i, excel_file in enumerate(excel_files):
        try:
            with open(excel_file, 'rb') as f:
                xl = pd.ExcelFile(f)
                sheet_types = {}
                
                for sheet_name in xl.sheet_names:
                    detected = detect_sheet_type(sheet_name)
                    if detected:
                        sheet_types[sheet_name] = detected
                
                f.seek(0)
                new_component = import_excel_file(f, sheet_types)
                
                if new_component:
                    existing_idx = None
                    for idx, comp in enumerate(st.session_state.components):
                        if comp['component_type'] == new_component['component_type']:
                            existing_idx = idx
                            break
                    
                    if existing_idx is not None:
                        existing = st.session_state.components[existing_idx]
                        merged_props, _ = merge_properties(existing['properties'], new_component['properties'])
                        existing['properties'] = merged_props
                        existing['updated_at'] = datetime.now().isoformat()
                    else:
                        st.session_state.components.append(new_component)
                    
                    success_count += 1
        
        except Exception as e:
            failed_files.append((excel_file.name, str(e)))
        
        progress_bar.progress((i + 1) / len(excel_files))
    
    if save_components(st.session_state.components):
        st.success(f"✅ 批量导入完成: 成功{success_count}个")
        
        if failed_files:
            st.error(f"❌ 失败 {len(failed_files)} 个:")
            for name, error in failed_files:
                st.write(f"  - {name}: {error}")
        
        st.rerun()

def handle_create_component(name: str):
    """处理创建新构件类型"""
    if any(c['component_type'] == name for c in st.session_state.components):
        st.error(f"❌ 构件类型 '{name}' 已存在")
        return
    
    new_component = {
        'component_type': name,
        'properties': {'attributes': [], 'calculations': [], 'core_params': []},
        'source_file': 'manual',
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat()
    }
    
    st.session_state.components.append(new_component)
    
    if save_components(st.session_state.components):
        st.session_state.selected_component = name
        st.success(f"✅ 已创建: {name}")
        st.rerun()

def render_component_list():
    """渲染构件类型列表"""
    st.subheader("📑 构件类型列表")
    
    components = st.session_state.components
    
    search_term = st.text_input("🔍 搜索", placeholder="输入关键词...")
    
    filtered = components
    if search_term:
        filtered = [c for c in components if search_term.lower() in c['component_type'].lower()]
    
    if filtered:
        names = [c['component_type'] for c in filtered]
        
        selected = st.radio(
            "选择构件类型",
            names,
            index=names.index(st.session_state.selected_component) if st.session_state.selected_component in names else 0
        )
        
        if selected != st.session_state.selected_component:
            st.session_state.selected_component = selected
            st.session_state.edit_mode = False
            st.session_state.batch_edit_mode = False
            st.session_state.active_tab = 0  # 重置标签页
            st.rerun()
    else:
        st.info("暂无数据")

def render_component_detail():
    """渲染构件详情"""
    components = st.session_state.components
    
    current = None
    current_idx = None
    for idx, comp in enumerate(components):
        if comp['component_type'] == st.session_state.selected_component:
            current = comp
            current_idx = idx
            break
    
    if not current:
        return
    
    # 标题和操作按钮
    render_component_header(current, current_idx)
    
    st.divider()
    
    # 属性标签页 - 使用 st.tabs 并保存选中状态
    props = current['properties']
    
    tab_names = [
        f"📋 项目特征/属性 ({len(props.get('attributes', []))})",
        f"🔢 计算项目 ({len(props.get('calculations', []))})",
        f"⚙️ 属性默认值/核心项目 ({len(props.get('core_params', []))})"
    ]
    
    # 使用 tabs，保持选中状态
    tabs = st.tabs(tab_names)
    
    # 渲染每个标签页内容
    with tabs[0]:
        st.session_state.active_tab = 0
        render_property_section(current, 'attributes', '项目特征/属性')
    
    with tabs[1]:
        st.session_state.active_tab = 1
        render_property_section(current, 'calculations', '计算项目')
    
    with tabs[2]:
        st.session_state.active_tab = 2
        render_property_section(current, 'core_params', '属性默认值/核心项目')

def render_component_header(component, idx):
    """渲染构件头部"""
    components = st.session_state.components
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        with st.expander(f"🔧 {component['component_type']}", expanded=False):
            new_name = st.text_input("修改名称", value=component['component_type'], key="rename")
            
            if st.button("💾 确认重命名", use_container_width=True):
                if new_name and new_name != component['component_type']:
                    if any(c['component_type'] == new_name for c in components if c != component):
                        st.error(f"❌ '{new_name}' 已存在")
                    else:
                        component['component_type'] = new_name
                        component['updated_at'] = datetime.now().isoformat()
                        
                        if save_components(components):
                            st.session_state.selected_component = new_name
                            st.success("✅ 已重命名")
                            st.rerun()
    
    with col2:
        st.write("")
        if st.button("🗑️ 删除", type="secondary"):
            components.pop(idx)
            if save_components(components):
                st.session_state.selected_component = None
                st.success("✅ 已删除")
                st.rerun()
    
    # 操作模式按钮 - 全局状态
    st.write("**操作模式：**")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.session_state.edit_mode:
            if st.button("✏️ 编辑模式 (开启)", type="primary", use_container_width=True):
                st.session_state.edit_mode = False
                st.rerun()
        else:
            if st.button("✏️ 编辑模式", use_container_width=True):
                st.session_state.edit_mode = True
                st.session_state.batch_edit_mode = False
                st.rerun()
    
    with col2:
        if st.session_state.batch_edit_mode:
            if st.button("📋 批量编辑 (开启)", type="primary", use_container_width=True):
                st.session_state.batch_edit_mode = False
                st.rerun()
        else:
            if st.button("📋 批量编辑", use_container_width=True):
                st.session_state.batch_edit_mode = True
                st.session_state.edit_mode = False
                st.rerun()
    
    with col3:
        component_json = json.dumps(component, ensure_ascii=False, indent=2)
        st.download_button(
            label="📄 导出JSON",
            data=component_json,
            file_name=f"{component['component_type']}.json",
            mime='application/json',
            use_container_width=True
        )

def render_property_section(component, section_type: str, section_name: str):
    """渲染属性区域"""
    properties = component['properties'].get(section_type, [])
    
    # 编辑模式 - 全局状态，所有标签页共享
    if st.session_state.edit_mode:
        render_edit_mode(component, section_type, section_name)
    elif st.session_state.batch_edit_mode:
        render_batch_edit(component, section_type, section_name)
    else:
        # 查看模式
        if not properties:
            st.info(f"暂无{section_name}")
            return
        
        # 显示表格
        if section_type == 'attributes':
            data = []
            for p in properties:
                values_str = '、'.join(p.get('values', []))[:40]
                data_type_class = f"data-type-{p.get('data_type', 'text')}"
                data.append({
                    '名称': p.get('name', ''),
                    'CODE': p.get('code', ''),
                    '类型': f'<span class="{data_type_class}">{p.get("data_type", "text")}</span>',
                    '可选值': values_str + '...' if len('、'.join(p.get('values', []))) > 40 else values_str
                })
        
        elif section_type == 'calculations':
            data = [{
                '名称': p.get('name', ''),
                'CODE': p.get('code', ''),
                '表达式': p.get('expression', ''),
                '单位': p.get('unit', '')
            } for p in properties]
        
        else:  # core_params
            data = []
            for p in properties:
                data_type_class = f"data-type-{p.get('data_type', 'text')}"
                data.append({
                    '名称': p.get('name', ''),
                    'CODE': p.get('code', ''),
                    '类型': f'<span class="{data_type_class}">{p.get("data_type", "text")}</span>',
                    '默认值': p.get('value', '')
                })
        
        df = pd.DataFrame(data)
        st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)

def render_edit_mode(component, section_type: str, section_name: str):
    """渲染编辑模式"""
    properties = component['properties'].get(section_type, [])
    
    # 添加新属性
    st.subheader(f"➕ 添加{section_name}")
    
    with st.form(f"add_{section_type}_{component['component_type']}"):
        col1, col2 = st.columns(2)
        
        with col1:
            name = st.text_input("名称", placeholder=f"如: {section_name}名称")
        
        with col2:
            code = st.text_input("CODE", placeholder="如: CODE").upper()
        
        if section_type == 'attributes':
            col3, col4 = st.columns(2)
            with col3:
                data_type = st.selectbox("数据类型", options=['text', 'number'])
            with col4:
                st.write("")
            values = st.text_area("可选值（每行一个）", placeholder="值1\n值2\n值3")
        
        elif section_type == 'calculations':
            expression = st.text_input("计算表达式", placeholder="如: 长*宽*高")
            unit = st.text_input("单位", placeholder="如: m³")
        
        else:  # core_params
            col3, col4 = st.columns(2)
            with col3:
                data_type = st.selectbox("数据类型", options=['text', 'number'])
            with col4:
                st.write("")
            value = st.text_input("默认值", placeholder="默认值")
        
        submitted = st.form_submit_button("✅ 添加", use_container_width=True)
        
        if submitted:
            if not name or not code:
                st.error("❌ 名称和CODE不能为空")
            elif any(p.get('code') == code for p in properties):
                st.error(f"❌ CODE '{code}' 已存在")
            else:
                if section_type == 'attributes':
                    new_item = {'name': name, 'code': code, 'data_type': data_type, 
                               'values': [v.strip() for v in values.split('\n') if v.strip()]}
                elif section_type == 'calculations':
                    new_item = {'name': name, 'code': code, 'expression': expression, 'unit': unit}
                else:
                    new_item = {'name': name, 'code': code, 'data_type': data_type, 'value': value}
                
                properties.append(new_item)
                component['updated_at'] = datetime.now().isoformat()
                
                if save_components(st.session_state.components):
                    st.success(f"✅ 已添加: {name}")
                    # 保持在当前标签页，不rerun
    
    st.divider()
    
    # 编辑现有属性
    st.subheader(f"✏️ 编辑现有{section_name}")
    
    if not properties:
        st.info(f"暂无{section_name}，请在上方添加")
        return
    
    for i, prop in enumerate(properties):
        with st.container():
            st.markdown(f"**{i+1}. {prop.get('name', '')} ({prop.get('code', '')})**")
            
            with st.form(f"edit_{section_type}_{i}_{component['component_type']}"):
                col1, col2 = st.columns(2)
                
                with col1:
                    new_name = st.text_input("名称", value=prop.get('name', ''))
                
                with col2:
                    new_code = st.text_input("CODE", value=prop.get('code', '')).upper()
                
                # 类型特定字段
                if section_type == 'attributes':
                    col3, col4 = st.columns(2)
                    with col3:
                        current_dtype = prop.get('data_type', 'text')
                        dtype_index = 0 if current_dtype == 'text' else 1
                        new_data_type = st.selectbox("数据类型", options=['text', 'number'], index=dtype_index)
                    with col4:
                        st.write("")
                    new_values = st.text_area("可选值（每行一个）", 
                                             value='\n'.join(prop.get('values', [])), height=80)
                
                elif section_type == 'calculations':
                    new_expression = st.text_input("计算表达式", value=prop.get('expression', ''))
                    new_unit = st.text_input("单位", value=prop.get('unit', ''))
                
                else:  # core_params
                    col3, col4 = st.columns(2)
                    with col3:
                        current_dtype = prop.get('data_type', 'text')
                        dtype_index = 0 if current_dtype == 'text' else 1
                        new_data_type = st.selectbox("数据类型", options=['text', 'number'], index=dtype_index)
                    with col4:
                        st.write("")
                    new_value = st.text_input("默认值", value=prop.get('value', ''))
                
                col_save, col_delete = st.columns(2)
                
                with col_save:
                    save_submitted = st.form_submit_button("💾 保存修改", use_container_width=True)
                
                with col_delete:
                    delete_submitted = st.form_submit_button("🗑️ 删除", type="secondary", use_container_width=True)
                
                if save_submitted:
                    other_codes = [p.get('code', '') for j, p in enumerate(properties) if j != i]
                    if new_code in other_codes:
                        st.error(f"❌ CODE '{new_code}' 已存在")
                    else:
                        prop['name'] = new_name
                        prop['code'] = new_code
                        
                        if section_type == 'attributes':
                            prop['data_type'] = new_data_type
                            prop['values'] = [v.strip() for v in new_values.split('\n') if v.strip()]
                        elif section_type == 'calculations':
                            prop['expression'] = new_expression
                            prop['unit'] = new_unit
                        else:
                            prop['data_type'] = new_data_type
                            prop['value'] = new_value
                        
                        component['updated_at'] = datetime.now().isoformat()
                        
                        if save_components(st.session_state.components):
                            st.success("✅ 已保存")
                            # 保持在当前标签页
                
                if delete_submitted:
                    properties.pop(i)
                    component['updated_at'] = datetime.now().isoformat()
                    
                    if save_components(st.session_state.components):
                        st.success("✅ 已删除")
                        # 保持在当前标签页
            
            st.divider()

def render_batch_edit(component, section_type: str, section_name: str):
    """渲染批量编辑模式"""
    properties = component['properties'].get(section_type, [])
    
    st.subheader(f"📋 批量编辑{section_name}")
    
    # 批量编辑 - 即使没有数据也要显示添加界面
    if not properties:
        st.info(f"暂无{section_name}，请在下方添加")
    
    # 构建DataFrame
    if section_type == 'attributes':
        data = [{
            '名称': p.get('name', ''),
            'CODE': p.get('code', ''),
            '数据类型': p.get('data_type', 'text'),
            '可选值(|分隔)': '|'.join(p.get('values', []))
        } for p in properties] if properties else []
    elif section_type == 'calculations':
        data = [{
            '名称': p.get('name', ''),
            'CODE': p.get('code', ''),
            '表达式': p.get('expression', ''),
            '单位': p.get('unit', '')
        } for p in properties] if properties else []
    else:
        data = [{
            '名称': p.get('name', ''),
            'CODE': p.get('code', ''),
            '数据类型': p.get('data_type', 'text'),
            '默认值': p.get('value', '')
        } for p in properties] if properties else []
    
    # 如果没有数据，创建一个空DataFrame
    if not data:
        if section_type == 'attributes':
            data = [{'名称': '', 'CODE': '', '数据类型': 'text', '可选值(|分隔)': ''}]
        elif section_type == 'calculations':
            data = [{'名称': '', 'CODE': '', '表达式': '', '单位': ''}]
        else:
            data = [{'名称': '', 'CODE': '', '数据类型': 'text', '默认值': ''}]
    
    edited_df = st.data_editor(
        pd.DataFrame(data),
        num_rows="dynamic",
        use_container_width=True,
        key=f"batch_{section_type}_{component['component_type']}"
    )
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("💾 保存批量修改", type="primary", use_container_width=True):
            # 过滤掉空行
            valid_rows = edited_df[(edited_df['名称'] != '') | (edited_df['CODE'] != '')]
            
            codes = [row['CODE'] for _, row in valid_rows.iterrows() if row['CODE']]
            if len(codes) != len(set(codes)):
                st.error("❌ CODE不能重复")
                return
            
            new_properties = []
            for _, row in valid_rows.iterrows():
                if section_type == 'attributes':
                    new_properties.append({
                        'name': row['名称'],
                        'code': row['CODE'].upper(),
                        'data_type': row['数据类型'],
                        'values': [v.strip() for v in str(row['可选值(|分隔)']).split('|') if v.strip()]
                    })
                elif section_type == 'calculations':
                    new_properties.append({
                        'name': row['名称'],
                        'code': row['CODE'].upper(),
                        'expression': row['表达式'],
                        'unit': row['单位']
                    })
                else:
                    new_properties.append({
                        'name': row['名称'],
                        'code': row['CODE'].upper(),
                        'data_type': row['数据类型'],
                        'value': row['默认值']
                    })
            
            component['properties'][section_type] = new_properties
            component['updated_at'] = datetime.now().isoformat()
            
            if save_components(st.session_state.components):
                st.success("✅ 已保存")
                # 保持在当前标签页
    
    with col2:
        if st.button("❌ 取消", use_container_width=True):
            st.rerun()

if __name__ == '__main__':
    main()

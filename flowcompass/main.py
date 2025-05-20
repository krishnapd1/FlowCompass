"""
Python Function Execution Flow Tracer
"""
import os
import ast
import json
import argparse
from collections import defaultdict
from typing import List, Dict, Optional, Set

# Metadata for each function
dataclass = __import__('dataclasses').dataclass

@dataclass
class FunctionMeta:
    func_name: str
    qualified_name: str
    file_path: str
    lineno: int
    docstring: str
    code: str
    node: ast.FunctionDef

@dataclass
class FunctionCallNode:
    func_name: str
    qualified_name: str
    file_path: str
    lineno: int
    call_line: int
    func_docstring: str
    func_code: str
    call_order: int
    external_call: bool = False
    is_recursive: bool = False
    threaded: bool = False
    child_calls: List['FunctionCallNode'] = None

    def to_dict(self):
        return {
            "func_name": self.func_name,
            "qualified_name": self.qualified_name,
            "file_path": self.file_path,
            "lineno": self.lineno,
            "call_line": self.call_line,
            "func_docstring": self.func_docstring,
            "func_code": self.func_code,
            "call_order": self.call_order,
            "external_call": self.external_call,
            "is_recursive": self.is_recursive,
            "threaded": self.threaded,
            "child_calls": [c.to_dict() for c in self.child_calls or []],
        }

class FunctionIndexer:
    def __init__(self, source_dir: str):
        self.source_dir = source_dir
        self.function_index: Dict[str, List[FunctionMeta]] = defaultdict(list)

    def index(self):
        for root, _, files in os.walk(self.source_dir):
            for file in files:
                if file.endswith('.py'):
                    path = os.path.join(root, file)
                    rel_path = os.path.relpath(path, self.source_dir)
                    
                    with open(path, 'r', encoding='utf-8') as f:
                        source = f.read()
                        tree = ast.parse(source, filename=path)
                        
                        # Index functions and methods
                        for node in ast.walk(tree):
                            if isinstance(node, ast.FunctionDef):
                                qualified_name = node.name
                                docstring = ast.get_docstring(node) or ""
                                code = ast.get_source_segment(source, node)
                                
                                self.function_index[node.name].append(
                                    FunctionMeta(
                                        func_name=node.name,
                                        qualified_name=qualified_name,
                                        file_path=rel_path,
                                        lineno=node.lineno,
                                        docstring=docstring,
                                        code=code,
                                        node=node
                                    )
                                )
        return self.function_index

class CallVisitor(ast.NodeVisitor):
    def __init__(self, index, include_external, skip_threaded):
        self.index = index
        self.include_external = include_external
        self.skip_threaded = skip_threaded
        self.calls = []  # list of (FunctionMeta, call_lineno)

    def visit_Call(self, node):
        # Regular function calls
        name = self.get_call_name(node)
        if name in self.index:
            self.calls.append((self.index[name][0], node.lineno))
        elif self.include_external:
            fake_meta = FunctionMeta(
                func_name=name,
                qualified_name=name,
                file_path="<external>",
                lineno=0,
                docstring="",
                code="",
                node=ast.FunctionDef(name=name, args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=[], decorator_list=[])
            )
            self.calls.append((fake_meta, node.lineno))
        
        # Special handling for ThreadPoolExecutor.submit
        if isinstance(node.func, ast.Attribute) and node.func.attr == 'submit':
            # This is a executor.submit(...) call
            if node.args and len(node.args) > 0:
                # The first argument is the function to execute
                func_arg = node.args[0]
                self.add_threaded_call(func_arg, node)
        
        # Add support for threading.Thread(target=func)
        if isinstance(node.func, ast.Name) and node.func.id == 'Thread' or \
        (isinstance(node.func, ast.Attribute) and node.func.attr == 'Thread' and
            isinstance(node.func.value, ast.Name) and node.func.value.id == 'threading'):
            
            # Look for target=func parameter
            for kw in node.keywords:
                if kw.arg == 'target':
                    self._add_threaded_function(kw.value, node.lineno)
                    break
                
        self.generic_visit(node)

    def add_threaded_call(self, func_arg, node):
        if isinstance(func_arg, ast.Attribute) and hasattr(func_arg.value, 'id'):
            # For patterns like module.function (e.g., itemSearch_service.execute_search)
            func_name = func_arg.attr
            
            # Add this as a function call if not skipping threaded calls
            if not self.skip_threaded:
                if func_name in self.index:
                    self.calls.append((self.index[func_name][0], node.lineno))
                elif self.include_external:
                    fake_meta = FunctionMeta(
                        func_name=func_name,
                        qualified_name=f"{func_arg.value.id}.{func_name}",
                        file_path="<external-threaded>",
                        lineno=0,
                        docstring="",
                        code="",
                        node=ast.FunctionDef(name=func_name, args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=[], decorator_list=[])
                    )
                    self.calls.append((fake_meta, node.lineno))
                    
        elif isinstance(func_arg, ast.Name):
            # For simple function references
            func_name = func_arg.id
            if not self.skip_threaded:
                if func_name in self.index:
                    self.calls.append((self.index[func_name][0], node.lineno))
                elif self.include_external:
                    fake_meta = FunctionMeta(
                        func_name=func_name,
                        qualified_name=func_name,
                        file_path="<external-threaded>",
                        lineno=0,
                        docstring="",
                        code="",
                        node=ast.FunctionDef(name=func_name, args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=[], decorator_list=[])
                    )
                    self.calls.append((fake_meta, node.lineno))
    def get_call_name(self, node):
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            return node.func.attr
        return "<unknown>"

class CallAnalyzer:
    def __init__(self, index: Dict[str, List[FunctionMeta]], include_external=False, skip_threaded=False):
        self.index = index
        self.include_external = include_external
        self.skip_threaded = skip_threaded
        self.visited: Set[str] = set()

    def analyze(self, func_meta: FunctionMeta, call_line=0, call_order=0, path_stack=None) -> FunctionCallNode:
        if path_stack is None:
            path_stack = []

        full_name = func_meta.qualified_name
        is_recursive = full_name in path_stack
        path_stack.append(full_name)

        node = FunctionCallNode(
            func_name=func_meta.func_name,
            qualified_name=func_meta.qualified_name,
            file_path=func_meta.file_path,
            lineno=func_meta.lineno,
            call_line=call_line,
            func_docstring=func_meta.docstring,
            func_code=func_meta.code,
            call_order=call_order,
            external_call=func_meta.file_path.startswith('<external'),
            is_recursive=is_recursive,
            threaded=False,  # Will be updated for threaded calls
            child_calls=[]
        )

        if is_recursive:
            return node

        # Use visitor to find all function calls
        visitor = CallVisitor(self.index, self.include_external, self.skip_threaded)
        visitor.visit(func_meta.node)
        
        visited_funcs = []
        # Process each function call
        for i, call_info in enumerate(visitor.calls):
            meta, lineno = call_info
            
            # Check if this is a threaded call (from executor.submit)
            is_threaded = meta.file_path.startswith('<external-threaded>')
            
            # Create the child node recursively
            child_node = self.analyze(
                meta, call_line=lineno, call_order=i + 1, path_stack=path_stack[:])
                
            # Update threaded status if needed
            child_node.threaded = is_threaded
            
            # Add to the call tree
            print(child_node.func_name, child_node.threaded)
            if child_node.func_name not in ["advanced_query"] and child_node.func_name not in visited_funcs:
                visited_funcs.append(child_node.func_name)
                node.child_calls.append(child_node)
        
        return node

class OutputRenderer:
    def __init__(self, root: FunctionCallNode):
        self.root = root

    def print_tree(self, node: Optional[FunctionCallNode] = None, prefix=""):
        node = node or self.root
        thread_indicator = "[THREADED] " if node.threaded else ""
        docstring_preview = node.func_docstring[:40] + ('...' if len(node.func_docstring) > 40 else '')
        
        # Add call_order to the output
        order_indicator = f"({node.call_order}) " if node.call_order > 0 else ""
        
        print(f"{prefix}{order_indicator}{thread_indicator}{node.func_name} ({node.file_path}) [{docstring_preview}]")
        
        # Sort child calls by call_order before printing
        sorted_children = sorted(node.child_calls, key=lambda x: x.call_order)
        for child in sorted_children:
            self.print_tree(child, prefix + "|   ")

    def save_json(self, path):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.root.to_dict(), f, indent=2)

css_styles = """
        :root {
            --primary-color: #0d6efd;
            --secondary-color: #6c757d;
            --accent-color: #3f51b5;
            --light-bg: #f8f9fa;
            --dark-bg: #212529;
            --border-color: #dee2e6;
            --success-color: #4caf50;
            --warning-color: #ff9800;
            --info-color: #03a9f4;
        }

        * {
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 0;
            height: 100vh;
            overflow: hidden;
            background-color: #f5f7fa;
            color: #333;
        }

        .app-container {
            display: flex;
            flex-direction: column;
            height: 100vh;
            overflow: hidden;
        }

        .header {
            background: linear-gradient(135deg, #1a5fb4 0%, #38b6ff 100%);
            color: white;
            padding: 0.8rem 1.5rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            z-index: 100;
        }

        .header-title {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .header-icon {
            background-color: white;
            color: var(--primary-color);
            width: 36px;
            height: 36px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 2px 5px rgba(0,0,0,0.2);
        }

        .header-actions {
            display: flex;
            gap: 8px;
        }

        .btn {
            border: none;
            border-radius: 4px;
            padding: 6px 16px;
            font-weight: 500;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s;
        }

        .btn-sm {
            padding: 4px 12px;
            font-size: 0.85rem;
        }

        .btn-icon {
            padding: 6px;
            border-radius: 50%;
            width: 32px;
            height: 32px;
        }

        .btn-primary {
            background-color: white;
            color: var(--primary-color);
        }

        .btn-primary:hover {
            background-color: rgba(255,255,255,0.9);
        }

        .btn-success {
            background-color: var(--success-color);
            color: white;
        }

        .btn-outline {
            background-color: transparent;
            color: white;
            border: 1px solid rgba(255,255,255,0.5);
        }

        .btn-outline:hover {
            background-color: rgba(255,255,255,0.1);
        }

        /* Main content - side by side layout */
        .main-content {
            display: flex;
            height: calc(100vh - 56px);
            overflow: hidden;
            position: relative;
        }

        .flowchart-panel {
            width: 70%;
            height: 100%;
            border-right: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            background-color: white;
            position: relative;
        }

        .code-panel {
            width: 30%;
            height: 100%;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            background-color: white;
        }

        .panel-header {
            padding: 12px 16px;
            background-color: #f5f5f5;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .panel-title {
            font-size: 16px;
            font-weight: 500;
            color: var(--secondary-color);
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .panel-body {
            flex: 1;
            overflow: auto;
            position: relative;
        }

        /* Resizable panels */
        .resizer {
            width: 8px;
            height: 100%;
            background-color: #f5f5f5;
            border-left: 1px solid #dadce0;
            border-right: 1px solid #dadce0;
            position: absolute;
            right: 0;
            top: 0;
            cursor: col-resize;
            z-index: 10;
        }

        .resizer:hover, .resizer.active {
            background-color: #d5d9e2;
        }

        /* Fix for zooming - keep content in viewport */
        .mermaid-container {
            height: 100%;
            width: 100%;
            overflow: auto;
            position: relative;
            contain: strict;
        }

        .mermaid {
            min-width: 100%;
            min-height: 100%;
            padding: 20px;
            transform-origin: center;
            transition: transform 0.3s ease;
        }

        .empty-state {
            height: 100%;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            color: var(--secondary-color);
            padding: 2rem;
            text-align: center;
        }

        .empty-icon {
            font-size: 48px;
            margin-bottom: 1rem;
            opacity: 0.5;
        }

        /* Code containers */
        .code-container {
            display: none;
            flex-direction: column;
            flex: 1;
            overflow: auto;
            margin: 0;
        }

        .code-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 15px;
            background-color: #f8f9fa;
            border-bottom: 1px solid #eaeaea;
        }

        .code-title {
            display: flex;
            align-items: center;
        }

        .function-title {
            color: var(--primary-color);
            font-weight: 600;
            margin-right: 10px;
        }

        .file-path {
            font-size: 0.8rem;
            color: #666;
            font-style: italic;
            margin-top: 4px;
        }

        .code-content {
            padding: 15px;
            background-color: #fafafa;
            overflow-y: auto;
        }

        /* Nav tabs styling */
        .nav-tabs {
            border-bottom: 1px solid var(--border-color);
        }

        .nav-tabs .nav-link {
            border: none;
            color: var(--secondary-color);
            padding: 10px 15px;
            font-weight: 500;
            border-radius: 0;
            margin-right: 2px;
        }

        .nav-tabs .nav-link.active {
            color: var(--primary-color);
            background-color: transparent;
            border-bottom: 2px solid var(--primary-color);
        }

        .nav-tabs .nav-link:hover {
            border-color: transparent;
            background-color: rgba(13, 110, 253, 0.05);
        }

        .tab-content {
            flex: 1;
            overflow: hidden;
        }

        .tab-pane {
            height: 100%;
        }

        pre {
            margin: 0;
            border-radius: 6px;
        }

        code {
            border-radius: 6px;
            font-family: 'Cascadia Code', 'Fira Code', Consolas, monospace;
        }

        .docstring {
            font-size: 0.85rem;
            color: #666;
            font-style: italic;
            margin-top: 4px;
            padding: 6px;
            background-color: rgba(0, 0, 0, 0.03);
            border-left: 3px solid #0d6efd;
        }

        .function-calls-list {
            padding: 10px 15px;
            background-color: #f0f7f4;
            border-left: 3px solid var(--accent-color);
            margin-bottom: 0;
        }

        .function-calls-list ol {
            margin-bottom: 0;
            padding-left: 25px;
        }

        .call-sequence {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 18px;
            height: 18px;
            border-radius: 50%;
            background-color: var(--accent-color);
            color: white;
            font-size: 0.7rem;
            font-weight: bold;
            margin-right: 8px;
        }

        .sequence-badge {
            display: inline-block;
            font-size: 0.65rem;
            font-weight: bold;
            color: #555;
        }

        .zoom-controls {
            background-color: white;
            border-radius: 4px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
            z-index: 10;
        }

        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }

        .animate-fade-in {
            animation: fadeIn 0.3s ease forwards;
        }

        .loading-progress {
            height: 3px;
            width: 100%;
            position: fixed;
            top: 0;
            left: 0;
            background-color: var(--accent-color);
            z-index: 9999;
            animation: progress 2s ease-in-out;
        }

        @keyframes progress {
            0% { width: 0%; }
            50% { width: 50%; }
            100% { width: 100%; }
        }

        .clickable-node:hover {
            cursor: pointer;
            opacity: 0.9;
        }

        @media (max-width: 1200px) {
            .main-content {
                flex-direction: column;
            }

            .flowchart-panel {
                width: 100%;
                height: 70%;
                border-right: none;
                border-bottom: 1px solid var(--border-color);
            }

            .code-panel {
                width: 100%;
                height: 30%;
            }

            .resizer {
                display: none;
            }
        }

        .mermaid .node path {
            fill: #ECECFF;
            stroke: #9370DB;
            stroke-width: 1px;
        }

        .mermaid .node text {
            fill: #333;
            font-weight: 500;
        }

        .mermaid .edgePath .path {
            stroke: #9370DB;
            stroke-width: 1.5px;
        }

        .mermaid .flowchart-link {
            stroke: #9370DB;
            fill: none;
        }

        .mermaid .marker {
            fill: #9370DB;
        }
    """

def generate_html(source, output_path=None):
    """Generate an HTML visualization of the function call tree.
    
    Args:
        source: Either a FunctionCallNode object or a path to a JSON file
        output_path: Path where the HTML file will be saved. If None, generates from function name
    
    Returns:
        str: Path to the generated HTML file
    """
    import json
    import html
    import re
    from datetime import datetime
    
    # Handle input - either FunctionCallNode or JSON file path
    if isinstance(source, str):
        # Load from JSON file
        with open(source, 'r', encoding='utf-8') as f:
            data = json.load(f)
            root_func_name = data.get("func_name", "function")
    else:
        # Use FunctionCallNode directly
        data = source.to_dict()
        root_func_name = source.func_name
    
    # Set default output path if none provided
    if output_path is None:
        output_path = f"{root_func_name}_flowchart.html"
    
    # CSS styles extracted from reference
    
    
    # Create mermaid flowchart
    mermaid_chart = "flowchart TD\n"
    
    # Track nodes and edges
    nodes = []
    edges = []
    node_ids = {}
    node_count = 0
    
    # Add class definitions
    nodes.append("    classDef root color:black,font-weight:bold")
    nodes.append("    classDef node color:black")
    nodes.append("    classDef threadedNode stroke:#2196f3,stroke-width:2px")
    
    # Process nodes recursively and build a mapping
    def process_node(node_data, parent_id=None):
        nonlocal node_count
        
        func_name = node_data["func_name"]
        
        # Create a unique ID for this node that's safe for mermaid
        func_id = re.sub(r'[^a-zA-Z0-9]', '_', func_name)
        
        # Create a safe node ID
        if func_id not in node_ids:
            node_id = func_id
            node_key = func_id
            node_ids[func_id] = func_id
        else:
            # If we already have this ID, make it unique
            node_id = f"{func_id}_{node_count}"
            node_key = func_id
            node_ids[func_id + str(node_count)] = node_id
            node_count += 1
        
        # Create node label
        file_path = node_data.get("file_path", "unknown")
        docstring = node_data.get("func_docstring", "")
        
        # Truncate docstring
        if docstring and len(docstring) > 40:
            docstring = docstring[:40] + "..."
        
        # Escape special characters
        docstring = html.escape(docstring)
        
        # Create node label HTML
        file_info = f"<div class='file-path'>{html.escape(file_path)}</div>"
        docstring_text = f"<div class='docstring'>{docstring}</div>" if docstring else ""
        node_label = f"{html.escape(func_name)}{file_info}{docstring_text}"
        
        # Determine node class
        if parent_id is None:
            nodes.append(f"    {node_id}[\"{node_label}\"]:::root")
        else:
            nodes.append(f"    {node_id}[\"{node_label}\"]:::node")
        
        # Add class for threaded nodes
        if node_data.get("threaded", False):
            nodes.append(f"    class {node_key} threadedNode")
        
        # Make node clickable
        nodes.append(f"    class {node_id} clickable-node")
        nodes.append(f"    click {node_id} call showCode(\"{node_key}\")")
        
        # Add edge if not root node
        if parent_id is not None:
            call_order = node_data.get("call_order", 0)
            if call_order > 0:
                edges.append(f"    {parent_id} -->|\"<small class='sequence-badge'>{call_order}</small>\"| {node_id}")
            else:
                edges.append(f"    {parent_id} --> {node_id}")
        
        # Process child nodes
        for child in sorted(node_data.get("child_calls", []), key=lambda x: x.get("call_order", 0)):
            process_node(child, node_id)
        
        return node_id
    
    # Start processing from root
    root_id = process_node(data)
    
    # Add all nodes and edges to mermaid chart
    mermaid_chart += "\n".join(nodes) + "\n" + "\n".join(edges)
    
    # Generate function details for code display
    function_details = ""
    
    # Function to recursively process all nodes
    def generate_code_container(node_data):
        func_name = node_data["func_name"]
        file_path = node_data.get("file_path", "unknown")
        lineno = node_data.get("lineno", 0)
        func_code = node_data.get("func_code", "# Code not available")
        docstring = node_data.get("func_docstring", "")
        
        # Create a unique ID for this function that matches the flowchart
        func_id = re.sub(r'[^a-zA-Z0-9]', '_', func_name)
        
        # Format docstring with line breaks for display
        docstring_html = ""
        if docstring:
            escaped_docstring = html.escape(docstring).replace('\n', '<br>')
            docstring_html = f"""
            <div class="card mb-3">
                <div class="card-header bg-light">
                    <i class="fas fa-comment-alt me-2"></i>
                    Documentation
                </div>
                <div class="card-body">
                    <div class="docstring">{escaped_docstring}</div>
                </div>
            </div>"""
        
        # Generate function calls list if there are child calls
        calls_html = ""
        child_calls = node_data.get("child_calls", [])
        if child_calls:
            calls_list = []
            for i, child in enumerate(sorted(child_calls, key=lambda x: x.get("call_order", 0))):
                call_order = child.get("call_order", i + 1)
                calls_list.append(f"<li><span class='call-sequence'>{call_order}</span> {html.escape(child.get('func_name', 'unknown'))}</li>")
            
            calls_html = f"""
            <div class="card mb-3">
                <div class="card-header bg-light">
                    <i class="fas fa-exchange-alt me-2"></i>
                    Function Calls
                </div>
                <div class="card-body p-0">
                    <div class="function-calls-list">
                        <ol>
                            {"".join(calls_list)}
                        </ol>
                    </div>
                </div>
            </div>"""
        
        # Generate the HTML for this function's code container
        container_html = f"""
        <div id="code-{func_id}" class="code-container">
            <div class="card shadow-sm border-0">
                <div class="card-header bg-white p-3 border-bottom d-flex justify-content-between align-items-center">
                    <div class="d-flex align-items-center">
                        <div class="function-icon rounded bg-primary bg-opacity-10 p-2 me-3">
                            <i class="fas fa-function text-primary"></i>
                        </div>
                        <div>
                            <h3 class="h5 mb-0 fw-bold function-title">{html.escape(func_name)}</h3>
                            <div class="mt-1 d-flex align-items-center">
                                <i class="fas fa-file-code text-secondary me-2"></i>
                                <span class="file-path">{html.escape(file_path)}</span>
                            </div>
                        </div>
                    </div>
                    <div class="ms-auto">
                        <button class="btn btn-sm btn-outline-secondary" type="button" id="copy-btn-{func_id}"
                                onclick="copyToClipboard('{func_id}')" title="Copy code">
                            <i class="fas fa-copy"></i>
                        </button>
                    </div>
                </div>
                <div class="card-body p-0">
                    <ul class="nav nav-tabs nav-fill" role="tablist">
                        <li class="nav-item" role="presentation">
                            <button class="nav-link active px-4 py-3" id="code-tab-{func_id}"
                                    data-bs-toggle="tab"
                                    data-bs-target="#code-content-{func_id}"
                                    type="button" role="tab">
                                <i class="fas fa-code me-2"></i>Implementation
                            </button>
                        </li>
                        {f'<li class="nav-item" role="presentation"><button class="nav-link px-4 py-3" id="docs-tab-{func_id}" data-bs-toggle="tab" data-bs-target="#docs-content-{func_id}" type="button" role="tab"><i class="fas fa-book me-2"></i>Documentation</button></li>' if docstring_html else ''}
                        {f'<li class="nav-item" role="presentation"><button class="nav-link px-4 py-3" id="calls-tab-{func_id}" data-bs-toggle="tab" data-bs-target="#calls-content-{func_id}" type="button" role="tab"><i class="fas fa-project-diagram me-2"></i>Call Hierarchy</button></li>' if calls_html else ''}
                    </ul>
                    <div class="tab-content">
                        <div class="tab-pane fade show active" id="code-content-{func_id}" role="tabpanel">
                            <div class="code-content">
                                <pre><code class="python">{html.escape(func_code)}</code></pre>
                            </div>
                        </div>
                        {f'''
                        <div class="tab-pane fade" id="docs-content-{func_id}" role="tabpanel">
                            <div class="p-4 bg-light">
                                {docstring_html}
                            </div>
                        </div>''' if docstring_html else ''}

                        {f'''
                        <div class="tab-pane fade" id="calls-content-{func_id}" role="tabpanel">
                            <div class="p-4 bg-light">
                                {calls_html}
                            </div>
                        </div>''' if calls_html else ''}
                    </div>
                </div>
            </div>
        </div>
        """
        
        result = container_html
        
        # Process children recursively
        for child in child_calls:
            result += generate_code_container(child)
            
        return result
    
    # Generate HTML for all functions
    function_details = generate_code_container(data)
    
    # Final HTML content
    html_content = f"""<!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Flow Compass: {html.escape(root_func_name)}</title>
        <!-- Bootstrap CSS -->
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
        <!-- Font Awesome -->
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <!-- Mermaid JS -->
        <script src="https://cdn.jsdelivr.net/npm/mermaid@11.6.0/dist/mermaid.min.js"></script>
        <!-- Highlight.js for syntax highlighting -->
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.7.0/styles/github.min.css">
        <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.7.0/highlight.min.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.7.0/languages/python.min.js"></script>
        <script src="https://html2canvas.hertzen.com/dist/html2canvas.min.js"></script>
        <!-- Animate.css for animations -->
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/animate.css/4.1.1/animate.min.css">
        <style>
            {css_styles}
        </style>
    </head>
    <body>
        <div class="loading-progress" id="loading-bar"></div>

        <div class="app-container">
            <div class="header">
                <div class="header-title">
                    <div class="header-icon">
                        <i class="fa-solid fa-compass"></i>
                    </div>
                    <h1 style="margin: 0; font-size: 1.25rem; font-weight: bold;">Flow Compass</h1>
                </div>
                <div class="header-actions">
                    <a class="btn btn-primary" href="https://github.com/Krishnaggarwal9" target="_blank" rel="noopener noreferrer">
                        <i class="fa-brands fa-github" style="margin-right: 8px;"></i>
                        <span>Github</span>
                    </a>
                </div>
            </div>

            <div class="main-content">
                <div class="flowchart-panel">
                    <div class="panel-header">
                        <div class="panel-title">
                            <div class="rounded-circle bg-primary d-flex align-items-center justify-content-center me-3" style="width: 36px; height: 36px;">
                                <i class="fas fa-sitemap text-white"></i>
                            </div>
                            <h2 class="h5 mb-0 fw-bold">Graph</h2>
                        </div>
                        <div class="badge bg-light text-secondary border px-3 py-2">
                            <i class="fas fa-mouse-pointer me-1"></i>
                            Click any node in the diagram to view code
                        </div>
                    </div>
                    <div class="panel-body">
                        <div class="mermaid-container" style="width: 100%; height: 100%; overflow: auto;">
                            <div class="mermaid" style="padding: 20px; transform-origin: center; transition: transform 0.3s ease;">
                            {mermaid_chart}
                            </div>
                        </div>
                        <div class="position-absolute bottom-0 end-0 m-3">
                            <div class="d-flex bg-white rounded shadow p-1">
                                <button class="btn btn-sm btn-outline-primary me-1" type="button" id="zoom-in" title="Zoom In">
                                    <i class="fas fa-search-plus"></i>
                                </button>
                                <button class="btn btn-sm btn-outline-primary me-1" type="button" id="zoom-out" title="Zoom Out">
                                    <i class="fas fa-search-minus"></i>
                                </button>
                                <button class="btn btn-sm btn-outline-secondary" type="button" id="zoom-reset" title="Reset Zoom">
                                    <i class="fas fa-sync-alt"></i>
                                </button>
                                <button class="btn btn-sm btn-outline-primary me-1" type="button" id="screenshot-btn" title="Take Screenshot">
                                    <i class="fas fa-camera"></i>
                                </button>
                                <button class="btn btn-sm btn-outline-primary" type="button" id="fullscreen-btn" title="Fullscreen">
                                    <i class="fas fa-expand"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                    <div class="resizer" id="panel-resizer"></div>
                </div>

                <div class="code-panel">
                    <div class="panel-header">
                        <div class="d-flex align-items-center">
                            <div class="rounded-circle bg-primary d-flex align-items-center justify-content-center me-3" style="width: 36px; height: 36px;">
                                <i class="fas fa-code text-white"></i>
                            </div>
                            <h2 class="h5 mb-0 fw-bold" style="color: #6c757d;">Implementation</h2>
                        </div>
                    </div>
                    <div class="panel-body p-0" id="code-display-area">
                        <div class="empty-state" id="empty-code-state">
                            <i class="fas fa-code empty-icon"></i>
                            <h3>No Function Selected</h3>
                            <p>Click on any function node in the diagram to view its implementation details.</p>
                        </div>
                        
                        {function_details}
                    </div>
                </div>
            </div>
        </div>
    """
    html_content += """
        <!-- Bootstrap Bundle with Popper -->
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/js/bootstrap.bundle.min.js"></script>

        <script>
            function copyToClipboard(funcId) {
                const codeElem = document.querySelector(`#code-content-\${funcId} code`);
                if (codeElem) {
                    const textToCopy = codeElem.textContent;
                    navigator.clipboard.writeText(textToCopy).then(
                        function() {
                            const copyBtn = document.getElementById(`copy-btn-\${funcId}`);
                            const originalHTML = copyBtn.innerHTML;
                            copyBtn.innerHTML = '<i class="fas fa-check"></i>';
                            copyBtn.classList.remove('btn-outline-secondary');
                            copyBtn.classList.add('btn-success');

                            setTimeout(function() {
                                copyBtn.innerHTML = originalHTML;
                                copyBtn.classList.remove('btn-success');
                                copyBtn.classList.add('btn-outline-secondary');
                            }, 2000);
                        },
                        function() {
                            console.error('Failed to copy text');
                        }
                    );
                }
            }

            window.showCode = function(funcId) {
                document.querySelectorAll('.code-container').forEach((container) => {
                    container.style.display = 'none';
                });
                const container = document.getElementById('code-' + funcId);
                if (container) {
                    container.classList.add('animate__animated', 'animate__fadeIn');
                    const alertElem = document.querySelector('#code-display-area .alert');
                    if (alertElem) {
                        alertElem.style.display = 'none';
                    }
                    document.getElementById('empty-code-state').style.display = 'none';
                    const displayArea = document.getElementById('code-display-area');
                    displayArea.appendChild(container);
                    container.style.display = 'block';

                    // Highlight the selected node
                    document.querySelectorAll('g.node rect, g.node circle').forEach(elem => {
                        elem.setAttribute('fill', '#f8f9fa');
                        elem.setAttribute('stroke', '#9370DB');
                        elem.setAttribute('stroke-width', '1');
                    });
                    const nodeElements = document.querySelectorAll(`[id*="${funcId}"] rect, [id*="${funcId}"] circle`);
                    nodeElements.forEach(elem => {
                        elem.setAttribute('fill', '#e3f2fd');
                        elem.setAttribute('stroke', '#0d6efd');
                        elem.setAttribute('stroke-width', '2');
                    });
                    displayArea.scrollIntoView({ behavior: 'smooth', block: 'start' });
                } else {
                    console.warn('Code container not found for: ' + funcId);
                }
                return false;
            };

            let currentZoom = 1;
            const zoomFactor = 0.1;
            const mermaidContainer = document.querySelector('.mermaid');
            const mermaidScrollContainer = document.querySelector('.mermaid-container');

            document.getElementById('zoom-in').addEventListener('click', function() {
                currentZoom += zoomFactor;
                applyZoom();
            });
            document.getElementById('zoom-out').addEventListener('click', function() {
                currentZoom = Math.max(0.5, currentZoom - zoomFactor);
                applyZoom();
            });
            document.getElementById('zoom-reset').addEventListener('click', function() {
                currentZoom = 1;
                applyZoom();
            });

            function applyZoom() {
                mermaidContainer.style.transform = `scale(${currentZoom})`;
                mermaidContainer.style.transformOrigin = 'top left';
                if (currentZoom > 1) {
                    mermaidContainer.style.minWidth = `${100 * currentZoom}%`;
                    mermaidContainer.style.minHeight = `${100 * currentZoom}%`;
                } else {
                    mermaidContainer.style.minWidth = '100%';
                    mermaidContainer.style.minHeight = '100%';
                }
            }

            document.getElementById('fullscreen-btn').addEventListener('click', function() {
                const flowchartContainer = document.querySelector('.flowchart-panel');
                if (!document.fullscreenElement) {
                    if (flowchartContainer.requestFullscreen) {
                        flowchartContainer.requestFullscreen();
                    } else if (flowchartContainer.mozRequestFullScreen) {
                        flowchartContainer.mozRequestFullScreen();
                    } else if (flowchartContainer.webkitRequestFullscreen) {
                        flowchartContainer.webkitRequestFullscreen();
                    } else if (flowchartContainer.msRequestFullscreen) {
                        flowchartContainer.msRequestFullscreen();
                    }
                    this.innerHTML = '<i class="fas fa-compress"></i>';
                } else {
                    if (document.exitFullscreen) {
                        document.exitFullscreen();
                    } else if (document.mozCancelFullScreen) {
                        document.mozCancelFullScreen();
                    } else if (document.webkitExitFullscreen) {
                        document.webkitExitFullscreen();
                    } else if (document.msExitFullscreen) {
                        document.msExitFullscreen();
                    }
                    this.innerHTML = '<i class="fas fa-expand"></i>';
                }
            });

            mermaid.initialize({
                startOnLoad: true,
                securityLevel: 'loose',
                theme: 'default',
                flowchart: {
                    useMaxWidth: true,
                    htmlLabels: true,
                    curve: 'linear'
                }
            });

            

            const resizer = document.getElementById('panel-resizer');
            const flowchartPanel = document.querySelector('.flowchart-panel');
            const codePanel = document.querySelector('.code-panel');
            const appContainer = document.querySelector('.app-container');

            let isResizing = false;
            let initialWidth;
            let initialX;
            let totalWidth;

            resizer.addEventListener('mousedown', function(e) {
                isResizing = true;
                initialWidth = flowchartPanel.offsetWidth;
                initialX = e.clientX;
                totalWidth = appContainer.offsetWidth;
                resizer.classList.add('active');
                document.body.style.userSelect = 'none';
                document.body.style.cursor = 'col-resize';
            });

            document.addEventListener('mousemove', function(e) {
                if (!isResizing) return;
                const deltaX = e.clientX - initialX;
                const newLeftPanelWidth = (initialWidth + deltaX) / totalWidth * 100;
                if (newLeftPanelWidth < 30 || newLeftPanelWidth > 80) return;
                flowchartPanel.style.width = `${newLeftPanelWidth}%`;
                codePanel.style.width = `${100 - newLeftPanelWidth}%`;
            });

            document.addEventListener('mouseup', function() {
                if (isResizing) {
                    isResizing = false;
                    resizer.classList.remove('active');
                    document.body.style.userSelect = '';
                    document.body.style.cursor = '';
                }
            });
            
            document.getElementById('screenshot-btn').addEventListener('click', function() {
            // Show loading indicator
            const btn = this;
            const originalHTML = btn.innerHTML;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
            btn.disabled = true;
            
            // Get the mermaid container
            const mermaidContainer = document.querySelector('.mermaid-container');
            
            // Take screenshot with html2canvas with higher scale factor
            html2canvas(mermaidContainer, {
                scale: 10,  // Increase scale factor for higher resolution
                backgroundColor: '#ffffff',
                useCORS: true,
                logging: false,
                allowTaint: true,
                imageTimeout: 10000  // Longer timeout for large diagrams
            }).then(canvas => {
                // Create download link
                const link = document.createElement('a');
                link.download = 'flowchart_screenshot.png';
                link.href = canvas.toDataURL('image/png', 1.0);  // Use maximum quality
                
                // Trigger download
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                
                // Restore button
                btn.innerHTML = originalHTML;
                btn.disabled = false;
            }).catch(err => {
                console.error('Screenshot error:', err);
                // Restore button
                btn.innerHTML = originalHTML;
                btn.disabled = false;
                alert('Failed to take screenshot. Check console for details.');
            });
        });
        
        </script>
    </body>
    </html>
    """
    
    # Write HTML file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"HTML flowchart saved to {output_path}")
    return output_path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-dir', required=True)
    parser.add_argument('--function-name', required=True)
    parser.add_argument('--include-external', action='store_true', help="Include undefined/external calls")
    parser.add_argument('--skip-threaded', action='store_true', help="Skip threaded/parallel calls")
    parser.add_argument('--output-json', default=None, help="Output path for JSON report")
    parser.add_argument('--no-print-tree', dest='print_tree', action='store_false', help="Do not print tree to stdout")
    parser.add_argument('--generate-html', action='store_true', help="Generate HTML visualization")
    parser.add_argument('--output-html', default=None, help="Output path for HTML report")

    args = parser.parse_args()

    indexer = FunctionIndexer(args.source_dir)
    function_index = indexer.index()

    if args.function_name not in function_index:
        raise ValueError(f"Function {args.function_name} not found.")

    root_meta = function_index[args.function_name][0]
    analyzer = CallAnalyzer(function_index, args.include_external, args.skip_threaded)
    tree_root = analyzer.analyze(root_meta)

    renderer = OutputRenderer(tree_root)
    if args.print_tree:
        renderer.print_tree()

    output_json = args.output_json or f"{args.function_name}_report.json"
    renderer.save_json(output_json)
    print(f"JSON saved to {output_json}")
    
    if args.generate_html:
        output_html = args.output_html or f"{args.function_name}_flowchart.html"
        generate_html(tree_root, output_html)     
   
if __name__ == '__main__':
    main()
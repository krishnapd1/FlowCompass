
# 📘 Project Documentation: Python Function Execution Flow Tracer

---

## 📌 Overview

This tool statically analyzes a Python codebase to **trace the full execution flow** of a given top-level function. It parses all files, identifies all function definitions and call relationships, and generates:

- A **printable tree view** of the function call hierarchy.
- A **nested JSON report** with detailed metadata for each function.
- A **html flow chart** with the function call hierarchy and detailed codeflow.

---
## Installation

```bash
pip install flowcompass
```
---

## ⚙️ Command-Line Usage

```bash
flowcompass \
  --source-dir ./my_project \
  --function-name create_book_api
```

### Available Flags

| Flag | Description | Default |
|------|-------------|---------|
| `--source-dir` | Path to root codebase | *Required* |
| `--function-name` | Function to trace | *Required* |
| `--include-external` | Include undefined/external calls | `False` |
| `--skip-threaded` | Skip threaded/parallel calls | `False` |
| `--output-json` | Output path for JSON report | `<function_name>_report.json` |
| `--print-tree` | Print tree to stdout | `True` |

---

## 🧪 Example

Given the function `create_book_api`, the output might be:

```bash
create_book_api (app.py) [Main api handler for creating book]
|-- validate_input (helpers/create_book_helper.py) [validates the input given by user]
|   |-- input_validation (utility/inputvalidator.py) [simple input check]
|-- format_response (helpers/format_response.py) []
```

JSON saved as:
```
create_book_api_report.json
```

---

## ✅ Key Features

| Feature | Description |
|--------|-------------|
| Recursive Analysis | Builds a full tree of function calls starting from any named function. |
| Source-Aware | Resolves internal calls across multiple files and directories. |
| External Call Detection | Optionally includes external library or undefined calls. |
| Threaded Call Tracking | Detects calls made via `Thread`, `ThreadPoolExecutor.submit()`, etc. |
| Recursion Detection | Flags recursive calls to avoid infinite loops. |
| Call Metadata | Captures function name, docstring, file, line number, call line, and source code. |

---

## 🏗️ Architecture

### 1. **Function Indexer**
- Walks through all `.py` files in the provided directory.
- Uses `ast` to find all top-level and class-level function definitions.
- Stores them in a function index:  
  `Dict[str, List[FunctionMeta]]`

### 2. **AST Analyzer**
- Recursively visits `ast.Call` nodes within a function body.
- Resolves which functions are being called (via name or attribute).
- Creates a tree of `FunctionCallNode` objects representing call flow.

### 3. **Call Tree Builder**
- Builds a call tree with these fields:
  - `func_name`, `qualified_name`, `file_path`, `lineno`, `call_line`
  - `threaded`, `external_call`, `is_recursive`
  - `child_calls`: nested list of other `FunctionCallNode`s

### 4. **Output Renderer**
- **Tree print view** using `|--` format.
- **JSON export** for structured output or further integration.

---

## 🧩 JSON Output Schema

Each node in the call tree has this format:

```json
{
  "func_name": "validate_input",
  "qualified_name": "helpers.input.validate_input",
  "file_path": "helpers/input.py",
  "lineno": 12,
  "call_line": 25,
  "func_docstring": "Validates the input",
  "func_code": "def validate_input(...): ...",
  "call_order": 1,
  "external_call": false,
  "is_recursive": false,
  "threaded": false,
  "child_calls": [ ... ]
}
```

---

## 🧵 Threaded Call Detection

The tool detects function calls passed into:
- `executor.submit(...)`
- `threading.Thread(target=...)`

These are flagged as:
```json
"threaded": true
```

---

## 🚧 Handling Edge Cases

| Case | Handling Strategy |
|------|-------------------|
| External calls | Skipped by default, include with `--include-external` |
| Threaded calls | Included by default, skip with `--skip-threaded` |
| Recursive calls | Tracked with visited set and `is_recursive` flag |
| Function name collisions | Disambiguated via file + qualified name |
| Missing root function | Graceful error message |

---

## 🔄 Future Enhancements

| Idea | Description |
|------|-------------|
| HTML report | Interactive call tree in browser |
| Graphviz/DOT export | For visual flow diagrams |
| Full class-method resolution | Map all method calls to their class |
| Asynchronous (`async def`) support | Track coroutine flows |

---

## 🧠 Requirements

- Python 3.6+
- No external libraries required — uses `ast`, `os`, `json`, `argparse`

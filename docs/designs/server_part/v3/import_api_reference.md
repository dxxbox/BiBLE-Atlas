# Import API 接口文档

## 服务信息

- **服务地址**: `http://localhost:9220`
- **API前缀**: `/api/v1/import`
- **Content-Type**: `multipart/form-data` (上传), `application/json` (查询)

---

## 1. 向量模型说明

### 可选向量模型

| 模型ID | 模型名称 | 维度 | 特点 | 适用场景 |
|--------|---------|------|------|---------|
| `mini` | paraphrase-multilingual-MiniLM-L12-v2 | 384 | 轻量快速 | 快速原型、资源受限 |
| `mpnet` | paraphrase-multilingual-mpnet-base-v2 | 768 | 平衡性好（推荐） | 通用场景 |
| `bge-base` | BAAI/bge-base-zh-v1.5 | 768 | 中文优化基础版 | 中文文档 |
| `bge-large` | BAAI/bge-large-zh-v1.5 | 1024 | 中文优化高精度 | 中文文档，追求精度 |
| `bge-m3` | BAAI/bge-m3 | 1024 | 多语言长文本 | 多语言混合、长文档 |
| `e5-large` | intfloat/multilingual-e5-large | 1024 | 多语言高性能 | 多语言文档 |

---

## 2. 知识库类型说明

系统支持多种知识库类型，用于组织和管理不同类型的文档。每个知识库独立索引和检索。

### 可用知识库类型

| 知识库ID | 中文名称 | 说明 | 适用文档类型 |
|---------|---------|------|-------------|
| `CODE` | 代码库 | 存储源代码、函数、类定义等 | .h, .cc, .cpp, .py, .java, .go 等源代码文件 |
| `SCT` | 测试用例库 | 存储测试用例、测试脚本 | TTCN-3测试用例、单元测试、集成测试文档 |
| `BUILD` | 构建配置库 | 存储构建脚本、配置文件 | Makefile, CMakeLists.txt, build.gradle 等 |
| `SYNTAX` | 语法定义库 | 存储语法规则、ASN.1定义 | ASN.1文件、语法定义文档 |
| `SPEC` | 规格说明库 | 存储技术规范、接口文档 | 3GPP规范、API文档、协议定义 |
| `ALG` | 算法库 | 存储算法描述、数学模型 | 算法文档、公式推导、优化策略 |
| `DESIGN` | 设计文档库 | 存储架构设计、模块设计 | 设计文档、UML图、架构说明 |
| `FLOW` | 流程库 | 存储流程图、时序图 | 工作流程、业务流程、调用时序 |
| `SESSION` | 会话记录库 | 存储对话记录、问答历史 | 技术讨论、问题解决记录 |
| `SKILL` | 技能文档库 | 存储操作指南、最佳实践 | 使用手册、技能树、操作步骤 |

### 使用建议

1. **按类型分类**：将不同类型的文档导入对应的知识库，便于精确检索
2. **独立索引**：每个知识库独立建立索引，互不干扰
3. **跨库检索**：检索时可以指定多个知识库进行联合查询
4. **命名规范**：使用大写的知识库ID进行导入操作

### 示例

```bash
# 导入源代码到 CODE 库
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=CODE" \
  -F "files=@src/main.cpp"

# 导入测试用例到 SCT 库
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=SCT" \
  -F "files=@test/test_main.ttcn"

# 导入设计文档到 DESIGN 库
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=DESIGN" \
  -F "files=@docs/architecture.md"
```

---

## 3. 提交导入任务

### 基本信息
- **端点**: `POST /api/v1/import/jobs`
- **功能**: 上传文件并创建导入任务
- **请求类型**: `multipart/form-data`

### 请求参数

#### 必填参数
| 参数 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `library` | string | 目标知识库名称。可选值: `CODE`(代码), `SCT`(测试用例), `BUILD`(构建配置), `SYNTAX`(语法定义), `SPEC`(规格说明), `ALG`(算法文档), `DESIGN`(设计文档), `FLOW`(流程图), `SESSION`(会话记录), `SKILL`(技能文档) | `"CODE"` |
| `files` | file[] | 要上传的文件列表（至少1个） | 多个文件 |

#### 可选参数
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `vector_model` | string | `null` | 向量模型: `mini`, `mpnet`, `bge-base`, `bge-large`, `bge-m3`, `e5-large`。不传则不使用向量化 |
| `import_mode` | string | `"replace"` | 导入模式: `replace`(替换), `append`(追加) |
| `custom_parser` | file | `null` | 自定义解析器Python脚本文件（.py），用于解析特殊格式的文档 |

### 请求示例

#### 示例1：最简请求（不使用向量化）
```bash
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=CODE" \
  -F "files=@document1.md" \
  -F "files=@document2.md"
```

#### 示例2：使用推荐的 mpnet 模型（768维）
```bash
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=DESIGN" \
  -F "vector_model=mpnet" \
  -F "files=@document1.md" \
  -F "files=@document2.md"
```

#### 示例3：中文文档使用 bge-base 模型（768维）
```bash
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=SPEC" \
  -F "vector_model=bge-base" \
  -F "files=@chinese_doc.md"
```

#### 示例4：追求高精度使用 bge-large 模型（1024维）
```bash
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=ALG" \
  -F "vector_model=bge-large" \
  -F "files=@important_doc.md"
```

#### 示例5：多语言混合文档使用 bge-m3（1024维）
```bash
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=SKILL" \
  -F "vector_model=bge-m3" \
  -F "files=@multilang_doc.md"
```

#### 示例6：使用自定义解析器 + 向量化
```bash
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=SCT" \
  -F "vector_model=mpnet" \
  -F "custom_parser=@my_custom_parser.py" \
  -F "files=@custom_format.txt"
```

#### 示例7：追加模式导入
```bash
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=BUILD" \
  -F "vector_model=mpnet" \
  -F "import_mode=append" \
  -F "files=@new_doc.md"
```

### 成功响应 (201 Created)

#### 响应1：所有文件解析成功
```json
{
  "success": true,
  "job_id": "import_20260412_123456_abc123",
  "status": "importing",
  "message": "文档已解析完成，正在后台导入到OpenSearch",
  "details": {
    "library": "CODE",
    "use_vector": true,
    "vector_model": "mpnet",
    "vector_dims": 768,
    "import_mode": "replace",
    "total_documents": 23,
    "parse_results": {
      "total_files": 3,
      "parsed_files": 3,
      "failed_files": 0,
      "failed_file_details": []
    }
  }
}
```

**响应字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | boolean | 操作是否成功 |
| `job_id` | string | 任务ID，用于后续查询状态 |
| `status` | string | 任务状态: `importing`表示正在异步导入到OpenSearch |
| `message` | string | 操作结果描述 |
| `details` | object | 详细信息 |

**details对象字段**:
| 字段 | 类型 | 说明 |
|------|------|------|
| `library` | string | 知识库名称 |
| `use_vector` | boolean | 是否使用向量化 |
| `vector_model` | string/null | 向量模型名称 |
| `vector_dims` | integer/null | 向量维度 |
| `import_mode` | string | 导入模式 |
| `total_documents` | integer | 解析出的文档总数 |
| `parse_results` | object | 文件解析结果 |

**parse_results对象字段**:
| 字段 | 类型 | 说明 |
|------|------|------|
| `total_files` | integer | 总文件数 |
| `parsed_files` | integer | 解析成功的文件数 |
| `failed_files` | integer | 解析失败的文件数 |
| `failed_file_details` | array | 失败文件的详细信息列表（仅包含失败的文件，成功文件不返回详情以减少响应体积） |

**failed_file_details数组元素字段**（仅失败文件）:
| 字段 | 类型 | 说明 |
|------|------|------|
| `filename` | string | 文件名 |
| `error` | string | 错误信息 |
| `size_bytes` | integer | 文件大小（字节） |

#### 响应2：部分文件解析失败
```json
{
  "success": true,
  "job_id": "import_20260412_123457_def456",
  "status": "importing",
  "message": "文档已解析完成，正在后台导入到OpenSearch。1个文件解析失败。",
  "details": {
    "library": "DESIGN",
    "use_vector": false,
    "vector_model": null,
    "import_mode": "append",
    "total_documents": 15,
    "parse_results": {
      "total_files": 3,
      "parsed_files": 2,
      "failed_files": 1,
      "failed_file_details": [
        {
          "filename": "invalid.md",
          "error": "解析失败: 文件格式不正确",
          "size_bytes": 2048
        }
      ]
    }
  }
}
```

**说明**：
- 为减少响应体积，仅返回失败文件的详细信息
- 成功文件数量可通过 `parsed_files` 字段获知
- 如需所有文件的详细状态，可在解析完成后查询任务详情

### 错误响应

#### 400 Bad Request - 没有提供文件
```json
{
  "detail": "No files provided"
}
```

#### 400 Bad Request - 无效的向量模型
```json
{
  "detail": "Invalid vector_model: invalid_model. Available: mini, mpnet, bge-base, bge-large, bge-m3, e5-large"
}
```

#### 400 Bad Request - 无效的知识库名称
```json
{
  "detail": "Invalid library. Must be one of: ['CODE', 'SCT', 'BUILD', 'SYNTAX', 'SPEC', 'ALG', 'DESIGN', 'FLOW', 'SESSION', 'SKILL']"
}
```

#### 400 Bad Request - 无效的导入模式
```json
{
  "detail": "Invalid import_mode. Must be one of: ['replace', 'append']"
}
```

#### 400 Bad Request - 文件数量超限
```json
{
  "detail": "Too many files. Maximum: 10 files per request"
}
```

#### 400 Bad Request - 不支持的文件类型
```json
{
  "detail": "Unsupported file type: document.pdf. Supported: .md, .json"
}
```

#### 400 Bad Request - 所有文件解析失败
```json
{
  "detail": "All files failed to parse. Cannot proceed with import.",
  "failed_file_details": [
    {
      "filename": "bad1.md",
      "error": "Invalid markdown format"
    },
    {
      "filename": "bad2.json",
      "error": "JSON decode error"
    }
  ]
}
```

#### 404 Not Found - 自定义解析器执行失败
```json
{
  "detail": "Custom parser execution failed: module 'custom_parser' has no attribute 'parse'"
}
```

#### 413 Payload Too Large - 文件过大
```json
{
  "detail": "File too large: document.md (15MB). Maximum size: 10MB"
}
```

#### 500 Internal Server Error
```json
{
  "detail": "Internal server error occurred during file processing"
}
```

---

## 3.1 自定义解析器说明

如果你的文档格式不是标准的 `.md` 或 `.json`，可以上传自定义的Python解析脚本来处理特殊格式。

### 解析器要求

自定义解析器必须是一个Python脚本（.py文件），包含一个 `parse` 函数：

```python
def parse(filename: str) -> list:
    """
    解析文档内容
    
    Args:
        filename: 文件路径（绝对路径）
        
    Returns:
        list: 解析后的文档列表，每个文档是一个字典，包含以下字段：
            - title: 文档标题（必填）
            - content: 文档内容（必填）
            - metadata: 元数据（可选），如 {"author": "张三", "date": "2024-01-01"}
            
    Raises:
        Exception: 当解析失败时抛出异常，异常信息将被记录到任务日志中
    """
    documents = []
    
    try:
        # 读取文件内容
        with open(filename, 'r', encoding='utf-8') as f:
            file_content = f.read()
        
        # 你的解析逻辑
        # ...
        
    except Exception as e:
        raise Exception(f"Failed to parse {filename}: {str(e)}")
    
    return documents
```

### 示例：解析自定义格式

**示例1：解析简单的分隔符格式**
```python
# custom_parser.py
import os

def parse(filename: str) -> list:
    """解析用 === 分隔的文档"""
    documents = []
    
    try:
        # 读取文件内容
        with open(filename, 'r', encoding='utf-8') as f:
            file_content = f.read()
        
        sections = file_content.split('===')
        
        for i, section in enumerate(sections):
            section = section.strip()
            if not section:
                continue
                
            # 第一行作为标题
            lines = section.split('\n', 1)
            title = lines[0].strip()
            content = lines[1].strip() if len(lines) > 1 else ""
            
            documents.append({
                "title": title,
                "content": content,
                "metadata": {
                    "section_index": i + 1,
                    "source_file": os.path.basename(filename)
                }
            })
        
        if not documents:
            raise ValueError("No valid sections found in file")
            
    except FileNotFoundError:
        raise Exception(f"File not found: {filename}")
    except UnicodeDecodeError:
        raise Exception(f"Failed to decode file {filename}, please ensure it's UTF-8 encoded")
    except Exception as e:
        raise Exception(f"Failed to parse {filename}: {str(e)}")
    
    return documents
```

**示例2：解析CSV格式**
```python
# csv_parser.py
import csv
import os

def parse(filename: str) -> list:
    """解析CSV文件，每行作为一个文档"""
    documents = []
    
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            # 检查必需的列
            if reader.fieldnames is None:
                raise ValueError("CSV file is empty or has no header")
            
            for i, row in enumerate(reader, start=1):
                # 假设CSV有 title 和 content 列
                title = row.get('title', '').strip()
                content = row.get('content', '').strip()
                
                if not title:
                    title = f'Document {i}'
                
                if not content:
                    # 跳过没有内容的行
                    continue
                
                documents.append({
                    "title": title,
                    "content": content,
                    "metadata": {
                        "row_number": i,
                        "source_file": os.path.basename(filename),
                        **{k: v for k, v in row.items() if k not in ['title', 'content'] and v}
                    }
                })
        
        if not documents:
            raise ValueError("No valid documents found in CSV file")
            
    except FileNotFoundError:
        raise Exception(f"File not found: {filename}")
    except csv.Error as e:
        raise Exception(f"CSV parsing error: {str(e)}")
    except UnicodeDecodeError:
        raise Exception(f"Failed to decode file {filename}, please ensure it's UTF-8 encoded")
    except Exception as e:
        raise Exception(f"Failed to parse {filename}: {str(e)}")
    
    return documents
```

**示例3：解析XML格式**
```python
# xml_parser.py
import xml.etree.ElementTree as ET
import os

def parse(filename: str) -> list:
    """解析XML文档"""
    documents = []
    
    try:
        # 读取并解析XML文件
        tree = ET.parse(filename)
        root = tree.getroot()
        
        # 假设XML结构是 <documents><document><title>...</title><content>...</content></document></documents>
        for i, doc in enumerate(root.findall('document'), start=1):
            title_elem = doc.find('title')
            content_elem = doc.find('content')
            
            title = title_elem.text.strip() if title_elem is not None and title_elem.text else f'Document {i}'
            content = content_elem.text.strip() if content_elem is not None and content_elem.text else ''
            
            if not content:
                # 跳过没有内容的文档
                continue
            
            # 提取其他元数据
            metadata = {
                "source_file": os.path.basename(filename),
                "doc_index": i
            }
            
            # 提取其他属性作为元数据
            for child in doc:
                if child.tag not in ['title', 'content'] and child.text:
                    metadata[child.tag] = child.text.strip()
            
            documents.append({
                "title": title,
                "content": content,
                "metadata": metadata
            })
        
        if not documents:
            raise ValueError("No valid documents found in XML file")
            
    except FileNotFoundError:
        raise Exception(f"File not found: {filename}")
    except ET.ParseError as e:
        raise Exception(f"XML parsing failed: {str(e)}")
    except Exception as e:
        raise Exception(f"Failed to parse {filename}: {str(e)}")
    
    return documents
```

### 使用自定义解析器

```bash
# 上传自定义解析器和文档
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=SCT" \
  -F "vector_model=mpnet" \
  -F "custom_parser=@my_csv_parser.py" \
  -F "files=@data.csv" \
  -F "files=@more_data.csv"
```

### 注意事项

1. **函数签名**：parse 函数接收文件路径（绝对路径），需要在函数内部自己读取文件内容
2. **错误处理**：
   - 必须捕获并处理异常（文件读取失败、编码错误、格式错误等）
   - 抛出的异常信息会被记录到任务日志中，帮助诊断问题
   - 建议使用有意义的错误信息，如 `raise Exception(f"Failed to parse {filename}: {str(e)}")`
3. **返回格式**：必须返回包含 `title` 和 `content` 字段的字典列表
4. **文件编码**：建议使用 `encoding='utf-8'` 读取文件，如果文件可能是其他编码，需要添加编码检测和转换逻辑
5. **安全性**：自定义解析器在隔离的沙箱环境中执行，限制了某些危险操作
6. **标准库**：只能使用Python标准库，不支持第三方库（如pandas、numpy等）
7. **性能**：大文件可能需要较长解析时间，建议优化解析逻辑或分批处理
8. **验证**：建议验证解析结果，确保 title 和 content 不为空，跳过无效文档

---

## 4. 查询任务状态

### 基本信息
- **端点**: `GET /api/v1/import/jobs/{job_id}`
- **功能**: 查询导入任务的当前状态和进度

### 路径参数
| 参数 | 类型 | 说明 |
|------|------|------|
| `job_id` | string | 任务ID（由创建任务时返回） |

### 请求示例
```bash
curl http://localhost:9220/api/v1/import/jobs/import_20260412_123456_abc123
```

### 成功响应 (200 OK)

#### 状态1：正在解析文件
```json
{
  "job_id": "import_20260412_123456_abc123",
  "status": "parsing",
  "progress": 0.0,
  "message": "正在解析文件...",
  "parse_results": null,
  "result": null,
  "error": null,
  "created_at": "2026-04-12T12:34:56",
  "started_at": null,
  "completed_at": null
}
```

#### 状态2：正在向量化
```json
{
  "job_id": "import_20260412_123456_abc123",
  "status": "vectorizing",
  "progress": 0.35,
  "message": "正在生成向量 (35/100)...",
  "parse_results": {
    "total_files": 2,
    "parsed_files": 2,
    "failed_files": 0
  },
  "result": null,
  "error": null,
  "created_at": "2026-04-12T12:34:56",
  "started_at": "2026-04-12T12:35:01",
  "completed_at": null
}
```

#### 状态3：正在导入OpenSearch
```json
{
  "job_id": "import_20260412_123456_abc123",
  "status": "importing",
  "progress": 0.75,
  "message": "正在导入到OpenSearch (112/150)...",
  "parse_results": {
    "total_files": 2,
    "parsed_files": 2,
    "failed_files": 0
  },
  "result": null,
  "error": null,
  "created_at": "2026-04-12T12:34:56",
  "started_at": "2026-04-12T12:35:01",
  "completed_at": null
}
```

#### 状态4：任务完成
```json
{
  "job_id": "import_20260412_123456_abc123",
  "status": "completed",
  "progress": 1.0,
  "message": "导入完成",
  "parse_results": {
    "total_files": 2,
    "parsed_files": 2,
    "failed_files": 0
  },
  "result": {
    "index_name": "test_common",
    "imported_docs": 150,
    "total_docs": 150,
    "failed_docs": 0,
    "has_vector": true,
    "vector_dims": 768
  },
  "error": null,
  "created_at": "2026-04-12T12:34:56",
  "started_at": "2026-04-12T12:35:01",
  "completed_at": "2026-04-12T12:36:30"
}
```

**响应字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| `job_id` | string | 任务ID |
| `status` | string | 任务状态: `parsing`, `vectorizing`, `importing`, `completed`, `failed`, `cancelled` |
| `progress` | float | 任务进度 (0.0-1.0) |
| `message` | string | 当前状态描述 |
| `parse_results` | object/null | 文件解析结果（解析完成后有值） |
| `result` | object/null | 最终结果（仅completed时有值） |
| `error` | string/null | 错误信息（仅failed时有值） |
| `created_at` | datetime | 任务创建时间 |
| `started_at` | datetime/null | 任务开始时间 |
| `completed_at` | datetime/null | 任务完成时间 |

**result对象字段**（仅completed状态）:
| 字段 | 类型 | 说明 |
|------|------|------|
| `index_name` | string | OpenSearch索引名称 |
| `imported_docs` | integer | 成功导入的文档数 |
| `total_docs` | integer | 总文档数 |
| `failed_docs` | integer | 失败的文档数 |
| `has_vector` | boolean | 是否包含向量 |
| `vector_dims` | integer/null | 向量维度 |

#### 状态5：任务失败
```json
{
  "job_id": "import_20260412_123456_abc123",
  "status": "failed",
  "progress": 0.45,
  "message": "同步失败",
  "parse_results": {
    "total_files": 2,
    "parsed_files": 2,
    "failed_files": 0
  },
  "result": null,
  "error": "OpenSearch connection timeout: Failed to connect to OpenSearch after 3 retries",
  "created_at": "2026-04-12T12:34:56",
  "started_at": "2026-04-12T12:35:01",
  "completed_at": "2026-04-12T12:35:45"
}
```

#### 状态6：任务已取消
```json
{
  "job_id": "import_20260412_123456_abc123",
  "status": "cancelled",
  "progress": 0.25,
  "message": "任务已取消",
  "parse_results": {
    "total_files": 2,
    "parsed_files": 2,
    "failed_files": 0
  },
  "result": null,
  "error": null,
  "created_at": "2026-04-12T12:34:56",
  "started_at": "2026-04-12T12:35:01",
  "completed_at": "2026-04-12T12:35:15"
}
```

### 错误响应

#### 404 Not Found - 任务不存在
```json
{
  "detail": "Job not found: import_20260412_999999_notexist"
}
```

#### 400 Bad Request - 无效的任务ID格式
```json
{
  "detail": "Invalid job_id format"
}
```

---

## 5. 取消任务

### 基本信息
- **端点**: `POST /api/v1/import/jobs/{job_id}/cancel`
- **功能**: 取消正在执行的导入任务

### 路径参数
| 参数 | 类型 | 说明 |
|------|------|------|
| `job_id` | string | 任务ID |

### 请求示例
```bash
curl -X POST http://localhost:9220/api/v1/import/jobs/import_20260412_123456_abc123/cancel
```

### 成功响应 (200 OK)
```json
{
  "success": true,
  "job_id": "import_20260412_123456_abc123",
  "message": "任务取消请求已提交"
}
```

**响应字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | boolean | 操作是否成功 |
| `job_id` | string | 任务ID |
| `message` | string | 操作结果描述 |

### 错误响应

#### 404 Not Found - 任务不存在
```json
{
  "detail": "Job not found: import_20260412_999999_notexist"
}
```

#### 400 Bad Request - 任务已完成无法取消
```json
{
  "detail": "Cannot cancel job in status: completed"
}
```

#### 400 Bad Request - 任务已失败无法取消
```json
{
  "detail": "Cannot cancel job in status: failed"
}
```

#### 400 Bad Request - 任务已取消
```json
{
  "detail": "Job is already cancelled"
}
```

#### 500 Internal Server Error - 取消失败
```json
{
  "detail": "Failed to cancel Celery task: Task revoke timeout"
}
```

---

## 6. 获取任务列表

### 基本信息
- **端点**: `GET /api/v1/import/jobs`
- **功能**: 获取导入任务列表，支持过滤和分页

### 查询参数
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `status` | string | - | 过滤状态: `parsing`, `vectorizing`, `saving`, `syncing`, `completed`, `failed`, `cancelled` |
| `library` | string | - | 过滤知识库名称 |
| `limit` | integer | 20 | 返回数量限制 (最大100) |
| `offset` | integer | 0 | 分页偏移 |

### 请求示例

#### 示例1：获取所有任务
```bash
curl http://localhost:9220/api/v1/import/jobs
```

#### 示例2：获取正在运行的任务
```bash
curl "http://localhost:9220/api/v1/import/jobs?status=vectorizing"
```

#### 示例3：获取特定知识库的任务
```bash
curl "http://localhost:9220/api/v1/import/jobs?library=CODE"
```

#### 示例4：分页获取
```bash
curl "http://localhost:9220/api/v1/import/jobs?limit=10&offset=20"
```

### 成功响应 (200 OK)
```json
{
  "total": 15,
  "limit": 20,
  "offset": 0,
  "items": [
    {
      "job_id": "import_20260412_123456_abc123",
      "status": "completed",
      "progress": 1.0,
      "message": "导入完成",
      "parse_results": {
        "total_files": 2,
        "parsed_files": 2,
        "failed_files": 0
      },
      "result": {
        "index_name": "test_common",
        "imported_docs": 150,
        "total_docs": 150,
        "failed_docs": 0,
        "has_vector": true,
        "vector_dims": 768
      },
      "error": null,
      "created_at": "2026-04-12T12:34:56",
      "started_at": "2026-04-12T12:35:01",
      "completed_at": "2026-04-12T12:36:30"
    },
    {
      "job_id": "import_20260412_123500_def456",
      "status": "vectorizing",
      "progress": 0.45,
      "message": "正在生成向量 (45/100)...",
      "parse_results": {
        "total_files": 3,
        "parsed_files": 3,
        "failed_files": 0
      },
      "result": null,
      "error": null,
      "created_at": "2026-04-12T12:35:00",
      "started_at": "2026-04-12T12:35:05",
      "completed_at": null
    },
    {
      "job_id": "import_20260412_123400_ghi789",
      "status": "failed",
      "progress": 0.30,
      "message": "导入失败",
      "parse_results": {
        "total_files": 1,
        "parsed_files": 1,
        "failed_files": 0
      },
      "result": null,
      "error": "OpenSearch connection refused",
      "created_at": "2026-04-12T12:34:00",
      "started_at": "2026-04-12T12:34:05",
      "completed_at": "2026-04-12T12:34:20"
    }
  ]
}
```

**响应字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| `total` | integer | 总任务数 |
| `limit` | integer | 当前页大小 |
| `offset` | integer | 当前页偏移 |
| `items` | array | 任务列表（格式同"查询任务状态"） |

### 错误响应

#### 400 Bad Request - 无效的状态值
```json
{
  "detail": "Invalid status: invalid_status. Must be one of: parsing, vectorizing, saving, syncing, completed, failed, cancelled"
}
```

#### 400 Bad Request - 无效的分页参数
```json
{
  "detail": "limit must be between 1 and 100"
}
```

---

## 7. 任务状态说明

| 状态 | 说明 | 可取消 | 进度范围 |
|------|------|--------|---------|
| `parsing` | 正在解析文件 | ✅ | 0.0-0.3 |
| `vectorizing` | 正在生成向量 | ✅ | 0.3-0.6 |
| `importing` | 正在导入到OpenSearch | ✅ | 0.6-0.99 |
| `completed` | 任务完成 | ❌ | 1.0 |
| `failed` | 任务失败 | ❌ | - |
| `cancelled` | 任务已取消 | ❌ | - |

---

## 8. 使用示例

### Python

#### 完整流程：上传文件 → 轮询状态 → 获取结果
```python
import requests
import time

BASE_URL = "http://localhost:9220/api/v1/import"

# 1. 上传文件并创建导入任务
def create_import_job(library, files, vector_model=None):
    url = f"{BASE_URL}/jobs"
    
    # 准备表单数据
    data = {
        "library": library
    }
    if vector_model:
        data["vector_model"] = vector_model
    
    # 准备文件
    files_data = [
        ("files", (file_path.split("/")[-1], open(file_path, "rb")))
        for file_path in files
    ]
    
    response = requests.post(url, data=data, files=files_data)
    
    # 关闭文件
    for _, (_, f) in files_data:
        f.close()
    
    if response.status_code == 201:
        return response.json()
    else:
        raise Exception(f"Failed to create job: {response.text}")

# 2. 查询任务状态
def get_job_status(job_id):
    url = f"{BASE_URL}/jobs/{job_id}"
    response = requests.get(url)
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to get job status: {response.text}")

# 3. 轮询直到任务完成
def wait_for_job(job_id, interval=2):
    print(f"等待任务完成: {job_id}")
    
    while True:
        status = get_job_status(job_id)
        current_status = status["status"]
        progress = status["progress"]
        message = status["message"]
        
        print(f"[{current_status}] 进度: {progress*100:.1f}% - {message}")
        
        if current_status == "completed":
            print("任务完成!")
            return status
        elif current_status == "failed":
            error = status.get("error", "Unknown error")
            raise Exception(f"任务失败: {error}")
        elif current_status == "cancelled":
            raise Exception("任务已取消")
        
        time.sleep(interval)

# 使用示例
if __name__ == "__main__":
    # 上传文件（使用向量化）
    result = create_import_job(
        library="CODE",
        files=["doc1.md", "doc2.md"],
        vector_model="mpnet"
    )
    
    print(f"任务已创建: {result['job_id']}")
    print(f"解析结果: {result['details']['parse_results']}")
    print(f"总文档数: {result['details']['total_documents']}")
    
    # 轮询任务状态
    final_status = wait_for_job(result['job_id'])
    
    # 输出最终结果
    print("\n=== 最终结果 ===")
    print(f"索引名称: {final_status['result']['index_name']}")
    print(f"导入文档数: {final_status['result']['imported_docs']}")
    print(f"向量维度: {final_status['result']['vector_dims']}")
```

#### 示例：不使用向量化
```python
# 快速导入，不使用向量化
result = create_import_job(
    library="SKILL",
    files=["doc1.md", "doc2.md"]
)
```

#### 示例：获取任务列表
```python
def get_job_list(status=None, library=None, limit=20, offset=0):
    url = f"{BASE_URL}/jobs"
    params = {"limit": limit, "offset": offset}
    
    if status:
        params["status"] = status
    if library:
        params["library"] = library
    
    response = requests.get(url, params=params)
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to get job list: {response.text}")

# 获取所有正在运行的任务
running_jobs = get_job_list(status="vectorizing")
print(f"正在运行的任务数: {running_jobs['total']}")

for job in running_jobs['items']:
    print(f"- {job['job_id']}: {job['message']} ({job['progress']*100:.0f}%)")
```

#### 示例：取消任务
```python
def cancel_job(job_id):
    url = f"{BASE_URL}/jobs/{job_id}/cancel"
    response = requests.post(url)
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to cancel job: {response.text}")

# 取消任务
result = cancel_job("import_20260412_123456_abc123")
print(result['message'])
```

### JavaScript

#### 完整流程：上传文件 → 轮询状态 → 获取结果
```javascript
const BASE_URL = "http://localhost:9220/api/v1/import";

// 1. 上传文件并创建导入任务
async function createImportJob(library, files, vectorModel = null) {
  const url = `${BASE_URL}/jobs`;
  
  const formData = new FormData();
  formData.append("library", library);
  
  if (vectorModel) {
    formData.append("vector_model", vectorModel);
  }
  
  // 添加文件
  files.forEach(file => {
    formData.append("files", file);
  });
  
  const response = await fetch(url, {
    method: "POST",
    body: formData
  });
  
  if (!response.ok) {
    throw new Error(`Failed to create job: ${await response.text()}`);
  }
  
  return await response.json();
}

// 2. 查询任务状态
async function getJobStatus(jobId) {
  const url = `${BASE_URL}/jobs/${jobId}`;
  const response = await fetch(url);
  
  if (!response.ok) {
    throw new Error(`Failed to get job status: ${await response.text()}`);
  }
  
  return await response.json();
}

// 3. 轮询直到任务完成
async function waitForJob(jobId, interval = 2000) {
  console.log(`等待任务完成: ${jobId}`);
  
  while (true) {
    const status = await getJobStatus(jobId);
    const currentStatus = status.status;
    const progress = status.progress;
    const message = status.message;
    
    console.log(`[${currentStatus}] 进度: ${(progress * 100).toFixed(1)}% - ${message}`);
    
    if (currentStatus === "completed") {
      console.log("任务完成!");
      return status;
    } else if (currentStatus === "failed") {
      const error = status.error || "Unknown error";
      throw new Error(`任务失败: ${error}`);
    } else if (currentStatus === "cancelled") {
      throw new Error("任务已取消");
    }
    
    await new Promise(resolve => setTimeout(resolve, interval));
  }
}

// 使用示例（浏览器环境）
async function handleFileUpload(fileInputElement) {
  try {
    const files = Array.from(fileInputElement.files);
    
    // 创建任务
    const result = await createImportJob("common", files, "mpnet");
    
    console.log(`任务已创建: ${result.job_id}`);
    console.log(`解析结果:`, result.details.parse_results);
    console.log(`总文档数: ${result.details.total_documents}`);
    
    // 轮询任务状态
    const finalStatus = await waitForJob(result.job_id);
    
    // 输出最终结果
    console.log("\n=== 最终结果 ===");
    console.log(`索引名称: ${finalStatus.result.index_name}`);
    console.log(`导入文档数: ${finalStatus.result.imported_docs}`);
    console.log(`向量维度: ${finalStatus.result.vector_dims}`);
    
  } catch (error) {
    console.error("导入失败:", error.message);
  }
}
```

#### 示例：获取任务列表
```javascript
async function getJobList(options = {}) {
  const { status, library, limit = 20, offset = 0 } = options;
  
  const params = new URLSearchParams({ limit, offset });
  if (status) params.append("status", status);
  if (library) params.append("library", library);
  
  const url = `${BASE_URL}/jobs?${params}`;
  const response = await fetch(url);
  
  if (!response.ok) {
    throw new Error(`Failed to get job list: ${await response.text()}`);
  }
  
  return await response.json();
}

// 获取所有正在运行的任务
const runningJobs = await getJobList({ status: "vectorizing" });
console.log(`正在运行的任务数: ${runningJobs.total}`);

runningJobs.items.forEach(job => {
  console.log(`- ${job.job_id}: ${job.message} (${(job.progress * 100).toFixed(0)}%)`);
});
```

#### 示例：取消任务
```javascript
async function cancelJob(jobId) {
  const url = `${BASE_URL}/jobs/${jobId}/cancel`;
  const response = await fetch(url, { method: "POST" });
  
  if (!response.ok) {
    throw new Error(`Failed to cancel job: ${await response.text()}`);
  }
  
  return await response.json();
}

// 取消任务
const result = await cancelJob("import_20260412_123456_abc123");
console.log(result.message);
```

---

## 9. 最佳实践

### 9.1 向量模型选择

1. **测试阶段**：使用 `mini` 或不使用向量化，快速验证功能
2. **生产环境**：
   - 通用场景：`mpnet`（推荐）
   - 中文为主：`bge-base` 或 `bge-large`
   - 多语言混合：`bge-m3` 或 `e5-large`
3. **资源受限**：不使用向量化，仅用关键词检索

### 9.2 错误处理

1. **部分文件失败**：检查 `parse_results.failed_files` 数量和 `parse_results.failed_file_details` 详细信息，修复后重新上传
2. **导入失败**：查看错误信息，检查OpenSearch服务状态，修复后重新提交任务
3. **任务超时**：设置合理的轮询间隔（建议2-5秒）

### 9.3 性能优化

1. **批量上传**：一次上传多个文件（最多10个）比分多次上传效率高
2. **选择合适的向量模型**：根据精度和速度需求平衡选择
3. **避免频繁轮询**：建议2-5秒轮询一次，避免给服务器造成压力

### 9.4 监控和调试

1. **查询任务列表**：定期检查失败任务，分析失败原因
2. **关注 parse_results**：了解哪些文件解析成功，哪些失败
3. **保存 job_id**：便于后续查询和问题排查

---

## 10. 注意事项

1. **异步处理**：
   - 文件上传和解析是同步的，立即返回结果
   - 向量化和OpenSearch导入是异步的，通过Celery后台执行
   - 需要轮询查询任务状态来获取最终结果

2. **文件限制**：
   - 单文件最大：10MB
   - 单次最多：10个文件
   - 支持格式：.md, .json（可通过自定义解析器扩展）

3. **向量化选择**：
   - 不是所有场景都需要向量化
   - 向量化会增加处理时间和存储空间
   - 根据实际需求选择是否使用向量化

4. **任务取消**：
   - 只能取消正在执行的任务（parsing/vectorizing/importing）
   - 已完成/已失败/已取消的任务无法再取消
   - 取消操作是异步的，需要一定时间生效

5. **响应优化**：
   - 批量上传时，响应中仅返回失败文件的详细信息（`failed_file_details`）
   - 成功文件数量通过 `parsed_files` 字段获知，不返回详情以减少响应体积
   - 特别是大批量导入（如100+文件）时，这可以显著减少响应数据量

6. **状态码说明**：
   - 201：创建成功
   - 200：查询成功
   - 400：请求参数错误
   - 404：资源不存在
   - 413：文件过大
   - 500：服务器内部错误

---

## 11. 常见问题

### Q1: 向量化需要多长时间？
**A**: 取决于文档数量和向量模型：
- mini: ~100文档/秒
- mpnet: ~50文档/秒
- bge-large: ~20文档/秒

### Q2: 可以不使用向量化吗？
**A**: 可以。不传 `vector_model` 参数即可。适用于：
- 简单关键词检索场景
- 资源受限环境
- 快速原型开发

### Q3: 导入失败怎么办？
**A**: 检查任务状态中的错误信息，常见原因：
- OpenSearch服务不可用
- 向量模型加载失败
- 文件格式不正确
- 可以修复问题后重新提交导入任务

### Q4: 如何选择导入模式？
**A**:
- **replace**: 清空目标知识库后导入（适用于全量更新）
- **append**: 追加到现有知识库（适用于增量更新）

### Q5: 支持哪些文件格式？
**A**: 默认支持 .md 和 .json。通过自定义解析器可支持任意格式。

### Q6: 任务会自动清理吗？
**A**: 任务记录会永久保存，但临时文件会在任务完成后自动清理。

### Q7: 可以同时运行多个导入任务吗？
**A**: 可以。Celery支持并发执行多个任务，受worker数量限制。

### Q8: 如何知道任务完成了？
**A**: 轮询查询任务状态，当 `status` 为 `completed` 时表示完成。

### Q9: 自定义解析器可以使用哪些Python库？
**A**: 仅支持Python标准库（如 `json`, `csv`, `xml.etree.ElementTree`, `re` 等），不支持第三方库（如 `pandas`, `numpy`, `beautifulsoup4` 等）。解析器在隔离的沙箱环境中执行，某些危险操作也会被限制。

---

## 12. 相关文档

- [搜索API文档](API_REFERENCE.md) - 检索功能API参考
- [Import流程详细设计](../08_Import流程_no_session_skill_详细设计.md) - 完整技术设计文档
- [架构总览](../01_架构总览.md) - 系统整体架构说明

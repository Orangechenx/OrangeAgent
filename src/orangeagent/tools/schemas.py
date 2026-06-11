TRACE_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "trace_search",
        "description": (
            "Case-insensitive exact substring search over a session trace file. "
            "Use this to locate functions, registers, addresses, constants, and hexdump text "
            "in very large traces. Every call must include exactly one of from_line or before_line, "
            "plus limit. before_line searches backward and returns nearest earlier matches first. "
            "For hex data starting with 0x, the harness automatically tries byte-reversed endian "
            "order as fallback. limit must be no greater than 100."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Exact substring to find. Case-insensitive for ASCII.",
                },
                "file": {
                    "type": "string",
                    "enum": ["code", "rw", "bl"],
                    "description": (
                        "Which trace file to search. "
                        "'code' = instruction execution log, "
                        "'rw' = memory read/write hexdump log, "
                        "'bl' = external function call log."
                    ),
                },
                "from_line": {
                    "type": "integer",
                    "description": "1-based line to start searching from.",
                    "minimum": 1,
                },
                "before_line": {
                    "type": "integer",
                    "description": "Search backward from this 1-based line. Mutually exclusive with from_line.",
                    "minimum": 1,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max matching lines to return. Must be <= 100.",
                    "minimum": 1,
                    "maximum": 100,
                },
            },
            "required": ["query", "limit"],
        },
    },
}

TRACE_CONTEXT_TOOL = {
    "type": "function",
    "function": {
        "name": "trace_context",
        "description": (
            "Return neighboring trace lines around a 1-based file line. "
            "Use after trace_search to inspect instruction context. "
            "Each line-count argument must be no greater than 100."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "line": {
                    "type": "integer",
                    "description": "1-based target file line.",
                },
                "file": {
                    "type": "string",
                    "enum": ["code", "rw", "bl"],
                    "description": "Which trace file to read context from.",
                },
                "before": {
                    "type": "integer",
                    "description": "Number of lines before the target. Must be <= 100.",
                    "minimum": 0,
                    "maximum": 100,
                },
                "after": {
                    "type": "integer",
                    "description": "Number of lines after the target. Must be <= 100.",
                    "minimum": 0,
                    "maximum": 100,
                },
            },
            "required": ["line", "before", "after"],
        },
    },
}

TRACE_CROSS_REF_TOOL = {
    "type": "function",
    "function": {
        "name": "trace_cross_ref",
        "description": (
            "Look up all trace records correlated to a given hex sequence ID across all trace files. "
            "Returns the code.log instruction line, any rw.log memory records, and any bl.log "
            "external function call records for that sequence. The sequence ID is the hex number "
            "at the start of lines in each trace file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "seq_id": {
                    "type": "string",
                    "description": "Hex sequence ID (without 0x prefix), e.g. '942' or 'a8dc9f'.",
                },
            },
            "required": ["seq_id"],
        },
    },
}

TRACE_TOOLS = [TRACE_SEARCH_TOOL, TRACE_CONTEXT_TOOL, TRACE_CROSS_REF_TOOL]


# --- JADX static analysis tools ---

JADX_SEARCH_CLASSES_TOOL = {
    "type": "function",
    "function": {
        "name": "jadx_search_classes_by_keyword",
        "description": (
            "Search decompiled APK code for classes containing a keyword. "
            "Can search in class names, method names, fields, code bodies, or comments. "
            "Use this as your primary discovery tool to find relevant code."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "search_term": {
                    "type": "string",
                    "description": "The keyword or string to search for.",
                },
                "package": {
                    "type": "string",
                    "description": "Optional package name to limit search scope.",
                },
                "search_in": {
                    "type": "string",
                    "enum": ["class", "method", "field", "code", "comment"],
                    "description": "Search scope: class names, method names, fields, code bodies, or comments.",
                },
                "offset": {"type": "integer", "description": "Pagination offset.", "minimum": 0},
                "count": {"type": "integer", "description": "Max results (1-50).", "minimum": 1, "maximum": 50},
            },
            "required": ["search_term"],
        },
    },
}

JADX_GET_CLASS_SOURCE_TOOL = {
    "type": "function",
    "function": {
        "name": "jadx_get_class_source",
        "description": "Fetch the decompiled Java source code of a specific class by its full qualified name.",
        "parameters": {
            "type": "object",
            "properties": {
                "class_name": {
                    "type": "string",
                    "description": "Full qualified class name, e.g. 'com.example.app.MainActivity'.",
                },
            },
            "required": ["class_name"],
        },
    },
}

JADX_GET_METHOD_BY_NAME_TOOL = {
    "type": "function",
    "function": {
        "name": "jadx_get_method_by_name",
        "description": "Fetch the source code of a specific method from a class.",
        "parameters": {
            "type": "object",
            "properties": {
                "class_name": {
                    "type": "string",
                    "description": "Full qualified class name.",
                },
                "method_name": {
                    "type": "string",
                    "description": "Method name to fetch (without parameter types).",
                },
            },
            "required": ["class_name", "method_name"],
        },
    },
}

JADX_GET_XREFS_TO_CLASS_TOOL = {
    "type": "function",
    "function": {
        "name": "jadx_get_xrefs_to_class",
        "description": "Find all references to a class throughout the APK codebase.",
        "parameters": {
            "type": "object",
            "properties": {
                "class_name": {
                    "type": "string",
                    "description": "Full qualified class name to find references to.",
                },
                "offset": {"type": "integer", "description": "Pagination offset.", "minimum": 0},
                "count": {"type": "integer", "description": "Max results (1-50).", "minimum": 1, "maximum": 50},
            },
            "required": ["class_name"],
        },
    },
}

JADX_GET_XREFS_TO_METHOD_TOOL = {
    "type": "function",
    "function": {
        "name": "jadx_get_xrefs_to_method",
        "description": "Find all call sites of a specific method throughout the APK codebase.",
        "parameters": {
            "type": "object",
            "properties": {
                "class_name": {
                    "type": "string",
                    "description": "Full qualified class name containing the method.",
                },
                "method_name": {
                    "type": "string",
                    "description": "Method name to find call sites for.",
                },
                "offset": {"type": "integer", "description": "Pagination offset.", "minimum": 0},
                "count": {"type": "integer", "description": "Max results (1-50).", "minimum": 1, "maximum": 50},
            },
            "required": ["class_name", "method_name"],
        },
    },
}

JADX_GET_METHODS_OF_CLASS_TOOL = {
    "type": "function",
    "function": {
        "name": "jadx_get_methods_of_class",
        "description": "List all method names in a class.",
        "parameters": {
            "type": "object",
            "properties": {
                "class_name": {
                    "type": "string",
                    "description": "Full qualified class name.",
                },
            },
            "required": ["class_name"],
        },
    },
}

JADX_GET_FIELDS_OF_CLASS_TOOL = {
    "type": "function",
    "function": {
        "name": "jadx_get_fields_of_class",
        "description": "List all field names in a class.",
        "parameters": {
            "type": "object",
            "properties": {
                "class_name": {
                    "type": "string",
                    "description": "Full qualified class name.",
                },
            },
            "required": ["class_name"],
        },
    },
}

JADX_GET_ANDROID_MANIFEST_TOOL = {
    "type": "function",
    "function": {
        "name": "jadx_get_android_manifest",
        "description": "Retrieve and return the AndroidManifest.xml content.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}

JADX_GET_SMALI_OF_CLASS_TOOL = {
    "type": "function",
    "function": {
        "name": "jadx_get_smali_of_class",
        "description": "Fetch the smali bytecode representation of a class (useful for deep analysis).",
        "parameters": {
            "type": "object",
            "properties": {
                "class_name": {
                    "type": "string",
                    "description": "Full qualified class name.",
                },
            },
            "required": ["class_name"],
        },
    },
}

JADX_GET_STRINGS_TOOL = {
    "type": "function",
    "function": {
        "name": "jadx_get_strings",
        "description": "Retrieve contents of strings.xml resource files.",
        "parameters": {
            "type": "object",
            "properties": {
                "offset": {"type": "integer", "description": "Pagination offset.", "minimum": 0},
                "count": {"type": "integer", "description": "Max results (0 = all).", "minimum": 0},
            },
        },
    },
}

JADX_GET_MAIN_ACTIVITY_CLASS_TOOL = {
    "type": "function",
    "function": {
        "name": "jadx_get_main_activity_class",
        "description": "Fetch the main activity class from AndroidManifest.xml.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}

JADX_TOOLS = [
    JADX_SEARCH_CLASSES_TOOL,
    JADX_GET_CLASS_SOURCE_TOOL,
    JADX_GET_METHOD_BY_NAME_TOOL,
    JADX_GET_XREFS_TO_CLASS_TOOL,
    JADX_GET_XREFS_TO_METHOD_TOOL,
    JADX_GET_METHODS_OF_CLASS_TOOL,
    JADX_GET_FIELDS_OF_CLASS_TOOL,
    JADX_GET_ANDROID_MANIFEST_TOOL,
    JADX_GET_SMALI_OF_CLASS_TOOL,
    JADX_GET_STRINGS_TOOL,
    JADX_GET_MAIN_ACTIVITY_CLASS_TOOL,
]


# --- Frida dynamic analysis tools ---

FRIDA_LIST_DEVICES_TOOL = {
    "type": "function",
    "function": {
        "name": "frida_list_devices",
        "description": "列出所有可用的 Frida 设备（USB/本地/远程）。在开始任何动态分析前调用。",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}

FRIDA_LIST_PROCESSES_TOOL = {
    "type": "function",
    "function": {
        "name": "frida_list_processes",
        "description": "列出设备上正在运行的进程。",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "string",
                    "description": "设备 ID（可选，默认使用 USB 设备）",
                },
            },
        },
    },
}

FRIDA_ENUMERATE_CLASSES_TOOL = {
    "type": "function",
    "function": {
        "name": "frida_enumerate_classes",
        "description": "枚举目标进程中已加载的所有 Java 类。用于定位目标类。",
        "parameters": {
            "type": "object",
            "properties": {
                "pid": {
                    "type": "string",
                    "description": "进程 PID 或包名，如 'com.example.app'",
                },
                "device_id": {
                    "type": "string",
                    "description": "设备 ID（可选）",
                },
            },
            "required": ["pid"],
        },
    },
}

FRIDA_HOOK_METHOD_TOOL = {
    "type": "function",
    "function": {
        "name": "frida_hook_method",
        "description": "Hook 目标类的方法，捕获调用参数和调用栈。注意：此工具会阻塞等待调用触发。",
        "parameters": {
            "type": "object",
            "properties": {
                "pid": {
                    "type": "string",
                    "description": "进程 PID 或包名",
                },
                "class": {
                    "type": "string",
                    "description": "完整类名，如 'com.example.app.SignUtil'",
                },
                "method": {
                    "type": "string",
                    "description": "方法名",
                },
                "device_id": {
                    "type": "string",
                    "description": "设备 ID（可选）",
                },
            },
            "required": ["pid", "class", "method"],
        },
    },
}

FRIDA_GENERATE_HOOK_SCRIPT_TOOL = {
    "type": "function",
    "function": {
        "name": "frida_generate_hook_script",
        "description": "生成标准 Frida Hook 脚本内容。无需设备连接。",
        "parameters": {
            "type": "object",
            "properties": {
                "class": {
                    "type": "string",
                    "description": "目标类名",
                },
                "method": {
                    "type": "string",
                    "description": "目标方法名",
                },
                "overload": {
                    "type": "string",
                    "description": "方法重载签名（可选）",
                },
            },
            "required": ["class", "method"],
        },
    },
}

FRIDA_GENERATE_ENUMERATE_SCRIPT_TOOL = {
    "type": "function",
    "function": {
        "name": "frida_generate_enumerate_script",
        "description": "生成枚举已加载 Java 类的 Frida 脚本。无需设备连接。",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}

FRIDA_TOOLS = [
    FRIDA_LIST_DEVICES_TOOL,
    FRIDA_LIST_PROCESSES_TOOL,
    FRIDA_ENUMERATE_CLASSES_TOOL,
    FRIDA_HOOK_METHOD_TOOL,
    FRIDA_GENERATE_HOOK_SCRIPT_TOOL,
    FRIDA_GENERATE_ENUMERATE_SCRIPT_TOOL,
]


# --- Network analysis tools ---

NETWORK_MAKE_REQUEST_TOOL = {
    "type": "function",
    "function": {
        "name": "network_make_request",
        "description": "发送 HTTP/HTTPS 请求并返回响应内容、状态码和头部。用于验证接口、分析请求和响应。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "完整的请求 URL"},
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "DELETE"],
                    "description": "HTTP 方法，默认 GET",
                },
                "headers": {
                    "type": "string",
                    "description": "JSON 格式的请求头，如 '{\"User-Agent\": \"...\"}'",
                },
                "body": {
                    "type": "string",
                    "description": "请求体（JSON 字符串或表单数据）",
                },
            },
            "required": ["url"],
        },
    },
}

NETWORK_ANALYZE_PARAMS_TOOL = {
    "type": "function",
    "function": {
        "name": "network_analyze_params",
        "description": "分析请求 URL 中的查询参数和请求体中的字段，标识可能的签名参数和动态字段。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "请求 URL"},
                "body": {"type": "string", "description": "请求体内容"},
            },
            "required": [],
        },
    },
}

NETWORK_TOOLS = [
    NETWORK_MAKE_REQUEST_TOOL,
    NETWORK_ANALYZE_PARAMS_TOOL,
]


# --- APKTool tools ---

APKTOOL_DECODE_TOOL = {
    "type": "function",
    "function": {
        "name": "apktool_decode",
        "description": "使用 apktool 解包 APK 文件为 Smali 代码和资源文件。",
        "parameters": {
            "type": "object",
            "properties": {
                "apk_path": {"type": "string", "description": "APK 文件路径"},
            },
            "required": ["apk_path"],
        },
    },
}

APKTOOL_BUILD_TOOL = {
    "type": "function",
    "function": {
        "name": "apktool_build",
        "description": "从解码后的目录重新构建 APK。",
        "parameters": {
            "type": "object",
            "properties": {
                "dir": {"type": "string", "description": "解码后的目录路径"},
                "output": {"type": "string", "description": "输出 APK 路径"},
            },
            "required": ["dir"],
        },
    },
}

APKTOOL_MANIFEST_TOOL = {
    "type": "function",
    "function": {
        "name": "apktool_manifest",
        "description": "读取解码后 APK 的 AndroidManifest.xml 内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "decoded_dir": {"type": "string", "description": "解码后的目录路径"},
            },
            "required": ["decoded_dir"],
        },
    },
}

APKTOOL_SEARCH_STRING_TOOL = {
    "type": "function",
    "function": {
        "name": "apktool_search_string",
        "description": "在解码后的 Smali 文件中搜索关键词。",
        "parameters": {
            "type": "object",
            "properties": {
                "decoded_dir": {"type": "string", "description": "解码后的目录路径"},
                "keyword": {"type": "string", "description": "搜索关键词"},
            },
            "required": ["decoded_dir", "keyword"],
        },
    },
}

APKTOOL_TOOLS = [
    APKTOOL_DECODE_TOOL,
    APKTOOL_BUILD_TOOL,
    APKTOOL_MANIFEST_TOOL,
    APKTOOL_SEARCH_STRING_TOOL,
]


# --- JS Reverse tools ---

JS_FORMAT_TOOL = {
    "type": "function",
    "function": {
        "name": "js_format",
        "description": "格式化/美化 JavaScript 代码。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "待格式化的 JS 代码"},
            },
            "required": ["code"],
        },
    },
}

JS_EXTRACT_STRINGS_TOOL = {
    "type": "function",
    "function": {
        "name": "js_extract_strings",
        "description": "从 JS 代码中提取所有字符串字面量。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "JS 代码"},
            },
            "required": ["code"],
        },
    },
}

JS_DEOBFUSCATE_TOOL = {
    "type": "function",
    "function": {
        "name": "js_deobfuscate",
        "description": "反混淆 JS 代码：解码 \\x 转义、恢复可读性。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "混淆的 JS 代码"},
            },
            "required": ["code"],
        },
    },
}

JS_REVERSE_TOOLS = [
    JS_FORMAT_TOOL,
    JS_EXTRACT_STRINGS_TOOL,
    JS_DEOBFUSCATE_TOOL,
]


# --- IDA Pro tools ---

IDA_LIST_FUNCTIONS_TOOL = {
    "type": "function",
    "function": {
        "name": "ida_list_functions",
        "description": "列出 IDA 中分析出的函数列表。",
        "parameters": {
            "type": "object",
            "properties": {
                "binary": {"type": "string", "description": "二进制文件路径"},
            },
        },
    },
}

IDA_ANALYZE_FUNCTION_TOOL = {
    "type": "function",
    "function": {
        "name": "ida_analyze_function",
        "description": "分析指定函数的汇编代码和伪代码。",
        "parameters": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "函数地址或名称"},
            },
            "required": ["address"],
        },
    },
}

IDA_DECOMPILE_TOOL = {
    "type": "function",
    "function": {
        "name": "ida_decompile",
        "description": "反编译指定地址的代码为伪代码。",
        "parameters": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "地址"},
            },
            "required": ["address"],
        },
    },
}

IDA_SEARCH_XREFS_TOOL = {
    "type": "function",
    "function": {
        "name": "ida_search_xrefs",
        "description": "搜索指定地址的交叉引用。",
        "parameters": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "地址"},
            },
            "required": ["address"],
        },
    },
}

IDA_GET_STRINGS_TOOL = {
    "type": "function",
    "function": {
        "name": "ida_get_strings",
        "description": "获取二进制文件中的所有字符串。",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}

IDA_TOOLS = [
    IDA_LIST_FUNCTIONS_TOOL,
    IDA_ANALYZE_FUNCTION_TOOL,
    IDA_DECOMPILE_TOOL,
    IDA_SEARCH_XREFS_TOOL,
    IDA_GET_STRINGS_TOOL,
]


# --- Unidbg tools ---

UNIDBG_RUN_TOOL = {
    "type": "function",
    "function": {
        "name": "unidbg_run",
        "description": "使用 unidbg 模拟执行 Native 方法。需要 Java 环境和 unidbg 项目。",
        "parameters": {
            "type": "object",
            "properties": {
                "class": {"type": "string", "description": "Java 类路径，如 com.example.SignUtil"},
                "so": {"type": "string", "description": "SO 文件路径"},
                "method": {"type": "string", "description": "要调用的方法名（可选）"},
                "args": {"type": "string", "description": "方法参数（可选）"},
            },
            "required": ["class"],
        },
    },
}

UNIDBG_GENERATE_TEMPLATE_TOOL = {
    "type": "function",
    "function": {
        "name": "unidbg_generate_template",
        "description": "生成 unidbg 调用的 Java 模板代码。用于快速搭建 unidbg 环境。",
        "parameters": {
            "type": "object",
            "properties": {
                "class": {"type": "string", "description": "目标类名"},
                "method": {"type": "string", "description": "目标方法名"},
                "so": {"type": "string", "description": "SO 名称"},
            },
            "required": [],
        },
    },
}

UNIDBG_TOOLS = [
    UNIDBG_RUN_TOOL,
    UNIDBG_GENERATE_TEMPLATE_TOOL,
]
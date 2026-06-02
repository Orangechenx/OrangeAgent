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
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
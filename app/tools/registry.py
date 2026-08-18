from __future__ import annotations

import ast
import json
import operator
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

# 支持的算术运算符（安全求值，绝不使用 eval）
_OPS: dict[type, Callable[..., Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def get_current_time() -> dict[str, Any]:
    return {"now": datetime.now(UTC).isoformat(), "timezone": "UTC"}


def calculate(expression: str) -> dict[str, Any]:
    result = _safe_eval(expression)
    return {"expression": expression, "result": result}


def get_weather(city: str) -> dict[str, Any]:
    # 演示用固定数据；生产应接真实天气 API
    return {"city": city, "temp": 25, "condition": "晴", "source": "mock"}


def _safe_eval(expression: str) -> float | int:
    if not re.fullmatch(r"[0-9\s+\-*/().]+", expression or ""):
        raise ValueError(f"非法表达式: {expression}")
    try:
        return _eval_node(ast.parse(expression, mode="eval").body)
    except (ValueError, SyntaxError, ZeroDivisionError) as exc:
        raise ValueError(f"无法计算表达式: {expression}") from exc


def _eval_node(node: ast.AST) -> float | int:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError("不支持的表达式")


TOOLS: dict[str, Any] = {
    "get_current_time": get_current_time,
    "calculate": calculate,
    "get_weather": get_weather,
}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取当前 UTC 时间。当用户询问现在几点/当前时间时使用。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "计算一个算术表达式。当用户要求做数学计算时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "只含数字与 +-*/() 的算术表达式，如 2+3*4"}
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询指定城市的天气。当用户询问某地天气时使用。",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string", "description": "城市名"}},
                "required": ["city"],
            },
        },
    },
]


def execute_tool(name: str, arguments: str) -> str:
    """执行工具并返回 JSON 字符串结果（含错误信息，便于模型自行纠正）。"""
    fn = TOOLS.get(name)
    if fn is None:
        return json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False)
    try:
        args = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        return json.dumps({"error": "invalid arguments JSON"}, ensure_ascii=False)
    if not isinstance(args, dict):
        return json.dumps({"error": "arguments must be an object"}, ensure_ascii=False)
    try:
        result = fn(**args)
    except (TypeError, ValueError) as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False, default=str)

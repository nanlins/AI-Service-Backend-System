"""工具注册表单元测试：安全计算、天气/时间工具、执行器错误处理。"""

import json

import pytest

from app.tools.registry import TOOL_SCHEMAS, calculate, execute_tool, get_current_time, get_weather


def test_calculate_basic_arithmetic():
    assert calculate("2+3*4")["result"] == 14
    assert calculate("(1+2)*3")["result"] == 9
    assert calculate("10/4")["result"] == 2.5
    assert calculate("-5+3")["result"] == -2


def test_calculate_rejects_dangerous_input():
    with pytest.raises(ValueError):
        calculate("__import__('os').system('ls')")
    with pytest.raises(ValueError):
        calculate("1/0")
    with pytest.raises(ValueError):
        calculate("abc")


def test_get_weather_returns_fields():
    assert get_weather("北京")["city"] == "北京"
    assert "temp" in get_weather("上海")


def test_get_current_time_returns_utc():
    assert "now" in get_current_time()
    assert get_current_time()["timezone"] == "UTC"


def test_tool_schemas_contain_three_tools():
    names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert names == {"get_current_time", "calculate", "get_weather"}


def test_execute_tool_returns_json():
    out = json.loads(execute_tool("calculate", '{"expression": "2+2"}'))
    assert out["result"] == 4


def test_execute_tool_unknown_name():
    out = json.loads(execute_tool("nope", "{}"))
    assert "error" in out


def test_execute_tool_invalid_arguments_json():
    out = json.loads(execute_tool("calculate", "not-json"))
    assert "error" in out


def test_execute_tool_missing_required_arg():
    out = json.loads(execute_tool("get_weather", "{}"))
    assert "error" in out

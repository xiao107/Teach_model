#!/usr/bin/env python3
"""
Integration test for the updated UI rendering system.
Tests the JSON parsing and response formatting.
"""
import json
from backend.agent import _parse_json_response

def test_json_parsing():
    """Test various JSON response formats"""
    
    print("=" * 60)
    print("Testing JSON Parsing")
    print("=" * 60)
    
    # Test 1: Direct JSON
    test1 = '{"thought": "我需要先了解数据", "reply": "好的老师，我来加载数据"}'
    result1, cleaned1 = _parse_json_response(test1)
    print("\n✓ Test 1: Direct JSON")
    print(f"  Parsed: {result1}")
    print(f"  Cleaned: {cleaned1}")
    assert result1 is not None
    assert result1.get("thought") == "我需要先了解数据"
    
    # Test 2: JSON in code block
    test2 = '''这是一些文本
```json
{
  "thought": "分析数据结构",
  "reply": "数据已加载"
}
```
更多文本'''
    result2, cleaned2 = _parse_json_response(test2)
    print("\n✓ Test 2: JSON in code block")
    print(f"  Parsed: {result2}")
    print(f"  Cleaned: {cleaned2[:50]}...")
    assert result2 is not None
    assert "这是一些文本" in cleaned2
    
    # Test 3: Plain text (no JSON)
    test3 = "这只是普通文本，没有JSON"
    result3, cleaned3 = _parse_json_response(test3)
    print("\n✓ Test 3: Plain text")
    print(f"  Parsed: {result3}")
    print(f"  Cleaned: {cleaned3}")
    assert result3 is None
    assert cleaned3 == test3
    
    # Test 4: JSON without code fence
    test4 = '''```
{
  "thought": "测试",
  "reply": "回复"
}
```'''
    result4, cleaned4 = _parse_json_response(test4)
    print("\n✓ Test 4: JSON without 'json' language tag")
    print(f"  Parsed: {result4}")
    assert result4 is not None
    
    print("\n" + "=" * 60)
    print("All tests passed! ✓")
    print("=" * 60)

def test_response_structure():
    """Test the response structure that will be sent to frontend"""
    
    print("\n" + "=" * 60)
    print("Testing Response Structure")
    print("=" * 60)
    
    # Simulate backend response
    structured_response = {
        "thought": "我需要先检查数据是否已加载",
        "reply": "老师好！目前还没有加载数据。\n\n请问您想加载哪个数据集？"
    }
    
    json_string = json.dumps(structured_response, ensure_ascii=False)
    print("\n✓ Backend sends:")
    print(json_string)
    
    # Simulate frontend parsing
    parsed = json.loads(json_string)
    print("\n✓ Frontend receives:")
    print(f"  thought: {parsed.get('thought')}")
    print(f"  reply: {parsed.get('reply')}")
    
    assert parsed.get("thought") is not None
    assert parsed.get("reply") is not None
    
    print("\n" + "=" * 60)
    print("Response structure test passed! ✓")
    print("=" * 60)

if __name__ == "__main__":
    try:
        test_json_parsing()
        test_response_structure()
        print("\n🎉 All integration tests passed!")
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)

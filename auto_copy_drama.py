"""
飞书漫剧素材自动复制脚本（应用身份认证 + 飞书机器人通知 + 环境变量）
==============================================
功能：将素材制作需求表（多维表格）中已完成的需求自动复制到个人剧目表格（电子表格）。
筛选条件：
  1. 只复制需求完成时间为当天的数据
  2. 只复制剧目类型为"漫剧"或"真人剧"的记录（排除"漫剧自剪"和"真人剧自剪"）
通知：执行完成后通过飞书机器人发送结果通知

认证方式：使用 Tenant Access Token（应用身份），需要将应用添加为源表和目标表的协作者。

使用前准备：
  1. 前往飞书开放平台 https://open.feishu.cn 创建企业自建应用
  2. 在应用中添加权限：
     - 多维表格：bitable:app（读取和更新记录）
     - 电子表格：sheets:spreadsheet（写入数据）
  3. 发布应用并获取 App ID 和 App Secret
  4. 将应用添加为源多维表格和目标电子表格的协作者（可编辑权限）
  5. 在飞书群中创建自定义机器人，获取 Webhook 地址
  6. 在 GitHub 仓库中设置 Secrets
  7. pip install requests
  8. python auto_copy_drama.py
"""

import os
import requests
import json
import sys
from datetime import datetime, date
from typing import Optional, Union, List


# =============================================================================
#  配置区域（优先从环境变量读取）
# =============================================================================

# 飞书应用凭证（从环境变量读取）
APP_ID = os.environ.get("APP_ID", "cli_aac77dbda9381cdc")
APP_SECRET = os.environ.get("APP_SECRET", "fP5iK0pfc9UaBQ9H3lecpb1aoakYA1nV")

# 飞书机器人 Webhook（从环境变量读取）
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")

# 源表配置（素材制作需求表 - 多维表格）- 这些不是敏感信息，直接写在代码中
SOURCE_BASE_TOKEN = "CcirbyeoXaCzotsAFElcEWiTnJE"
SOURCE_TABLE_ID   = "tblImLKgDcZy6HJM"
SOURCE_VIEW_ID    = "vew37dlKUv"

# 源表字段名
FIELD_STATUS         = "素材完成情况"
FIELD_TAKEN_TIME     = "投手取走日期"
FIELD_DRAMA_ID       = "剧目ID"
FIELD_DRAMA_NAME     = "剧名"
FIELD_DRAMA_TYPE     = "剧目类型"
FIELD_COMPLETE_DATE  = "需求完成时间"
STATUS_COMPLETED     = "已完成"

# 目标表配置
SPREADSHEET_TOKEN = "Rnsts6vGWhaXg7tLZR8cBG4enod"
SHEET_MANJU   = "FaO5SI"
SHEET_ZHENREN = "WPMdEB"


# =============================================================================
#  脚本主体
# =============================================================================

API_BASE = "https://open.feishu.cn/open-apis"


def get_tenant_token(app_id: str, app_secret: str) -> str:
    """获取应用级别的 tenant_access_token"""
    url = f"{API_BASE}/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret})
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 tenant token 失败: {data}")
    return data["tenant_access_token"]


def get_sheet_metadata(spreadsheet_token: str, token: str) -> dict:
    """获取电子表格的基本信息"""
    url = f"{API_BASE}/sheets/v3/spreadsheets/{spreadsheet_token}"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取表格元数据失败: {data}")
    
    spreadsheet = data.get("data", {}).get("spreadsheet", {})
    title = spreadsheet.get("title", "未知表格")
    print(f"  表格名称: {title}")
    
    return {
        SHEET_MANJU: "漫剧",
        SHEET_ZHENREN: "真人剧"
    }


def list_source_records(token: str) -> list:
    """读取源多维表格的所有记录"""
    url = f"{API_BASE}/bitable/v1/apps/{SOURCE_BASE_TOKEN}/tables/{SOURCE_TABLE_ID}/records"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"view_id": SOURCE_VIEW_ID, "page_size": 500}
    all_records = []
    page_token = None

    while True:
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(url, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"读取多维表格记录失败: {data}")
        items = data.get("data", {}).get("items", [])
        all_records.extend(items)
        if not data.get("data", {}).get("has_more"):
            break
        page_token = data["data"].get("page_token")

    print(f"  共读取到 {len(all_records)} 条记录")
    return all_records


def convert_timestamp_to_date_with_time(value: Union[int, float, str]) -> Optional[str]:
    """将时间戳转换为日期时间字符串（格式：2026/07/08 13:21）"""
    if value is None:
        return None
    
    if isinstance(value, str):
        if not value.isdigit():
            return value
        value = int(value)
    
    if not isinstance(value, (int, float)):
        return str(value)
    
    try:
        if value > 1000000000000:  # 13位毫秒时间戳
            dt = datetime.fromtimestamp(value / 1000)
        elif value > 1000000000:   # 10位秒时间戳
            dt = datetime.fromtimestamp(value)
        else:
            return str(value)
        return dt.strftime("%Y/%m/%d %H:%M")
    except (ValueError, OSError) as e:
        return str(value)


def convert_timestamp_to_datetime(value: Union[int, float, str]) -> Optional[datetime]:
    """将时间戳转换为 datetime 对象"""
    if value is None:
        return None
    
    if isinstance(value, str):
        if not value.isdigit():
            return None
        value = int(value)
    
    if not isinstance(value, (int, float)):
        return None
    
    try:
        if value > 1000000000000:  # 13位毫秒时间戳
            return datetime.fromtimestamp(value / 1000)
        elif value > 1000000000:   # 10位秒时间戳
            return datetime.fromtimestamp(value)
        else:
            return None
    except (ValueError, OSError):
        return None


def get_field_value(record: dict, field_name: str) -> Optional[str]:
    """安全获取记录中的字段值，自动识别并转换时间戳（返回日期+时间）"""
    fields = record.get("fields", {})
    value = fields.get(field_name)
    
    if value is None:
        return None
    if isinstance(value, list):
        return str(value[0]) if value else None
    
    if isinstance(value, (int, float)):
        if value > 1000000000:
            result = convert_timestamp_to_date_with_time(value)
            if result and "/" in result:
                return result
    
    return str(value) if value else None


def get_field_raw_value(record: dict, field_name: str) -> Optional[Union[int, float, str]]:
    """获取字段的原始值（不转换）"""
    fields = record.get("fields", {})
    return fields.get(field_name)


def is_today_timestamp(value: Union[int, float, str]) -> bool:
    """判断时间戳是否属于今天"""
    dt = convert_timestamp_to_datetime(value)
    if dt is None:
        return False
    return dt.date() == date.today()


def is_valid_drama_type(drama_type: str) -> tuple:
    """判断剧目类型是否有效，并返回对应的目标子表"""
    if not drama_type:
        return (False, None)
    
    if drama_type == "漫剧":
        return (True, "manju")
    elif drama_type == "真人剧":
        return (True, "zhenren")
    else:
        return (False, None)


def filter_pending_records(records: list) -> list:
    """筛选待处理的记录"""
    pending = []
    today = date.today()
    today_str = today.strftime("%Y/%m/%d")
    
    print(f"  筛选条件: 需求完成时间 = 今天 ({today_str})")
    print(f"  剧目类型: 仅限「漫剧」和「真人剧」（排除自剪）")
    
    for r in records:
        status = get_field_value(r, FIELD_STATUS)
        taken = get_field_value(r, FIELD_TAKEN_TIME)
        drama_type = get_field_value(r, FIELD_DRAMA_TYPE) or ""
        
        if status != STATUS_COMPLETED:
            continue
        
        if taken is not None and taken.strip() != "":
            continue
        
        raw_date = get_field_raw_value(r, FIELD_COMPLETE_DATE)
        if raw_date is None:
            continue
        
        if not is_today_timestamp(raw_date):
            continue
        
        valid, _ = is_valid_drama_type(drama_type)
        if not valid:
            continue
        
        complete_date = get_field_value(r, FIELD_COMPLETE_DATE) or ""
        pending.append({
            "record": r,
            "complete_date": complete_date,
            "drama_type": drama_type
        })
    
    print(f"  筛选出 {len(pending)} 条待处理记录（今天完成 + 有效类型）")
    return pending


def sort_pending_records(pending_records: list) -> list:
    """按需求完成日期升序排序"""
    def parse_date(date_str: str) -> datetime:
        if not date_str:
            return datetime.min
        
        if date_str.isdigit():
            try:
                ts = int(date_str)
                if ts > 1000000000000:
                    return datetime.fromtimestamp(ts / 1000)
                elif ts > 1000000000:
                    return datetime.fromtimestamp(ts)
            except (ValueError, OSError):
                pass
        
        formats = [
            "%Y/%m/%d %H:%M",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d",
            "%Y-%m-%d",
            "%Y年%m月%d日",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except (ValueError, TypeError):
                try:
                    return datetime.strptime(date_str[:10], fmt[:10])
                except (ValueError, TypeError):
                    continue
        
        return datetime.min
    
    sorted_records = sorted(
        pending_records,
        key=lambda x: parse_date(x["complete_date"]),
        reverse=False
    )
    if sorted_records:
        print(f"  排序完成，共 {len(sorted_records)} 条")
    return sorted_records


def append_to_target_sheet(token: str, spreadsheet_token: str, sheet_id: str, rows: list) -> None:
    """向目标电子表格追加数据（5列）"""
    if not rows:
        return
    
    url = f"{API_BASE}/sheets/v2/spreadsheets/{spreadsheet_token}/values_append"
    headers = {"Authorization": f"Bearer {token}"}
    body = {
        "valueRange": {
            "range": f"{sheet_id}!A:E",
            "values": rows,
        }
    }
    resp = requests.post(
        url, params={"insertDataOption": "INSERT_ROWS"},
        headers=headers, json=body
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"写入电子表格失败: {data}")


def update_taken_time(token: str, record_id: str, timestamp: str) -> None:
    """更新源表中记录的投手取走时间"""
    url = (
        f"{API_BASE}/bitable/v1/apps/{SOURCE_BASE_TOKEN}"
        f"/tables/{SOURCE_TABLE_ID}/records/{record_id}"
    )
    headers = {"Authorization": f"Bearer {token}"}
    body = {"fields": {FIELD_TAKEN_TIME: timestamp}}
    resp = requests.put(url, headers=headers, json=body)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"更新记录 {record_id} 失败: {data}")


def debug_record_fields(record: dict):
    """调试：打印记录中的所有字段"""
    fields = record.get("fields", {})
    print("\n  [DEBUG] 记录中的所有字段:")
    for key, value in fields.items():
        print(f"    {key}: {value} (类型: {type(value).__name__})")


# =============================================================================
#  飞书机器人通知函数
# =============================================================================

def send_feishu_message(webhook_url: str, message: str) -> bool:
    """向飞书自定义机器人发送文本消息"""
    if not webhook_url:
        print("  ⚠️ 未配置飞书 Webhook，跳过消息发送")
        return False
    
    headers = {"Content-Type": "application/json"}
    data = {
        "msg_type": "text",
        "content": {"text": message}
    }
    
    try:
        resp = requests.post(webhook_url, json=data, headers=headers, timeout=10)
        result = resp.json()
        if result.get("code") == 0:
            print("  ✅ 飞书消息发送成功")
            return True
        else:
            print(f"  ❌ 飞书消息发送失败: {result}")
            return False
    except Exception as e:
        print(f"  ❌ 飞书消息发送异常: {e}")
        return False


def build_success_message(manju_count: int, zhenren_count: int, total: int, 
                          success_count: int, update_tasks_count: int,
                          drama_list: List[dict]) -> str:
    """构建成功执行的通知消息"""
    lines = [
        "✅ **素材复制任务完成**",
        "",
        f"📊 **执行统计**",
        f"  • 漫剧: {manju_count} 条",
        f"  • 真人剧: {zhenren_count} 条",
        f"  • 总计: {total} 条",
        f"  • 更新取走时间: {success_count}/{update_tasks_count} 条",
        "",
    ]
    
    if drama_list:
        lines.append("📋 **今日复制的剧目**")
        for i, item in enumerate(drama_list[:5]):
            lines.append(f"  {i+1}. {item['name']} ({item['id']})")
        if len(drama_list) > 5:
            lines.append(f"  ... 还有 {len(drama_list) - 5} 条")
    
    return "\n".join(lines)


def build_error_message(error_msg: str) -> str:
    """构建错误通知消息"""
    return f"""
❌ **素材复制任务失败**

**错误信息**
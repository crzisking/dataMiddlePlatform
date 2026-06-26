"""【B2 脚手架】从业务库自动拉一个视图/表的字段，生成可粘进 register_views.py 的配置块。

省去手敲所有列名/类型的麻烦：你把生成的块粘进 scripts/register_views.py 的 VIEWS，
只需补每列的中文含义、用途、样例等（这些库里没有，得人来写），再运行 register_views.py 登记。

用法：
    uv run python scripts/scaffold_schema.py v_ai_制程不良明细
    uv run python scripts/scaffold_schema.py 某裸表名 --source-type table

⚠️ 运行时会对业务库做**一次只读的元数据查询**（INFORMATION_SCHEMA，不碰业务数据、不锁表）。
   生产库不便碰时，可对副本库跑，或先取得许可。
"""

import argparse
import sys

import app.core.eventloop  # noqa: F401  先设置 Windows 事件循环（pymssql 同步，其实用不到，统一习惯）
from app.services.texttosql.db import list_columns


def main() -> int:
    parser = argparse.ArgumentParser(description="拉取视图/表字段，生成语义层登记模板")
    parser.add_argument("object_name", help="视图或表名，如 v_ai_制程不良明细")
    parser.add_argument(
        "--source-type", default="view", choices=["view", "table"], help="view 或 table"
    )
    args = parser.parse_args()

    cols = list_columns(args.object_name)
    if not cols:
        print(f"没查到字段：{args.object_name}（确认名字对、只读账号能看到它）")
        return 1

    # 拼出 register_views.py 里 VIEWS 用的一条 dict。列名/类型已填好，
    # 含义等 PLACEHOLDER 留给人补（register_views.py 有防呆，没填会拒绝运行）。
    lines = ["{"]
    lines.append(f'    "source_type": "{args.source_type}",')
    lines.append(f'    "object_name": "{args.object_name}",')
    lines.append('    "desc": "PLACEHOLDER：一句话说清这个视图/表是干嘛的",')
    lines.append('    "grain": "PLACEHOLDER：一行 = 一个什么",')
    lines.append('    "columns": [')
    for c in cols:
        # 列名、类型自动填；中文含义/单位/取值留空待补
        lines.append(
            f'        {{"name": "{c["name"]}", "type": "{c["type"]}", '
            f'"desc": "PLACEHOLDER", "unit": "", "values": ""}},'
        )
    lines.append("    ],")
    lines.append('    "relations": None,  # 视图留 None；裸表必填，如 "A.k = B.k"')
    lines.append('    "samples": "PLACEHOLDER：1~2 个典型问法 ↔ SQL 样例",')
    lines.append('    "aliases": "PLACEHOLDER：业务术语别名",')
    lines.append('    "required_filter": "PLACEHOLDER：必带过滤列(通常日期)",')
    lines.append('    "default_window": "近30天",')
    lines.append('    "max_window": "1年",')
    lines.append('    "isolation": "nolock",')
    lines.append('    "enabled": False,  # 补完内容后改 True')
    lines.append("},")

    print(f"# 共 {len(cols)} 个字段。下面这块粘进 register_views.py 的 VIEWS，补好 PLACEHOLDER：\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

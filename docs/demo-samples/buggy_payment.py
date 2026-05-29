# CodeSentinel demo 固定样本 —— 故意写错，用于稳定触发 critical/warning/suggestion。
# 改这个文件务必同步更新 docs/demo-script.md 的"预期产出"一节。
#
# 设计意图（每条对应一个 Agent 维度，保证三类 severity 都出现）：
#   security    : SQL 注入（拼接）、硬编码密钥、eval 用户输入  → 期望 critical
#   performance : O(n²) 成员判断、循环内字符串拼接            → 期望 warning
#   style       : 无类型注解、单字母命名、裸 except 吞异常      → 期望 suggestion

import sqlite3

API_SECRET = "sk-live-9f3a1c0b2e7d4855a6f1demo000hardcoded"


def get_user_orders(db_path, uid):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # SQL 注入：uid 直接拼进语句
    cur.execute("SELECT * FROM orders WHERE user_id = " + str(uid))
    return cur.fetchall()


def find_duplicates(items):
    # O(n²)：每个元素都对整个 seen 列表做线性 in 判断
    seen = []
    dups = []
    for x in items:
        if x in seen:
            dups.append(x)
        seen.append(x)
    return dups


def build_report(rows):
    # 循环内字符串拼接：每次都重新分配整个字符串
    s = ""
    for r in rows:
        s = s + str(r) + "\n"
    return s


def run_rule(expr, ctx):
    # eval 执行外部传入的表达式，等价于任意代码执行
    return eval(expr, {}, ctx)


def charge(amount, token):
    try:
        # 省略真实扣款逻辑
        return {"ok": True, "amount": amount, "secret": API_SECRET}
    except:
        # 裸 except 吞掉一切异常，调用方无从得知失败原因
        return None

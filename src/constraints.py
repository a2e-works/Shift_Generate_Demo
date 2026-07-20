"""
STEP3: 制約条件チェックロジック

ここでの「制約」は、シフトを自動で組むためのソルバー用ルールではなく、
既存のExcelシフトや管理者の判断を検証・補助するためのチェック関数群である。

設計原則に沿い、ここでの判定はすべて
「違反しているから却下する」ものではなく
「管理者が気づくべき事項を可視化する」ためのものとして扱う。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from members import Member, load_members

CONSTRAINTS_PATH = Path(__file__).resolve().parent.parent / "data" / "constraints.json"

# 役職の段階(単独以上とみなす境界の比較に使う)
STAGE_ORDER = ["見学", "補助", "単独", "教育担当補助", "教育担当"]


def load_constraints(path: Path = CONSTRAINTS_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _stage_at_least(stage: str, min_stage: str) -> bool:
    return STAGE_ORDER.index(stage) >= STAGE_ORDER.index(min_stage)


def check_qualification_gaps(members: List[Member], constraints: dict) -> List[dict]:
    """『単独対応以上のスキルを持つのに、必要資格を保有していない』メンバーを洗い出す。

    シフトを作る担当者が見落としがちな『資格充足率』のギャップを機械的に検出する。
    """
    gaps = []
    requirements = constraints.get("qualification_requirements", {})
    for member in members:
        for equipment, rule in requirements.items():
            stage = member.equipment_skills.get(equipment)
            if stage is None or not _stage_at_least(stage, rule["min_stage"]):
                continue
            required_certs = set(rule.get("any_of_certifications", []))
            held_certs = set(member.certifications)
            if required_certs and not (required_certs & held_certs):
                gaps.append(
                    {
                        "member": member.name,
                        "member_id": member.member_id,
                        "equipment": equipment,
                        "current_stage": stage,
                        "missing_any_of": sorted(required_certs),
                    }
                )
    return gaps


def find_pair_rule(member_a_id: str, member_b_id: str, pair_rules: List[dict]) -> Optional[dict]:
    pair = {member_a_id, member_b_id}
    for rule in pair_rules:
        if set(rule["members"]) == pair:
            return rule
    return None


def check_ng_pair(member_a_id: str, member_b_id: str, constraints: dict) -> Optional[str]:
    """NGペアに該当する場合、理由を返す。該当しなければNone。"""
    rule = find_pair_rule(member_a_id, member_b_id, constraints.get("ng_pairs", []))
    return rule["reason"] if rule else None


def check_recommended_pair(member_a_id: str, member_b_id: str, constraints: dict) -> Optional[str]:
    """推奨ペアに該当する場合、理由を返す。該当しなければNone。"""
    rule = find_pair_rule(member_a_id, member_b_id, constraints.get("recommended_pairs", []))
    return rule["reason"] if rule else None


def check_night_shift_limit(role: str, planned_nights_this_month: int, constraints: dict) -> dict:
    """役職ごとの月間夜勤上限に対して、予定夜勤数が収まっているかを判定する。"""
    limits = constraints.get("night_shift_limits", {}).get("max_nights_per_month", {})
    limit = limits.get(role)
    if limit is None:
        return {"role": role, "limit": None, "planned": planned_nights_this_month, "within_limit": True}
    return {
        "role": role,
        "limit": limit,
        "planned": planned_nights_this_month,
        "within_limit": planned_nights_this_month <= limit,
    }


def is_requested_day_off(member_id: str, date_str: str, constraints: dict) -> bool:
    return date_str in constraints.get("requested_days_off", {}).get(member_id, [])


def is_on_long_leave(member_id: str, date_str: str, constraints: dict) -> Tuple[bool, Optional[str]]:
    leave = constraints.get("long_leave", {}).get(member_id)
    if not leave:
        return False, None
    if leave["start"] <= date_str <= leave["end"]:
        return True, leave.get("reason")
    return False, None


if __name__ == "__main__":
    members = load_members()
    members_by_id = {m.member_id: m for m in members}
    constraints = load_constraints()

    print("=== 資格充足ギャップ(単独対応以上だが必要資格を保有していない) ===")
    gaps = check_qualification_gaps(members, constraints)
    for g in gaps:
        certs = " / ".join(g["missing_any_of"])
        print(f"  {g['member']} ({g['equipment']}: {g['current_stage']}) - 未保有: {certs}")
    print(f"  合計 {len(gaps)} 件")

    print()
    print("=== NGペア ===")
    for rule in constraints.get("ng_pairs", []):
        names = [members_by_id[mid].name for mid in rule["members"]]
        print(f"  {' × '.join(names)}: {rule['reason']}")

    print()
    print("=== 推奨ペア(教育・育成目的) ===")
    for rule in constraints.get("recommended_pairs", []):
        names = [members_by_id[mid].name for mid in rule["members"]]
        print(f"  {' × '.join(names)}: {rule['reason']}")

    print()
    print("=== 希望休(登録されているメンバーのみ) ===")
    for member_id, dates in constraints.get("requested_days_off", {}).items():
        print(f"  {members_by_id[member_id].name}: {', '.join(dates)}")

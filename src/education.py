"""
STEP2: 教育ロードマップ判定ロジック

メンバーの experience_counts(実績回数)と経験月数を
education_roadmap.json の昇格条件と突き合わせ、
「次の段階に進めるか」「あと何が足りないか」を判定する。

このモジュールは何かを自動で決定・変更するものではない。
あくまで管理者が判断するための材料(誰が次の段階に近いか、
何が不足しているか)を可視化するためのものである。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional

from members import Member, load_members

ROADMAP_PATH = Path(__file__).resolve().parent.parent / "data" / "education_roadmap.json"


def load_roadmap(path: Path = ROADMAP_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_progress(member: Member, equipment: str, roadmap: dict) -> dict:
    """指定メンバー・指定設備について、次段階への到達状況を評価する。"""
    eq_roadmap = roadmap.get(equipment)
    if eq_roadmap is None:
        return {"error": f"'{equipment}' の教育ロードマップが未定義です"}

    stage_order = eq_roadmap["stage_order"]
    current_stage = member.equipment_skills.get(equipment)
    if current_stage is None or current_stage not in stage_order:
        return {"error": f"{member.name} は '{equipment}' のスキル記録がありません"}

    stage_index = stage_order.index(current_stage)

    if stage_index == len(stage_order) - 1:
        return {
            "member": member.name,
            "equipment": equipment,
            "current_stage": current_stage,
            "next_stage": None,
            "eligible_for_next_stage": False,
            "message": "最終段階(教育担当)に到達済み",
        }

    transition = eq_roadmap["transitions"][stage_index]
    counts = member.experience_counts.get(equipment, {})

    requirements = []
    all_counts_met = True
    for count_type, required in transition["required_counts"].items():
        current = counts.get(count_type, 0)
        met = current >= required
        all_counts_met = all_counts_met and met
        requirements.append(
            {"type": count_type, "required": required, "current": current, "met": met}
        )

    min_months = transition.get("min_experience_months")
    months_met = True if min_months is None else member.experience_months >= min_months

    return {
        "member": member.name,
        "equipment": equipment,
        "current_stage": current_stage,
        "next_stage": transition["to"],
        "requirements": requirements,
        "min_experience_months": min_months,
        "months_met": months_met,
        "eligible_for_next_stage": all_counts_met and months_met,
    }


def evaluate_all(members: Iterable[Member], roadmap: dict) -> Iterator[dict]:
    """全メンバー×保有スキルの設備すべてについて判定結果を返す。"""
    for member in members:
        for equipment in member.equipment_skills:
            yield evaluate_progress(member, equipment, roadmap)


def missing_requirements_text(result: dict) -> str:
    """不足条件を1行の日本語テキストにまとめる(ダッシュボード等での表示用)。"""
    if result.get("eligible_for_next_stage"):
        return "昇格条件クリア"
    parts = [
        f"{r['type']} {r['current']}/{r['required']}"
        for r in result.get("requirements", [])
        if not r["met"]
    ]
    if result.get("min_experience_months") is not None and not result.get("months_met"):
        parts.append(f"経験月数 {result['min_experience_months']}ヶ月以上")
    return "、".join(parts) if parts else "-"


if __name__ == "__main__":
    members = load_members()
    roadmap = load_roadmap()
    results = list(evaluate_all(members, roadmap))

    ready = [r for r in results if r.get("eligible_for_next_stage")]
    in_progress = [
        r for r in results if r.get("next_stage") and not r.get("eligible_for_next_stage")
    ]

    print(f"=== 昇格条件クリア済み({len(ready)}件) ===")
    for r in ready:
        print(f"  {r['member']} / {r['equipment']}: {r['current_stage']} → {r['next_stage']}")

    print()
    print(f"=== 育成中・条件未達({len(in_progress)}件のうち一部を表示) ===")
    for r in in_progress[:10]:
        print(
            f"  {r['member']} / {r['equipment']}: {r['current_stage']} → {r['next_stage']} "
            f"(不足: {missing_requirements_text(r)})"
        )

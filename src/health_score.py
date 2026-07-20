"""
STEP4: シフト健全度計算設計

セクション8で定義した「シフト健全度」を、STEP1〜3で作ったデータから
実際に計算できるようにする。

定義(原資料より):
  予定外の出来事(欠勤・退職・教育・資格更新・希望休など)が発生しても、
  安全かつ継続的に現場を運営できる組織力。

構成要素として、以下の5指標を 0〜100 で算出し、平均を総合スコアとする。
それぞれ「高いほど健全」になるよう方向をそろえている。

  1. 教育達成率      education_achievement_rate
  2. 属人化耐性       key_person_dependency_score (高い = 属人化していない)
  3. 資格充足率       qualification_fulfillment_rate
  4. バックアップ率    backup_coverage_rate
  5. 変更耐性         change_resilience_score

注意: 「変更回数ではなく変更耐性を評価する」という原則があるため、
変更耐性はシフト変更の回数ではなく、「今この瞬間に誰か1人が抜けても
チームとして回るか」をチームごとにシミュレーションして算出する。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from members import Member, load_members, EDUCATION_STAGES
from education import load_roadmap
from constraints import load_constraints, check_qualification_gaps

INDEPENDENT_STAGE_INDEX = EDUCATION_STAGES.index("単独")  # 2


def _stage_index(stage: str) -> int:
    return EDUCATION_STAGES.index(stage)


def calc_education_achievement_rate(members: List[Member]) -> float:
    """全メンバー×保有設備スキルについて、教育ロードマップ上どこまで進んでいるかの平均。

    各スキルの到達段階(0〜4)を最大段階(4)で割り、百分率にして平均する。
    """
    ratios = []
    max_index = len(EDUCATION_STAGES) - 1
    for member in members:
        for stage in member.equipment_skills.values():
            ratios.append(_stage_index(stage) / max_index)
    if not ratios:
        return 0.0
    return round(sum(ratios) / len(ratios) * 100, 1)


def calc_key_person_dependency_score(members: List[Member], roadmap: dict, target_independent: int = 3) -> dict:
    """設備ごとに『単独対応以上』ができる人数を数え、少なすぎる設備がないかを見る。

    1人しかいない = 属人化リスク最大(0点)。target_independent人以上いれば満点(100点)。
    """
    equipment_list = list(roadmap.keys())
    counts = {eq: 0 for eq in equipment_list}
    for member in members:
        for equipment, stage in member.equipment_skills.items():
            if equipment in counts and _stage_index(stage) >= INDEPENDENT_STAGE_INDEX:
                counts[equipment] += 1

    per_equipment_score = {}
    for equipment, count in counts.items():
        score = min(count, target_independent) / target_independent * 100
        per_equipment_score[equipment] = {"independent_count": count, "score": round(score, 1)}

    overall = round(
        sum(v["score"] for v in per_equipment_score.values()) / len(per_equipment_score), 1
    ) if per_equipment_score else 0.0

    return {"overall": overall, "by_equipment": per_equipment_score}


def calc_qualification_fulfillment_rate(members: List[Member], constraints: dict) -> dict:
    """『単独対応以上のスキルを持つ人』のうち、必要資格を保有している人の割合。"""
    requirements = constraints.get("qualification_requirements", {})
    total_checks = 0
    for member in members:
        for equipment, rule in requirements.items():
            stage = member.equipment_skills.get(equipment)
            if stage and _stage_index(stage) >= _stage_index(rule["min_stage"]):
                total_checks += 1

    gaps = check_qualification_gaps(members, constraints)
    satisfied = total_checks - len(gaps)
    rate = round(satisfied / total_checks * 100, 1) if total_checks else 100.0
    return {"rate": rate, "satisfied": satisfied, "total_checks": total_checks, "gap_count": len(gaps)}


def calc_backup_coverage_rate(members: List[Member]) -> dict:
    """バックアップ可能業務を1つ以上持っているメンバーの割合。"""
    with_backup = sum(1 for m in members if m.backup_capable_tasks)
    rate = round(with_backup / len(members) * 100, 1) if members else 0.0
    return {"rate": rate, "with_backup": with_backup, "total": len(members)}


def calc_change_resilience_score(members: List[Member]) -> dict:
    """チームごとに『何かしらの設備を単独対応以上でこなせる人』が何人いるかを見る。

    1人しかいないチームは、その1人が急に休むと即座に立ち行かなくなる
    (= 変更耐性が低い)。3人中2人以上いれば高耐性とみなす。
    """
    teams: Dict[str, List[Member]] = defaultdict(list)
    for m in members:
        teams[m.team].append(m)

    team_scores = {}
    for team, team_members in teams.items():
        capable = sum(
            1
            for m in team_members
            if any(_stage_index(s) >= INDEPENDENT_STAGE_INDEX for s in m.equipment_skills.values())
        )
        # チーム人数に対する充足度(2人以上いれば満点とみなす)
        target = min(2, len(team_members))
        score = min(capable, target) / target * 100 if target else 0.0
        team_scores[team] = {"capable_members": capable, "team_size": len(team_members), "score": round(score, 1)}

    overall = round(sum(v["score"] for v in team_scores.values()) / len(team_scores), 1) if team_scores else 0.0
    return {"overall": overall, "by_team": team_scores}


def calc_shift_health_score(members: List[Member], roadmap: dict, constraints: dict) -> dict:
    education = calc_education_achievement_rate(members)
    dependency = calc_key_person_dependency_score(members, roadmap)
    qualification = calc_qualification_fulfillment_rate(members, constraints)
    backup = calc_backup_coverage_rate(members)
    resilience = calc_change_resilience_score(members)

    components = {
        "教育達成率": education,
        "属人化耐性": dependency["overall"],
        "資格充足率": qualification["rate"],
        "バックアップ率": backup["rate"],
        "変更耐性": resilience["overall"],
    }
    overall = round(sum(components.values()) / len(components), 1)

    return {
        "overall_score": overall,
        "components": components,
        "details": {
            "education_achievement_rate": education,
            "key_person_dependency": dependency,
            "qualification_fulfillment": qualification,
            "backup_coverage": backup,
            "change_resilience": resilience,
        },
    }


if __name__ == "__main__":
    members = load_members()
    roadmap = load_roadmap()
    constraints = load_constraints()

    result = calc_shift_health_score(members, roadmap, constraints)

    print("=== シフト健全度 ===")
    print(f"総合スコア: {result['overall_score']} / 100")
    print()
    print("--- 内訳 ---")
    for name, score in result["components"].items():
        print(f"  {name}: {score}")

    print()
    print("--- 属人化耐性(設備別: 単独対応以上の人数) ---")
    for eq, v in result["details"]["key_person_dependency"]["by_equipment"].items():
        print(f"  {eq}: {v['independent_count']}人 (スコア {v['score']})")

    print()
    print("--- 変更耐性(チーム別) ---")
    for team, v in result["details"]["change_resilience"]["by_team"].items():
        print(f"  チーム{team}: {v['capable_members']}/{v['team_size']}人が単独対応可能 (スコア {v['score']})")

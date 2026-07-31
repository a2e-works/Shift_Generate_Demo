"""
必要人数チェック + 交代要員(振替)の提案ロジック

チーム制の運行では、早番B・夜勤は「チームで運行する」ことが前提のため、
早番A(教育投資枠、必須人数なし)とは違い、誰かが休むと必要人数を割り込む
可能性がある。その場合に「他チームの誰を回せば埋まるか」を提案する。

考え方:
- チーム定員は3名。早番B・夜勤の必要人数は2名(1名の欠勤までは同一チーム内で
  吸収できるが、2名以上欠けると他チームからの応援が必要、という前提)。
- 交代要員の候補は、その日「休み」または「明け」で元々出勤予定がなかった
  他チームのメンバーに限る(元々出勤しているメンバーを動かすと、そのチームで
  新たな欠員が生じてしまうため)。
- 候補は、単独対応以上のスキルを持つ人(capable)を優先し、欠勤者と同じチームの
  残りのメンバーとNGペアにならない人を優先する。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from members import Member
from constraints import check_ng_pair
from health_score import _stage_index, INDEPENDENT_STAGE_INDEX


def _is_capable(member: Member) -> bool:
    return any(_stage_index(s) >= INDEPENDENT_STAGE_INDEX for s in member.equipment_skills.values())


def day_team_status(date_str: str, team: str, schedule: List[dict], constraints: dict) -> dict:
    """指定日・指定チームの、シフト種別・必要人数・予定人数を返す。"""
    day = next((d for d in schedule if d["date"] == date_str), None)
    if day is None:
        return {"error": f"{date_str} のシフトデータが見つからない"}
    shift = day["team_shifts"][team]
    required = constraints.get("shift_required_headcount", {}).get(shift, 0)
    return {"date": date_str, "team": team, "shift": shift, "required_headcount": required}


def find_substitute_candidates(
    date_str: str,
    team: str,
    absent_member_id: str,
    members: List[Member],
    schedule: List[dict],
    constraints: dict,
    max_candidates: int = 3,
) -> List[dict]:
    """その日、他チームで『休み』または『明け』のため元々空いている人から交代候補を探す。"""
    day = next((d for d in schedule if d["date"] == date_str), None)
    if day is None:
        return []

    team_members_today = [m for m in members if m.team == team and m.member_id != absent_member_id]

    candidates = []
    for m in members:
        if m.team == team:
            continue  # 同じチームは対象外(全員同じシフトのため元々空いていない)
        their_shift = day["team_shifts"][m.team]
        if their_shift not in ("休み", "明け"):
            continue  # 元々出勤予定がある人は動かさない

        ng_conflict = any(check_ng_pair(m.member_id, other.member_id, constraints) for other in team_members_today)
        candidates.append(
            {
                "member_id": m.member_id,
                "name": m.name,
                "team": m.team,
                "role": m.role,
                "capable": _is_capable(m),
                "ng_conflict": ng_conflict,
            }
        )

    candidates.sort(key=lambda c: (c["ng_conflict"], not c["capable"]))
    return candidates[:max_candidates]


def simulate_substitution(
    date_str: str,
    team: str,
    absent_member_id: str,
    members: List[Member],
    schedule: List[dict],
    constraints: dict,
) -> dict:
    """希望休を承認した場合、その日の必要人数を満たせるか、満たせない場合は誰と交代するかを判定する。"""
    members_by_id = {m.member_id: m for m in members}
    absent_member = members_by_id[absent_member_id]
    status = day_team_status(date_str, team, schedule, constraints)
    shift = status["shift"]
    required = status["required_headcount"]

    team_size_today = sum(1 for m in members if m.team == team)
    scheduled_after_leave = team_size_today - 1
    meets_requirement = scheduled_after_leave >= required

    if required == 0:
        return {
            "date": date_str,
            "team": team,
            "shift": shift,
            "required_headcount": required,
            "scheduled_after_leave": scheduled_after_leave,
            "needs_substitute": False,
            "day_score_before": 100,
            "day_score_after": 100,
            "message": f"{shift}は必要人数の定めがないため、交代なしで承認可能",
        }

    if meets_requirement:
        return {
            "date": date_str,
            "team": team,
            "shift": shift,
            "required_headcount": required,
            "scheduled_after_leave": scheduled_after_leave,
            "needs_substitute": False,
            "day_score_before": 100,
            "day_score_after": 100,
            "message": f"チーム内に{scheduled_after_leave}名残るため、交代なしで必要人数({required}名)を満たす",
        }

    candidates = find_substitute_candidates(date_str, team, absent_member_id, members, schedule, constraints)
    usable = [c for c in candidates if not c["ng_conflict"]]

    if usable:
        best = usable[0]
        day = next((d for d in schedule if d["date"] == date_str), None)
        best_original_shift = day["team_shifts"][best["team"]] if day else "休み"
        return {
            "date": date_str,
            "team": team,
            "shift": shift,
            "required_headcount": required,
            "scheduled_after_leave": scheduled_after_leave,
            "needs_substitute": True,
            "swap_out": absent_member.name,
            "swap_in": best["name"],
            "swap_in_team": best["team"],
            "candidates": candidates,
            "day_score_before": 100,
            "day_score_after": 100,
            "message": f"{absent_member.name}(チーム{team})の代わりに、"
            f"{best['name']}(チーム{best['team']}、この日は元々{best_original_shift})を配置すれば必要人数を維持できる",
        }

    day_score_after = round(scheduled_after_leave / required * 100, 1) if required else 100
    return {
        "date": date_str,
        "team": team,
        "shift": shift,
        "required_headcount": required,
        "scheduled_after_leave": scheduled_after_leave,
        "needs_substitute": True,
        "swap_out": absent_member.name,
        "swap_in": None,
        "candidates": candidates,
        "day_score_before": 100,
        "day_score_after": day_score_after,
        "message": f"交代できる候補が見つからない(候補はいるがNGペアが絡む等)。"
        f"必要人数{required}名に対し{scheduled_after_leave}名までしか維持できない見込み",
    }


if __name__ == "__main__":
    from members import load_members
    from constraints import load_constraints
    from shift_schedule import generate_schedule, DEMO_START_DATE, DEMO_NUM_DAYS

    members = load_members()
    constraints = load_constraints()
    schedule = generate_schedule(members, DEMO_START_DATE, DEMO_NUM_DAYS)
    members_by_id = {m.member_id: m for m in members}

    print("=== 各日の必要人数チェック(例: 2026-08-15) ===")
    for team in ["A", "B", "C", "D", "E"]:
        status = day_team_status("2026-08-15", team, schedule, constraints)
        print(f"  チーム{team}: {status['shift']}(必要人数: {status['required_headcount']}名)")

    print()
    print("=== 希望休を承認した場合の交代シミュレーション ===")
    demo_cases = [
        ("M09", "2026-08-15"),  # 小林拓也(チームC) 早番Bの日
        ("M09", "2026-08-16"),  # 小林拓也(チームC) 夜勤の日
        ("M12", "2026-08-20"),  # 山田悠斗(チームB) 早番Aの日
    ]
    for member_id, date_str in demo_cases:
        member = members_by_id[member_id]
        result = simulate_substitution(date_str, member.team, member_id, members, schedule, constraints)
        print(f"  {member.name} / {date_str}({result['shift']}): {result['message']}")
        if result.get("needs_substitute") and result.get("swap_in"):
            print(f"    → {result['swap_out']} を休みにし、{result['swap_in']}({result['swap_in_team']}) を配置")
        print(f"    当日の充足度: {result['day_score_before']} → {result['day_score_after']}")

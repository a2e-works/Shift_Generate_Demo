"""
STEP5: 仮想シフト作成

セクション5のシフトモデル(早番A/早番B/夜勤/明け/休み、5チームローテーション)を
実際のカレンダーとして展開する。

重要: これは「最適なシフトを自動で作る」ものではない。
むしろ逆で、既存Excel運用でありがちな「単純な5チームローテーションをそのまま回す」
という前提を再現し、それが希望休・夜勤上限・NGペアと衝突する箇所を検出することで、
"何もしなければどこで無理が生じるか"を可視化するのが目的である
(設計原則1・2、セクション7の希望休の考え方に対応)。

ローテーション順序:
  早番A(教育投資枠) → 早番B → 夜勤 → 明け → 休み → (最初に戻る)

5チームは1日ずつずれた状態でこのサイクルを回るため、毎日5種類の状態が
必ず埋まる(1チーム1状態)。
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List

from members import Member, load_members
from constraints import load_constraints

SCHEDULE_PATH = Path(__file__).resolve().parent.parent / "data" / "shift_schedule.json"

ROTATION_CYCLE = ["早番A", "早番B", "夜勤", "明け", "休み"]
TEAM_OFFSETS = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}

DEMO_START_DATE = date(2026, 8, 1)
DEMO_NUM_DAYS = 31  # 2026年8月分


def shift_for_team(day_index: int, team: str) -> str:
    offset = TEAM_OFFSETS[team]
    return ROTATION_CYCLE[(day_index + offset) % 5]


def generate_schedule(
    members: List[Member], start_date: date = DEMO_START_DATE, num_days: int = DEMO_NUM_DAYS
) -> List[dict]:
    schedule = []
    for i in range(num_days):
        current_date = start_date + timedelta(days=i)
        date_str = current_date.isoformat()
        team_shifts = {team: shift_for_team(i, team) for team in TEAM_OFFSETS}
        member_shifts = {m.member_id: team_shifts[m.team] for m in members}
        schedule.append({"date": date_str, "team_shifts": team_shifts, "member_shifts": member_shifts})
    return schedule


def save_schedule(schedule: List[dict], path: Path = SCHEDULE_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(schedule, f, ensure_ascii=False, indent=2)


def load_schedule(path: Path = SCHEDULE_PATH) -> List[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---- 衝突検出(=既存ローテーションのままだと何が起きるか) ----


def detect_requested_day_off_conflicts(schedule: List[dict], constraints: dict, members_by_id: Dict[str, Member]) -> List[dict]:
    """希望休の日に、実際には休みでないシフトが割り当たっているケースを検出する。"""
    conflicts = []
    requested = constraints.get("requested_days_off", {})
    for day in schedule:
        for member_id, dates in requested.items():
            if day["date"] in dates:
                shift = day["member_shifts"].get(member_id)
                if shift != "休み":
                    conflicts.append(
                        {
                            "date": day["date"],
                            "member": members_by_id[member_id].name,
                            "scheduled_shift": shift,
                        }
                    )
    return conflicts


def detect_night_shift_overages(schedule: List[dict], constraints: dict, members_by_id: Dict[str, Member]) -> List[dict]:
    """役職ごとの月間夜勤上限を、単純ローテーションのままだと超えてしまう人を検出する。"""
    night_counts = defaultdict(int)
    for day in schedule:
        for member_id, shift in day["member_shifts"].items():
            if shift == "夜勤":
                night_counts[member_id] += 1

    limits = constraints.get("night_shift_limits", {}).get("max_nights_per_month", {})
    overages = []
    for member_id, count in night_counts.items():
        member = members_by_id[member_id]
        limit = limits.get(member.role)
        if limit is not None and count > limit:
            overages.append(
                {"member": member.name, "role": member.role, "scheduled_nights": count, "limit": limit}
            )
    return overages


def detect_ng_pair_conflicts(schedule: List[dict], constraints: dict, members_by_id: Dict[str, Member]) -> List[dict]:
    """NGペアが同じ日に同じ勤務(休み以外)に入ってしまっているケースを検出する。"""
    conflicts = []
    for rule in constraints.get("ng_pairs", []):
        m1, m2 = rule["members"]
        for day in schedule:
            s1, s2 = day["member_shifts"].get(m1), day["member_shifts"].get(m2)
            if s1 == s2 and s1 != "休み":
                conflicts.append(
                    {
                        "date": day["date"],
                        "members": [members_by_id[m1].name, members_by_id[m2].name],
                        "shift": s1,
                        "reason": rule["reason"],
                    }
                )
    return conflicts


def detect_long_leave_conflicts(schedule: List[dict], constraints: dict, members_by_id: Dict[str, Member]) -> List[dict]:
    """長期休暇期間中に、休み以外のシフトが割り当たっているケースを検出する。"""
    conflicts = []
    for member_id, leave in constraints.get("long_leave", {}).items():
        for day in schedule:
            if leave["start"] <= day["date"] <= leave["end"]:
                shift = day["member_shifts"].get(member_id)
                if shift != "休み":
                    conflicts.append(
                        {
                            "date": day["date"],
                            "member": members_by_id[member_id].name,
                            "scheduled_shift": shift,
                            "reason": leave.get("reason"),
                        }
                    )
    return conflicts


if __name__ == "__main__":
    members = load_members()
    members_by_id = {m.member_id: m for m in members}
    constraints = load_constraints()

    schedule = generate_schedule(members)
    save_schedule(schedule)
    print(f"{DEMO_START_DATE.isoformat()} から {DEMO_NUM_DAYS}日分の仮想シフトを生成しました → {SCHEDULE_PATH}")

    print()
    print("=== 希望休との衝突(単純ローテーションのままだと休めない日) ===")
    off_conflicts = detect_requested_day_off_conflicts(schedule, constraints, members_by_id)
    for c in off_conflicts:
        print(f"  {c['date']} {c['member']}: 希望休だが「{c['scheduled_shift']}」が割当済み")
    print(f"  合計 {len(off_conflicts)} 件")

    print()
    print("=== 夜勤回数の役職別上限オーバー ===")
    overages = detect_night_shift_overages(schedule, constraints, members_by_id)
    for o in overages:
        print(f"  {o['member']}({o['role']}): {o['scheduled_nights']}回 / 上限{o['limit']}回")
    print(f"  合計 {len(overages)} 件")

    print()
    print("=== NGペアの同時配置 ===")
    ng_conflicts = detect_ng_pair_conflicts(schedule, constraints, members_by_id)
    for c in ng_conflicts[:5]:
        print(f"  {c['date']} {' × '.join(c['members'])}: 同じ「{c['shift']}」に配置")
    print(f"  合計 {len(ng_conflicts)} 件(先頭5件のみ表示)")

    print()
    print("=== 長期休暇との衝突 ===")
    leave_conflicts = detect_long_leave_conflicts(schedule, constraints, members_by_id)
    for c in leave_conflicts:
        print(f"  {c['date']} {c['member']}: 長期休暇中だが「{c['scheduled_shift']}」が割当済み")
    print(f"  合計 {len(leave_conflicts)} 件")

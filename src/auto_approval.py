"""
希望休の自動承認ロジック + 週40時間の労働時間チェック

このモジュールが実現する2つのこと:

1. 労働時間チェック(健全度とは無関係の法令順守チェック)
   週40時間を超える勤務は労働基準法上の問題になりうるため、シフト健全度の
   良し悪しとは別に、常にチェックする。違反がある週は、その週にかかる希望休を
   自動承認の対象から外す(=管理者の手動確認に回す)。

2. 希望休の自動承認判定
   以下をすべて満たす希望休だけを、管理者の承認なしで自動的に通す。
   管理者はこの機能自体をON/OFFできる(auto_approval.enabled)。

   a. 自動承認機能が有効になっている
   b. 申請日から希望日までが、設定した日数(例: 14日)以上ある
   c. その週に週40時間超えの違反がチーム内に無い
      (違反があると『誰かが代わりに出る』余地が無い可能性が高いため)
   d. 承認後もチームに単独対応できる人が十分残る(健全度への影響が小さい)
   e. NGペアの相手が同じ日に関わる、当事者間の調整が必要な状況ではない

   いずれか1つでも満たさない場合は、通常どおり管理者の手動承認に回す。
   週40時間の違反がある場合は、健全度が良くても自動承認しない
   (「健全度関係なく」対応する、というルール)。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List

from members import Member, load_members
from constraints import load_constraints, check_ng_pair
from shift_schedule import generate_schedule, DEMO_START_DATE, DEMO_NUM_DAYS
from health_score import _stage_index, INDEPENDENT_STAGE_INDEX


def _week_key(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def calc_weekly_hours(schedule: List[dict], constraints: dict) -> Dict[str, Dict[str, int]]:
    """メンバーID -> 週キー -> その週の合計勤務時間、を計算する。"""
    hours_by_shift = constraints["working_hour_limits"]["hours_by_shift"]
    weekly: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for day in schedule:
        d = date.fromisoformat(day["date"])
        wk = _week_key(d)
        for member_id, shift in day["member_shifts"].items():
            weekly[member_id][wk] += hours_by_shift.get(shift, 0)
    return weekly


def find_weekly_hour_violations(schedule: List[dict], members: List[Member], constraints: dict) -> List[dict]:
    """週40時間(設定値)を超えているメンバー・週の一覧を返す。健全度とは無関係のチェック。"""
    limit = constraints["working_hour_limits"]["max_hours_per_week"]
    weekly = calc_weekly_hours(schedule, constraints)
    members_by_id = {m.member_id: m for m in members}
    violations = []
    for member_id, weeks in weekly.items():
        for wk, hours in weeks.items():
            if hours > limit:
                violations.append(
                    {
                        "member_id": member_id,
                        "member": members_by_id[member_id].name,
                        "team": members_by_id[member_id].team,
                        "week": wk,
                        "hours": hours,
                        "limit": limit,
                    }
                )
    return violations


def _team_backup_headcount(team: str, members: List[Member]) -> int:
    """そのチームで設備を単独対応以上でこなせる人数(health_score.pyの考え方を簡略に再利用)。"""
    count = 0
    for m in members:
        if m.team != team:
            continue
        if any(_stage_index(s) >= INDEPENDENT_STAGE_INDEX for s in m.equipment_skills.values()):
            count += 1
    return count


def evaluate_auto_approval(
    member_id: str,
    request_date: str,
    submitted_date: str,
    members: List[Member],
    schedule: List[dict],
    constraints: dict,
) -> dict:
    """1件の希望休について、自動承認できるかどうかを判定する。

    戻り値には、どの条件で自動承認/手動承認になったかの理由を必ず含める
    (「なぜ自動で通ったか/通らなかったか」を管理者・メンバー双方が追跡できるように)。
    """
    members_by_id = {m.member_id: m for m in members}
    member = members_by_id[member_id]
    reasons = []

    settings = constraints.get("auto_approval", {})
    if not settings.get("enabled", False):
        return {"auto_approved": False, "reasons": ["管理者設定により自動承認機能がOFFになっている"]}

    # b. 申請日から希望日までの日数
    days_before = (date.fromisoformat(request_date) - date.fromisoformat(submitted_date)).days
    min_days = settings.get("min_days_before", 14)
    if days_before < min_days:
        reasons.append(f"申請期限({min_days}日前まで)を満たしていない(実際: {days_before}日前)")

    # c. 週40時間違反がその週のチーム内に無いか
    violations = find_weekly_hour_violations(schedule, members, constraints)
    week_of_request = _week_key(date.fromisoformat(request_date))
    team_violation_this_week = [
        v for v in violations if v["team"] == member.team and v["week"] == week_of_request
    ]
    if team_violation_this_week:
        names = "、".join(v["member"] for v in team_violation_this_week)
        reasons.append(f"週40時間の労働時間超過がチーム内に存在するため、健全度に関係なく手動確認が必要({names})")

    # d. 承認後の残人数(健全度への影響)
    backup_headcount = _team_backup_headcount(member.team, members)
    is_capable = any(
        _stage_index(s) >= INDEPENDENT_STAGE_INDEX for s in member.equipment_skills.values()
    )
    residual = backup_headcount - (1 if is_capable else 0)
    min_backup = settings.get("min_backup_headcount", 2)
    if residual < min_backup:
        reasons.append(f"承認後にチームに残る対応可能人数が{residual}人(基準{min_backup}人)を下回る")

    # e. NGペアの相手がこの日に関わる状況ではないか(簡易チェック)
    ng_partner_reason = None
    for other in members:
        if other.member_id == member_id:
            continue
        if check_ng_pair(member_id, other.member_id, constraints):
            ng_partner_reason = f"{other.name}とのNGペア調整が絡むため当事者間の確認が必要"
            break
    if ng_partner_reason:
        reasons.append(ng_partner_reason)

    auto_approved = len(reasons) == 0
    if auto_approved:
        reasons.append(
            f"申請期限・週40時間・チームの残人数({residual}人)・NGペアのいずれも問題なし → 自動承認"
        )
    return {"auto_approved": auto_approved, "reasons": reasons, "residual_backup": residual}


def evaluate_all_requests(members: List[Member], schedule: List[dict], constraints: dict) -> List[dict]:
    """constraints.json内の希望休をすべて自動承認判定し、結果のリストを返す。"""
    members_by_id = {m.member_id: m for m in members}
    requested = constraints.get("requested_days_off", {})
    submitted_on = constraints.get("requested_days_off_submitted_on", {})
    results = []
    for member_id, dates in requested.items():
        submitted_date = submitted_on.get(member_id)
        if not submitted_date:
            continue
        for request_date in dates:
            result = evaluate_auto_approval(member_id, request_date, submitted_date, members, schedule, constraints)
            results.append(
                {
                    "member": members_by_id[member_id].name,
                    "member_id": member_id,
                    "date": request_date,
                    "submitted_on": submitted_date,
                    **result,
                }
            )
    return results


if __name__ == "__main__":
    members = load_members()
    constraints = load_constraints()
    schedule = generate_schedule(members, DEMO_START_DATE, DEMO_NUM_DAYS)

    print("=== 週40時間の労働時間チェック(健全度とは無関係) ===")
    violations = find_weekly_hour_violations(schedule, members, constraints)
    if not violations:
        print("  違反なし")
    for v in violations:
        print(f"  {v['member']}(チーム{v['team']}) {v['week']}: {v['hours']}時間(上限{v['limit']}時間)")

    print()
    print("=== 希望休の自動承認判定(登録されている全申請) ===")
    for result in evaluate_all_requests(members, schedule, constraints):
        status = "自動承認" if result["auto_approved"] else "手動確認へ"
        print(f"  {result['member']} / {result['date']}(申請:{result['submitted_on']}) → {status}")
        for r in result["reasons"]:
            print(f"    - {r}")

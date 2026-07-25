"""
STEP7: 未来シミュレーション

原資料セクション9「将来シミュレーション」を、実際に計算できるようにする。
単なる楽観的な右肩上がりの予測ではなく、以下を明示的にモデル化する:

1. 教育は「教育担当が同乗している早番A」でしか進まない(現実的な前提)。
   → チームに教育担当が1人もいない設備は、何ヶ月経っても頭打ちになる。
2. その頭打ち(理論上限)を検出し、「あと何人、教育担当が必要か」を数える。
3. 教育担当を増やした場合(昇格・増員)のwhat-ifを試せるようにする。
4. 退職シミュレーション: 役職ごとに後任育成に必要なリードタイムが異なるという
   前提(リーダー6ヶ月・サブリーダー3ヶ月・それ以外1ヶ月)のもと、
   「いつ・どの役職が抜けると危険か」を判定する。

前提・簡略化(すべて明示):
  - 早番Aは1チームあたり月6回とみなす(31日÷5パターン≒6.2回の近似)。
  - 進捗は各設備の遷移条件のうち「見学/補助/単独対応/教育担当補助」という
    汎用カウントのみを見る(停電試験・法定点検などのイベント回数要件は
    小さな数のため達成可能とみなし、対象外とする)。
  - 資格取得・バックアップ可否は本シミュレーションでは変化しないものとする
    (資格取得は別途の取り組みが必要という前提)。
  - 1人の教育担当が同時に指導できる人数に上限は設けない(要望に基づく仮定)。
"""

from __future__ import annotations

import copy
from typing import Dict, List, Optional

from members import Member, load_members, EDUCATION_STAGES
from education import load_roadmap
from constraints import load_constraints
from health_score import (
    calc_education_achievement_rate,
    calc_key_person_dependency_score,
    calc_qualification_fulfillment_rate,
    calc_backup_coverage_rate,
    calc_change_resilience_score,
)

EARLY_A_DAYS_PER_MONTH = 6  # 31日 ÷ 5パターン ≒ 6.2回 の近似(前提として明示)

# 遷移index(0:見学→補助, 1:補助→単独, 2:単独→教育担当補助, 3:教育担当補助→教育担当)
# それぞれの「進捗の主要カウント」のキー名。停電試験等の副条件は簡略化のため対象外。
GATING_KEY_BY_TRANSITION_INDEX = ["見学", "補助", "単独対応", "教育担当補助"]

ROLE_SUCCESSION_LEAD_MONTHS = {
    "リーダー": 6,
    "サブリーダー": 3,
    "中堅": 1,
    "一般": 1,
    "新人": 1,
}


def _stage_index(stage: str) -> int:
    return EDUCATION_STAGES.index(stage)


def _team_instructor_map(members: List[Member], equipment_list: List[str]) -> Dict[str, Dict[str, bool]]:
    """チームごと・設備ごとに『教育担当が1人でもいるか』を判定する。"""
    teams: Dict[str, List[Member]] = {}
    for m in members:
        teams.setdefault(m.team, []).append(m)
    result = {}
    for team, team_members in teams.items():
        result[team] = {
            eq: any(m.equipment_skills.get(eq) == "教育担当" for m in team_members)
            for eq in equipment_list
        }
    return result


def simulate_future(members: List[Member], roadmap: dict, num_months: int) -> List[dict]:
    """教育担当同乗を前提に、num_months分の月次シミュレーションを行う。

    戻り値: 各月末時点でのスナップショット(健全度内訳+その月の昇格イベント)のリスト。
    月0 は現状(シミュレーション前)を表す。
    """
    equipment_list = list(roadmap.keys())
    sim_members = copy.deepcopy(members)

    # 各(メンバーID, 設備)の『次の遷移に向けた累積カウント』。
    # 既存のexperience_countsのうち、現在の遷移条件の主要キーの値を初期値として引き継ぐ。
    progress_counter: Dict[tuple, int] = {}
    for m in sim_members:
        for eq, stage in m.equipment_skills.items():
            idx = _stage_index(stage)
            if idx >= len(GATING_KEY_BY_TRANSITION_INDEX):
                continue
            key = GATING_KEY_BY_TRANSITION_INDEX[idx]
            progress_counter[(m.member_id, eq)] = m.experience_counts.get(eq, {}).get(key, 0)

    def snapshot(month: int, events: List[dict]) -> dict:
        constraints = load_constraints()
        education = calc_education_achievement_rate(sim_members)
        dependency = calc_key_person_dependency_score(sim_members, roadmap)
        qualification = calc_qualification_fulfillment_rate(sim_members, constraints)
        backup = calc_backup_coverage_rate(sim_members)
        resilience = calc_change_resilience_score(sim_members)
        components = {
            "教育達成率": education,
            "属人化耐性": dependency["overall"],
            "資格充足率": qualification["rate"],
            "バックアップ率": backup["rate"],
            "変更耐性": resilience["overall"],
        }
        overall = round(sum(components.values()) / len(components), 1)
        return {"month": month, "overall_score": overall, "components": components, "events": events}

    snapshots = [snapshot(0, [])]

    for month in range(1, num_months + 1):
        instructor_map = _team_instructor_map(sim_members, equipment_list)
        events = []
        for m in sim_members:
            for eq in equipment_list:
                stage = m.equipment_skills.get(eq)
                if stage is None or stage == "教育担当":
                    continue
                if not instructor_map.get(m.team, {}).get(eq, False):
                    continue  # 教育担当が同乗していないので進まない(頭打ち)
                idx = _stage_index(stage)
                required = roadmap[eq]["transitions"][idx]["required_counts"][GATING_KEY_BY_TRANSITION_INDEX[idx]]
                key = (m.member_id, eq)
                progress_counter[key] = progress_counter.get(key, 0) + EARLY_A_DAYS_PER_MONTH
                if progress_counter[key] >= required:
                    next_stage = roadmap[eq]["transitions"][idx]["to"]
                    m.equipment_skills[eq] = next_stage
                    progress_counter[key] = 0
                    events.append({"member": m.name, "equipment": eq, "new_stage": next_stage, "month": month})
        snapshots.append(snapshot(month, events))

    return snapshots


def instructor_gap_report(members: List[Member], roadmap: dict) -> dict:
    """教育担当が不在のため頭打ちになっている(チーム, 設備)の一覧と、必要な増員数。"""
    equipment_list = list(roadmap.keys())
    instructor_map = _team_instructor_map(members, equipment_list)
    gaps = []
    for team, eq_map in sorted(instructor_map.items()):
        for eq, has_instructor in eq_map.items():
            if not has_instructor:
                gaps.append({"team": team, "equipment": eq})
    return {"gaps": gaps, "gap_count": len(gaps)}


def find_ceiling(members: List[Member], roadmap: dict, horizon_months: int = 36) -> dict:
    """十分長い期間シミュレーションし、教育達成率・総合スコアが頭打ちになる値(理論上限)を求める。"""
    snapshots = simulate_future(members, roadmap, horizon_months)
    final = snapshots[-1]
    # 直近6ヶ月でスコアが変化していなければ「頭打ちに到達した」とみなす
    plateaued = True
    if len(snapshots) > 6:
        recent = [s["overall_score"] for s in snapshots[-6:]]
        plateaued = max(recent) - min(recent) < 0.05
    return {
        "ceiling_overall_score": final["overall_score"],
        "ceiling_education_rate": final["components"]["教育達成率"],
        "plateaued_within_horizon": plateaued,
        "horizon_months": horizon_months,
    }


def what_if_add_instructors(members: List[Member], roadmap: dict, promotions: List[tuple], horizon_months: int = 36) -> dict:
    """指定した(メンバーID, 設備)を即座に『教育担当』に昇格させた場合の理論上限の変化を見る。

    promotions: [(member_id, equipment), ...]
    """
    before = find_ceiling(members, roadmap, horizon_months)

    promoted_members = copy.deepcopy(members)
    by_id = {m.member_id: m for m in promoted_members}
    for member_id, equipment in promotions:
        if member_id in by_id:
            by_id[member_id].equipment_skills[equipment] = "教育担当"

    after = find_ceiling(promoted_members, roadmap, horizon_months)
    return {
        "promotions": promotions,
        "before_ceiling_overall": before["ceiling_overall_score"],
        "after_ceiling_overall": after["ceiling_overall_score"],
        "before_ceiling_education_rate": before["ceiling_education_rate"],
        "after_ceiling_education_rate": after["ceiling_education_rate"],
    }


def distinct_promotion_need(members: List[Member], gaps: List[dict]) -> dict:
    """頭打ち解消に必要な『組み合わせの数』と『実際に昇格させるべき人数』を分けて算出する。

    1人が同じチーム内の複数設備をまとめて担当できるため、
    (チーム×設備)の不足件数と、実際に必要な人数は一致しない。
    """
    suggestions = suggest_instructor_candidates(members, gaps)
    by_person: Dict[str, List[str]] = {}
    for s in suggestions:
        by_person.setdefault(s["candidate"], []).append(f"{s['team']}/{s['equipment']}")
    return {
        "gap_count": len(gaps),
        "distinct_people_needed": len(by_person),
        "breakdown": [{"candidate": name, "covers": items} for name, items in by_person.items()],
    }


def suggest_instructor_candidates(members: List[Member], gaps: List[dict]) -> List[dict]:
    """教育担当が不在の(チーム, 設備)ごとに、最も昇格に近い候補(現在の到達段階が一番高い人)を提案する。"""
    suggestions = []
    for gap in gaps:
        team_members = [m for m in members if m.team == gap["team"]]
        candidates = sorted(
            team_members,
            key=lambda m: _stage_index(m.equipment_skills.get(gap["equipment"], "見学")),
            reverse=True,
        )
        if candidates:
            top = candidates[0]
            suggestions.append(
                {
                    "team": gap["team"],
                    "equipment": gap["equipment"],
                    "candidate": top.name,
                    "current_stage": top.equipment_skills.get(gap["equipment"]),
                }
            )
    return suggestions


def find_instructor_teams(members: List[Member], equipment: str) -> List[dict]:
    """指定設備について、すでに教育担当がいるチームと担当者名を返す。"""
    result = []
    for m in members:
        if m.equipment_skills.get(equipment) == "教育担当":
            result.append({"team": m.team, "name": m.name})
    return result


def suggest_team_reassignment(members: List[Member], gap: dict) -> List[dict]:
    """頭打ち箇所について、他チームの教育担当を恒久的に異動させる案の候補を探す。

    異動元チームがその設備の対応力を失わずに済むか(他に単独対応以上の人が残るか)を
    合わせて判定する。将来的な『チーム編成の見直し』提案の土台となる関数。
    """
    team, equipment = gap["team"], gap["equipment"]
    candidates = []
    for m in members:
        if m.equipment_skills.get(equipment) == "教育担当" and m.team != team:
            origin_team_members = [x for x in members if x.team == m.team and x.member_id != m.member_id]
            origin_still_covered = any(
                _stage_index(x.equipment_skills.get(equipment, "見学")) >= _stage_index("単独")
                for x in origin_team_members
            )
            candidates.append(
                {"name": m.name, "from_team": m.team, "origin_team_still_covered": origin_still_covered}
            )
    return candidates


def gap_resolution_options(members: List[Member], gap: dict) -> dict:
    """教育担当が不在の(チーム, 設備)について、対応案を提示する。

    原資料セクション13(V2構想: 複数案を提示し管理者が選ぶ)の考え方を、
    『教育担当不在』という具体的な状況に当てはめたもの。
    """
    team, equipment = gap["team"], gap["equipment"]
    team_members = [m for m in members if m.team == team]
    local_candidates = sorted(
        team_members,
        key=lambda m: _stage_index(m.equipment_skills.get(equipment, "見学")),
        reverse=True,
    )
    other_team_instructors = [
        i for i in find_instructor_teams(members, equipment) if i["team"] != team
    ]

    option_a = None
    if local_candidates:
        top = local_candidates[0]
        option_a = {
            "案": "内部昇格",
            "内容": f"{top.name}(現在 {top.equipment_skills.get(equipment)})を教育担当に育てる",
            "メリット": "チーム内で完結し、長期的に最も安定する",
            "留意点": "昇格まで時間がかかる(教育達成率がすぐには上がらない)",
        }

    option_b = None
    if other_team_instructors:
        names = "、".join(f"{i['name']}(チーム{i['team']})" for i in other_team_instructors)
        option_b = {
            "案": "他チームからの応援",
            "内容": f"{names} を臨時にチーム{team}の早番Aへ応援に回す",
            "メリット": "即効性がある(来月から教育を開始できる)",
            "留意点": "応援元チームの負荷が増える。頻度・期間を決めておく必要あり",
        }

    option_c = None
    if local_candidates:
        top = local_candidates[0]
        option_c = {
            "案": "常駐化+ローテーション制",
            "内容": (
                f"{top.name}など最もスキルの高いメンバーを一時的に教育専任(常日勤)にする。"
                "ただし固定化すると不公平感が出るため、対象者を数ヶ月ごとに交代する"
                "ローテーション制にする"
            ),
            "メリット": "即効性があり、特定の1人に負担が偏らない",
            "留意点": "交代の仕組み・引き継ぎのルール作りが必要",
        }

    option_d = None
    reassignment_candidates = suggest_team_reassignment(members, gap)
    if reassignment_candidates:
        safe = [c for c in reassignment_candidates if c["origin_team_still_covered"]]
        if safe:
            c = safe[0]
            option_d = {
                "案": "チーム編成の見直し(異動)",
                "内容": f"{c['name']}(チーム{c['from_team']})を チーム{team} へ恒久的に異動する。異動元(チーム{c['from_team']})には他に単独対応以上の人が残るため、教育体制は維持される",
                "メリット": "応援と違い恒久的な解決になり、翌月以降ずっと教育が進む",
                "留意点": "異動対象者本人の負担・生活環境の変化への配慮が必要",
            }
        else:
            c = reassignment_candidates[0]
            option_d = {
                "案": "チーム編成の見直し(異動)",
                "内容": f"{c['name']}(チーム{c['from_team']})を チーム{team} へ異動する案もあるが、異動元(チーム{c['from_team']})の教育体制が手薄になるため単独では非推奨",
                "メリット": "恒久的な解決になりうる",
                "留意点": "異動元チームに新たな頭打ちが生まれるため、内部昇格と組み合わせて検討する必要がある",
            }

    return {
        "team": team,
        "equipment": equipment,
        "options": [o for o in (option_a, option_b, option_c, option_d) if o],
    }


def succession_risk(members: List[Member], role: str, team: str, months_until_departure: int) -> dict:
    """『このチームのこの役職が、あと何ヶ月後かに抜ける』という想定でのリスク判定。"""
    lead_time = ROLE_SUCCESSION_LEAD_MONTHS.get(role, 1)
    at_risk = months_until_departure < lead_time

    candidate_tag = {"リーダー": "リーダー候補", "サブリーダー": "サブリーダー候補"}.get(role)
    candidates = []
    if candidate_tag:
        candidates = [
            {"name": m.name, "team": m.team, "role": m.role}
            for m in members
            if m.future_candidate == candidate_tag
        ]

    return {
        "role": role,
        "team": team,
        "months_until_departure": months_until_departure,
        "required_lead_time_months": lead_time,
        "at_risk": at_risk,
        "candidates_org_wide": candidates,
        "candidates_in_team": [c for c in candidates if c["team"] == team],
    }


if __name__ == "__main__":
    members = load_members()
    roadmap = load_roadmap()

    print("=== 3・6・12ヶ月後の健全度予測(現ペース: 教育担当同乗の早番Aのみ+1) ===")
    snapshots = simulate_future(members, roadmap, 12)
    for m in (0, 3, 6, 12):
        s = snapshots[m]
        print(f"  {m}ヶ月後: 総合{s['overall_score']} (教育達成率 {s['components']['教育達成率']})")

    print()
    print("=== 教育担当が不在で頭打ちになっている箇所 ===")
    gap_report = instructor_gap_report(members, roadmap)
    for g in gap_report["gaps"]:
        print(f"  チーム{g['team']} / {g['equipment']}: 教育担当が不在")
    print(f"  頭打ち箇所: {gap_report['gap_count']}件(チーム×設備の組み合わせ数)")
    need = distinct_promotion_need(members, gap_report["gaps"])
    print(f"  ただし1人が同じチーム内の複数設備を兼任できるため、実際に昇格が必要な人数は{need['distinct_people_needed']}人")
    for b in need["breakdown"]:
        print(f"    {b['candidate']}: {len(b['covers'])}件担当 → {', '.join(b['covers'])}")

    print()
    print("=== 現状の体制での理論上限(36ヶ月シミュレーション) ===")
    ceiling = find_ceiling(members, roadmap, 36)
    print(f"  総合スコアの上限: {ceiling['ceiling_overall_score']} (教育達成率の上限: {ceiling['ceiling_education_rate']})")
    print(f"  36ヶ月以内に頭打ちに到達: {'はい' if ceiling['plateaued_within_horizon'] else 'いいえ(まだ伸びる余地あり)'}")

    print()
    print("=== 増員(教育担当への昇格)の候補と効果 ===")
    suggestions = suggest_instructor_candidates(members, gap_report["gaps"])
    for s in suggestions[:5]:
        print(f"  チーム{s['team']} / {s['equipment']}: {s['candidate']}(現在 {s['current_stage']})を教育担当にすると解消")
    top_promotions = [(next(m.member_id for m in members if m.name == s["candidate"]), s["equipment"]) for s in suggestions]
    what_if = what_if_add_instructors(members, roadmap, top_promotions, 36)
    print(
        f"  全候補({len(top_promotions)}人)を教育担当に昇格させた場合: "
        f"総合スコア上限 {what_if['before_ceiling_overall']} → {what_if['after_ceiling_overall']}"
        f" (教育達成率上限 {what_if['before_ceiling_education_rate']} → {what_if['after_ceiling_education_rate']})"
    )

    print()
    print("=== 頭打ち箇所への対応案(例: チームDの受変電設備) ===")
    sample_gap = {"team": "D", "equipment": "受変電設備"}
    resolution = gap_resolution_options(members, sample_gap)
    for opt in resolution["options"]:
        print(f"  [{opt['案']}] {opt['内容']}")
        print(f"    メリット: {opt['メリット']} / 留意点: {opt['留意点']}")

    print()
    print("=== 退職シミュレーション(役職別リードタイム: リーダー6ヶ月/サブリーダー3ヶ月/それ以外1ヶ月) ===")
    scenario = succession_risk(members, role="リーダー", team="C", months_until_departure=4)
    print(f"  シナリオ: チームCのリーダーが4ヶ月後に退職予定")
    print(f"    必要リードタイム: {scenario['required_lead_time_months']}ヶ月 → {'危険(準備期間不足)' if scenario['at_risk'] else '対応可能な見込み'}")
    print(f"    リーダー候補(全社): {[c['name']+'('+c['team']+')' for c in scenario['candidates_org_wide']]}")
    print(f"    チームC内の候補: {[c['name'] for c in scenario['candidates_in_team']] or 'なし(要注意)'}")

"""
デモデータ生成: experience_counts のバックフィル

members.json の equipment_skills(現在の到達段階)と矛盾しないように、
education_roadmap.json の required_counts を満たす実績回数を自動生成する。

ルール:
- 現在の到達段階より手前の遷移(transition)は、必要回数ちょうどを満たす実績を入れる。
- 中堅・サブリーダーは「次の段階に向けて育成中」の設定なので、
  次の遷移の実績回数を必要数の6割(切り捨て、最低0)だけ入れておく。
  (=まだ昇格条件は満たしていないが、進行中であることをSTEP2のレポートで確認できるようにする)
- リーダー・新人・一般は次段階への進行中データは入れない(0のまま)。

このスクリプトは実行するたびに data/members.json を上書きするため、
手で個別調整した実績値がある場合は上書きされる点に注意。
"""

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
MEMBERS_PATH = BASE / "data" / "members.json"
ROADMAP_PATH = BASE / "data" / "education_roadmap.json"

PARTIAL_PROGRESS_ROLES = {"中堅", "サブリーダー"}
PARTIAL_RATIO = 0.6


def main():
    with open(MEMBERS_PATH, "r", encoding="utf-8") as f:
        members = json.load(f)
    with open(ROADMAP_PATH, "r", encoding="utf-8") as f:
        roadmap = json.load(f)

    for member in members:
        experience_counts = {}
        for equipment, current_stage in member.get("equipment_skills", {}).items():
            eq_roadmap = roadmap.get(equipment)
            if eq_roadmap is None:
                continue
            stage_order = eq_roadmap["stage_order"]
            if current_stage not in stage_order:
                continue
            stage_index = stage_order.index(current_stage)
            counts = {}

            # 現在の段階に到達済みの遷移は、必要回数ちょうどを満たす
            for i in range(stage_index):
                transition = eq_roadmap["transitions"][i]
                for count_type, required in transition["required_counts"].items():
                    counts[count_type] = required

            # 次の段階に向けて進行中のデータ(中堅・サブリーダーのみ)
            if stage_index < len(stage_order) - 1 and member["role"] in PARTIAL_PROGRESS_ROLES:
                next_transition = eq_roadmap["transitions"][stage_index]
                for count_type, required in next_transition["required_counts"].items():
                    counts[count_type] = int(required * PARTIAL_RATIO)

            experience_counts[equipment] = counts

        member["experience_counts"] = experience_counts

    with open(MEMBERS_PATH, "w", encoding="utf-8") as f:
        json.dump(members, f, ensure_ascii=False, indent=2)

    print(f"experience_counts を {len(members)} 名分バックフィルしました: {MEMBERS_PATH}")


if __name__ == "__main__":
    main()

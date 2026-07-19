"""
STEP1: メンバー15名の属性設計

このモジュールは「誰をどこへ配置するか」ではなく、
将来のシフト改善判断(教育・属人化解消・シフト健全度計算)に必要な
メンバー属性を保持するためのデータモデルを定義する。

設計原則:
- 個人を評価するためのデータではなく、組織の健全性を可視化するための土台。
- Excelに元々ある情報(氏名・経験月数など)は極力そのまま扱えるようにする。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "members.json"

# 役職の並び(育成の階段を表す。シフト健全度計算などで序列として使う)
ROLE_ORDER = ["新人", "一般", "中堅", "サブリーダー", "リーダー"]

# 教育ロードマップの段階(セクション11の思想と対応)
EDUCATION_STAGES = ["見学", "補助", "単独", "教育担当補助", "教育担当"]


@dataclass
class Member:
    member_id: str                     # 例: "M01"
    name: str                          # 表示名(デモ用の仮名)
    team: str                          # 所属チーム A〜E
    role: str                          # ROLE_ORDER のいずれか
    experience_months: int             # 経験月数

    certifications: List[str] = field(default_factory=list)
    # 設備別スキル: 設備名 -> EDUCATION_STAGES のいずれか
    equipment_skills: Dict[str, str] = field(default_factory=dict)

    event_experience_count: int = 0        # イベント対応(停電試験・危険物搬入等)の経験回数
    night_shift_experience_count: int = 0  # 夜勤経験回数
    teaching_experience_count: int = 0     # 教育担当としての経験回数

    backup_capable_tasks: List[str] = field(default_factory=list)  # バックアップ可能業務

    development_priority: str = "中"       # 育成優先度: 高 / 中 / 低
    future_candidate: Optional[str] = None  # 例: "リーダー候補", "サブリーダー候補", None

    def role_rank(self) -> int:
        """役職の階段上の位置(0=新人 〜 4=リーダー)。健全度計算等で利用予定。"""
        return ROLE_ORDER.index(self.role)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Member":
        return Member(**d)


def load_members(path: Path = DATA_PATH) -> List[Member]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [Member.from_dict(m) for m in raw]


def save_members(members: List[Member], path: Path = DATA_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([m.to_dict() for m in members], f, ensure_ascii=False, indent=2)


def summarize(members: List[Member]) -> dict:
    """簡易サマリ。STEP4(シフト健全度)の元になる集計の土台として、
    まずは人数構成や教育段階の分布だけを見えるようにする。"""
    summary = {
        "total": len(members),
        "by_role": {},
        "by_team": {},
        "future_candidates": [],
    }
    for m in members:
        summary["by_role"][m.role] = summary["by_role"].get(m.role, 0) + 1
        summary["by_team"][m.team] = summary["by_team"].get(m.team, 0) + 1
        if m.future_candidate:
            summary["future_candidates"].append((m.name, m.future_candidate))
    return summary


if __name__ == "__main__":
    members = load_members()
    summary = summarize(members)

    print(f"総メンバー数: {summary['total']}")
    print("役職別内訳:", summary["by_role"])
    print("チーム別内訳:", summary["by_team"])
    print("将来候補:")
    for name, candidate in summary["future_candidates"]:
        print(f"  - {name}: {candidate}")

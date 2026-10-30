"""Независимая сверка показателей с исходной выгрузкой."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from soc.data import load, targets

path = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else Path("iavd_incidents_raw_target.parquet")
)
d, snapshot = load(path)
a = d[d.active]
raw = pd.read_parquet(
    path,
    columns=[
        "EntityId",
        "Фаза реагирования",
        "Критичность",
        "SLA просрочен (взятие в работу)",
    ],
)
mask = (
    ~raw["Фаза реагирования"]
    .str.split("~~||~~", regex=False)
    .map(lambda x: "Закрыт" in x if isinstance(x, list) else False)
)
assert len(a) == int(mask.sum())
assert int(a.overdue.sum()) == int(
    raw.loc[mask, "SLA просрочен (взятие в работу)"].eq("True").sum()
)
result = {
    "rows": len(d),
    "snapshot": str(snapshot),
    "period_start": str(d.created.min()),
    "period_end": str(d.created.max()),
    "open": len(a),
    "urgent_open": int(a.severity.isin(["Критическая", "Высокая"]).sum()),
    "older_3_days": int(a.age.gt(3).sum()),
    "overdue_open": int(a.overdue.sum()),
    "unknown_sla_open": int(a.overdue.isna().sum()),
    "open_types": a.kind.value_counts().head(6).to_dict(),
    "open_ages": a.age_group.value_counts(sort=False).to_dict(),
    "verdicts": d.verdict.value_counts(dropna=False).to_dict(),
    "targets": targets(d).to_dict(),
}
Path("output").mkdir(exist_ok=True)
Path("output/audit.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(result, ensure_ascii=False, indent=2))

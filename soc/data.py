from pathlib import Path
import pandas as pd

FIELDS = {
    "EntityId": "id",
    "Создан": "created",
    "Дата закрытия (факт)": "closed",
    "Дата взятия в работу": "assigned",
    "Критичность": "severity",
    "Тип инцидента": "kind",
    "Фаза реагирования": "phase",
    "Наименование": "rule",
    "Hostname Цели": "target",
    "SLA просрочен (взятие в работу)": "sla",
    "Вердикт": "verdict",
}
LEVELS = ["Критическая", "Высокая", "Средняя", "Низкая", "Не указано"]
AGES = ["До 1 часа", "1–4 часа", "4–24 часа", "1–3 суток", "Более 3 суток"]


def tokens(value):
    return (
        []
        if pd.isna(value)
        else [x.strip() for x in str(value).split("~~||~~") if x.strip()]
    )


def workflow(value):
    parts = tokens(value)
    for phase in ["Закрыт", "Ожидание", "В работе", "Новый", "Устранение"]:
        if phase in parts:
            return phase
    return "Не указано"


def prepare(frame):
    missing = set(FIELDS) - set(frame)
    if missing:
        raise ValueError("В выгрузке отсутствуют поля: " + ", ".join(sorted(missing)))
    d = frame[list(FIELDS)].rename(columns=FIELDS).copy()
    if d.id.isna().any() or d.id.duplicated().any():
        raise ValueError("EntityId должен быть заполненным и уникальным.")
    for col in ["created", "closed", "assigned"]:
        d[col] = pd.to_datetime(d[col], utc=True, errors="coerce").dt.tz_convert(
            "Europe/Moscow"
        )
    if d.created.isna().any():
        raise ValueError("Есть карточки без корректного времени создания.")
    snapshot = d[["created", "closed", "assigned"]].max().max()
    for col in ["severity", "kind", "rule"]:
        d[col] = d[col].fillna("Не указано")
    d["severity"] = d.severity.replace({"Отсутствует": "Не указано"})
    d["status"] = d.phase.map(workflow)
    d["active"] = d.status.ne("Закрыт")
    d["age"] = (snapshot - d.created).dt.total_seconds() / 86400
    d["age_group"] = pd.cut(
        d.age * 24, [0, 1, 4, 24, 72, float("inf")], labels=AGES, right=False
    )
    d["overdue"] = (
        d.sla.astype("string")
        .str.lower()
        .map({"true": True, "false": False})
        .astype("boolean")
    )
    d["priority"] = d.severity.map({x: i for i, x in enumerate(LEVELS)}).fillna(
        len(LEVELS)
    )
    return d, snapshot


def load(path):
    if not Path(path).is_file():
        raise FileNotFoundError(
            f"Датасет не найден: {path}. Укажите файл через --data."
        )
    return prepare(pd.read_parquet(path, columns=list(FIELDS)))


def date_bounds(dates):
    """Московские даты включительно; stop — начало следующего дня."""
    if len(dates) != 2 or any(x is None or pd.isna(x) for x in dates):
        raise ValueError("Укажите начало и конец периода.")
    start, end = (pd.Timestamp(x) for x in dates)
    if pd.isna(start) or pd.isna(end):
        raise ValueError("Укажите корректные даты.")
    start = pd.Timestamp(start.date(), tz="Europe/Moscow")
    end = pd.Timestamp(end.date(), tz="Europe/Moscow")
    if start > end:
        raise ValueError("Начало периода должно быть не позже окончания.")
    return start, end, end + pd.Timedelta(days=1)


def created_between(d, dates):
    start, _, stop = date_bounds(dates)
    return d.loc[d.created.ge(start) & d.created.lt(stop)]


def select(
    d,
    status="Открытые",
    severities=(),
    kinds=(),
    age="Все",
    target="",
    include_status=True,
):
    if include_status and status != "Все":
        d = d[d.active] if status == "Открытые" else d[d.status.eq(status)]
    if severities:
        d = d[d.severity.isin(severities)]
    if kinds:
        d = d[d.kind.isin(kinds)]
    if age != "Все":
        d = d[d.age_group.eq(age)]
    if target:
        d = d[d.target.map(lambda x: target in tokens(x))]
    return d


def targets(d):
    rows = d.loc[d.active, ["id", "target"]].copy()
    rows["target"] = rows.target.map(tokens)
    rows = rows.explode("target").dropna().drop_duplicates(["id", "target"])
    counts = rows.target.value_counts()
    return counts[counts.gt(1)].head(6)


def queue(d, query=""):
    if query.strip():
        q = query.strip()
        d = d[d.id.astype(str).eq(q)]
    d = d.sort_values(["priority", "created"], ascending=[True, True])
    result = pd.DataFrame(
        {
            "Номер": d.id,
            "Тип": d.kind,
            "Уровень": d.severity,
            "Суток": d.age.where(d.active).round(1),
            "Создан": d.created.dt.tz_localize(None),
            "SLA": d.overdue.map({True: "Просрочен", False: "В срок"}).fillna(
                "Неизвестно"
            ),
        }
    )
    return result.reset_index(drop=True)

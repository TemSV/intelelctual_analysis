import argparse
import sys
from pathlib import Path
import html
import pandas as pd
from taipy.gui import Gui, notify
import taipy.gui.builder as tgb
from soc.data import (
    load,
    select,
    queue,
    targets,
    AGES,
    LEVELS,
    date_bounds,
    created_between,
)
from soc.charts import (
    stacked,
    arrival_chart,
    arrival_step,
    arrival_profile,
    rule_chart,
    verdict_chart,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

parser = argparse.ArgumentParser(description="Дашборд аналитика SOC")
parser.add_argument(
    "--data", default=str(Path(__file__).parent / "iavd_incidents_raw_target.parquet")
)
parser.add_argument("--port", type=int, default=5011)
args = parser.parse_args()
cards, snapshot = load(args.data)
status = "Открытые"
severities = []
kinds = []
age = "Все"
target = ""
search = ""
first_date = cards.created.min().date()
last_date = cards.created.max().date()
default_range = [max(first_date, (snapshot - pd.Timedelta(days=29)).date()), last_date]
date_range = default_range.copy()
applied_range = default_range.copy()
view = "Разбор очереди"
show_queue = True
show_composition = False
show_queue_filters = True
show_context = False
analysis_view = "Нагрузка"
show_load = True
show_rules = False
show_verdicts = False
status_options = [
    "Открытые",
    "Все",
    "Закрыт",
    "В работе",
    "Ожидание",
    "Новый",
    "Устранение",
    "Не указано",
]
severity_options = [x for x in LEVELS if x in set(cards.severity)]
kind_options = sorted(cards.kind.unique().tolist())
age_options = ["Все"] + AGES
target_options = [("", "Все узлы")] + [
    (x, x.replace("\\", " / ")) for x in targets(cards).index
]
detail_open = False
detail_text = ""
stamp = snapshot.strftime("%d.%m.%Y, %H:%M MSK")
plot_config = {"displayModeBar": False, "responsive": True}


def values(status, severities, kinds, age, target, search, dates):
    selected = select(cards, status, severities, kinds, age, target)
    flow = select(cards, status, severities, kinds, "Все", target, include_status=False)
    active = selected[selected.active]
    _, end, _ = date_bounds(dates)
    period_cards = created_between(flow, dates)
    profile = arrival_profile(flow, dates, snapshot)
    complete_days = int(profile.days.sum())
    mean = float(profile.total.sum() / complete_days) if complete_days else None
    partial = period_cards[period_cards.created.ge(snapshot.normalize())]
    partial_count = f"{len(partial):,}".replace(",", " ")
    context_note = (
        f"{snapshot:%d.%m.%Y}: неполный день — {partial_count} карточек."
        if end.date() == snapshot.date()
        else ""
    )
    table = queue(selected, search)
    missing_sla = int(selected.overdue.isna().sum())
    card_word = (
        "карточки" if missing_sla % 10 == 1 and missing_sla % 100 != 11 else "карточек"
    )
    summary = f"Статус: {status}"
    for title, items in [("Критичность", severities), ("Тип", kinds)]:
        if items:
            summary += " · " + title + ": " + ", ".join(items)
    if age != "Все":
        summary += " · Возраст: " + age
    if target:
        summary += " · Выбран узел"
    return dict(
        total=f"{len(selected):,}".replace(",", " "),
        total_label=(
            "Открытые инциденты" if status == "Открытые" else "Выбранные карточки"
        ),
        urgent=str(selected.severity.isin(["Критическая", "Высокая"]).sum()),
        old=str(active.age.gt(3).sum()),
        sla=str(selected.overdue.fillna(False).sum()),
        queue_hint=(
            "Нет карточек. Измените фильтры или очистите поиск." if table.empty else ""
        ),
        unknown=(
            f"У {missing_sla} {card_word} нет данных о сроке" if missing_sla else ""
        ),
        summary=summary,
        queue_data=table,
        queue_note=f"Карточек в таблице: {len(table):,}".replace(",", " "),
        rules_fig=rule_chart(period_cards),
        verdicts_fig=verdict_chart(period_cards),
        age_fig=stacked(active, "age_group", AGES),
        types_fig=stacked(selected, "kind"),
        flow_fig=arrival_chart(flow, dates, snapshot),
        period_total=f"{len(period_cards):,}".replace(",", " "),
        period_priority=f'{period_cards.severity.isin(["Критическая","Высокая"]).sum():,}'.replace(
            ",", " "
        ),
        period_mean=f"{mean:,.1f}".replace(",", " ") if mean is not None else "—",
        flow_title=f"Нагрузка · {arrival_step(dates).lower()}",
        context_note=context_note,
    )


globals().update(values(status, severities, kinds, age, target, search, applied_range))


def refresh(state):
    result = values(
        state.status,
        state.severities,
        state.kinds,
        state.age,
        state.target,
        state.search,
        state.applied_range,
    )
    with state:
        for key, value in result.items():
            setattr(state, key, value)


def on_change(state, name, value):
    if name == "analysis_view":
        with state:
            state.show_load = value == "Нагрузка"
            state.show_rules = value == "Правила"
            state.show_verdicts = value == "Вердикты"
        return
    if name == "view":
        with state:
            state.show_queue = value == "Разбор очереди"
            state.show_composition = value == "Состав очереди"
            state.show_queue_filters = value in {"Разбор очереди", "Состав очереди"}
            state.show_context = value == "Анализ потока"
        return
    if name == "search":
        table = queue(
            select(
                cards,
                state.status,
                state.severities,
                state.kinds,
                state.age,
                state.target,
            ),
            value,
        )
        with state:
            state.queue_data = table
            state.queue_note = f"Карточек в таблице: {len(table):,}".replace(",", " ")
            state.queue_hint = (
                "Нет карточек. Измените фильтры или очистите поиск."
                if table.empty
                else ""
            )
        return
    if name in {"status", "severities", "kinds", "age", "target"}:
        refresh(state)


def on_dates_change(state, name, value):
    if not value or len(value) != 2 or any(x is None or pd.isna(x) for x in value):
        return
    try:
        start, end, _ = date_bounds(value)
        if start.date() < first_date or end.date() > last_date:
            raise ValueError(
                f"Доступный период: {first_date:%d.%m.%Y} — {last_date:%d.%m.%Y}."
            )
    except (ValueError, TypeError) as exc:
        state.date_range = list(state.applied_range)
        notify(state, "warning", str(exc))
        return
    state.applied_range = [start.date(), end.date()]
    refresh(state)


def full_period(state):
    with state:
        state.date_range = [first_date, last_date]
        state.applied_range = [first_date, last_date]
    refresh(state)


def reset(state):
    with state:
        state.status = "Открытые"
        state.severities = []
        state.kinds = []
        state.age = "Все"
        state.target = ""
        state.search = ""
        state.date_range = default_range.copy()
        state.applied_range = default_range.copy()
    refresh(state)


def open_card(state, var, payload):
    index = payload.get("index")
    if index is None or index not in state.queue_data.index:
        return
    card_id = int(state.queue_data.loc[index, "Номер"])
    row = cards.loc[cards.id.eq(card_id)].iloc[0]
    fields = ["EntityId", "Описание инцидента", "CMDLINE", "processName", "src", "dst"]
    raw = pd.read_parquet(
        args.data, columns=fields, filters=[("EntityId", "=", card_id)]
    ).iloc[0]

    def safe(v):
        return (
            "Не указано" if pd.isna(v) else html.escape(str(v)).replace("~~||~~", "; ")
        )

    entries = [
        ("Критичность", row.severity),
        ("Фаза обработки", row.status),
        ("Создан", row.created.strftime("%d.%m.%Y %H:%M MSK")),
        ("Тип", row.kind),
        ("Правило SIEM", row.rule),
        ("Вердикт в выгрузке", row.verdict),
        ("Целевой узел", row.target),
    ]
    text = f"## Инцидент № {card_id}\n\n"
    text += "".join(f"**{name}:** {safe(value)}\n\n" for name, value in entries)
    text += "### Описание события\n\n" + safe(raw["Описание инцидента"]) + "\n\n"
    text += "### Технический контекст\n\n"
    for name, caption in [
        ("processName", "Процесс"),
        ("CMDLINE", "Командная строка"),
        ("src", "Источник"),
        ("dst", "Назначение"),
    ]:
        if pd.notna(raw[name]):
            text += f"**{caption}:** {safe(raw[name])}\n\n"
    state.detail_text = text
    state.detail_open = True


def close_card(state, *_):
    state.detail_open = False


def on_exception(state, function_name, exception):
    notify(
        state, "error", "Не удалось обновить данные. Подробности в журнале приложения."
    )
    print(f"{function_name}: {exception}", flush=True)


with tgb.Page() as page:
    with tgb.part(class_name="shell"):
        with tgb.layout(columns="3 1", class_name="page-header"):
            with tgb.part():
                tgb.text("Разбор инцидентов", class_name="title")
            with tgb.part(class_name="snapshot"):
                tgb.text("Исторический срез", class_name="muted small")
                tgb.text("{stamp}", class_name="snapshot-value")
        with tgb.layout(columns="230px 1", class_name="workspace"):
            with tgb.part(class_name="filters"):
                tgb.text("Фильтры", class_name="section-title")
                with tgb.part(render="{show_queue_filters}"):
                    tgb.selector(
                        "{status}", lov=status_options, dropdown=True, label="Статус"
                    )
                tgb.selector(
                    "{severities}",
                    lov=severity_options,
                    multiple=True,
                    dropdown=True,
                    label="Критичность",
                )
                tgb.selector(
                    "{kinds}",
                    lov=kind_options,
                    multiple=True,
                    dropdown=True,
                    label="Тип инцидента",
                )
                with tgb.part(render="{show_queue_filters}"):
                    tgb.selector(
                        "{age}", lov=age_options, dropdown=True, label="Возраст"
                    )
                tgb.selector(
                    "{target}",
                    lov=target_options,
                    dropdown=True,
                    label="Повторяющийся узел",
                    value_by_id=True,
                )
                tgb.button("Сбросить фильтры", on_action=reset, class_name="reset")
            with tgb.part(class_name="content"):
                tgb.toggle(
                    "{view}",
                    lov=["Разбор очереди", "Состав очереди", "Анализ потока"],
                    class_name="view-tabs",
                )
                with tgb.part(render="{show_queue_filters}"):
                    with tgb.layout(columns="1 1 1 1", class_name="metrics"):
                        for val, caption in [
                            ("total", "{total_label}"),
                            ("urgent", "Высокая / критическая"),
                            ("old", "Открыты более 3 суток"),
                            ("sla", "Просрочено взятие в работу"),
                        ]:
                            with tgb.part(class_name="metric-block"):
                                tgb.text("{" + val + "}", class_name="metric")
                                tgb.text(caption, class_name="metric-label")
                                if val == "sla":
                                    tgb.text(
                                        "{unknown}", class_name="muted small sla-note"
                                    )
                    tgb.text("{summary}", class_name="selection-summary")
                with tgb.part(render="{show_queue}", class_name="queue-view"):
                    with tgb.layout(columns="1 1", class_name="queue-toolbar"):
                        with tgb.part():
                            tgb.text("Карточки", class_name="section-title")
                            tgb.text("{queue_note}", class_name="muted small")
                        tgb.input("{search}", label="Номер карточки", change_delay=350)
                    tgb.table(
                        "{queue_data}",
                        on_action=open_card,
                        editable=False,
                        on_edit=False,
                        on_add=False,
                        on_delete=False,
                        height="340px",
                        auto_loading=True,
                        date_format="dd.MM.yyyy HH:mm",
                        format__Суток="%.1f",
                        class_name="queue",
                    )
                    tgb.text("{queue_hint}", class_name="muted small table-help")
                with tgb.part(render="{show_composition}"):
                    with tgb.layout(columns="1 1", class_name="chart-row"):
                        with tgb.part():
                            tgb.text(
                                "Возраст открытых карточек", class_name="section-title"
                            )
                            tgb.chart(figure="{age_fig}", plot_config=plot_config)
                        with tgb.part():
                            tgb.text(
                                "Типы инцидентов · топ-6", class_name="section-title"
                            )
                            tgb.chart(figure="{types_fig}", plot_config=plot_config)
                with tgb.part(render="{show_context}", class_name="context-view"):
                    with tgb.layout(columns="3 1", class_name="context-toolbar"):
                        tgb.date_range(
                            "{date_range}",
                            label_start="С",
                            label_end="По",
                            format="dd.MM.yyyy",
                            on_change=on_dates_change,
                            width="100%",
                            class_name="context-dates",
                        )
                        tgb.button(
                            "Весь период",
                            on_action=full_period,
                            class_name="full-period",
                        )
                    with tgb.layout(
                        columns="1 1 1", class_name="metrics context-metrics"
                    ):
                        for val, caption in [
                            ("period_total", "Карточек за период · все статусы"),
                            ("period_priority", "Высокая / критическая за период"),
                            ("period_mean", "В среднем за полный день"),
                        ]:
                            with tgb.part(class_name="metric-block"):
                                tgb.text("{" + val + "}", class_name="metric")
                                tgb.text(caption, class_name="metric-label")
                    tgb.toggle(
                        "{analysis_view}",
                        lov=["Нагрузка", "Правила", "Вердикты"],
                        class_name="view-tabs analysis-tabs",
                    )
                    with tgb.part(render="{show_load}"):
                        tgb.text("{flow_title}", class_name="chart-title")
                        tgb.chart(figure="{flow_fig}", plot_config=plot_config)
                        tgb.text("{context_note}", class_name="muted small")
                    with tgb.part(render="{show_rules}"):
                        tgb.text(
                            "Карточки по правилам SIEM · топ-10",
                            class_name="chart-title",
                        )
                        tgb.chart(figure="{rules_fig}", plot_config=plot_config)
                    with tgb.part(render="{show_verdicts}"):
                        tgb.text("Вердикты", class_name="chart-title")
                        tgb.chart(figure="{verdicts_fig}", plot_config=plot_config)
    with tgb.dialog(
        "{detail_open}",
        title="Карточка инцидента",
        on_action=close_card,
        labels="Закрыть",
        width="850px",
    ):
        tgb.text("{detail_text}", mode="markdown", class_name="details")

if __name__ == "__main__":
    Gui(page, css_file="app.css").run(
        host="127.0.0.1",
        port=args.port,
        title="Инциденты SOC",
        dark_mode=False,
        use_reloader=False,
        run_browser=False,
        watermark="",
        margin="0px",
        stylekit=False,
    )

import textwrap
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from .data import LEVELS, date_bounds, created_between

COLORS = {
    "Критическая": "#b7353f",
    "Высокая": "#465868",
    "Средняя": "#8997a3",
    "Низкая": "#c5cdd3",
    "Не указано": "#e2e6e9",
}


def base():
    f = go.Figure()
    f.update_layout(
        template="plotly_white",
        height=330,
        margin=dict(l=4, r=40, t=15, b=65),
        font=dict(family="Segoe UI, Arial, sans-serif", size=12, color="#243442"),
        paper_bgcolor="white",
        plot_bgcolor="white",
        showlegend=False,
        xaxis=dict(showgrid=False, zeroline=False, rangemode="tozero"),
        yaxis=dict(showgrid=False, zeroline=False),
        bargap=0.4,
        legend=dict(
            orientation="h", y=-0.2, x=0, traceorder="reversed", font=dict(size=11)
        ),
    )
    return f


def label(value):
    return "<br>".join(textwrap.wrap(str(value).replace("~~||~~", " / "), 32))


def empty(message="Нет данных для выбранных условий"):
    f = base()
    f.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(color="#7b8791"),
    )
    f.update_xaxes(visible=False)
    f.update_yaxes(visible=False)
    return f


def stacked(d, column, order=None):
    if d.empty:
        return empty()
    counts = pd.crosstab(d[column], d.severity)
    order = (
        order if order is not None else counts.sum(axis=1).nlargest(6).index.tolist()
    )
    counts = counts.reindex(order, fill_value=0)
    f = base()
    for level in reversed(LEVELS):
        if level in counts:
            f.add_bar(
                y=[label(x) for x in order],
                x=counts[level],
                orientation="h",
                name=level,
                marker_color=COLORS[level],
                hovertemplate="%{y}<br>" + level + ": %{x}<extra></extra>",
            )
    for name, total in counts.sum(axis=1).items():
        f.add_annotation(
            x=int(total),
            y=label(name),
            text=str(total),
            showarrow=False,
            xanchor="left",
            xshift=5,
        )
    f.update_layout(barmode="stack", showlegend=True)
    f.update_yaxes(autorange="reversed")
    f.update_xaxes(
        range=[0, max(float(counts.sum(axis=1).max()) * 1.2, 1)],
        title_text="Карточек",
        title_font_size=11,
    )
    return f


def arrival_step(selected_dates):
    start, end, _ = date_bounds(selected_dates)
    days = (end - start).days + 1
    return "Дни" if days <= 45 else ("Недели" if days <= 180 else "Месяцы")


def arrival_counts(d, selected_dates):
    start, end, _ = date_bounds(selected_dates)
    step = arrival_step(selected_dates)
    if step == "Дни":
        dates = pd.date_range(start, end, freq="D")
        freq = "D"
    elif step == "Недели":
        dates = pd.date_range(
            start - pd.Timedelta(days=start.dayofweek), end, freq="W-MON"
        )
        freq = "W-SUN"
    else:
        dates = pd.date_range(start.replace(day=1), end, freq="MS")
        freq = "M"
    d = created_between(d, selected_dates)
    if d.empty:
        return pd.DataFrame(0, index=dates, columns=LEVELS)
    buckets = (
        d.created.dt.tz_localize(None)
        .dt.to_period(freq)
        .dt.start_time.dt.tz_localize("Europe/Moscow")
    )
    counts = (
        pd.crosstab(buckets, d.severity)
        .reindex(index=dates, columns=LEVELS, fill_value=0)
        .fillna(0)
    )
    return counts


def arrival_profile(d, selected_dates, snapshot=None):
    """День среза исключён; среднее учитывает нулевые календарные дни."""
    start, end, stop = date_bounds(selected_dates)
    step = arrival_step(selected_dates)
    complete_stop = (
        stop
        if snapshot is None
        else min(stop, pd.Timestamp(snapshot).tz_convert("Europe/Moscow").normalize())
    )
    full = d.loc[d.created.lt(complete_stop)]
    counts = arrival_counts(full, selected_dates)
    rows = []
    for day in counts.index:
        next_day = (
            (day + pd.offsets.MonthBegin(1))
            if step == "Месяцы"
            else day + pd.Timedelta(days=7 if step == "Недели" else 1)
        )
        left = max(day, start)
        right = min(next_day, complete_stop)
        days = (right - left).days
        if days <= 0:
            continue
        caption = (
            f"{left:%d.%m.%Y}"
            if step == "Дни"
            else f"{left:%d.%m.%Y} — {right-pd.Timedelta(days=1):%d.%m.%Y}"
        )
        partial = left != day or right != next_day
        total = int(counts.loc[day].sum())
        priority = int(counts.loc[day, ["Высокая", "Критическая"]].sum())
        rows.append(
            dict(
                position=left + (right - left) / 2,
                start=left,
                stop=right,
                days=days,
                total=total,
                priority=priority,
                total_rate=total / days,
                priority_rate=priority / days,
                partial=partial,
                caption=caption,
            )
        )
    return pd.DataFrame(
        rows,
        columns=[
            "position",
            "start",
            "stop",
            "days",
            "total",
            "priority",
            "total_rate",
            "priority_rate",
            "partial",
            "caption",
        ],
    )


def arrival_chart(d, selected_dates, snapshot=None):
    p = arrival_profile(d, selected_dates, snapshot)
    if p.empty:
        return empty("Нет полных дней для сравнения")
    step = arrival_step(selected_dates)
    f = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.24)
    for row, column, title, color in [
        (1, "total_rate", "Все карточки", "#536a7a"),
        (2, "priority_rate", "Высокая и критическая важность", "#b7353f"),
    ]:
        f.add_trace(
            go.Scatter(
                x=p.position,
                y=p[column],
                mode="lines+markers",
                name=title,
                line=dict(color=color, width=2),
                marker=dict(
                    color=color,
                    size=6,
                    symbol=["circle-open" if part else "circle" for part in p.partial],
                ),
                customdata=[
                    [r.caption, int(r.days), int(r.total if row == 1 else r.priority)]
                    for r in p.itertuples()
                ],
                hovertemplate="%{customdata[0]}<br>Карточек: %{customdata[2]}<br>Полных дней: %{customdata[1]}<br>В среднем за день: %{y:.1f}<extra></extra>",
            ),
            row=row,
            col=1,
        )
        f.add_annotation(
            x=0,
            y=1.1,
            xref="paper",
            yref="y domain" if row == 1 else "y2 domain",
            text=title,
            font=dict(size=13, color=color),
            showarrow=False,
            xanchor="left",
        )
        f.update_yaxes(
            range=[0, max(float(p[column].max()) * 1.3, 1)],
            title_text="Карточек / день",
            title_font_size=11,
            showgrid=True,
            gridcolor="#edf0f2",
            zeroline=False,
            nticks=4,
            row=row,
            col=1,
        )
        peak = p[column].idxmax()
        if p.loc[peak, column] > 0:
            f.add_annotation(
                x=p.loc[peak, "position"],
                y=p.loc[peak, column],
                text=f"{p.loc[peak,column]:.1f}",
                yshift=13,
                showarrow=False,
                font=dict(size=11, color=color),
                row=row,
                col=1,
            )
    for i, r in p.loc[p.partial].iterrows():
        f.add_annotation(
            x=r.position,
            y=r.total_rate,
            text=f"{int(r.days)} дн.",
            yshift=-20,
            xanchor="left" if i == 0 else "right",
            font=dict(size=11, color="#626e78"),
            showarrow=False,
            row=1,
            col=1,
        )
    stride = max(1, (len(p) + 9) // 10)
    ticks = p.iloc[::stride]
    f.update_xaxes(showgrid=False, zeroline=False)
    f.update_xaxes(
        tickmode="array",
        tickvals=ticks.position.tolist(),
        ticktext=[
            x.strftime("%m.%Y" if step == "Месяцы" else "%d.%m") for x in ticks.position
        ],
        row=2,
        col=1,
    )
    f.update_layout(
        template="plotly_white",
        height=330,
        showlegend=False,
        font=dict(family="Segoe UI, Arial, sans-serif", size=12, color="#243442"),
        margin=dict(l=55, r=25, t=30, b=35),
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    return f


def rule_counts(d, limit=10):
    return (
        d.rule.fillna("Не указано").replace("", "Не указано").value_counts().head(limit)
    )


def verdict_counts(d):
    if d.empty:
        return pd.DataFrame(columns=["cards", "percent"])
    names = (
        d.verdict.fillna("Не указан")
        .astype(str)
        .str.strip()
        .replace(
            {
                "False Positive": "Ложное срабатывание",
                "Не указан": "Без вердикта",
                "": "Без вердикта",
            }
        )
    )
    counts = names.value_counts()
    return pd.DataFrame({"cards": counts, "percent": counts / len(d) * 100})


def rule_chart(d):
    counts = rule_counts(d)
    if counts.empty:
        return empty()
    f = base()
    f.add_bar(
        x=counts.values,
        y=["<br>".join(textwrap.wrap(str(x), 56)) for x in counts.index],
        orientation="h",
        marker_color="#637584",
        text=[f"{v:,}".replace(",", " ") for v in counts],
        textposition="outside",
        cliponaxis=False,
        customdata=counts.index.tolist(),
        hovertemplate="%{customdata}<br>Карточек: %{x}<extra></extra>",
    )
    f.update_layout(
        height=max(340, len(counts) * 34), margin=dict(l=4, r=45, t=12, b=35)
    )
    f.update_yaxes(autorange="reversed", tickfont_size=12)
    f.update_xaxes(
        range=[0, max(float(counts.max()) * 1.25, 1)],
        showticklabels=False,
        title_text="Карточек",
        title_font_size=11,
    )
    return f


def verdict_chart(d):
    counts = verdict_counts(d)
    if counts.empty:
        return empty()
    labels = [
        f"{int(r.cards):,} · {r.percent:.1f}%".replace(",", " ").replace(".", ",")
        for r in counts.itertuples()
    ]
    f = base()
    f.add_bar(
        x=counts.cards,
        y=[label(x) for x in counts.index],
        orientation="h",
        marker_color="#637584",
        text=labels,
        textposition="outside",
        cliponaxis=False,
        customdata=[[name, float(row.percent)] for name, row in counts.iterrows()],
        hovertemplate="%{customdata[0]}<br>Карточек: %{x}<br>Доля всех выбранных: %{customdata[1]:.1f}%<extra></extra>",
    )
    f.update_layout(
        height=max(340, len(counts) * 48), margin=dict(l=4, r=100, t=12, b=35)
    )
    f.update_yaxes(autorange="reversed", tickfont_size=11)
    f.update_xaxes(
        range=[0, max(float(counts.cards.max()) * 1.3, 1)],
        showticklabels=False,
        title_text="Карточек · % от выбранного периода",
        title_font_size=11,
    )
    return f

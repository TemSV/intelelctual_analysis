import unittest
import pandas as pd
from soc.data import (
    FIELDS,
    prepare,
    select,
    queue,
    targets,
    workflow,
    created_between,
    date_bounds,
)
from soc.charts import (
    arrival_chart,
    stacked,
    arrival_counts,
    arrival_step,
    arrival_profile,
    rule_counts,
    verdict_counts,
    rule_chart,
    verdict_chart,
)


class DataTests(unittest.TestCase):
    def setUp(self):
        rows = []
        for i in range(4):
            row = {col: None for col in FIELDS}
            row.update(
                {
                    "EntityId": i + 1,
                    "Создан": f"2025-09-0{i+1}T12:00:00Z",
                    "Критичность": ["Высокая", "Средняя", "Высокая", "Низкая"][i],
                    "Тип инцидента": ["A", "A", "B", "B"][i],
                    "Фаза реагирования": [
                        "В работе",
                        "Ожидание",
                        "Закрыт~~||~~Проанализирован",
                        "Новый",
                    ][i],
                    "Hostname Цели": "host~~||~~host",
                    "SLA просрочен (взятие в работу)": ["True", None, "False", "False"][
                        i
                    ],
                }
            )
            rows.append(row)
        self.raw = pd.DataFrame(rows)
        self.d, self.snapshot = prepare(self.raw)

    def test_closed_token_and_unknown(self):
        self.assertEqual(workflow("Закрыт~~||~~Проанализирован"), "Закрыт")
        self.assertEqual(workflow(None), "Не указано")
        self.assertEqual(len(select(self.d)), 3)

    def test_combined_filters(self):
        self.assertEqual(
            select(self.d, severities=["Высокая"], kinds=["A"]).id.tolist(), [1]
        )
        self.assertTrue(select(self.d, severities=["Высокая"], kinds=["B"]).empty)
        self.assertEqual(len(select(self.d, status="Все", severities=["Высокая"])), 2)

    def test_unknown_sla_and_duplicate_targets(self):
        self.assertTrue(pd.isna(self.d.loc[1, "overdue"]))
        self.assertEqual(targets(self.d).loc["host"], 3)

    def test_queue_search_and_closed_age(self):
        self.assertEqual(queue(self.d, "3")["Номер"].tolist(), [3])
        self.assertTrue(pd.isna(queue(self.d, "3").iloc[0]["Суток"]))
        self.assertTrue(queue(self.d, "does-not-exist").empty)

    def test_validation_and_timezone(self):
        self.assertEqual(self.d.created.iloc[0].hour, 15)
        with self.assertRaises(ValueError):
            prepare(pd.concat([self.raw, self.raw]))
        with self.assertRaises(ValueError):
            prepare(self.raw.drop(columns="EntityId"))

    def test_figures_empty_and_day_counts(self):
        f = arrival_chart(self.d, ["2025-08-29", "2025-09-04"])
        self.assertEqual(sum(f.data[0].y), 4)
        self.assertEqual(sum(f.data[1].y), 2)
        self.assertEqual(len(f.data[0].x), 7)
        self.assertTrue(rule_chart(self.d.iloc[:0]).layout.annotations)
        self.assertTrue(verdict_chart(self.d.iloc[:0]).layout.annotations)
        self.assertTrue(stacked(self.d.iloc[:0], "kind").layout.annotations)

    def test_range_includes_both_calendar_dates(self):
        self.assertEqual(
            created_between(self.d, ["2025-09-02", "2025-09-03"]).id.tolist(), [2, 3]
        )
        edges = pd.DataFrame(
            {
                "created": pd.to_datetime(
                    [
                        "2025-09-01T20:59:59Z",
                        "2025-09-01T21:00:00Z",
                        "2025-09-02T20:59:59Z",
                        "2025-09-02T21:00:00Z",
                    ],
                    utc=True,
                )
            }
        )
        self.assertEqual(
            created_between(edges, ["2025-09-02", "2025-09-02"]).index.tolist(), [1, 2]
        )

    def test_arbitrary_range_and_zero_days_in_histogram(self):
        f = arrival_chart(self.d, ["2025-09-02", "2025-09-06"])
        self.assertEqual(sum(f.data[0].y), 3)
        self.assertEqual(len(f.data[0].x), 5)
        self.assertEqual(f.data[0].y[-1], 0)

    def test_one_day_and_invalid_ranges(self):
        self.assertEqual(
            len(arrival_chart(self.d, ["2025-09-02", "2025-09-02"]).data[0].x), 1
        )
        for dates in [
            ["2025-09-03", "2025-09-02"],
            [None, "2025-09-02"],
            ["invalid", "2025-09-02"],
        ]:
            with self.assertRaises(ValueError):
                date_bounds(dates)

    def test_long_ranges_keep_counts_and_partial_periods(self):
        for dates, step in [
            (["2025-08-01", "2025-10-01"], "Недели"),
            (["2024-04-12", "2025-09-03"], "Месяцы"),
        ]:
            self.assertEqual(arrival_step(dates), step)
            expected = len(created_between(self.d, dates))
            self.assertEqual(
                int(arrival_counts(self.d, dates).to_numpy().sum()), expected
            )
            f = arrival_chart(self.d, dates)
            p = arrival_profile(self.d, dates)
            self.assertEqual(int(p.total.sum()), expected)
            self.assertLess(len(f.data[0].x), 30)
            self.assertTrue(p.partial.iloc[0])

    def test_unspecified_severity_is_preserved_in_totals(self):
        raw = self.raw.copy()
        raw.loc[0, "Критичность"] = "Отсутствует"
        d, _ = prepare(raw)
        self.assertEqual(d.loc[0, "severity"], "Не указано")
        f = arrival_chart(d, ["2025-09-01", "2025-09-04"])
        self.assertEqual(sum(f.data[0].y), len(d))

    def test_rate_uses_selected_calendar_days_including_zero_days(self):
        p = arrival_profile(self.d, ["2025-01-01", "2025-09-04"])
        september = p.loc[p.start.dt.month.eq(9)].iloc[0]
        self.assertEqual(september.days, 4)
        self.assertEqual(september.total_rate, 1)
        self.assertEqual(september.priority_rate, 0.5)
        august = p.loc[p.start.dt.month.eq(8)].iloc[0]
        self.assertEqual(august.days, 31)
        self.assertEqual(august.total_rate, 0)

    def test_incomplete_snapshot_day_is_excluded_without_extrapolation(self):
        p = arrival_profile(self.d, ["2025-09-01", "2025-09-04"], self.snapshot)
        self.assertEqual(p.total.sum(), 3)
        self.assertEqual(p.days.sum(), 3)
        self.assertEqual(p.priority.sum(), 2)
        self.assertEqual(p.stop.max(), self.snapshot.normalize())
        empty = arrival_chart(self.d, ["2025-09-04", "2025-09-04"], self.snapshot)
        self.assertIn("Нет полных дней", empty.layout.annotations[0].text)

    def test_trend_uses_two_named_panels_without_legend(self):
        f = arrival_chart(self.d, ["2025-09-01", "2025-09-04"])
        self.assertEqual([t.type for t in f.data], ["scatter", "scatter"])
        self.assertEqual(
            [t.name for t in f.data], ["Все карточки", "Высокая и критическая важность"]
        )
        self.assertFalse(f.layout.showlegend)
        self.assertEqual(f.layout.yaxis.range[0], 0)
        self.assertEqual(f.layout.yaxis2.range[0], 0)

    def test_search_uses_only_exact_card_number(self):
        d = self.d.copy()
        d["id"] = [1, 12, 21, 101]
        self.assertEqual(queue(d, "1")["Номер"].tolist(), [1])
        self.assertEqual(queue(d, " 12 ")["Номер"].tolist(), [12])
        self.assertTrue(queue(d, "A").empty)
        self.assertEqual(len(queue(d, "")), 4)

    def test_rules_rank_by_count_and_keep_unknown(self):
        d = self.d.copy()
        d["rule"] = ["R1", "R2", "R1", None]
        counts = rule_counts(d)
        self.assertEqual(counts.loc["R1"], 2)
        self.assertEqual(counts.loc["Не указано"], 1)
        self.assertEqual(int(counts.sum()), len(d))
        self.assertEqual(rule_counts(d, limit=1).to_dict(), {"R1": 2})
        self.assertEqual(rule_chart(d).layout.xaxis.range[0], 0)

    def test_verdict_percentages_include_unknown_and_all_outcomes(self):
        d = pd.DataFrame(
            {
                "verdict": [
                    "False Positive",
                    "False Positive",
                    None,
                    "Не указан",
                    "Решён",
                    "Дубликат",
                ]
            }
        )
        counts = verdict_counts(d)
        self.assertEqual(counts.cards.sum(), 6)
        self.assertAlmostEqual(counts.percent.sum(), 100)
        self.assertEqual(counts.loc["Без вердикта", "cards"], 2)
        self.assertEqual(counts.loc["Решён", "cards"], 1)
        self.assertEqual(counts.loc["Дубликат", "cards"], 1)
        self.assertAlmostEqual(counts.loc["Ложное срабатывание", "percent"], 100 / 3)
        one = verdict_counts(d.iloc[:1])
        self.assertEqual(one.percent.iloc[0], 100)
        self.assertEqual(verdict_chart(d).layout.xaxis.range[0], 0)


if __name__ == "__main__":
    unittest.main()

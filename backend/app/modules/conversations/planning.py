import re
from datetime import date

from app.core.db import rows
from app.modules.conversations.parser import amounts
from app.modules.resources import normalize


async def handle_planning(ctx, action, text, message, now):
    from app.modules.conversations.service import ask, propose

    data = action["extracted_data"]
    field = data.get("answer_field")
    if action["intent"] == "CREATE_GOAL":
        goal = data.setdefault("goal", {})
        values = amounts(text)
        if values and len(set(values)) == 1 and ("target_amount" not in goal or field == "target_amount"):
            goal["target_amount"] = values[0]
        if field == "goal_name":
            goal["name"] = text.strip()[:100]
        if not goal.get("name"):
            return await ask(ctx, action, data, "goal_name", "Qual é o nome da meta?", now)
        if not goal.get("target_amount"):
            return await ask(ctx, action, data, "target_amount", "Qual é o valor total da meta?", now)
        return await propose(
            ctx,
            action,
            data,
            f"Criar meta {goal['name']} de R$ {goal['target_amount']}? Responda sim.",
            message,
            now,
        ), f"Criar meta {goal['name']} de R$ {goal['target_amount']}? Responda sim."
    budget = data.setdefault("budget", {"name": "Orçamento familiar", "categories": []})
    if field == "budget_period":
        match = re.fullmatch(r"(\d{4})-(\d{2})", text.strip())
        if match:
            from datetime import timedelta

            from app.core.money import add_months

            try:
                start = date(int(match[1]), int(match[2]), 1)
                budget.update(
                    period_start=start.isoformat(),
                    period_end=(add_months(start, 1) - timedelta(days=1)).isoformat(),
                )
            except ValueError:
                pass
    if not budget.get("period_start"):
        return await ask(
            ctx, action, data, "budget_period", "Para qual mês? Informe AAAA-MM, por exemplo 2026-09.", now
        )
    if not budget["categories"]:
        if field == "budget_category":
            candidates = [
                c
                for c in await rows(ctx, "categories")
                if c["kind"] == "EXPENSE" and normalize(c["name"]) == normalize(text) and not c["archived_at"]
            ]
            if len(candidates) == 1:
                data["budget_category"] = str(candidates[0]["id"])
        if not data.get("budget_category"):
            return await ask(
                ctx,
                action,
                data,
                "budget_category",
                "Qual categoria receberá o orçamento? Informe o nome exato.",
                now,
            )
        values = amounts(text) if field == "budget_amount" else []
        if len(set(values)) != 1:
            return await ask(ctx, action, data, "budget_amount", "Qual é o limite desta categoria?", now)
        budget["categories"] = [{"category_id": data["budget_category"], "amount": values[0]}]
    question = f"Criar orçamento de R$ {budget['categories'][0]['amount']} para a categoria escolhida, no período {budget['period_start']} a {budget['period_end']}? Responda sim."
    return await propose(ctx, action, data, question, message, now), question

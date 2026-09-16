from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.core.db import emit, get, insert, rows, update
from app.modules.analytics import forecast
from app.modules.planning.service import budget_detail


def next_allowed(now, quiet, tz):
    local = now.astimezone(ZoneInfo(tz))
    start = quiet.get("start", 22)
    end = quiet.get("end", 8)
    inside = (local.hour >= start or local.hour < end) if start > end else start <= local.hour < end
    if not inside or start == end:
        return now
    result = local.replace(hour=end, minute=0, second=0, microsecond=0)
    if result <= local:
        result += timedelta(days=1)
    return result.astimezone(timezone.utc)


async def candidates(ctx, rule):
    today = ctx.today()
    config = rule["config"]
    kind = rule["kind"]
    result = []
    if kind in ("BUDGET_THRESHOLD", "BUDGET_FORECAST_EXCEEDED"):
        for budget in await rows(ctx, "budgets"):
            if not budget["period_start"] <= today <= budget["period_end"]:
                continue
            if config.get("budget_id") and str(budget["id"]) != config["budget_id"]:
                continue
            detail = await budget_detail(ctx, budget["id"])
            projections = (
                (await forecast.categories(ctx, today.strftime("%Y-%m")))["data"]
                if kind == "BUDGET_FORECAST_EXCEEDED"
                else []
            )
            for line in detail["categories"]:
                cat = await get(ctx, "categories", line["category_id"])
                threshold = Decimal(str(config.get("threshold", "0.8")))
                value = line["actual"]
                limit = line["amount"]
                if kind == "BUDGET_FORECAST_EXCEEDED":
                    item = next((p for p in projections if p["category_id"] == line["category_id"]), None)
                    if not item or item["projected"] is None:
                        continue
                    value = item["projected"]
                    threshold = Decimal(1)
                if limit <= 0 or value < limit * threshold:
                    continue
                text = f"{cat['name']}: R$ {value:.2f} {'projetados no ritmo atual' if kind == 'BUDGET_FORECAST_EXCEEDED' else 'realizados'} de R$ {limit:.2f} no orçamento de {today.strftime('%m/%Y')}."
                key = f"{rule['id']}:{budget['id']}:{line['category_id']}:{threshold}"
                result.append((key, text))
    elif kind == "DUE_SOON":
        projected = await forecast.cashflow(ctx, end=today + timedelta(days=1))
        total = sum(
            (e["expenses"] for e in projected["events"] if e["date"] == today + timedelta(days=1)), Decimal(0)
        )
        if total > 0:
            result.append(
                (f"{rule['id']}:{today}", f"Amanhã vencem R$ {total:.2f} em compromissos cadastrados.")
            )
    elif kind == "LOW_PROJECTED_BALANCE":
        projected = await forecast.cashflow(ctx)
        minimum = Decimal(str(config.get("minimum_balance", "0")))
        low = next((d for d in projected["daily"] if d["balance"] < minimum), None)
        if low:
            result.append(
                (
                    f"{rule['id']}:{today.strftime('%Y-%m')}",
                    f"O caixa projetado pode chegar a R$ {low['balance']:.2f} em {low['date'].strftime('%d/%m/%Y')}, abaixo do limite configurado.",
                )
            )
    return result


async def evaluate(ctx):
    for rule in await rows(ctx, "alert_rules"):
        if not rule["enabled"]:
            continue
        member = await ctx.conn.fetchval(
            "SELECT id FROM household_members WHERE user_id=$1 AND status='ACTIVE'", rule["recipient_user_id"]
        )
        if not member:
            continue
        for key, text in await candidates(ctx, rule):
            if await ctx.conn.fetchval("SELECT id FROM alerts WHERE dedup_key=$1", key):
                continue
            alert = await insert(
                ctx,
                "alerts",
                {
                    "alert_rule_id": rule["id"],
                    "dedup_key": key,
                    "payload": {"text": text},
                    "status": "PENDING",
                },
            )
            if rule["channel"] == "WHATSAPP" and rule["opt_in"]:
                identity = await ctx.conn.fetchrow(
                    "SELECT ci.* FROM channel_identities ci JOIN integrations i ON i.id=ci.integration_id WHERE ci.user_id=$1 AND ci.channel='WHATSAPP' AND ci.revoked_at IS NULL AND i.status='ACTIVE'",
                    rule["recipient_user_id"],
                )
                if not identity:
                    continue
                recent = await ctx.conn.fetchval(
                    "SELECT count(*) FROM alerts a JOIN alert_rules r ON r.id=a.alert_rule_id WHERE r.recipient_user_id=$1 AND a.triggered_at::date=current_date AND a.status IN ('PENDING','SENT')",
                    rule["recipient_user_id"],
                )
                if recent > 3:
                    await update(ctx, "alerts", alert["id"], {"status": "SUPPRESSED"})
                    continue
                outgoing = await insert(
                    ctx,
                    "outgoing_messages",
                    {
                        "integration_id": identity["integration_id"],
                        "recipient_identity_id": identity["id"],
                        "client_message_id": uuid4(),
                        "text": text,
                    },
                )
                event = await emit(
                    ctx,
                    "SendMessage",
                    outgoing["id"],
                    {"alert_rule_id": str(rule["id"]), "alert_id": str(alert["id"])},
                )
                await update(
                    ctx,
                    "outbox_events",
                    event["id"],
                    {
                        "available_at": next_allowed(
                            datetime.now(timezone.utc), rule["quiet_hours"], ctx.timezone
                        )
                    },
                )


async def still_relevant(ctx, alert_id):
    alert = await get(ctx, "alerts", alert_id)
    rule = await get(ctx, "alert_rules", alert["alert_rule_id"])
    return (
        rule["enabled"]
        and rule["opt_in"]
        and any(key == alert["dedup_key"] for key, _ in await candidates(ctx, rule))
    )

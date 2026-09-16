from datetime import datetime, timedelta, timezone

from app.core.db import insert, system_context, update, wire
from app.modules.analytics.service import summary
from app.modules.notifications.service import evaluate
from app.modules.planning.service import materialize


async def schedule(pool):
    from app.workers.runner import scopes

    for scope in await scopes(pool):
        async with system_context(pool, **scope) as ctx:
            await materialize(ctx, ctx.today() + timedelta(days=30))
            await evaluate(ctx)
            metrics = await summary(ctx)
            existing = await ctx.conn.fetchrow(
                "SELECT * FROM financial_snapshots WHERE snapshot_date=$1 AND calculation_version='1.0'",
                ctx.today(),
            )
            values = {"metrics": wire(metrics), "input_watermark": datetime.now(timezone.utc)}
            if existing:
                await update(ctx, "financial_snapshots", existing["id"], values)
            else:
                await insert(
                    ctx,
                    "financial_snapshots",
                    values | {"snapshot_date": ctx.today(), "calculation_version": "1.0"},
                )
            await ctx.conn.execute(
                "UPDATE pending_financial_actions SET status='EXPIRED',version=version+1 WHERE status IN ('WAITING_INFORMATION','WAITING_CONFIRMATION') AND expires_at<=now()"
            )
            await ctx.conn.execute(
                "UPDATE conversation_messages SET raw_text=NULL,normalized_text=NULL,media=NULL,response=NULL WHERE received_at<now()-interval '90 days'"
            )
            await ctx.conn.execute(
                "UPDATE pending_financial_actions SET raw_message=NULL,transcription=NULL,extracted_data='{}'::jsonb,question=NULL WHERE created_at<now()-interval '90 days' AND status NOT IN ('WAITING_INFORMATION','WAITING_CONFIRMATION')"
            )
            await ctx.conn.execute(
                "UPDATE outgoing_messages SET text=NULL WHERE created_at<now()-interval '90 days' AND status IN ('SENT','FAILED','UNKNOWN')"
            )

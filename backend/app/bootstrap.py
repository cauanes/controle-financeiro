import argparse
import asyncio
import getpass
import os
from uuid import uuid4

import asyncpg

from app.core.auth import hasher


async def bootstrap(url, slug, email, password, name="Minha família"):
    if len(password) < 12:
        raise ValueError("Use senha com pelo menos 12 caracteres.")
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            tenant, user, house = uuid4(), uuid4(), uuid4()
            await conn.execute(
                "INSERT INTO tenants(id,slug,name) VALUES($1,$2,$3)", tenant, slug.lower(), name
            )
            await conn.execute(
                "INSERT INTO users(id,tenant_id,email,display_name,password_hash) VALUES($1,$2,$3,$4,$5)",
                user,
                tenant,
                email.lower(),
                name,
                hasher.hash(password),
            )
            await conn.execute(
                "INSERT INTO households(id,tenant_id,name) VALUES($1,$2,$3)", house, tenant, name
            )
            await conn.execute(
                "INSERT INTO household_members(id,tenant_id,household_id,user_id,role) VALUES($1,$2,$3,$4,'OWNER')",
                uuid4(),
                tenant,
                house,
                user,
            )
            for parent, child, kind in [
                ("Alimentação", "Supermercado", "EXPENSE"),
                ("Transporte", "Combustível", "EXPENSE"),
                ("Educação", "Livros", "EXPENSE"),
                ("Moradia", "Aluguel", "EXPENSE"),
                ("Receitas", "Salário", "INCOME"),
            ]:
                parent_id = uuid4()
                await conn.execute(
                    "INSERT INTO categories(id,tenant_id,household_id,name,kind) VALUES($1,$2,$3,$4,$5)",
                    parent_id,
                    tenant,
                    house,
                    parent,
                    kind,
                )
                await conn.execute(
                    "INSERT INTO categories(id,tenant_id,household_id,name,kind,parent_id) VALUES($1,$2,$3,$4,$5,$6)",
                    uuid4(),
                    tenant,
                    house,
                    child,
                    kind,
                    parent_id,
                )
            return {"tenant_id": str(tenant), "user_id": str(user), "household_id": str(house)}
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="Minha família")
    args = parser.parse_args()
    password = getpass.getpass("Senha inicial (mínimo 12 caracteres): ")
    print(
        asyncio.run(
            bootstrap(os.environ["MIGRATION_DATABASE_URL"], args.tenant, args.email, password, args.name)
        )
    )

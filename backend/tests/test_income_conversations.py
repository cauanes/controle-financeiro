from uuid import uuid4

import asyncpg
from test_core import account


async def say(client, text):
    response = await client.post(
        "/api/v1/conversations/messages",
        json={"text": text},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def setup_profiles(client, family):
    conn = await asyncpg.connect(family["admin_url"])
    try:
        await conn.execute("UPDATE users SET display_name='Cauan' WHERE id=$1", family["user_id"])
        carla_id = uuid4()
        await conn.execute(
            "INSERT INTO users(id,tenant_id,email,display_name,password_hash) VALUES($1,$2,$3,'Carla','test')",
            carla_id,
            family["tenant_id"],
            f"carla-{uuid4().hex}@example.com",
        )
        await conn.execute(
            "INSERT INTO household_members(id,tenant_id,household_id,user_id,role) VALUES($1,$2,$3,$4,'ADMIN')",
            uuid4(), family["tenant_id"], family["household_id"], carla_id,
        )
    finally:
        await conn.close()

    categories = {}
    for name in ("Ensino", "Psicologia", "Programação"):
        result = await client.post("/api/v1/categories", json={"name": name, "kind": "INCOME"})
        assert result.status_code == 201, result.text
        categories[name] = result.json()["id"]
    for user_id, category, keywords in (
        (str(carla_id), "Ensino", ["aula", "aluna", "escola", "professora"]),
        (str(carla_id), "Psicologia", ["paciente", "terapia", "consulta"]),
        (family["user_id"], "Psicologia", ["paciente", "terapia", "consulta"]),
        (family["user_id"], "Programação", ["software", "site", "aplicativo"]),
    ):
        result = await client.post(
            "/api/v1/income-activities",
            json={"user_id": user_id, "category_id": categories[category], "keywords": keywords},
        )
        assert result.status_code == 201, result.text
    return str(carla_id), categories


async def test_income_asks_person_then_confirms_full_summary(client, family):
    carla_id, categories = await setup_profiles(client, family)
    await account(client, "Itaú")

    first = await say(client, "Recebi 770 Paciente Alice")
    assert first["status"] == "WAITING_INFORMATION"
    assert "Carla" in first["question"] and "Cauan" in first["question"]
    assert "1. Carla" in first["question"] and "2. Cauan" in first["question"]
    second = await say(client, "1")
    assert "conta" in second["question"]
    assert "1. Itaú" in second["question"]
    proposal = await say(client, "1")
    assert proposal["status"] == "WAITING_CONFIRMATION"
    for expected in ("770.00", "Carla", "Psicologia", "Itaú", "Paciente Alice"):
        assert expected in proposal["question"]
    assert "1. Confirmar e registrar" in proposal["question"]
    assert "2. Cancelar" in proposal["question"]
    assert (await client.get("/api/v1/transactions")).json()["data"] == []

    confirmed = await say(client, "1")
    assert confirmed["status"] == "CONFIRMED"
    transaction = (await client.get("/api/v1/transactions")).json()["data"][0]
    assert transaction["responsible_user_id"] == carla_id
    assert transaction["category_id"] == categories["Psicologia"]
    assert transaction["amount"] == "770.00"


async def test_income_rejects_activity_not_assigned_to_person(client, family):
    await setup_profiles(client, family)
    response = await say(client, "Carla recebeu 200 de programação")
    assert response["status"] == "WAITING_INFORMATION"
    assert "trabalho" in response["question"]
    assert "Ensino" in response["question"] and "Psicologia" in response["question"]
    assert "Programação" not in response["question"]


async def test_patient_shorthand_asks_who_earned_it(client, family):
    await setup_profiles(client, family)
    response = await say(client, "Paciente Alice 770")
    assert response["status"] == "WAITING_INFORMATION"
    assert "Carla" in response["question"] and "Cauan" in response["question"]


async def test_invalid_choice_keeps_income_pending(client, family):
    await setup_profiles(client, family)
    await say(client, "Recebi 770 Paciente Alice")
    response = await say(client, "9")
    assert response["status"] == "WAITING_INFORMATION"
    assert "opção não está disponível" in response["question"]
    assert (await client.get("/api/v1/transactions")).json()["data"] == []

"""The agents that ship with Dagi.

The factory is only useful if its agents survive a redeploy. The agents
themselves are data, so they live here in the repository, versioned with the
code, and are installed into the state database on start. An agent that the
operator saved from a real session is not touched: the seed only fills in
what is missing.
"""

from __future__ import annotations

from typing import Any

BUILTIN_AGENTS: list[dict[str, Any]] = [
    {
        "name": "work-contract",
        "task": (
            "Подготовь договор подряда по моим данным: заказчик, подрядчик, работы и результат, "
            "объект или место работ, кто предоставляет материалы, сроки, цена или смета, порядок оплаты, "
            "порядок сдачи и приёмки. Собери .docx, проверь и вычитай, приложи готовый договор в чат."
        ),
        "brief": (
            "Fill a work contract (Договор подряда) and deliver the finished .docx in the chat. "
            "Required inputs: customer, contractor, works and result, object or place of work, "
            "who provides the materials, deadline, price or estimate, payment order, and the handover "
            "and acceptance procedure. "
            "Optional: party details, start date, stages, warranty, special conditions. "
            "Work with the document tools: document_template to read the field contract, document_create "
            "to build the .docx, document_edit to change or fill a field by name, document_verify to "
            "check completeness and proofread, document_latest to find the produced file. "
            "Ask at most one clarifying question, and only when a required field is missing. "
            "Before delivery, verification must pass: no open placeholders, every required field filled, "
            "proofreading clean. "
            "Finish with the .docx attached in the chat and a short statement of what was filled and "
            "what remains."
        ),
        "tools": [
            "document_template",
            "document_create",
            "document_read",
            "document_edit",
            "document_verify",
            "document_latest",
            "read_file",
            "write_file",
            "list_dir",
        ],
        "skill": {
            "description": "Prepare a work contract as a .docx and deliver it in the chat",
            "triggers": ["договор", "подряд", "contract", "docx"],
            "body": "\n".join(
                [
                    "1. document_template -> read the required and optional fields.",
                    "2. Ask at most one question, only when a required field is missing.",
                    "3. document_create with every known value -> writes <name>.docx in the session workspace.",
                    "4. document_edit for corrections: pass the field name and the new value; a filled field "
                    "can be changed, and an unknown field name is reported back with the valid ones.",
                    "5. document_verify -> must be ok=true: no open placeholders, required fields filled, "
                    "proofreading clean. If it is not ok, fix what it reports and verify again. "
                    "Never deliver an unverified document.",
                    "6. Deliver: the .docx appears in the chat with a download link; state what was filled "
                    "and what stays optional.",
                ]
            ),
        },
    },
    {
        "name": "hermes-deploy",
        "task": (
            "Установка Hermes агента на удалённый сервер, юзера + токен. "
            "Результат — работающая настройка Telegram: бот на удалённом сервере отвечает."
        ),
        "brief": (
            "Deploy a new Hermes agent on a remote server: create the user, install Hermes, write the "
            "API token and the Telegram bot token into a protected file on the target, start the agent "
            "and prove the connection with a real message. The SSH key and the target host are in the "
            "protected environment, never in the chat. The first run may take a long time because the "
            "mechanisms are still being understood. The result of the work is a configured Telegram bot, "
            "not a written instruction: verify the bot answers before reporting success."
        ),
        "tools": [
            "inspect_runtime",
            "list_dir",
            "list_skills",
            "run_bash",
            "search_memory",
            "write_file",
        ],
        "skill": {
            "description": "Deploy a Hermes agent with a user, a token and a Telegram bot on a remote server",
            "triggers": ["hermes", "deploy", "telegram", "бот", "сервер", "ssh"],
            "body": "\n".join(
                [
                    "1. Read the target host, the account and the SSH key from the protected environment, "
                    "never from the chat.",
                    "2. Create the user on the target, install Hermes, and write the token file with mode 0600.",
                    "3. Register the Telegram bot with BotFather and store the token on the target only.",
                    "4. Start the agent on the target and prove the connection: a real message must come back.",
                    "5. Report what was configured and what was verified. A written instruction is not a "
                    "deployed agent; the proof is a working connection.",
                ]
            ),
        },
    },
]


def install_builtin_agents(state: Any) -> dict[str, list[str]]:
    """Install the built-in agents into the state database, idempotently.

    Only what is missing is created. A template or a skill that the operator
    saved or edited keeps its content.
    """
    installed: dict[str, list[str]] = {"templates": [], "skills": []}
    existing_templates = {item["name"] for item in state.list_templates()}
    for agent in BUILTIN_AGENTS:
        name = agent["name"]
        if name not in existing_templates:
            state.create_template(
                name,
                task=agent["task"],
                brief=agent["brief"],
                tools=agent.get("tools"),
            )
            installed["templates"].append(name)
        skill = agent.get("skill")
        if skill and state.get_skill(name) is None:
            state.create_skill(
                name, skill["description"], list(skill["triggers"]), skill["body"]
            )
            installed["skills"].append(name)
    return installed

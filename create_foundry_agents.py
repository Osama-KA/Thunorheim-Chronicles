import os
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from dotenv import load_dotenv

load_dotenv()

project = AIProjectClient(
    endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential(),
)

agents = [
    ("dm-agent", "You are the DM Agent for Thunorheim — orchestrator, intent classifier, and narrator. You drive the turn pipeline and are the only thing the player ever sees."),
    ("resolution-agent", "You are the Resolution Agent for Thunorheim — the logic engine. You evaluate actions through seven-bucket rules using honest logical reasoning. There are no dice."),
    ("npc-agent", "You are the NPC Agent for Thunorheim — the consistency layer. You resolve character references, load or create NPC sheets, and voice characters in-character after verdicts are issued."),
]

for name, instructions in agents:
    agent = project.agents.create_version(
        agent_name=name,
        definition=PromptAgentDefinition(
            model=os.environ["AZURE_AI_MODEL_DEPLOYMENT"],
            instructions=instructions,
        ),
    )
    print(f"{name}: id={agent.id} version={agent.version}")
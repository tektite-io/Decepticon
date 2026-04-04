from decepticon.agents.decepticon import create_decepticon_agent
from decepticon.agents.exploit import create_exploit_agent
from decepticon.agents.planner import create_planner_agent
from decepticon.agents.postexploit import create_postexploit_agent
from decepticon.agents.recon import create_recon_agent
from decepticon.agents.soundwave import create_soundwave_agent

# Backward compatibility aliases
create_planning_agent = create_planner_agent

__all__ = [
    "create_recon_agent",
    "create_planner_agent",
    "create_planning_agent",
    "create_soundwave_agent",
    "create_exploit_agent",
    "create_postexploit_agent",
    "create_decepticon_agent",
]

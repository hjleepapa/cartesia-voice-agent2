"""
Call Transfer Tools for LangChain Agent
Provides tools for transferring voice calls to human agents
"""

from typing import List, Optional
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field
import os


class TransferToAgentInput(BaseModel):
    """Input schema for transfer_to_agent tool"""
    department: str = Field(
        default="support",
        description="Department or team to transfer to (e.g., 'support', 'sales', 'technical')"
    )
    reason: str = Field(
        default="User requested transfer to human agent",
        description="Reason for the transfer request"
    )
    extension: Optional[str] = Field(
        default=None,
        description="Specific extension number to transfer to (optional, will use default if not provided)"
    )


class GetAvailableDepartmentsInput(BaseModel):
    """Input schema for get_available_departments tool"""
    pass


def transfer_to_agent_tool() -> BaseTool:
    """Tool to transfer a voice call to a human agent or department"""

    def _transfer_to_agent(department: str = "support", reason: str = "User requested transfer to human agent", extension: Optional[str] = None) -> str:
        """
        Transfer the current voice call to a human agent or department.

        Args:
            department: Department name (e.g., 'support', 'sales', 'technical')
            reason: Reason for transfer
            extension: Optional specific extension number

        Returns:
            A special marker string that will be detected by the system to initiate transfer
        """
        # Get default extension from environment or use provided
        target_extension = extension or os.getenv('VOICE_AGENT_FALLBACK_EXTENSION', '2001')
        default_department = os.getenv('VOICE_AGENT_FALLBACK_DEPARTMENT', 'support')

        # Use provided department or fallback to default
        target_department = department if department else default_department

        # Return special marker that will be detected by the system
        # Format: TRANSFER_INITIATED:extension|department|reason
        marker = f"TRANSFER_INITIATED:{target_extension}|{target_department}|{reason}"
        return marker

    return BaseTool(
        name="transfer_to_agent",
        description="""Transfer the current voice call to a human agent or department. 
        Use this when the user requests to speak with a human, agent, representative, or specific department.
        Examples: 'transfer me', 'speak to agent', 'talk to human', 'transfer to sales', 'I need help from support'.
        This tool will initiate the transfer process immediately.""",
        args_schema=TransferToAgentInput,
        func=_transfer_to_agent
    )


def get_available_departments_tool() -> BaseTool:
    """Tool to get list of available departments for transfer"""

    def _get_available_departments() -> str:
        """
        Get a list of available departments that users can be transferred to.

        Returns:
            A formatted string listing available departments
        """
        # Get departments from environment or use defaults
        departments_env = os.getenv('VOICE_AGENT_DEPARTMENTS', 'support,sales,technical')
        departments = [d.strip() for d in departments_env.split(',')]

        # Get default extension
        default_extension = os.getenv('VOICE_AGENT_FALLBACK_EXTENSION', '2001')

        result = f"Available departments for transfer:\n"
        for dept in departments:
            result += f"- {dept.title()} (extension {default_extension})\n"

        result += f"\nYou can transfer the user by saying 'transfer to [department]' or use the transfer_to_agent tool."
        return result

    return BaseTool(
        name="get_available_departments",
        description="""Get a list of available departments that users can be transferred to.
        Use this when the user asks 'what departments are available?', 'who can I talk to?', or 'what are my options?'.
        This helps users understand their transfer options.""",
        args_schema=GetAvailableDepartmentsInput,
        func=_get_available_departments
    )


def get_transfer_tools() -> List[BaseTool]:
    """
    Get all call transfer tools for the LangChain agent.

    Returns:
        List of BaseTool instances for call transfer functionality
    """
    return [
        transfer_to_agent_tool(),
        get_available_departments_tool()
    ]


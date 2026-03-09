"""Inter-agent messaging via Supabase."""

from shared.supabase_client import send_message, get_unread_messages, mark_messages_read
from shared.config import get_logger

log = get_logger("messaging")


class AgentMailbox:
    """Simple mailbox for an agent to send/receive messages."""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name

    def send(self, to_agent: str, msg_type: str, payload: dict) -> dict:
        log.debug("%s -> %s: %s", self.agent_name, to_agent, msg_type)
        return send_message(self.agent_name, to_agent, msg_type, payload)

    def receive(self) -> list[dict]:
        messages = get_unread_messages(self.agent_name)
        if messages:
            log.info("%s has %d unread messages", self.agent_name, len(messages))
        return messages

    def ack(self, messages: list[dict]) -> None:
        ids = [m["id"] for m in messages]
        mark_messages_read(ids)
        log.debug("%s acknowledged %d messages", self.agent_name, len(ids))

    def broadcast(self, msg_type: str, payload: dict) -> None:
        """Send to all agents."""
        for target in ("scout", "worker", "bd"):
            if target != self.agent_name:
                self.send(target, msg_type, payload)

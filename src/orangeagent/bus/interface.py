from abc import ABC, abstractmethod
from asyncio import Queue

from .models import Message


class MessageBus(ABC):
    """Abstract interface for message bus implementations.

    Defines the contract that both LocalMessageBus (in-process asyncio.Queue)
    and HttpMessageBus (HTTP + WebSocket) must fulfill.
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Connect to bus backend, create any persistent resources."""

    @abstractmethod
    async def close(self) -> None:
        """Disconnect and release all resources."""

    @abstractmethod
    def subscribe(self, agent_id: str) -> Queue[Message]:
        """Subscribe to messages for a specific agent.

        Returns an asyncio.Queue that receives messages routed to this agent.
        Must be synchronous — agent code calls this without await.
        """

    @abstractmethod
    def unsubscribe(self, agent_id: str) -> None:
        """Remove a subscription."""

    @abstractmethod
    def add_observer(self) -> Queue[Message]:
        """Subscribe to ALL messages flowing through the bus (observer pattern).

        Returns an asyncio.Queue that receives a copy of every dispatched message.
        Must be synchronous.
        """

    @abstractmethod
    def remove_observer(self, queue: Queue[Message]) -> None:
        """Remove a previously added observer queue."""

    @abstractmethod
    async def publish(self, msg: Message) -> None:
        """Publish a message to the bus.

        The bus handles persistence (if applicable) and dispatch to recipients.
        """

    @abstractmethod
    async def get_history(
        self,
        limit: int = 50,
        from_agent: str | None = None,
        msg_type: str | None = None,
    ) -> list[Message]:
        """Retrieve historical messages from persistent storage."""

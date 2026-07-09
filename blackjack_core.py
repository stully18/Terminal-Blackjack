from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import random


SUITS = ("spades", "hearts", "diamonds", "clubs")
RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")


@dataclass(frozen=True)
class Card:
    rank: str
    suit: str

    @property
    def value(self) -> int:
        if self.rank == "A":
            return 11
        if self.rank in {"J", "Q", "K"}:
            return 10
        return int(self.rank)


class Deck:
    def __init__(self) -> None:
        self.cards = [Card(rank, suit) for suit in SUITS for rank in RANKS]
        random.shuffle(self.cards)

    def draw(self) -> Card:
        if not self.cards:
            self.__init__()
        return self.cards.pop()


class Outcome(Enum):
    PLAYER_BLACKJACK = "player_blackjack"
    DEALER_BLACKJACK = "dealer_blackjack"
    PLAYER_BUST = "player_bust"
    DEALER_BUST = "dealer_bust"
    PLAYER_WIN = "player_win"
    DEALER_WIN = "dealer_win"
    PUSH = "push"


@dataclass(frozen=True)
class Resolution:
    outcome: Outcome
    payout: int
    message: str


def hand_value(hand: list[Card]) -> int:
    total = sum(card.value for card in hand)
    aces = sum(1 for card in hand if card.rank == "A")

    while total > 21 and aces:
        total -= 10
        aces -= 1

    return total


def is_blackjack(hand: list[Card]) -> bool:
    return len(hand) == 2 and hand_value(hand) == 21


def is_bust(hand: list[Card]) -> bool:
    return hand_value(hand) > 21


def is_soft_17(hand: list[Card]) -> bool:
    total = sum(card.value for card in hand)
    aces = sum(1 for card in hand if card.rank == "A")

    while total > 21 and aces:
        total -= 10
        aces -= 1

    return total == 17 and aces > 0


def dealer_should_hit(hand: list[Card]) -> bool:
    return hand_value(hand) < 17


def resolve_round(player_hand: list[Card], dealer_hand: list[Card], bet: int) -> Resolution:
    player_blackjack = is_blackjack(player_hand)
    dealer_blackjack = is_blackjack(dealer_hand)

    if player_blackjack and dealer_blackjack:
        return Resolution(Outcome.PUSH, bet, "Both hands have blackjack. Push.")
    if player_blackjack:
        return Resolution(
            Outcome.PLAYER_BLACKJACK,
            bet + int(bet * 1.5),
            "Blackjack pays 3:2.",
        )
    if dealer_blackjack:
        return Resolution(Outcome.DEALER_BLACKJACK, 0, "Dealer has blackjack.")
    if is_bust(player_hand):
        return Resolution(Outcome.PLAYER_BUST, 0, "Player busts.")
    if is_bust(dealer_hand):
        return Resolution(Outcome.DEALER_BUST, bet * 2, "Dealer busts.")

    player_total = hand_value(player_hand)
    dealer_total = hand_value(dealer_hand)

    if player_total > dealer_total:
        return Resolution(Outcome.PLAYER_WIN, bet * 2, "Player wins.")
    if dealer_total > player_total:
        return Resolution(Outcome.DEALER_WIN, 0, "Dealer wins.")
    return Resolution(Outcome.PUSH, bet, "Push.")

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import sys
import termios
import time
import tty

from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from blackjack_core import (
    Card,
    Deck,
    Outcome,
    Resolution,
    dealer_should_hit,
    hand_value,
    is_blackjack,
    is_bust,
    resolve_round,
)


STARTING_BANKROLL = 100
MINIMUM_BET = 1
WHOOSH_DELAY = 0.025
SUIT_SYMBOLS = {
    "spades": "♠",
    "hearts": "♥",
    "diamonds": "♦",
    "clubs": "♣",
}
SUIT_STYLES = {
    "spades": "bright_white",
    "clubs": "bright_white",
    "hearts": "bright_red",
    "diamonds": "bright_red",
}


console = Console()


@dataclass(frozen=True)
class Odds:
    win: float
    push: float
    lose: float
    ev: float


@dataclass
class TableState:
    bankroll: int
    bets: list[int]
    player_hands: list[list[Card]]
    dealer_hand: list[Card]
    active_hand: int = 0
    hide_dealer_hole: bool = True
    notice: str = ""
    controls: str = ""
    odds: str = ""
    dealer_pose: str = "idle"

    @property
    def bet(self) -> int:
        return self.bets[self.active_hand]

    @property
    def player_hand(self) -> list[Card]:
        return self.player_hands[self.active_hand]


def format_money(amount: int) -> str:
    return f"${amount}"


def card_text(card: Card) -> Text:
    symbol = SUIT_SYMBOLS[card.suit]
    style = SUIT_STYLES[card.suit]
    return Text(f"{card.rank}{symbol}", style=style)


def card_label(card: Card) -> str:
    return f"{card.rank}{SUIT_SYMBOLS[card.suit]}"


def rank_counts(cards: list[Card]) -> tuple[tuple[str, int], ...]:
    counts = {rank: 0 for rank in ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")}
    for card in cards:
        counts[card.rank] += 1
    return tuple((rank, count) for rank, count in counts.items() if count)


def ranks_value(ranks: tuple[str, ...]) -> int:
    total = 0
    aces = 0
    for rank in ranks:
        if rank == "A":
            total += 11
            aces += 1
        elif rank in {"J", "Q", "K"}:
            total += 10
        else:
            total += int(rank)

    while total > 21 and aces:
        total -= 10
        aces -= 1

    return total


def remove_rank(
    counts: tuple[tuple[str, int], ...],
    rank_to_remove: str,
) -> tuple[tuple[str, int], ...]:
    updated = []
    for rank, count in counts:
        if rank == rank_to_remove:
            if count > 1:
                updated.append((rank, count - 1))
        else:
            updated.append((rank, count))
    return tuple(updated)


def outcome_from_totals(player_total: int, dealer_total: int) -> Outcome:
    if player_total > 21:
        return Outcome.PLAYER_BUST
    if dealer_total > 21:
        return Outcome.DEALER_BUST
    if player_total > dealer_total:
        return Outcome.PLAYER_WIN
    if dealer_total > player_total:
        return Outcome.DEALER_WIN
    return Outcome.PUSH


def odds_from_outcomes(outcomes: dict[Outcome, float], bet_units: int = 1) -> Odds:
    win = outcomes.get(Outcome.PLAYER_WIN, 0.0) + outcomes.get(Outcome.DEALER_BUST, 0.0)
    push = outcomes.get(Outcome.PUSH, 0.0)
    lose = (
        outcomes.get(Outcome.DEALER_WIN, 0.0)
        + outcomes.get(Outcome.PLAYER_BUST, 0.0)
        + outcomes.get(Outcome.DEALER_BLACKJACK, 0.0)
    )
    ev = (win - lose) * bet_units
    return Odds(win, push, lose, ev)


@lru_cache(maxsize=None)
def dealer_final_totals(
    dealer_ranks: tuple[str, ...],
    counts: tuple[tuple[str, int], ...],
) -> tuple[tuple[int, float], ...]:
    total = ranks_value(dealer_ranks)
    if total >= 17:
        return ((total, 1.0),)

    card_count = sum(count for _, count in counts)
    if card_count == 0:
        return ((total, 1.0),)

    totals: dict[int, float] = {}
    for rank, count in counts:
        probability = count / card_count
        next_counts = remove_rank(counts, rank)
        for final_total, final_probability in dealer_final_totals(
            dealer_ranks + (rank,),
            next_counts,
        ):
            totals[final_total] = totals.get(final_total, 0.0) + probability * final_probability

    return tuple(sorted(totals.items()))


def stand_outcomes(
    player_ranks: tuple[str, ...],
    dealer_up_rank: str,
    counts: tuple[tuple[str, int], ...],
) -> dict[Outcome, float]:
    player_total = ranks_value(player_ranks)
    if player_total > 21:
        return {Outcome.PLAYER_BUST: 1.0}

    card_count = sum(count for _, count in counts)
    if card_count == 0:
        return {Outcome.PUSH: 1.0}

    outcomes: dict[Outcome, float] = {}
    for hole_rank, count in counts:
        hole_probability = count / card_count
        after_hole = remove_rank(counts, hole_rank)
        for dealer_total, dealer_probability in dealer_final_totals(
            (hole_rank, dealer_up_rank),
            after_hole,
        ):
            outcome = outcome_from_totals(player_total, dealer_total)
            outcomes[outcome] = outcomes.get(outcome, 0.0) + hole_probability * dealer_probability

    return outcomes


def hit_once_outcomes(
    player_ranks: tuple[str, ...],
    dealer_up_rank: str,
    counts: tuple[tuple[str, int], ...],
) -> dict[Outcome, float]:
    card_count = sum(count for _, count in counts)
    if card_count == 0:
        return stand_outcomes(player_ranks, dealer_up_rank, counts)

    outcomes: dict[Outcome, float] = {}
    for rank, count in counts:
        probability = count / card_count
        next_counts = remove_rank(counts, rank)
        drawn_ranks = player_ranks + (rank,)
        for outcome, outcome_probability in stand_outcomes(
            drawn_ranks,
            dealer_up_rank,
            next_counts,
        ).items():
            outcomes[outcome] = outcomes.get(outcome, 0.0) + probability * outcome_probability

    return outcomes


def visible_odds(deck: Deck, state: TableState, actions: dict[str, str]) -> str:
    if len(state.dealer_hand) < 2:
        return ""

    dealer_hole = state.dealer_hand[0]
    dealer_up = state.dealer_hand[1]
    unseen_cards = deck.cards + ([dealer_hole] if state.hide_dealer_hole else [])
    counts = rank_counts(unseen_cards)
    player_ranks = tuple(card.rank for card in state.player_hand)

    stand = odds_from_outcomes(stand_outcomes(player_ranks, dealer_up.rank, counts))
    hit = odds_from_outcomes(hit_once_outcomes(player_ranks, dealer_up.rank, counts))

    parts = [
        f"S win {stand.win:.0%} push {stand.push:.0%} EV {stand.ev:+.2f}x",
        f"H win {hit.win:.0%} push {hit.push:.0%} lose {hit.lose:.0%} EV {hit.ev:+.2f}x",
    ]
    if "d" in actions:
        double = odds_from_outcomes(hit_once_outcomes(player_ranks, dealer_up.rank, counts), bet_units=2)
        parts.append(f"D win {double.win:.0%} push {double.push:.0%} lose {double.lose:.0%} EV {double.ev:+.2f}x")
    if "q" in actions:
        parts.append("Q split available")

    return "  |  ".join(parts)


def hand_markup(hand: list[Card], hide_first_card: bool = False) -> Text:
    rendered = Text()
    visible_cards = hand[1:] if hide_first_card else hand

    if hide_first_card and hand:
        rendered.append("??", style="dim")
        if visible_cards:
            rendered.append("  ")

    for index, card in enumerate(visible_cards):
        if index:
            rendered.append("  ")
        rendered.append_text(card_text(card))

    return rendered


def hand_panel(
    title: str,
    hand: list[Card],
    hide_first_card: bool = False,
    border_style: str = "cyan",
) -> Panel:
    if not hand:
        total = "-"
    elif hide_first_card:
        total = "?"
    else:
        total = str(hand_value(hand))
    contents = Table.grid(expand=True)
    contents.add_column(justify="center")
    contents.add_row(hand_markup(hand, hide_first_card))
    contents.add_row(Text(f"Total: {total}", style="dim"))
    return Panel(contents, title=title, border_style=border_style, box=box.ROUNDED, padding=(1, 2))


def dealer_panel(pose: str) -> Panel:
    if pose == "deal_player":
        body = [
            "       .------.",
            "      /  o  o  \\",
            "     |    __    |",
            "      \\  '--'  /",
            "       '-.__.-'",
            "      __/|  |\\____ [##]",
            "     /   |__|",
            "        /____\\",
            "       /_/  \\_\\",
        ]
    elif pose == "deal_dealer":
        body = [
            "       .------.",
            "      /  o  o  \\",
            "     |    __    |",
            "      \\  '--'  /",
            "       '-.__.-'",
            " [##]____/|  |\\__",
            "           |__|   \\",
            "          /____\\",
            "         /_/  \\_\\",
        ]
    else:
        body = [
            "       .------.",
            "      /  o  o  \\",
            "     |    __    |",
            "      \\  '--'  /",
            "       '-.__.-'",
            "      __/|  |\\__",
            "     /   |__|   \\",
            "        /____\\",
            "       /_/  \\_\\",
        ]

    dealer = Text(
        "\n".join(body),
        style="bold bright_white",
    )
    return Panel(
        Align.center(dealer),
        title="Dealer",
        border_style="green",
        box=box.ROUNDED,
        padding=(0, 2),
    )


def status_panel(bankroll: int, bet: int, notice: str = "") -> Panel:
    table = Table.grid(expand=True)
    table.add_column(justify="center")
    table.add_column(justify="center")
    table.add_column(justify="center")
    table.add_row(
        Text(f"Bankroll {format_money(bankroll)}", style="bold green"),
        Text(f"Bet {format_money(bet)}", style="bold yellow"),
        Text(notice or "Blackjack pays 3:2", style="dim"),
    )
    return Panel(table, box=box.SIMPLE_HEAVY, border_style="bright_black")


def controls_panel(controls: str, odds: str = "") -> Panel:
    content = Text(controls, style="bold cyan")
    if odds:
        content.append("\n")
        content.append(odds, style="dim")
    return Panel(
        Align.center(content),
        border_style="bright_black",
        box=box.SIMPLE,
        padding=(0, 1),
    )


def player_hands_panel(state: TableState) -> Table:
    hands = Table.grid(expand=True)
    for _ in state.player_hands:
        hands.add_column(ratio=1)

    panels = []
    split = len(state.player_hands) > 1
    for index, hand in enumerate(state.player_hands):
        active = index == state.active_hand
        title = "Player" if not split else f"Hand {index + 1} - Bet {format_money(state.bets[index])}"
        border_style = "bright_yellow" if active else "cyan"
        panels.append(hand_panel(title, hand, border_style=border_style))

    hands.add_row(*panels)
    return hands


def render_table(state: TableState) -> None:
    if console.is_terminal:
        console.clear()
    title = Text("TERMINAL BLACKJACK", style="bold white on dark_green")
    layout = Table.grid(expand=True)
    layout.add_column(ratio=1)
    layout.add_row(Align.center(title))
    layout.add_row(status_panel(state.bankroll, state.bet, state.notice))
    layout.add_row(dealer_panel(state.dealer_pose))
    layout.add_row(hand_panel("Dealer", state.dealer_hand, state.hide_dealer_hole))
    layout.add_row(player_hands_panel(state))
    if state.controls or state.odds:
        layout.add_row(controls_panel(state.controls, state.odds))
    console.print(layout)


def prompt_bet(bankroll: int) -> int | None:
    while True:
        console.print()
        raw = Prompt.ask(
            f"[bold yellow]Place your bet[/] [dim]({MINIMUM_BET}-{bankroll}, or q to quit)[/]"
        )
        if raw.strip().lower() in {"q", "quit", "exit"}:
            return None
        try:
            bet = int(raw)
        except ValueError:
            console.print("[red]Enter a whole-dollar bet or q to quit.[/]")
            continue
        if MINIMUM_BET <= bet <= bankroll:
            return bet
        console.print(f"[red]Bet must be between {MINIMUM_BET} and {bankroll}.[/]")


def can_split(state: TableState) -> bool:
    hand = state.player_hand
    return len(state.player_hands) == 1 and len(hand) == 2 and hand[0].rank == hand[1].rank


def read_key() -> str:
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        return sys.stdin.read(1).lower()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def available_actions(state: TableState) -> dict[str, str]:
    actions = {"h": "hit", "s": "stand"}
    if len(state.player_hand) == 2 and state.bankroll >= state.bet:
        actions["d"] = "double"
    if can_split(state) and state.bankroll >= state.bet:
        actions["q"] = "split"
    return actions


def action_hint(actions: dict[str, str]) -> str:
    labels = {
        "h": "H hit",
        "s": "S stand",
        "d": "D double",
        "q": "Q split",
    }
    return "  ".join(labels[key] for key in actions)


def prompt_action(deck: Deck, state: TableState) -> str:
    actions = available_actions(state)
    state.controls = action_hint(actions)
    state.odds = visible_odds(deck, state, actions)
    render_table(state)

    if console.is_terminal and sys.stdin.isatty():
        while True:
            key = read_key()
            if key in actions:
                return actions[key]

    while True:
        action = Prompt.ask("[bold cyan]Action[/]", show_choices=False).lower()
        if action in {"hit", "h"}:
            return "hit"
        if action in {"stand", "s"}:
            return "stand"
        if action in {"double", "d"} and "d" in actions:
            return "double"
        if action in {"split", "q"} and "q" in actions:
            return "split"
        console.print(f"[red]Use {action_hint(actions)}.[/]")


def whoosh_card(card: Card, target: str, hidden: bool = False) -> None:
    if not console.is_terminal:
        return

    label = "??" if hidden else card_label(card)
    destination = "YOU" if target == "player" else "DEALER"
    width = max(28, min(console.width - 8, 70))
    frames = range(0, width - len(label) - 8, 7)

    sys.stdout.write("\033[?25l")
    try:
        for position in frames:
            left = "-" * position
            right = "-" * (width - position - len(label) - 6)
            line = f"  {left}[{label}]{right}> {destination}"
            sys.stdout.write("\r\033[K" + line)
            sys.stdout.flush()
            time.sleep(WHOOSH_DELAY)
    finally:
        sys.stdout.write("\r\033[K\033[?25h")
        sys.stdout.flush()


def deal_card(deck: Deck, state: TableState, target: str) -> None:
    state.controls = ""
    state.odds = ""
    card = deck.draw()
    if target == "player":
        whoosh_card(card, target)
        state.player_hand.append(card)
        state.dealer_pose = "deal_player"
        state.notice = "Dealer slides a card to you"
    else:
        hide_dealt_card = state.hide_dealer_hole and not state.dealer_hand
        whoosh_card(card, target, hidden=hide_dealt_card)
        state.dealer_hand.append(card)
        state.dealer_pose = "deal_dealer"
        state.notice = "Dealer takes a card"
    if console.is_terminal:
        render_table(state)


def split_player_hand(deck: Deck, state: TableState) -> None:
    first, second = state.player_hand
    state.bankroll -= state.bet
    state.player_hands = [[first], [second]]
    state.bets = [state.bet, state.bet]
    state.active_hand = 0
    state.controls = ""
    state.odds = ""
    state.notice = "Split into two hands"
    render_table(state)
    deal_card(deck, state, "player")
    state.active_hand = 1
    deal_card(deck, state, "player")
    state.active_hand = 0


def double_current_hand(deck: Deck, state: TableState) -> None:
    state.bankroll -= state.bet
    state.bets[state.active_hand] *= 2
    state.controls = ""
    state.odds = ""
    state.notice = f"Double on hand {state.active_hand + 1}"
    deal_card(deck, state, "player")


def deal_opening_hand(deck: Deck, state: TableState) -> None:
    deal_card(deck, state, "player")
    deal_card(deck, state, "dealer")
    deal_card(deck, state, "player")
    deal_card(deck, state, "dealer")


def play_dealer_turn(deck: Deck, state: TableState) -> None:
    while dealer_should_hit(state.dealer_hand):
        deal_card(deck, state, "dealer")


def play_player_hand(deck: Deck, state: TableState) -> None:
    while True:
        if hand_value(state.player_hand) == 21:
            state.controls = ""
            state.odds = ""
            state.notice = f"Hand {state.active_hand + 1} has 21. Standing."
            render_table(state)
            return

        action = prompt_action(deck, state)
        state.controls = ""
        state.odds = ""
        if action == "stand":
            return
        if action == "double":
            double_current_hand(deck, state)
            return
        if action == "split":
            split_player_hand(deck, state)
            continue

        deal_card(deck, state, "player")
        if is_bust(state.player_hand):
            return


def result_style(resolution: Resolution) -> str:
    if resolution.payout == 0:
        return "bold red"
    if "Push" in resolution.message or "push" in resolution.message:
        return "bold yellow"
    return "bold green"


def show_resolution(resolution: Resolution, bankroll: int) -> None:
    table = Table.grid(expand=True)
    table.add_column(justify="center")
    table.add_row(Text(resolution.message, style=result_style(resolution)))
    table.add_row(Text(f"Bankroll: {format_money(bankroll)}", style="bold green"))
    console.print(Panel(table, title="Round Result", border_style="magenta", box=box.ROUNDED))


def show_resolution_for_hand(
    resolution: Resolution,
    bankroll: int,
    hand_index: int,
    hand_count: int,
) -> None:
    if hand_count == 1:
        show_resolution(resolution, bankroll)
        return

    table = Table.grid(expand=True)
    table.add_column(justify="center")
    table.add_row(Text(resolution.message, style=result_style(resolution)))
    table.add_row(Text(f"Bankroll: {format_money(bankroll)}", style="bold green"))
    console.print(
        Panel(
            table,
            title=f"Hand {hand_index + 1} Result",
            border_style="magenta",
            box=box.ROUNDED,
        )
    )


def play_round(bankroll: int) -> int | None:
    bet = prompt_bet(bankroll)
    if bet is None:
        return None

    bankroll -= bet
    deck = Deck()
    state = TableState(bankroll, [bet], [[]], [])
    deal_opening_hand(deck, state)
    state.dealer_pose = "idle"
    state.controls = ""
    state.odds = ""
    state.notice = "Your move"
    render_table(state)

    if is_blackjack(state.player_hand) or is_blackjack(state.dealer_hand):
        state.hide_dealer_hole = False
        state.controls = ""
        state.odds = ""
        state.notice = "Natural blackjack"
        render_table(state)
        resolution = resolve_round(state.player_hand, state.dealer_hand, bet)
        bankroll += resolution.payout
        show_resolution(resolution, bankroll)
        return bankroll

    state.active_hand = 0
    while state.active_hand < len(state.player_hands):
        state.controls = ""
        state.odds = ""
        state.notice = f"Hand {state.active_hand + 1}: your move"
        play_player_hand(deck, state)
        state.active_hand += 1

    state.active_hand = 0
    if any(not is_bust(hand) for hand in state.player_hands):
        state.hide_dealer_hole = False
        state.dealer_pose = "idle"
        render_table(state)
        play_dealer_turn(deck, state)

    state.hide_dealer_hole = False
    state.active_hand = 0
    state.dealer_pose = "idle"
    state.controls = ""
    state.odds = ""
    state.notice = "Dealer reveals"
    render_table(state)
    for index, hand in enumerate(state.player_hands):
        resolution = resolve_round(hand, state.dealer_hand, state.bets[index])
        bankroll += resolution.payout
        show_resolution_for_hand(resolution, bankroll, index, len(state.player_hands))
    return bankroll


def show_welcome() -> None:
    if console.is_terminal:
        console.clear()
    console.print(
        Panel(
            Align.center(
                Group(
                    Text("TERMINAL BLACKJACK", style="bold white"),
                    Text("Beat the dealer. Blackjack pays 3:2.", style="green"),
                )
            ),
            border_style="green",
            box=box.DOUBLE,
            padding=(1, 4),
        )
    )


def main() -> int:
    bankroll = STARTING_BANKROLL
    show_welcome()

    while bankroll >= MINIMUM_BET:
        next_bankroll = play_round(bankroll)
        if next_bankroll is None:
            console.print("[dim]Leaving the table.[/]")
            return 0
        bankroll = next_bankroll
        if bankroll < MINIMUM_BET:
            break
        if not Confirm.ask("[bold cyan]Play another hand?[/]", default=True):
            break

    if bankroll < MINIMUM_BET:
        console.print("[bold red]You are out of chips.[/]")
    console.print(f"[bold green]Final bankroll: {format_money(bankroll)}[/]")
    return 0


if __name__ == "__main__":
    sys.exit(main())

import unittest

from blackjack_core import (
    Card,
    Outcome,
    dealer_should_hit,
    hand_value,
    is_blackjack,
    is_bust,
    is_soft_17,
    resolve_round,
)


def c(rank: str, suit: str = "spades") -> Card:
    return Card(rank, suit)


class HandScoringTests(unittest.TestCase):
    def test_hard_total(self) -> None:
        self.assertEqual(hand_value([c("10"), c("7")]), 17)

    def test_soft_total(self) -> None:
        self.assertEqual(hand_value([c("A"), c("6")]), 17)

    def test_multiple_aces(self) -> None:
        self.assertEqual(hand_value([c("A"), c("A"), c("9")]), 21)

    def test_blackjack_detection(self) -> None:
        self.assertTrue(is_blackjack([c("A"), c("K")]))
        self.assertFalse(is_blackjack([c("A"), c("K"), c("Q")]))

    def test_bust_detection(self) -> None:
        self.assertTrue(is_bust([c("K"), c("Q"), c("2")]))

    def test_dealer_stands_on_soft_17(self) -> None:
        hand = [c("A"), c("6")]
        self.assertTrue(is_soft_17(hand))
        self.assertFalse(dealer_should_hit(hand))


class RoundResolutionTests(unittest.TestCase):
    def test_player_blackjack_pays_three_to_two_plus_returned_bet(self) -> None:
        result = resolve_round([c("A"), c("K")], [c("10"), c("9")], 10)
        self.assertEqual(result.outcome, Outcome.PLAYER_BLACKJACK)
        self.assertEqual(result.payout, 25)

    def test_dealer_blackjack_wins(self) -> None:
        result = resolve_round([c("10"), c("9")], [c("A"), c("K")], 10)
        self.assertEqual(result.outcome, Outcome.DEALER_BLACKJACK)
        self.assertEqual(result.payout, 0)

    def test_both_blackjack_pushes(self) -> None:
        result = resolve_round([c("A"), c("K")], [c("A"), c("Q")], 10)
        self.assertEqual(result.outcome, Outcome.PUSH)
        self.assertEqual(result.payout, 10)

    def test_player_bust_loses(self) -> None:
        result = resolve_round([c("K"), c("Q"), c("2")], [c("10"), c("7")], 10)
        self.assertEqual(result.outcome, Outcome.PLAYER_BUST)
        self.assertEqual(result.payout, 0)

    def test_dealer_bust_pays_one_to_one_plus_returned_bet(self) -> None:
        result = resolve_round([c("10"), c("9")], [c("K"), c("Q"), c("2")], 10)
        self.assertEqual(result.outcome, Outcome.DEALER_BUST)
        self.assertEqual(result.payout, 20)

    def test_player_win(self) -> None:
        result = resolve_round([c("10"), c("9")], [c("10"), c("8")], 10)
        self.assertEqual(result.outcome, Outcome.PLAYER_WIN)
        self.assertEqual(result.payout, 20)

    def test_dealer_win(self) -> None:
        result = resolve_round([c("10"), c("8")], [c("10"), c("9")], 10)
        self.assertEqual(result.outcome, Outcome.DEALER_WIN)
        self.assertEqual(result.payout, 0)

    def test_push(self) -> None:
        result = resolve_round([c("10"), c("8")], [c("Q"), c("8")], 10)
        self.assertEqual(result.outcome, Outcome.PUSH)
        self.assertEqual(result.payout, 10)


if __name__ == "__main__":
    unittest.main()

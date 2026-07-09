from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "demo.gif"
WIDTH = 920
HEIGHT = 540
BG = "#101418"
PANEL = "#162029"
GREEN = "#6ee7a8"
CYAN = "#70d6ff"
YELLOW = "#ffd166"
RED = "#ff6b6b"
MUTED = "#8b9aa7"
WHITE = "#e8edf2"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"
    paths = [
        Path("/usr/share/fonts/truetype/dejavu") / name,
        Path("/usr/share/fonts/truetype/ubuntu/UbuntuMono-B.ttf" if bold else "/usr/share/fonts/truetype/ubuntu/UbuntuMono-R.ttf"),
    ]
    for path in paths:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


FONT = font(18)
FONT_BOLD = font(18, bold=True)
FONT_SMALL = font(15)
FONT_TITLE = font(24, bold=True)
FONT_CARD = font(32, bold=True)


def text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, fill: str = WHITE, bold: bool = False) -> None:
    draw.text(xy, value, font=FONT_BOLD if bold else FONT, fill=fill)


def panel(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], title: str, border: str = CYAN) -> None:
    draw.rounded_rectangle(xy, radius=8, fill=PANEL, outline=border, width=2)
    draw.rectangle((xy[0] + 16, xy[1] - 12, xy[0] + 22 + len(title) * 9, xy[1] + 8), fill=PANEL)
    draw.text((xy[0] + 20, xy[1] - 12), title, font=FONT_SMALL, fill=border)


def card(draw: ImageDraw.ImageDraw, x: int, y: int, label: str, red: bool = False, hidden: bool = False) -> None:
    fill = "#f7fafc" if not hidden else "#253241"
    outline = RED if red else WHITE
    text_fill = outline if hidden or red else "#17202a"
    draw.rounded_rectangle((x, y, x + 58, y + 76), radius=6, fill=fill, outline=outline, width=2)
    if hidden:
        draw.text((x + 15, y + 25), "##", font=FONT_BOLD, fill=text_fill)
        draw.line((x + 12, y + 14, x + 46, y + 62), fill="#3f5063", width=2)
        draw.line((x + 46, y + 14, x + 12, y + 62), fill="#3f5063", width=2)
        return

    rank = label[:-1]
    suit = label[-1]
    draw.text((x + 7, y + 5), rank, font=FONT_SMALL, fill=text_fill)
    draw.text((x + 37, y + 52), rank, font=FONT_SMALL, fill=text_fill)
    bbox = draw.textbbox((0, 0), suit, font=FONT_CARD)
    suit_width = bbox[2] - bbox[0]
    suit_height = bbox[3] - bbox[1]
    draw.text(
        (x + (58 - suit_width) / 2, y + (76 - suit_height) / 2 - 3),
        suit,
        font=FONT_CARD,
        fill=text_fill,
    )


def dealer(draw: ImageDraw.ImageDraw, pose: str) -> None:
    lines = [
        "       .------.",
        "      /  o  o  \\",
        "     |    __    |",
        "      \\  '--'  /",
        "       '-.__.-'",
    ]
    if pose == "deal":
        lines += ["      __/|  |\\____ ╭###╮", "     /   |__|"]
    else:
        lines += ["      __/|  |\\__", "     /   |__|   \\"]
    lines += ["        /____\\", "       /_/  \\_\\"]
    y = 136
    for line in lines:
        draw.text((330, y), line, font=FONT, fill=WHITE)
        y += 18


def base_frame(notice: str, player_cards: list[str], dealer_cards: list[str], pose: str = "idle") -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((24, 18, WIDTH - 24, HEIGHT - 18), radius=12, outline="#334155", width=2)
    draw.text((310, 34), "TERMINAL BLACKJACK", font=FONT_TITLE, fill=WHITE)

    draw.rounded_rectangle((54, 76, WIDTH - 54, 112), radius=4, fill="#121a22", outline="#334155")
    draw.text((104, 84), "Bankroll $90", font=FONT_BOLD, fill=GREEN)
    draw.text((382, 84), "Bet $10", font=FONT_BOLD, fill=YELLOW)
    draw.text((580, 85), notice, font=FONT_SMALL, fill=MUTED)

    panel(draw, (92, 130, WIDTH - 92, 322), "Dealer", GREEN)
    dealer(draw, pose)

    panel(draw, (92, 344, 442, 448), "Dealer Hand", CYAN)
    x = 190
    for label in dealer_cards:
        card(draw, x, 362, label, red="♥" in label or "♦" in label, hidden=label == "??")
        x += 76

    panel(draw, (478, 344, WIDTH - 92, 448), "Player", CYAN)
    x = 600
    for label in player_cards:
        card(draw, x, 362, label, red="♥" in label or "♦" in label)
        x += 76

    draw.rounded_rectangle((92, 466, WIDTH - 92, 516), radius=4, fill="#121a22", outline="#334155")
    draw.text((156, 474), "H hit   S stand   D double", font=FONT_BOLD, fill=CYAN)
    draw.text((156, 494), "S win 25% EV -0.49x  |  H win 58% EV +0.23x  |  D win 58% EV +0.46x", font=FONT_SMALL, fill=MUTED)
    return image


def whoosh_frame(position: int) -> Image.Image:
    image = base_frame("Dealer slides a card to you", ["A♠"], ["??", "7♠"], "deal")
    draw = ImageDraw.Draw(image)
    y = 318
    start = 210
    end = 720
    x = start + int((end - start) * position / 5)
    draw.line((start, y, end, y), fill="#334155", width=2)
    draw.line((x - 80, y, x - 18, y), fill=CYAN, width=3)
    draw.rounded_rectangle((x + 5, y - 31, x + 67, y + 47), radius=8, fill="#05070a")
    card(draw, x, y - 38, "K♥", red=True)
    return image


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frames = [
        base_frame("Opening deal", ["A♠"], ["??", "7♠"]),
        base_frame("Opening deal", ["A♠"], ["??", "7♠"]),
        *[whoosh_frame(i) for i in range(6)],
        base_frame("Blackjack pays 3:2.", ["A♠", "K♥"], ["??", "7♠"]),
        base_frame("Dealer reveals", ["A♠", "K♥"], ["4♣", "7♠"]),
        base_frame("Blackjack pays 3:2.", ["A♠", "K♥"], ["4♣", "7♠"]),
    ]
    frames[0].save(
        OUTPUT,
        save_all=True,
        append_images=frames[1:],
        duration=[750, 450, 80, 80, 80, 80, 80, 160, 850, 900, 1100],
        loop=0,
        optimize=True,
    )
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()

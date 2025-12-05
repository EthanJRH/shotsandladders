'''
shots and ladders core classes and logic.

author: ethan holmgren
'''

from __future__ import annotations
from enum import Enum
from dataclasses import dataclass
from abc import ABC
from typing import Any
import random
import json
import logging


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


class SpaceContents(Enum):
    START = "START"
    END = "END"
    SHOT = "SHOT"
    DOUBLE_SHOT = "DOUBLE_SHOT"
    FRIEND_SHOT = "FRIEND_SHOT"


@dataclass
class Space:
    id: int
    snake_id: int | None = None
    contents: SpaceContents | None = None
    coords: tuple[int, int] | None = None
    prev_id: int | None = None
    next_id: int | None = None
    jump_to: int | None = None


class Board(ABC):
    """base board: owns a list of Space objects and common helpers.
    subclasses provide layout/geometry (e.g. RectangleBoard).
    """
    def __init__(self, spaces: list[Space] | None = None):
        self.spaces: list[Space] = spaces if spaces is not None else []
        self.traversal_order: list[int] | None = None

    @property
    def size(self) -> int:
        return len(self.spaces)

    def add_jump(self, from_id: int, to_id: int) -> None:
        """add a chute/ladder from one space id to another."""
        if from_id < 0 or from_id >= self.size:
            raise IndexError("from_id out of bounds")
        if to_id < 0 or to_id >= self.size:
            raise IndexError("to_id out of bounds")
        self.spaces[from_id].jump_to = to_id

    def add_shot(self, id: int, shot_type: SpaceContents) -> None:
        """add a shot space at the given id."""
        if id < 0 or id >= self.size:
            raise IndexError("id out of bounds")
        if shot_type not in {SpaceContents.SHOT, SpaceContents.DOUBLE_SHOT, SpaceContents.FRIEND_SHOT}:
            raise ValueError("invalid shot_type")
        self.spaces[id].contents = shot_type

    def get_space(self, id: int) -> Space:
        return self.spaces[id]


class RectangleBoard(Board):
    """rectangular board with serpentine (snake) traversal.

    - spaces stored in physical row-major order: id = row * width + col
    - traversal_order lists ids in play order (snake)
    - prev_id/next_id form a forced path following traversal_order
    """
    def __init__(self, width: int, height: int):
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be positive integers")
        total = width * height
        spaces = [Space(id=i, coords=(i // width, i % width)) for i in range(total)]
        super().__init__(spaces)
        self.width = width
        self.height = height

        # build snake (serpentine) traversal order (ids)
        order: list[int] = []
        for row in range(height):
            row_base = row * width
            cols = list(range(width))
            if row % 2 == 1:
                cols.reverse()
            order.extend(row_base + c for c in cols)

        self.traversal_order = order

        self._index_to_snake_pos: dict[int, int] = {idx: pos for pos, idx in enumerate(order)}

        # link prev_id/next_id along the traversal order
        for pos, phys_id in enumerate(order):
            self.spaces[phys_id].snake_id = pos
            if pos > 0:
                self.spaces[phys_id].prev_id = order[pos - 1]
            if pos < len(order) - 1:
                self.spaces[phys_id].next_id = order[pos + 1]

        # mark start / end
        self.spaces[order[0]].contents = SpaceContents.START
        self.spaces[order[-1]].contents = SpaceContents.END


@dataclass
class Piece:
    location: Space


@dataclass
class Player:
    name: str
    piece: Piece
    shots_taken: int = 0
    spaces_moved: int = 0
    turns_taken: int = 0

    def take_shot(self) -> None:
        self.shots_taken += 1


class Game:
    def __init__(self, board: Board):
        self.board = board
        self.players: list[Player] = []
        self.player_up: int = 0
        self.winner: Player | None = None

    @classmethod
    def with_rectangle_board(cls, width: int, height: int) -> Game:
        board = RectangleBoard(width, height)
        return cls(board)
    
    def add_player(self, name: str) -> None:
        if any(p.name == name for p in self.players):
            raise ValueError(f"player with name {name} already exists")
        if self.winner is not None:
            raise ValueError("cannot add player to finished game")
        start_space = self.board.get_space(0)
        piece = Piece(location=start_space)
        player = Player(name=name, piece=piece)
        self.players.append(player)

    def get_current_player(self) -> Player:
        return self.players[self.player_up]
    
    def set_next_player(self) -> None:
        self.player_up = (self.player_up + 1) % len(self.players)
    
    def take_turn(self, steps: int) -> int:
        if steps < 1:
            raise ValueError("steps must be at least 1")
        player = self.get_current_player()
        self.move_player(player, steps)
        player.turns_taken += 1
        player.spaces_moved += steps
        if player.piece.location.contents == SpaceContents.END:
            logger.info(f"player {player.name} has reached the end and wins the game!")
            self.winner = player
        self.set_next_player()
        return steps

    def roll_dice_take_turn(self) -> int:
        steps = random.randint(1, 6)
        return self.take_turn(steps)

    def move_player(self, player: Player, steps: int) -> None:
        current_space = player.piece.location
        end_hit = False
        for _ in range(steps):
            if not end_hit and current_space.next_id is None:
                end_hit = True
            if end_hit:
                current_space = self.board.get_space(current_space.prev_id)
            else:
                current_space = self.board.get_space(current_space.next_id)

        logger.info(f"player {player.name} moved {steps} steps to space {current_space.snake_id} (id {current_space.id})")

        self.check_for_shots(player, current_space)

        jump_space: Space | None = self.check_for_jumps(current_space)

        if jump_space:
            logger.info(f"player {player.name} jumps to space {jump_space.snake_id} (id {jump_space.id})")
            self.check_for_shots(player, jump_space)
            player.piece.location = jump_space
        else:
            player.piece.location = current_space

    @staticmethod
    def check_for_shots(player: Player, space: Space) -> None:
        if space.contents == SpaceContents.SHOT:
            logger.info(f"player {player.name} takes a shot")
            player.take_shot()
        elif space.contents == SpaceContents.DOUBLE_SHOT:
            logger.info(f"player {player.name} takes a double shot")
            player.take_shot()
            player.take_shot()
        elif space.contents == SpaceContents.FRIEND_SHOT:
            # TODO: implement friend shot logic
            logger.info(f"player {player.name} takes a friend shot")
            player.take_shot()
            player.take_shot()

    def check_for_jumps(self, space: Space) -> Space | None:
        if space.jump_to is not None:
            return self.board.get_space(space.jump_to)
        return None
    
    def get_game_state(self) -> dict[str, Any]:
        state = {
            "board_size": self.board.size,
            "winner": self.winner.name if self.winner else None,
            "players": [
                {
                    "name": player.name,
                    "location_id": player.piece.location.id,
                    "location_snake_id": player.piece.location.snake_id,
                    "shots_taken": player.shots_taken,
                    "spaces_moved": player.spaces_moved,
                    "turns_taken": player.turns_taken
                }
                for player in self.players
            ]
        }
        return state


class GameSimulator:
    def __init__(self, game: Game):
        self.game = game

    def simulate_game(self) -> None:
        print("initial game state:", json.dumps(self.game.get_game_state(), indent=2))

        while self.game.winner is None:
            self.game.roll_dice_take_turn()

        print(f"player {self.game.winner.name} wins!")
        print("final game state:", json.dumps(self.game.get_game_state(), indent=2))

    def reset_game(self) -> None:
        self.game.winner = None
        self.game.player_up = 0
        for player in self.game.players:
            player.piece.location = self.game.board.get_space(0)
            player.shots_taken = 0
            player.spaces_moved = 0
            player.turns_taken = 0

def easy_side() -> Board:
    board = RectangleBoard(6, 6)
    board.add_shot(1, SpaceContents.SHOT)
    board.add_shot(4, SpaceContents.FRIEND_SHOT)
    board.add_shot(6, SpaceContents.DOUBLE_SHOT)
    board.add_shot(17, SpaceContents.FRIEND_SHOT)
    board.add_shot(19, SpaceContents.FRIEND_SHOT)
    board.add_shot(22, SpaceContents.SHOT)
    board.add_shot(24, SpaceContents.SHOT)
    board.add_shot(31, SpaceContents.DOUBLE_SHOT)
    board.add_shot(33, SpaceContents.SHOT)
    # ladders
    board.add_jump(2, 14)
    board.add_jump(21, 26)
    board.add_jump(23, 34)
    # chutes
    board.add_jump(31, 5)
    board.add_jump(19, 14)
    board.add_jump(22, 9)
    return board

def hard_side() -> Board:
    board = RectangleBoard(6, 6)
    board.add_shot(1, SpaceContents.SHOT)
    board.add_shot(3, SpaceContents.FRIEND_SHOT)
    board.add_shot(7, SpaceContents.FRIEND_SHOT)
    board.add_shot(16, SpaceContents.DOUBLE_SHOT)
    board.add_shot(19, SpaceContents.SHOT)
    board.add_shot(26, SpaceContents.FRIEND_SHOT)
    board.add_shot(31, SpaceContents.DOUBLE_SHOT)
    board.add_shot(33, SpaceContents.SHOT)
    board.add_shot(35, SpaceContents.SHOT)
    # ladders
    board.add_jump(1, 21)
    board.add_jump(13, 18)
    board.add_jump(23, 34)
    # chutes
    board.add_jump(31, 4)
    board.add_jump(33, 22)
    board.add_jump(17, 10)
    board.add_jump(9, 2)
    return board

def main():
    board = hard_side()
    game = Game(board)
    game.add_player("ethan")
    game.add_player("damon")

    gs = GameSimulator(game)
    gs.simulate_game()
    
if __name__ == "__main__":
    main()

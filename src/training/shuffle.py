#=====================================================================
# Shuffle (シャッフル, the Digivice iC 10X)
#=====================================================================
"""Shuffle, the iC 10X's guessing minigame: which bucket is Chuumon in?

Read off the owner's video of a 10X (``utilities/IC/2.mp4``, five rounds;
the sprites and where they stand are in
``utilities/IC/make_poop_dodge_shuffle_sprites.py``) and the Master Book
(scan 64). A round:

1. Chuumon stands on the left of two buckets, still for a moment, then
   sinks into it, silently. The first round's is the opening scene, shown
   in place of READY; a later round's opens the round itself.
2. The SHUFFLE screen, its two frames taking turns, to the iC's shuffle
   tune; one bucket hops from the left to the right; the SELECT! screen,
   the same, to the game's READY sound (the device plays that one there).
   Both fill the screen, as the game's other two-frame animations do.
3. The player picks a bucket: LEFT/RIGHT move the pointer and A picks
   (the device's Select and Decide keys); with a mouse or a finger, the
   pointer follows it and a click or a tap on a bucket picks it.
4. The pointer goes, and Chuumon rises out of the bucket he is in until he
   peeks over its rim, and stays a moment. Found, he jumps up onto it and
   the next round starts from 1 there; missed, the game is over, to the
   iC's fail sound (its success jingle only for a game that reaches the
   tenth find).

Where he ends up is even odds each round (the book's 100 tries: 49 left,
51 right).

The result is the finds: none BAD, one GOOD, two GREAT, three or more
EXCELLENT (owner, 2026-10-06). The prize is the book's ladder, 5 P for the
first find doubling to 2560 P for the tenth, which ends the game. **Inferred:**
a miss pays the ladder's step for the finds before it -- the device never
asks whether to stop, so a game that could only lose everything would never
pay -- and any find is the success that raises Reliability; the video shows
neither (its one run with a find ends before its result).
"""
import random

from core import runtime_globals
from training.ic_minigame import ICMinigame

#: The buckets' columns; both stand on rows 15-30.
BUCKETS = (0, 16)
BUCKET_ROW = 15
#: Chuumon stands on the left bucket, his feet on its rim (rows 0-15), and
#: peeks out of a bucket with his head over the rim.
CHUUMON_ROWS = 16
PEEK_ROW = 8
#: The pointer stands over a bucket's middle (its point at row 15).
CURSOR_COL = 4
CURSOR_ROW = 9

#: The opening: Chuumon still, then a row lower every SINK_ROW_MS until he
#: is in, then the empty buckets a moment.
STILL_MS = 1100
SINK_ROW_MS = 80
EMPTY_MS = 300
INTRO_MS = STILL_MS + CHUUMON_ROWS * SINK_ROW_MS + EMPTY_MS
#: SHUFFLE: its two frames, four turns; the bucket's hop, left then right;
#: SELECT!: its two frames, six turns. The frames turn twice a second.
TITLE_FRAME_MS = 500
TITLE_MS = 4 * TITLE_FRAME_MS
HOP = ((BUCKETS[0], 500), (BUCKETS[1], 500))
HOP_MS = sum(ms for _, ms in HOP)
SELECT_FRAME_MS = 500
SELECT_MS = 6 * SELECT_FRAME_MS
TITLE_SOUND = "ic_shuffle"
SELECT_SOUND = "training_ready"
#: The reveal (the video's 12.9-14.7 s and 79.2-81.2 s): the buckets alone
#: a moment, Chuumon rising a row every RISE_ROW_MS from out of sight to
#: peeking, then peeking a while; a find, then the next round, a miss, then
#: the result.
REVEAL_PAUSE_MS = 200
RISE_ROW_MS = 75
RISE_MS = (CHUUMON_ROWS - PEEK_ROW) * RISE_ROW_MS
PEEK_MS = 1000
REVEAL_MS = REVEAL_PAUSE_MS + RISE_MS + PEEK_MS

#: The book's ladder: 5 P for the first find, doubling; the tenth, 2560 P,
#: is the last.
FIRST_PRIZE = 5
MOST_FINDS = 10


def prize_for(finds):
    """P for *finds* finds in a row."""
    return FIRST_PRIZE * 2 ** (finds - 1) if finds else 0


class Shuffle(ICMinigame):
    READY_MS = INTRO_MS

    def __init__(self, ui_manager):
        super().__init__(ui_manager)
        self.finds = 0
        self.home = 0           # the bucket Chuumon stands on and sinks into
        self.where = 0          # the bucket he ends up in
        self.choice = 0         # the bucket the pointer is over
        self.hit = False

    #-----------------------------------------------------------------
    # Rules
    #-----------------------------------------------------------------

    def start_game(self):
        self.new_round(opening=False)

    def new_round(self, opening=True):
        """Chuumon goes into a bucket and they are shuffled: the first
        round's opening was the READY scene; a later round's starts with him
        on the bucket he was found in."""
        self.home = self.where
        self.where = random.randrange(len(BUCKETS))
        self.choice = 0
        if opening:
            self.set_step("intro")
        else:
            self.show_title()

    def show_title(self):
        self.set_step("title")
        self.animated_sprite.play_shuffle_title(TITLE_MS / 1000)
        runtime_globals.game_sound.play(TITLE_SOUND)

    def show_select(self):
        self.set_step("select")
        self.animated_sprite.play_shuffle_select(SELECT_MS / 1000)
        runtime_globals.game_sound.play(SELECT_SOUND)

    def update_game(self):
        t = self.elapsed()
        step = self.step
        if step == "intro" and t >= INTRO_MS:
            self.show_title()
        elif step == "title" and t >= TITLE_MS:
            self.animated_sprite.stop()
            self.set_step("hop")
        elif step == "hop" and t >= HOP_MS:
            self.show_select()
        elif step == "select" and t >= SELECT_MS:
            self.animated_sprite.stop()
            self.set_step("choose")
        elif step == "reveal" and t >= REVEAL_MS:
            if self.hit and self.finds < MOST_FINDS:
                self.new_round()
            else:
                self.finish()

    def pick(self, bucket):
        self.choice = bucket
        self.hit = bucket == self.where
        if self.hit:
            self.finds += 1
        runtime_globals.game_sound.play("menu")
        self.set_step("reveal")

    def finish(self):
        self.end_game(min(self.finds, 3), prize_for(self.finds), succeeded=self.finds > 0,
                      cleared=self.finds >= MOST_FINDS)

    def point_at(self, choice):
        if choice != self.choice:
            self.choice = choice
            runtime_globals.game_sound.play("menu")

    def bucket_at(self, pos):
        """The bucket on that side of the LCD's middle."""
        return 0 if pos[0] < self.lcd_rect().centerx else 1

    def handle_game_event(self, event):
        if self.step != "choose":
            return False
        event_type, data = event
        if event_type in ("LEFT", "RIGHT"):
            self.point_at(0 if event_type == "LEFT" else 1)
            return True
        if event_type == "A":
            self.pick(self.choice)
            return True
        if event_type == "MOUSE_MOTION" and data and "pos" in data:
            self.point_at(self.bucket_at(data["pos"]))
            return True
        pos = self.tap_pos(event)
        if pos is not None:
            self.pick(self.bucket_at(pos))
            return True
        return False

    #-----------------------------------------------------------------
    # Drawing
    #-----------------------------------------------------------------

    def draw_ready(self, surface):
        self.draw_intro(surface, self.ready_elapsed())

    def draw_intro(self, surface, t):
        """Chuumon on his bucket, then sinking into it."""
        col = BUCKETS[self.home]
        if t < STILL_MS:
            # Standing on the rim, in front of it.
            self.blit_buckets(surface)
            self.blit_chuumon(surface, col, 0)
            return
        drop = (t - STILL_MS) // SINK_ROW_MS + 1
        if drop < CHUUMON_ROWS:
            self.blit_chuumon(surface, col, drop)
        self.blit_buckets(surface)

    def reveal_row(self, t):
        """Where Chuumon's top is *t* ms into the reveal: out of sight
        (CHUUMON_ROWS), rising a row at a time, then peeking."""
        if t < REVEAL_PAUSE_MS:
            return CHUUMON_ROWS
        rows = (t - REVEAL_PAUSE_MS) // RISE_ROW_MS + 1
        return max(PEEK_ROW, CHUUMON_ROWS - rows)

    def blit_chuumon(self, surface, col, row):
        """Chuumon with his top at *row*, nothing of him below the rim."""
        clip = surface.get_clip()
        x, y = self.at(0, 0)
        surface.set_clip(clip.clip((x, y, self.lcd_rect().width, (BUCKET_ROW + 1) * self.dot())))
        try:
            self.blit_art(surface, "shuffle_chuumon", col, row)
        finally:
            surface.set_clip(clip)

    def blit_buckets(self, surface):
        for col in BUCKETS:
            self.blit_art(surface, "shuffle_bucket", col, BUCKET_ROW)

    def draw_game(self, surface):
        t = self.elapsed()
        step = self.step
        if step == "intro":
            self.draw_intro(surface, t)
        elif step == "hop":
            col = HOP[-1][0]
            for at, ms in HOP:
                if t < ms:
                    col = at
                    break
                t -= ms
            self.blit_art(surface, "shuffle_bucket", col, BUCKET_ROW)
        elif step == "choose":
            self.blit_buckets(surface)
            self.blit_art(surface, "shuffle_cursor", BUCKETS[self.choice] + CURSOR_COL, CURSOR_ROW)
        elif step == "reveal":
            row = self.reveal_row(t)
            if row < CHUUMON_ROWS:
                self.blit_chuumon(surface, BUCKETS[self.where], row)
            self.blit_buckets(surface)
